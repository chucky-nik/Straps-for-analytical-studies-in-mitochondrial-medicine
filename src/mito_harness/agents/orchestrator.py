"""Orchestrator: план → поиск → extract → compare → viz → report → review → sanitize."""

from __future__ import annotations

import json
import re
from typing import Any

from mito_harness.agents.compare import score_directions
from mito_harness.agents.report import build_report_markdown, save_report
from mito_harness.agents.reviewer import review_report, sanitize_report_text
from mito_harness.catalog import DISEASES, list_diseases, resolve_disease, therapies_for_disease
from mito_harness.config import has_llm_api_key, settings
from mito_harness.logging_util import RunLogger
from mito_harness.schemas import HarnessResult, StudyRecord
from mito_harness.tools.clinicaltrials import clinicaltrials_search
from mito_harness.tools.parse import enrich_extracted_with_live_nct, parse_many
from mito_harness.tools.plot import plot_direction_ranking
from mito_harness.tools.pubmed import pubmed_search
from mito_harness.eval_metrics import compare_two_llms_on_records, evaluate_extraction
from mito_harness.skills_loader import load_skill


DEFAULT_QUERY = (
    "Сравнение митохондриально-таргетной терапии и стандарта лечения при LHON "
    "за последние 5 лет: антиоксиданты, генная терапия мтДНК, перспективы и аутсайдеры"
)

ROOT_META_PROMPT = """
Ты Root-оркестратор Harness для анализа митохондриальной медицины (ANTEI × ИТМО).

Роль:
- принять исследовательский запрос;
- построить план (поиск → извлечение → сравнение → оценка → визуализация → отчёт → ревью);
- делегировать субагентам и собрать итог;
- логировать план, делегирование, tool calls и подключённые skills.

Жёсткие ограничения (анти-галлюцинации / анти-вред):
1. Не добавляй PMID / DOI / NCT «из памяти модели» — только из ответов официальных API.
2. Любое утверждение об эффекте — только из ExtractedStudy с verified source_id.
3. ClinicalTrials.gov без опубликованных результатов ≠ доказанная эффективность.
4. Доклиника не равна клинической эффективности у людей.
5. Не давай клинических рекомендаций пациенту, дозировок, схем «начать/отменить SoC».
6. При сомнениях выбирай более осторожную формулировку и label insufficient/uncertain.
7. Источники только PubMed E-utilities и ClinicalTrials.gov API v2.
""".strip()


