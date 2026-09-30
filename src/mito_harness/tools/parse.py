"""Парсер аннотаций в Pydantic-схему с консервативной пост-валидацией."""

from __future__ import annotations

import json
import re
from typing import Any

from mito_harness.llm.client import get_llm
from mito_harness.schemas import (
    ArmKind,
    EvidenceLevel,
    ExtractedStudy,
    StudyRecord,
    StudyType,
)
from mito_harness.skills_loader import load_json_skill, load_skill
from mito_harness.tools.quality import (
    classify_journal,
    enrich_nct_fields,
    extract_conflicts,
    fetch_nct_status,
)

EXTRACT_SYSTEM = """Ты научный экстрактор клинических/доклинических данных.
Извлекай ТОЛЬКО то, что явно есть в title/abstract/метаданных.
Если данных нет — ставь null. НЕ выдумывай PMID/DOI/цифры/фазы/эффекты.
Не называй editorial/commentary/viewpoint рандомизированным исследованием.
ClinicalTrials.gov без результатов в тексте — effect_direction=null.
Верни ТОЛЬКО валидный JSON-объект без markdown.
"""

_OPINION_MARKERS = (
    "editorial",
    "commentary",
    "viewpoint",
    "letter to the editor",
    "perspective",
    "infographic",
)
_PRECLIN_MARKERS = (
    "mouse",
    "mice",
    "rat",
    "rats",
    "in vitro",
    "zebrafish",
    "cell line",
    "murine",
    "organoid",
)
_SOC_MARKERS = (
    "idebenone",
    "levodopa",
    "carbidopa",
    "resistance training",
    "sglt2",
    "beta-blocker",
    "ace inhibitor",
)


