"""CompareAgent: консервативный рейтинг (skills evidence + prospect + safety)."""

from __future__ import annotations

import re

from mito_harness.catalog import therapies_for_disease
from mito_harness.schemas import (
    ArmKind,
    DirectionLabel,
    DirectionScore,
    EvidenceLevel,
    ExtractedStudy,
    StudyType,
)
from mito_harness.skills_loader import load_json_skill, load_skill

_LEVEL_BASE = {
    EvidenceLevel.A: 40.0,
    EvidenceLevel.B: 30.0,
    EvidenceLevel.C: 18.0,
    EvidenceLevel.D: 8.0,
    EvidenceLevel.U: 4.0,
}

_LEVEL_RANK = {
    EvidenceLevel.A: 5,
    EvidenceLevel.B: 4,
    EvidenceLevel.C: 3,
    EvidenceLevel.D: 2,
    EvidenceLevel.U: 1,
}

_HUMAN_TYPES = {StudyType.RCT, StudyType.COHORT, StudyType.META_ANALYSIS, StudyType.CASE_SERIES}


def _blob(study: ExtractedStudy) -> str:
    return " ".join(
        filter(None, [study.intervention, study.title, study.effect_summary, study.notes])
    ).lower()


def _match_therapy(study: ExtractedStudy, therapy: dict, disease_id: str) -> bool:
    """Строгий матч: без ложных срабатываний на общие токены."""
    blob = _blob(study)
    tid = therapy["id"]

    shortcuts = {
        "mitoq": ["mitoq", "mitoquinone"],
        "skq1": ["skq1", "visomitin"],
        "ss31": ["elamipretide", "ss-31", "ss31", "bendavia"],
        "urolithin_a": ["urolithin a", "urolithin-a", "urolithin"],
        "nad_precursors": [
            "nicotinamide riboside",
            "nicotinamide mononucleotide",
            "nad+ precursor",
            " nmn ",
            " nr ",
        ],
        "mito_transplant": [
            "mitochondrial transplantation",
            "mitochondrial replacement",
            "spindle transfer",
        ],
    }

    if tid == "gene_mtdna":
        agents = ("lenadogene", "lumevoq", "raav2/2-nd4", "raav2", "allotopic")
        has_named_agent = any(a in blob for a in agents)
        has_gene_nd4 = "gene therapy" in blob and "nd4" in blob
        has_gene_lhon_ctx = "gene therapy" in blob and any(
            x in blob for x in ("lhon", "leber", "optic")
        )
        if disease_id == "lhon":
            # болезнь уже в запросе — достаточно агента или gene therapy+ND4/LHON-контекста
            return has_named_agent or has_gene_nd4 or has_gene_lhon_ctx
        return (has_named_agent or has_gene_nd4) and any(
            x in blob for x in ("lhon", "leber", "nd4", "optic neuropath")
        )

    if tid == "nad_precursors":
        # "nr"/"nmn" только как отдельные токены с пробелами — не NRF2/NR4A1
        padded = f" {re.sub(r'[^a-z0-9+]+', ' ', blob)} "
        tokens = [
            "nicotinamide riboside",
            "nicotinamide mononucleotide",
            "nad+ precursor",
            "nad precursor",
            " nmn ",
            " nr ",
        ]
        return any(t in padded for t in tokens)

    tokens = shortcuts.get(tid, [])
    if any(t in blob for t in tokens):
        return True

    name = therapy["name"].split("(")[0].strip().lower()
    if len(name) >= 5 and name in blob:
        return True
    return False


def _best_level(levels: list[EvidenceLevel]) -> EvidenceLevel:
    if not levels:
        return EvidenceLevel.U
    return max(levels, key=lambda x: _LEVEL_RANK[x])


def _assign_label(
    *,
    score: float,
    n: int,
    best: EvidenceLevel,
    harm: bool,
) -> DirectionLabel:
    if harm and n > 0:
        return DirectionLabel.NOT_PROMISING
    if n == 0 or score < 40:
        return DirectionLabel.INSUFFICIENT
    if score >= 65 and best in {EvidenceLevel.A, EvidenceLevel.B, EvidenceLevel.C}:
        return DirectionLabel.PROMISING
    if 40 <= score < 65 or best in {EvidenceLevel.D, EvidenceLevel.U}:
        return DirectionLabel.UNCERTAIN
    return DirectionLabel.INSUFFICIENT


