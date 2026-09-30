"""Сборка Markdown-отчёта с безопасными формулировками."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

from mito_harness.catalog import DISEASES
from mito_harness.config import settings
from mito_harness.schemas import (
    DirectionLabel,
    DirectionScore,
    ExtractedStudy,
    ExtractionEvalResult,
    LlmCompareResult,
    ReviewResult,
)
from mito_harness.skills_loader import load_json_skill


def _sanitize_query_for_report(query: str) -> str:
    """Убирает из эха запроса запрещённые/дозинговые формулировки (user injection)."""
    rules = load_json_skill("mito_extraction_rules")
    text = query or ""
    for phrase in rules.get("forbidden_claims", []) + rules.get("harmful_overclaim_patterns", []):
        if not phrase or len(phrase.strip()) < 4:
            continue
        # границы слова — не режем "curiosity"/"safety" по подстроке "cure"/"safe"
        pattern = re.compile(rf"(?<!\w){re.escape(phrase)}(?!\w)", re.I)
        text = pattern.sub("[removed: unsafe-query]", text)
    text = re.sub(
        r"\b(\d+\s*mg(?:/kg)?|\d+\s*мг|dose of\s+\d+|take\s+\d+)\b",
        "[removed: dosing]",
        text,
        flags=re.I,
    )
    return text


def _md_escape(text: str) -> str:
    """Экранирует символы, которые реально ломают Markdown в обычном тексте."""
    if not text:
        return ""
    out = text.replace("\\", "\\\\")
    for ch in ("`", "*", "_", "[", "]"):
        out = out.replace(ch, "\\" + ch)
    return out


def _doi_md(doi: str | None) -> str:
    if not doi:
        return ""
    d = doi.strip()
    # DOI с «_» в голом виде ломает italic; оформляем как ссылку
    return f", [DOI](https://doi.org/{d})"


def build_report_markdown(
    *,
    query: str,
    disease_id: str,
    studies: list[ExtractedStudy],
    ranking: list[DirectionScore],
    figure_path: Path | None,
    review: ReviewResult | None,
    skills_used: list[str],
    limitations: list[str],
    llm_compare: LlmCompareResult | None = None,
    extraction_eval: ExtractionEvalResult | None = None,
) -> str:
    disease = DISEASES[disease_id]
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    top = [r for r in ranking if r.label == DirectionLabel.PROMISING][:2]
    if not top:
        top = [r for r in ranking if r.label == DirectionLabel.UNCERTAIN and r.n_studies > 0][:2]
    bottom = [r for r in ranking if r.label in {DirectionLabel.INSUFFICIENT, DirectionLabel.NOT_PROMISING}]
    bottom = bottom[-3:] if bottom else ranking[-2:]

    lines: list[str] = []
    lines.append(f"# Мини-обзор: митохондриальная терапия — {_md_escape(disease['name_ru'])}")
    lines.append("")
    lines.append(f"_Сгенерировано Harness · {now}_")
    lines.append("")
    lines.append(
        "> **Не медицинская рекомендация.** Это исследовательский экспресс-обзор. "
        "Не начинайте, не отменяйте и не меняйте лечение на основании этого текста — "
        "решения принимает только лечащий врач."
    )
    lines.append("")
    lines.append("## Запрос")
    lines.append("")
    lines.append(_sanitize_query_for_report(query))
    lines.append("")
    lines.append("## Стандарт лечения (справочно из каталога, не назначение)")
    lines.append("")
    lines.append(_md_escape(disease["standard_of_care"]))
    lines.append("")
    lines.append("## Источники (официальные)")
    lines.append("")
    lines.append(
        f"Всего извлечено записей: **{len(studies)}** "
        "(только PubMed PMID и ClinicalTrials.gov NCT этого прогона)."
    )
    lines.append("")
    for s in studies[:40]:
        doi = _doi_md(s.doi)
        eff = s.effect_direction or "null"
        extra = []
        if s.journal_quality:
            extra.append(f"journal={s.journal_quality}")
        if s.nct_status:
            extra.append(f"nct_status={s.nct_status}/{s.nct_status_bucket}")
        if s.conflicts_of_interest:
            extra.append("COI=mentioned")
        extras = (", " + ", ".join(extra)) if extra else ""
        title = _md_escape(s.title or "")
        lines.append(
            f"- [{s.source_id}]({s.url}){doi} — {title} "
            f"(type=`{s.study_type.value}`, evidence=`{s.evidence_level.value}`, "
            f"effect=`{eff}`, year={s.year}{extras})"
        )
    lines.append("")
    lines.append("## Сигналы качества источников")
    lines.append("")
    n_trusted = sum(1 for s in studies if s.journal_quality == "trusted")
    n_suspect = sum(1 for s in studies if s.journal_quality == "suspect")
    n_coi = sum(1 for s in studies if s.conflicts_of_interest)
    n_term = sum(1 for s in studies if s.nct_is_terminal)
    n_active = sum(1 for s in studies if s.nct_is_active)
    lines.append(
        f"- Журналы: trusted={n_trusted}, suspect={n_suspect}, unknown="
        f"{sum(1 for s in studies if s.journal_quality == 'unknown')}"
    )
    lines.append(f"- Упоминания COI в abstract/notes: {n_coi}")
    lines.append(f"- NCT active={n_active}, terminal/withdrawn/suspended={n_term}")
    lines.append(
        "- Impact Factor через внешний платный API не запрашивается: используется "
        "curated whitelist/suspect list (см. `tools/quality.py` + skill `quality_signals`)."
    )
    if n_suspect or n_term:
        lines.append(
            "- **Осторожно:** suspect-журналы и terminal NCT не используются как опора "
            "для ярлыка `promising`."
        )
    lines.append("")
    lines.append("## Рейтинг направлений (консервативный)")
    lines.append("")
    for i, r in enumerate(ranking, 1):
        ids = ", ".join(r.supporting_ids[:8]) or "—"
        soc = "comparative_vs_SoC=supported" if r.claims_superior_to_soc else "comparative_vs_SoC=not_supported"
        name = _md_escape(r.direction_name)
        rationale = _md_escape(r.rationale)
        lines.append(
            f"{i}. **{name}** — score={r.score:.0f}, label=`{r.label.value}`, "
            f"best=`{r.evidence_level_best.value}`, n={r.n_studies}, {soc}. "
            f"{rationale}. IDs: {ids}"
        )
    lines.append("")
    lines.append("## Относительно более поддержанные направления")
    lines.append("")
    if top:
        for r in top:
            caveat = ""
            if not r.claims_superior_to_soc:
                caveat = " Не утверждается превосходство над стандартом лечения."
            name = _md_escape(r.direction_name)
            lines.append(
                f"- **{name}** (score={r.score:.0f}, `{r.label.value}`): "
                f"опора на {', '.join(r.supporting_ids) or 'нет ID'}.{caveat}"
            )
    else:
        lines.append(
            "- Недостаточно данных, чтобы выделить перспективные направления в этом окне поиска."
        )
    lines.append("")
    lines.append("## Аутсайдеры / недостаточно данных")
    lines.append("")
    for r in bottom:
        name = _md_escape(r.direction_name)
        rationale = _md_escape(r.rationale)
        lines.append(
            f"- **{name}** (score={r.score:.0f}, `{r.label.value}`): {rationale}."
        )
    lines.append("")
    if figure_path:
        # относительный путь от reports/ → figures/ (GitHub/локальный просмотр файла отчёта)
        fig = Path(figure_path)
        rel = Path("..") / "figures" / fig.name
        lines.append("## Визуализация")
        lines.append("")
        lines.append(f"![Рейтинг направлений]({rel.as_posix()})")
        lines.append("")
    lines.append("## Сравнение с SoC")
    lines.append("")
    lines.append(
        "Превосходство митотерапии над стандартом **не заявляется**, "
        "если нет человеческих сравнительных данных (РКИ/метаанализ с компаратором) в извлечённых записях. "
        "Доклиника и записи ClinicalTrials.gov без результатов не равны клинической эффективности."
    )
    lines.append("")
    lines.append("## Верификация (Reviewer)")
    lines.append("")
    if review:
        lines.append(f"- ok={review.ok}")
        if review.issues:
            for issue in review.issues:
                claim = _md_escape(str(issue.claim))
                reason = _md_escape(str(issue.reason))
                lines.append(
                    f"- [{issue.severity}] {issue.action}: {claim} — {reason}"
                )
        else:
            lines.append("- Критических замечаний нет.")
        lines.append(
            f"- verified IDs in pipeline: {_md_escape(', '.join(review.verified_source_ids[:30]))}"
        )
    lines.append("")
    lines.append("## Skills")
    lines.append("")
    lines.append(", ".join(f"`{s}`" for s in skills_used))
    lines.append("")
    if llm_compare is not None:
        lines.append("## Сравнение двух LLM (бонус ТЗ)")
        lines.append("")
        lines.append(
            f"- primary=`{llm_compare.primary_model}`, fallback=`{llm_compare.fallback_model}`, "
            f"n={llm_compare.n_compared}"
        )
        lines.append(
            f"- agreement study_type={llm_compare.agreement_study_type:.2f}, "
            f"effect_direction={llm_compare.agreement_effect_direction:.2f}"
        )
        lines.append("")
    if extraction_eval is not None:
        lines.append("## Метрики извлечения на ручной разметке (бонус ТЗ)")
        lines.append("")
        lines.append(
            f"- n={extraction_eval.n}; accuracy study_type="
            f"{extraction_eval.accuracy_study_type:.2f}; "
            f"intervention_kind={extraction_eval.accuracy_intervention_kind:.2f}"
        )
        lines.append("")
    lines.append("## Ограничения")
    lines.append("")
    for lim in limitations:
        lines.append(f"- {_md_escape(lim)}")
    lines.append("")
    return "\n".join(lines)


def save_report(md: str, disease_id: str) -> Path:
    out_dir = settings()["reports_dir"]
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"report_{disease_id}.md"
    path.write_text(md, encoding="utf-8")
    return path