def _strip_json(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _text_of(rec: StudyRecord) -> str:
    return f"{rec.title}\n{rec.abstract or ''}".lower()


def _classify_type(rec: StudyRecord, text: str) -> StudyType:
    title_l = (rec.title or "").lower()
    if rec.source == "clinicaltrials":
        return StudyType.OTHER  # реестр ≠ завершённое РКИ с результатом

    # Opinion / non-primary: title ИЛИ abstract (infographic иногда только в abstract)
    if any(m in title_l or m in text for m in _OPINION_MARKERS):
        return StudyType.OTHER

    # Официальные PublicationType из PubMed XML (приоритетнее эвристик)
    pub_types = [str(x).lower() for x in (rec.raw or {}).get("publication_types", []) or []]
    pub_blob = " | ".join(pub_types)
    if pub_types:
        if "retracted publication" in pub_blob or "retraction of publication" in pub_blob:
            return StudyType.OTHER
        if "meta-analysis" in pub_blob:
            return StudyType.META_ANALYSIS
        if "systematic review" in pub_blob:
            return StudyType.REVIEW
        if "randomized controlled trial" in pub_blob:
            return StudyType.RCT
        if "clinical trial" in pub_blob:
            # PublicationType "Clinical Trial" без randomized ≠ когорта и ≠ RCT
            if re.search(r"\brandomi[sz]ed\b", text):
                return StudyType.RCT
            if any(x in text for x in ("cohort", "observational", "prospective", "retrospective")):
                return StudyType.COHORT
            return StudyType.OTHER
        if "observational study" in pub_blob or "comparative study" in pub_blob:
            return StudyType.COHORT
        if "case reports" in pub_blob or "case report" in pub_blob:
            return StudyType.CASE_REPORT
        # letter/comment без клинического исхода → other
        letterish = any(x in pub_blob for x in ("editorial", "letter", "news", "comment"))
        clinical_obs = any(
            m in text
            for m in (
                "bilateral improvement",
                "visual acuity",
                "following gene therapy",
                "after gene therapy",
                "case report",
            )
        )
        if letterish and not clinical_obs:
            return StudyType.OTHER
        # Голый PublicationType "Review" (не systematic) — narrative/scoping
        if re.search(r"(^|\|)\s*review\s*(\||$)", pub_blob) and "systematic review" not in pub_blob:
            if not clinical_obs:
                return StudyType.REVIEW
        # иначе (напр. только Journal Article) — fall through к текстовым эвристикам ниже

    # Текстовые эвристики: нет pub_types ИЛИ pub_types не дали точный тип
    if "meta-analysis" in text and (
        "meta-analysis" in title_l
        or "systematic review and meta" in text
        or "meta analysis" in title_l
    ):
        return StudyType.META_ANALYSIS
    if "systematic review" in text:
        return StudyType.REVIEW

    humanish = any(
        w in text
        for w in (
            "patient",
            "patients",
            "participants",
            "subjects",
            "clinical trial",
            "open-label",
            "follow-up",
            "bilateral improvement",
            "visual acuity",
        )
    )
    if (
        re.search(r"\brandomi[sz]ed\b", text)
        and "trial" in text
        and not any(m in text for m in _OPINION_MARKERS)
        and "review" not in text
        and "assessing the treatment" not in title_l
    ):
        return StudyType.RCT
    if "case series" in text:
        return StudyType.CASE_SERIES
    if "case report" in text or (
        re.search(r"\bcase\b", text) is not None and "patient" in text
    ):
        return StudyType.CASE_REPORT
    # клиническое наблюдение исхода у людей (напр. bilateral improvement)
    if humanish and any(
        m in text
        for m in (
            "bilateral improvement",
            "visual acuity",
            "following gene therapy",
            "after gene therapy",
        )
    ):
        return StudyType.CASE_REPORT
    if humanish and any(
        m in text
        for m in (
            "trial",
            "cohort",
            "prospective",
            "retrospective",
            "follow-up",
            "interventional",
        )
    ):
        if "cohort" in text or "nonrandomized" in text or "non-randomised" in text or "non-randomized" in text:
            return StudyType.COHORT
        if "prospective" in text or "retrospective" in text or "follow-up" in text:
            return StudyType.COHORT
        if "interventional" in text or "open-label" in text:
            return StudyType.COHORT
        return StudyType.OTHER
    if any(m in text for m in _PRECLIN_MARKERS) and not humanish:
        return StudyType.PRECLINICAL
    if "cohort" in text:
        return StudyType.COHORT
    if "review" in text and "assessing" not in title_l:
        return StudyType.REVIEW
    # методические/оценочные тексты без первичных данных
    if any(m in title_l for m in ("assessing the treatment", "study design", "requires appropriate")):
        return StudyType.OTHER
    return StudyType.UNKNOWN


def _evidence_for(study_type: StudyType, source: str) -> EvidenceLevel:
    if source == "clinicaltrials":
        return EvidenceLevel.U
    return {
        StudyType.META_ANALYSIS: EvidenceLevel.A,
        StudyType.RCT: EvidenceLevel.B,
        StudyType.COHORT: EvidenceLevel.C,
        StudyType.CASE_SERIES: EvidenceLevel.C,
        StudyType.CASE_REPORT: EvidenceLevel.D,
        StudyType.PRECLINICAL: EvidenceLevel.D,
        StudyType.REVIEW: EvidenceLevel.U,
        StudyType.OTHER: EvidenceLevel.U,
        StudyType.UNKNOWN: EvidenceLevel.U,
    }[study_type]


def _kind_from_text(text: str) -> ArmKind:
    rules = load_json_skill("mito_extraction_rules")
    mito = [a.lower() for a in rules.get("mitochondrial_agents", [])]
    not_mito = [a.lower() for a in rules.get("not_mito_targeted_despite_overlap", [])]
    if any(a.lower() in text for a in not_mito) and not any(a in text for a in mito):
        # idebenone и т.п., если нет явного mito-агента
        if not (
            ("gene therapy" in text or "lenadogene" in text or "lumevoq" in text)
            and any(x in text for x in ("lhon", "leber", "nd4", "mitochondrial"))
        ):
            return ArmKind.STANDARD
    if any(a in text for a in mito):
        return ArmKind.MITO
    if ("gene therapy" in text or "lenadogene" in text or "lumevoq" in text) and any(
        x in text for x in ("lhon", "leber", "nd4", "mitochondrial")
    ):
        return ArmKind.MITO
    if any(m in text for m in _SOC_MARKERS):
        return ArmKind.STANDARD
    return ArmKind.UNKNOWN


def _heuristic_extract(rec: StudyRecord) -> ExtractedStudy:
    text = _text_of(rec)
    study_type = _classify_type(rec, text)
    kind = _kind_from_text(text)
    evidence = _evidence_for(study_type, rec.source)
    phase = None
    raw_phases = (rec.raw or {}).get("phases")
    if isinstance(raw_phases, list) and raw_phases:
        phase = ", ".join(str(p) for p in raw_phases)

    journal = rec.journal_or_status if rec.source == "pubmed" else None
    jq = classify_journal(journal) if rec.source == "pubmed" else None
    coi = extract_conflicts(rec.abstract) or extract_conflicts(rec.title)

    nct_fields: dict[str, Any] = {}
    if rec.source == "clinicaltrials":
        status = (rec.raw or {}).get("overallStatus") or rec.journal_or_status
        nct_fields = enrich_nct_fields(status if isinstance(status, str) else None)

    return ExtractedStudy(
        source=rec.source,
        source_id=rec.source_id,
        title=rec.title,
        url=rec.url,
        doi=rec.doi,
        year=rec.year,
        intervention_kind=kind,
        study_type=study_type,
        phase=phase,
        evidence_level=evidence,
        effect_summary=None,
        effect_direction=None,
        extraction_confidence=0.3,
        notes="heuristic_fallback",
        conflicts_of_interest=coi,
        journal_name=journal,
        journal_quality=jq,  # type: ignore[arg-type]
        **nct_fields,
    )


def _effect_grounded(effect: str | None, text: str) -> bool:
    if not effect:
        return False
    # text уже lower из _text_of; токены — целые слова, не подстроки
    hay = text.lower()
    tokens = [
        t
        for t in re.findall(r"[a-zA-Zа-яА-ЯёЁ0-9%]{4,}", effect.lower())
        if t not in {"with", "from", "that", "this", "were", "been", "have"}
    ]
    if not tokens:
        return False
    hits = sum(1 for t in tokens[:12] if re.search(rf"(?<!\w){re.escape(t)}(?!\w)", hay))
    return hits >= max(1, min(3, len(tokens) // 4))


def sanitize_extraction(study: ExtractedStudy, rec: StudyRecord) -> ExtractedStudy:
    """Снимает небезопасные/незаземлённые поля после LLM."""
    text = _text_of(rec)
    data = study.model_dump()

    # идентификаторы всегда из записи
    data["source"] = rec.source
    data["source_id"] = rec.source_id
    data["title"] = rec.title
    data["url"] = rec.url
    data["doi"] = rec.doi
    data["year"] = rec.year

    heuristic_type = _classify_type(rec, text)
    # не даём LLM завысить тип (opinion/review/preclinical → RCT и т.п.)
    llm_type = study.study_type
    if heuristic_type in {
        StudyType.REVIEW,
        StudyType.PRECLINICAL,
        StudyType.OTHER,
    } and llm_type in {StudyType.RCT, StudyType.META_ANALYSIS, StudyType.COHORT}:
        data["study_type"] = heuristic_type.value
    elif heuristic_type != StudyType.UNKNOWN and llm_type == StudyType.UNKNOWN:
        data["study_type"] = heuristic_type.value

    if rec.source == "clinicaltrials":
        data["study_type"] = StudyType.OTHER.value
        data["effect_direction"] = None
        data["effect_summary"] = data.get("effect_summary") or "registry_record_no_efficacy_claim"

    # эффект: без опоры в тексте и/или с выдуманными числами → очистить
    conf = float(data.get("extraction_confidence") or 0)
    eff = data.get("effect_summary")
    direction = data.get("effect_direction")
    reasons: list[str] = []
    clear_summary = False
    if direction in {"benefit", "harm", "mixed"}:
        if conf < 0.45 or not _effect_grounded(eff, text):
            reasons.append("effect_ungrounded_cleared")
    if eff:
        nums = re.findall(r"\d+(?:[.,]\d+)?%?", eff)
        if nums and not any(
            n.rstrip("%").replace(",", ".") in text or n in text for n in nums
        ):
            reasons.append("numeric_effect_ungrounded_cleared")
            clear_summary = True
    if reasons:
        data["effect_direction"] = None
        if clear_summary:
            data["effect_summary"] = None
        note = data.get("notes") or ""
        data["notes"] = (note + "; " + "; ".join(reasons)).strip("; ")

    # idebenone и пр. не мито-TPP
    kind = _kind_from_text(text)
    if kind == ArmKind.STANDARD and data.get("intervention_kind") == ArmKind.MITO.value:
        data["intervention_kind"] = ArmKind.STANDARD.value

    # согласовать evidence с типом/источником
    st = StudyType(data.get("study_type") or StudyType.UNKNOWN.value)
    data["evidence_level"] = _evidence_for(st, rec.source).value

    # n_participants: не оставлять выдуманные числа без цифры в тексте
    n = data.get("n_participants")
    if n is not None:
        if str(int(n)) not in text and f"n={int(n)}" not in text and f"n = {int(n)}" not in text:
            if not re.search(rf"\b{int(n)}\b", text):
                data["n_participants"] = None

    # качество источника
    journal = rec.journal_or_status if rec.source == "pubmed" else None
    data["journal_name"] = journal
    data["journal_quality"] = classify_journal(journal) if rec.source == "pubmed" else None
    coi = extract_conflicts(rec.abstract) or extract_conflicts(data.get("notes"))
    data["conflicts_of_interest"] = coi
    if rec.source == "clinicaltrials":
        status = (rec.raw or {}).get("overallStatus") or rec.journal_or_status
        data.update(enrich_nct_fields(status if isinstance(status, str) else None))

    return ExtractedStudy.model_validate(data)


def enrich_extracted_with_live_nct(
    studies: list[ExtractedStudy],
    *,
    refresh: bool = True,
) -> list[ExtractedStudy]:
    """Для ClinicalTrials записей подтягивает/нормализует live-статус NCT."""
    out: list[ExtractedStudy] = []
    for s in studies:
        if s.source != "clinicaltrials":
            out.append(s)
            continue
        if refresh:
            info = fetch_nct_status(s.source_id)
            status = info.get("status") or s.nct_status
        else:
            status = s.nct_status
        fields = enrich_nct_fields(status)
        data = s.model_dump()
        data.update(fields)
        # terminal/withdrawn/suspended — не benefit (мы уже внутри clinicaltrials)
        if data.get("nct_is_terminal"):
            data["effect_direction"] = None
            data["notes"] = (
                (data.get("notes") or "")
                + " | effect cleared: terminal/withdrawn/suspended NCT"
            ).strip(" |")
        out.append(ExtractedStudy.model_validate(data))
    return out


def parse_annotation_to_schema(
    rec: StudyRecord,
    *,
    disease_hint: str | None = None,
    use_llm: bool = True,
    llm: Any | None = None,
) -> ExtractedStudy:
    evidence_skill = load_skill("evidence_levels")
    rules = load_json_skill("mito_extraction_rules")
    if not use_llm:
        return _heuristic_extract(rec)

    prompt = f"""Skill evidence_levels:
{evidence_skill}

Mito extraction rules (JSON):
{json.dumps(rules, ensure_ascii=False)[:3500]}

Disease hint: {disease_hint or "n/a"}

Source record (official):
source={rec.source}
source_id={rec.source_id}
title={rec.title}
year={rec.year}
doi={rec.doi}
url={rec.url}
status_or_journal={rec.journal_or_status}
abstract:
{rec.abstract or ""}

Верни JSON со полями:
disease, intervention, intervention_kind (mito_therapy|standard_of_care|other|unknown),
comparator, study_type (rct|cohort|case_series|case_report|preclinical|review|meta_analysis|other|unknown),
phase, n_participants (int|null), primary_outcome, effect_summary, effect_direction
(benefit|neutral|harm|mixed|unclear|null), evidence_level (A|B|C|D|U),
population, notes, extraction_confidence (0..1).
source/source_id/title/url/doi/year НЕ меняй.
Если эффект не сказан явно — effect_direction=null.
"""
    try:
        client = llm if llm is not None else get_llm()
        raw = client.chat(prompt, system=EXTRACT_SYSTEM, temperature=0.0, max_tokens=1200)
        data = json.loads(_strip_json(raw))
        if not isinstance(data, dict):
            return _heuristic_extract(rec)
        base: dict[str, Any] = {
            "source": rec.source,
            "source_id": rec.source_id,
            "title": rec.title,
            "url": rec.url,
            "doi": rec.doi,
            "year": rec.year,
        }
        for k in ("source", "source_id", "title", "url", "doi", "year"):
            data.pop(k, None)
        base.update(data)
        extracted = ExtractedStudy.model_validate(base)
        return sanitize_extraction(extracted, rec)
    except Exception:  # noqa: BLE001
        return _heuristic_extract(rec)


def parse_many(
    records: list[StudyRecord],
    *,
    disease_hint: str | None = None,
    use_llm: bool = True,
    limit: int | None = None,
) -> list[ExtractedStudy]:
    subset = records[:limit] if limit else records
    return [
        parse_annotation_to_schema(r, disease_hint=disease_hint, use_llm=use_llm)
        for r in subset
    ]