_BAD_COMPARATORS = {
    "",
    "n/a",
    "na",
    "none",
    "null",
    "unknown",
    "not reported",
    "not applicable",
    "-",
    "—",
}

_COMPARATOR_MARKERS = (
    "placebo",
    "sham",
    "control",
    "standard",
    "usual care",
    "soc",
    "vehicle",
    "comparator",
    "idebenone",
    "levodopa",
    "active",
)


def _comparator_is_meaningful(comparator: str | None) -> bool:
    if not comparator:
        return False
    c = comparator.strip().lower()
    if c in _BAD_COMPARATORS or len(c) < 3:
        return False
    # явный маркер компаратора ИЛИ достаточно длинная конкретная терапия/ветка
    if any(m in c for m in _COMPARATOR_MARKERS):
        return True
    return len(c) >= 6 and c not in {"other", "study", "group", "arm"}


def _has_human_comparative_signal(matched: list[ExtractedStudy]) -> bool:
    return any(
        _comparator_is_meaningful(s.comparator)
        and s.effect_direction == "benefit"
        and s.study_type in {StudyType.RCT, StudyType.META_ANALYSIS}
        and s.source == "pubmed"
        for s in matched
    )


def score_directions(
    disease_id: str,
    studies: list[ExtractedStudy],
) -> tuple[list[DirectionScore], list[str]]:
    skills = ["evidence_levels", "prospect_criteria", "safety_guardrails", "mito_extraction_rules"]
    _ = load_skill("evidence_levels")
    _ = load_skill("prospect_criteria")
    _ = load_skill("safety_guardrails")
    rules = load_json_skill("mito_extraction_rules")
    assert "forbidden_claims" in rules

    therapies = therapies_for_disease(disease_id)
    ranking: list[DirectionScore] = []

    for therapy in therapies:
        matched = [s for s in studies if _match_therapy(s, therapy, disease_id)]

        # нет данных — нулевой score, без «ложной перспективности»
        if not matched:
            ranking.append(
                DirectionScore(
                    direction_id=therapy["id"],
                    direction_name=therapy["name"],
                    disease_id=disease_id,
                    score=0.0,
                    evidence_level_best=EvidenceLevel.U,
                    n_studies=0,
                    label=DirectionLabel.INSUFFICIENT,
                    rationale="n=0; insufficient_data — нет PMID/NCT по направлению в этом прогоне",
                    supporting_ids=[],
                    claims_superior_to_soc=False,
                )
            )
            continue

        # CT.gov без pubmed-публикации: не считаем доказанным benefit
        pubmed_matched = [s for s in matched if s.source == "pubmed"]
        levels = [s.evidence_level for s in matched]
        best = _best_level(levels)
        score = _LEVEL_BASE[best]
        score += min(len(matched), 5) * 4

        human_benefit = any(
            s.effect_direction == "benefit"
            and s.study_type in _HUMAN_TYPES
            and s.source == "pubmed"
            and (s.extraction_confidence or 0) >= 0.45
            for s in matched
        )
        preclin_benefit = any(
            s.effect_direction == "benefit" and s.study_type == StudyType.PRECLINICAL
            for s in matched
        )
        harm = any(s.effect_direction == "harm" for s in matched)

        if human_benefit:
            score += 15
        elif preclin_benefit:
            score += 5  # сознательно мало
        if harm:
            score -= 25
        if any(s.comparator for s in pubmed_matched):
            score += 8

        # фаза III на CT.gov даёт небольшой бонус дизайна, не «эффективности»
        if any(
            s.source == "clinicaltrials"
            and s.phase
            and ("III" in s.phase.upper() or "PHASE3" in s.phase.upper().replace(" ", ""))
            for s in matched
        ):
            score += 6

        only_preclin = all(s.study_type == StudyType.PRECLINICAL for s in matched)
        only_ct = all(s.source == "clinicaltrials" for s in matched)
        only_reviewish = all(
            s.study_type in {StudyType.REVIEW, StudyType.UNKNOWN, StudyType.OTHER} for s in matched
        )

        if only_preclin:
            score = min(score, 35.0)  # потолок: не «promising»
        if only_ct:
            score = min(score, 45.0)  # реестр ≠ доказанный исход
        if only_reviewish and not human_benefit:
            score = min(score, 40.0)

        # Late-phase registry (Phase 3) + несколько записей → минимум uncertain,
        # но НЕ promising без human PubMed interventional/outcome данных.
        late_phase_ct = any(
            s.source == "clinicaltrials"
            and s.phase
            and ("III" in s.phase.upper() or "PHASE3" in s.phase.upper().replace(" ", ""))
            for s in matched
        )
        if late_phase_ct and len(matched) >= 2 and not harm and not only_preclin:
            score = max(score, 42.0)

        # штраф: доклиника при сильном SoC в выборке
        has_human_soc = any(
            s.intervention_kind == ArmKind.STANDARD and s.study_type in _HUMAN_TYPES
            for s in studies
        )
        if only_preclin and has_human_soc:
            score -= 10

        # Штрафы качества источника (COI / suspect journal / terminal NCT)
        n_matched = len(matched) or 1
        n_suspect = sum(1 for s in matched if s.journal_quality == "suspect")
        if n_suspect:
            # пропорционально доле suspect в matched (макс −12)
            score -= 12.0 * (n_suspect / n_matched)
        if any(s.conflicts_of_interest for s in matched):
            score -= 3  # не дисквалификация, но осторожность
        if any(s.nct_is_terminal for s in matched):
            score -= 15
        terminal_only = bool(matched) and all(
            (s.source == "clinicaltrials" and s.nct_is_terminal) or s.source != "clinicaltrials"
            for s in matched
        ) and any(s.nct_is_terminal for s in matched)
        if terminal_only and all(s.source == "clinicaltrials" for s in matched):
            score = min(score, 25.0)

        score = max(0.0, min(100.0, score))
        superior = _has_human_comparative_signal(matched)

        label = _assign_label(score=score, n=len(matched), best=best, harm=harm)
        has_solid_human = any(
            s.source == "pubmed"
            and s.study_type in {StudyType.RCT, StudyType.COHORT, StudyType.META_ANALYSIS}
            and s.journal_quality != "suspect"
            for s in matched
        )
        # safety: promising только при человеческих interventional/observational данных в PubMed
        if label == DirectionLabel.PROMISING and (
            best not in {EvidenceLevel.A, EvidenceLevel.B, EvidenceLevel.C} or not has_solid_human
        ):
            label = DirectionLabel.UNCERTAIN
            score = min(score, 64.0)
        if any(s.nct_is_terminal for s in matched) and label == DirectionLabel.PROMISING:
            label = DirectionLabel.UNCERTAIN
            score = min(score, 50.0)
        # late-phase без solid human outcomes → uncertain, не insufficient
        if (
            label == DirectionLabel.INSUFFICIENT
            and late_phase_ct
            and len(matched) >= 2
            and not harm
            and not any(s.nct_is_terminal for s in matched)
        ):
            label = DirectionLabel.UNCERTAIN
            score = max(score, 42.0)

        n_coi = sum(1 for s in matched if s.conflicts_of_interest)
        n_suspect = sum(1 for s in matched if s.journal_quality == "suspect")
        n_terminal = sum(1 for s in matched if s.nct_is_terminal)
        rationale = (
            f"n={len(matched)}; best={best.value}; label={label.value}; "
            f"human_benefit={human_benefit}; preclinical_only={only_preclin}; "
            f"registry_only={only_ct}; superior_to_soc_supported={superior}; "
            f"coi={n_coi}; journal_suspect={n_suspect}; nct_terminal={n_terminal}"
        )
        ranking.append(
            DirectionScore(
                direction_id=therapy["id"],
                direction_name=therapy["name"],
                disease_id=disease_id,
                score=score,
                evidence_level_best=best,
                n_studies=len(matched),
                label=label,
                rationale=rationale,
                supporting_ids=[s.source_id for s in matched],
                claims_superior_to_soc=superior,
            )
        )

    ranking.sort(key=lambda x: (x.score, x.n_studies), reverse=True)
    return ranking, skills