class Orchestrator:
    def __init__(self, logger: RunLogger | None = None) -> None:
        self.log = logger or RunLogger()

    def _default_plan(self, disease_id: str) -> list[str]:
        return [
            f"1. Уточнить заболевание ({disease_id}) и митонаправления из каталога",
            "2. Поиск PubMed + ClinicalTrials.gov (только официальные API)",
            "3. Extract + sanitize (evidence_levels, mito_extraction_rules)",
            "4. Compare/rank (prospect_criteria + safety_guardrails)",
            "5. Визуализация рейтинга направлений",
            "6. Черновик отчёта с дисклеймером и PMID/NCT",
            "7. Reviewer (citation + forbidden claims) → санация → финал",
        ]

    def build_plan(self, disease_id: str, query: str) -> list[str]:
        """План под метапромптом; при наличии LLM — уточнение шагов, иначе статический."""
        fallback = self._default_plan(disease_id)
        if not has_llm_api_key():
            return fallback
        try:
            from mito_harness.llm import get_llm

            raw = get_llm().chat(
                (
                    f"Disease id: {disease_id}\n"
                    f"User query: {query}\n\n"
                    "Верни JSON-массив из 5–8 коротких шагов плана на русском. "
                    "Только JSON-массив строк, без markdown."
                ),
                system=ROOT_META_PROMPT,
                temperature=0.0,
                max_tokens=500,
            )
            text = raw.strip()
            if text.startswith("```"):
                text = re.sub(r"^```(?:json)?\s*", "", text)
                text = re.sub(r"\s*```$", "", text)
            data = json.loads(text)
            if isinstance(data, list) and all(isinstance(x, str) and x.strip() for x in data):
                return [s.strip() for s in data][:8]
        except Exception as e:  # noqa: BLE001
            self.log.log("orchestrator", "LLM plan fallback", error=str(e)[:200])
        return fallback

    def run(
        self,
        query: str | None = None,
        *,
        disease_id: str | None = None,
        max_pubmed: int = 12,
        max_ctgov: int = 8,
        use_llm_extract: bool | None = None,
        compare_llms: bool = False,
        run_extraction_eval: bool = True,
    ) -> HarnessResult:
        query = query or DEFAULT_QUERY
        disease = DISEASES.get(disease_id) if disease_id else None
        if disease is None:
            disease = resolve_disease(disease_id or query)
        if disease is None:
            disease = DISEASES["lhon"]
            self.log.log(
                "orchestrator",
                "Заболевание не распознано — fallback LHON",
                available=[d["id"] for d in list_diseases()],
            )

        disease_id = disease["id"]
        self.log.log(
            "orchestrator",
            "Root meta-prompt loaded",
            meta_prompt=ROOT_META_PROMPT,
        )
        plan = self.build_plan(disease_id, query)
        self.log.log("orchestrator", "План построен", plan=plan, disease=disease["name_ru"])

        therapies = therapies_for_disease(disease_id)
        self.log.log("delegate", "SearchAgent", therapies=[t["id"] for t in therapies])

        tool_calls: list[dict[str, Any]] = []
        records: list[StudyRecord] = []

        pubmed_q = disease["pubmed_query"]
        therapy_terms = " OR ".join(f"({t['pubmed_terms']})" for t in therapies[:5])
        combined = f"({pubmed_q}) AND ({therapy_terms})"
        self.log.log("tool", "pubmed_search", query=combined, max_results=max_pubmed)
        pm = pubmed_search(combined, max_results=max_pubmed)
        tool_calls.append({"tool": "pubmed_search", "n": len(pm), "query": combined})
        records.extend(pm)

        from mito_harness.skills_loader import load_json_skill

        rules = load_json_skill("mito_extraction_rules")
        soc_terms = rules.get("standard_comparators", {}).get(disease_id, ["standard care"])
        soc_or = " OR ".join(f'"{t}"' if " " in t else t for t in soc_terms[:4])
        soc_q = f"({pubmed_q}) AND ({soc_or} OR trial OR randomized)"
        self.log.log("tool", "pubmed_search", query=soc_q, max_results=max(6, max_pubmed // 2))
        pm2 = pubmed_search(soc_q, max_results=max(6, max_pubmed // 2))
        tool_calls.append({"tool": "pubmed_search", "n": len(pm2), "query": soc_q})
        records.extend(pm2)

        ct_q = (
            f"({disease['ctgov_query']}) AND "
            "(mitochondrial OR MitoQ OR elamipretide OR gene therapy OR NAD OR urolithin OR idebenone)"
        )
        self.log.log("tool", "clinicaltrials_search", query=ct_q, max_results=max_ctgov)
        ct = clinicaltrials_search(ct_q, max_results=max_ctgov)
        tool_calls.append({"tool": "clinicaltrials_search", "n": len(ct), "query": ct_q})
        records.extend(ct)

        uniq: dict[str, StudyRecord] = {}
        for r in records:
            uniq[f"{r.source}:{r.source_id}"] = r
        records = list(uniq.values())
        self.log.log("search", f"Уникальных записей: {len(records)}")

        if use_llm_extract is None:
            use_llm_extract = has_llm_api_key()
        self.log.log(
            "delegate",
            "ExtractAgent",
            use_llm=use_llm_extract,
            skills=["evidence_levels", "mito_extraction_rules"],
        )
        extracted = parse_many(
            records,
            disease_hint=disease["name_en"],
            use_llm=use_llm_extract,
        )
        self.log.log("tool", "enrich_nct_status", n=sum(1 for x in extracted if x.source == "clinicaltrials"))
        extracted = enrich_extracted_with_live_nct(extracted, refresh=True)
        tool_calls.append({"tool": "parse_annotation_to_schema", "n": len(extracted)})
        tool_calls.append(
            {
                "tool": "fetch_nct_status",
                "n": sum(1 for x in extracted if x.source == "clinicaltrials"),
            }
        )

        llm_compare = None
        if compare_llms:
            self.log.log("delegate", "LlmCompare", skill="quality_signals")
            llm_compare = compare_two_llms_on_records(
                records, limit=3, disease_hint=disease["name_en"]
            )
            tool_calls.append({"tool": "compare_two_llms", "n": llm_compare.n_compared})

        extraction_eval = None
        if run_extraction_eval:
            _ = load_skill("quality_signals")
            extraction_eval = evaluate_extraction(use_llm=False)
            self.log.log(
                "eval",
                "extraction_gold",
                n=extraction_eval.n,
                acc_type=extraction_eval.accuracy_study_type,
                acc_kind=extraction_eval.accuracy_intervention_kind,
            )

        self.log.log(
            "delegate",
            "CompareAgent",
            skills=["evidence_levels", "prospect_criteria", "safety_guardrails", "quality_signals"],
        )
        ranking, skills_used = score_directions(disease_id, extracted)
        skills_used = list(
            dict.fromkeys(
                skills_used
                + ["citation_checklist", "mito_extraction_rules", "quality_signals"]
            )
        )

        self.log.log("delegate", "VizAgent", tool="plot_direction_ranking")
        fig = plot_direction_ranking(ranking, disease_name=disease["name_ru"])
        tool_calls.append({"tool": "plot_direction_ranking", "path": str(fig)})

        limitations = [
            "Экспресс-обзор, не систематический обзор/метаанализ",
            f"Окно поиска ~{settings()['years_back']} лет",
            "Возможны пропуски из‑за формулировок запросов",
            "Не является клинической рекомендацией; не меняйте терапию самостоятельно",
            "Эффект без явной опоры в abstract очищается (анти-галлюцинация)",
            "ClinicalTrials.gov без результатов не считается доказанной эффективностью",
            "Ярлык promising не выдаётся при отсутствии человеческих данных A/B/C",
            "Suspect-журналы и terminal NCT понижают score и не тянут promising",
            "Impact Factor числом не подтягивается (нет платного API) — whitelist/suspect эвристика",
            "COI извлекается только если явно упомянут в abstract/notes",
        ]

        draft = build_report_markdown(
            query=query,
            disease_id=disease_id,
            studies=extracted,
            ranking=ranking,
            figure_path=fig,
            review=None,
            skills_used=skills_used,
            limitations=limitations,
            llm_compare=llm_compare,
            extraction_eval=extraction_eval,
        )

        self.log.log(
            "delegate",
            "ReviewerAgent",
            skills=["citation_checklist", "safety_guardrails", "mito_extraction_rules", "quality_signals"],
        )
        review = review_report(draft, extracted, ranking)
        if not review.ok:
            self.log.log("reviewer", "Ошибки — санация текста", n_issues=len(review.issues))
            draft = sanitize_report_text(draft, review.issues)
        final = build_report_markdown(
            query=query,
            disease_id=disease_id,
            studies=extracted,
            ranking=ranking,
            figure_path=fig,
            review=review,
            skills_used=skills_used,
            limitations=limitations,
            llm_compare=llm_compare,
            extraction_eval=extraction_eval,
        )
        review2 = review_report(final, extracted, ranking)
        if not review2.ok:
            final = sanitize_report_text(final, review2.issues)
            review = review_report(final, extracted, ranking)
            self.log.log("reviewer", "Повторное ревью после санации", ok=review.ok)
        else:
            review = review2

        report_path = save_report(final, disease_id)
        self.log.log("orchestrator", "Отчёт сохранён", path=str(report_path), review_ok=review.ok)

        return HarnessResult(
            query=query,
            disease_id=disease_id,
            disease_name=disease["name_ru"],
            plan=plan,
            studies_raw_count=len(records),
            studies_extracted=extracted,
            ranking=ranking,
            figure_path=str(fig),
            report_path=str(report_path),
            review=review,
            limitations=limitations,
            skills_used=skills_used,
            tool_calls=tool_calls,
            llm_compare=llm_compare,
            extraction_eval=extraction_eval,
        )
