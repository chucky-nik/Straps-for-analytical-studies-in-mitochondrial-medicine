#!/usr/bin/env python3
"""Офлайн-тесты логики безопасности и анти-галлюцинаций (без LLM/сети)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mito_harness.agents.compare import score_directions
from mito_harness.agents.reviewer import review_report
from mito_harness.schemas import (
    ArmKind,
    DirectionLabel,
    EvidenceLevel,
    ExtractedStudy,
    StudyType,
)
from mito_harness.tools.parse import sanitize_extraction
from mito_harness.schemas import StudyRecord


def _study(**kw) -> ExtractedStudy:
    base = dict(
        source="pubmed",
        source_id="99999999",
        title="Test",
        url="https://pubmed.ncbi.nlm.nih.gov/99999999/",
        study_type=StudyType.UNKNOWN,
        evidence_level=EvidenceLevel.U,
        extraction_confidence=0.8,
    )
    base.update(kw)
    return ExtractedStudy.model_validate(base)


def test_no_data_is_insufficient() -> None:
    ranking, _ = score_directions("lhon", [])
    assert ranking
    assert all(r.score == 0 and r.label == DirectionLabel.INSUFFICIENT for r in ranking)


def test_preclinical_cannot_be_promising() -> None:
    studies = [
        _study(
            source_id="111",
            title="MitoQ in mice with Leber",
            intervention="MitoQ",
            study_type=StudyType.PRECLINICAL,
            evidence_level=EvidenceLevel.D,
            effect_direction="benefit",
            extraction_confidence=0.9,
        )
    ]
    ranking, _ = score_directions("lhon", studies)
    mitoq = next(r for r in ranking if r.direction_id == "mitoq")
    assert mitoq.n_studies >= 1
    assert mitoq.label != DirectionLabel.PROMISING
    assert mitoq.score <= 35


def test_forbidden_medical_advice_caught() -> None:
    report = (
        "Не медицинская рекомендация.\n"
        "Вам следует принимать MitoQ. PMID:111\n"
    )
    studies = [_study(source_id="111")]
    rev = review_report(report, studies, ranking=[])
    assert rev.ok is False
    assert any("принимать" in i.claim.lower() or "следует" in i.claim.lower() or i.claim for i in rev.issues)


def test_unknown_pmid_rejected() -> None:
    report = "Не медицинская рекомендация. См. PMID:12345678"
    studies = [_study(source_id="111")]
    rev = review_report(report, studies, ranking=[])
    assert rev.ok is False


def test_effect_ungrounded_cleared() -> None:
    rec = StudyRecord(
        source="pubmed",
        source_id="222",
        title="Editorial on LHON",
        abstract="No numeric outcomes reported.",
        url="https://pubmed.ncbi.nlm.nih.gov/222/",
    )
    fake = _study(
        source_id="222",
        title=rec.title,
        effect_summary="reduced mortality by 40 percent in phase 3",
        effect_direction="benefit",
        study_type=StudyType.RCT,
        evidence_level=EvidenceLevel.B,
        extraction_confidence=0.9,
    )
    cleaned = sanitize_extraction(fake, rec)
    assert cleaned.effect_direction is None
    assert cleaned.study_type != StudyType.RCT  # editorial-ish → not RCT


def test_ctgov_no_efficacy() -> None:
    rec = StudyRecord(
        source="clinicaltrials",
        source_id="NCT01234567",
        title="Phase 3 gene therapy LHON",
        abstract="Status: Recruiting",
        url="https://clinicaltrials.gov/study/NCT01234567",
        raw={"phases": ["PHASE3"]},
    )
    fake = _study(
        source="clinicaltrials",
        source_id="NCT01234567",
        title=rec.title,
        url=rec.url,
        effect_direction="benefit",
        study_type=StudyType.RCT,
        evidence_level=EvidenceLevel.B,
        extraction_confidence=0.99,
    )
    cleaned = sanitize_extraction(fake, rec)
    assert cleaned.effect_direction is None
    assert cleaned.evidence_level == EvidenceLevel.U


def test_gene_match_not_loose_nd4_alone() -> None:
    studies = [
        _study(
            source_id="333",
            title="ND4 mutation epidemiology without therapy",
            intervention=None,
            study_type=StudyType.COHORT,
            evidence_level=EvidenceLevel.C,
        )
    ]
    ranking, _ = score_directions("lhon", studies)
    gene = next(r for r in ranking if r.direction_id == "gene_mtdna")
    assert gene.n_studies == 0
    assert gene.score == 0


def test_rct_with_comparator_scores_high() -> None:
    studies = [
        _study(
            source_id="1",
            title="MitoQ randomized trial",
            intervention="MitoQ",
            study_type=StudyType.RCT,
            evidence_level=EvidenceLevel.B,
            effect_direction="benefit",
            comparator="placebo",
            extraction_confidence=0.9,
        ),
        _study(
            source_id="2",
            title="Mitoquinone RCT in LHON",
            intervention="mitoquinone",
            study_type=StudyType.RCT,
            evidence_level=EvidenceLevel.B,
            effect_direction="benefit",
            comparator="standard care",
            extraction_confidence=0.9,
        ),
        _study(
            source_id="3",
            title="MitoQ phase 2 RCT",
            intervention="MitoQ",
            study_type=StudyType.RCT,
            evidence_level=EvidenceLevel.B,
            effect_direction="benefit",
            comparator="placebo",
            extraction_confidence=0.9,
        ),
    ]
    ranking, _ = score_directions("lhon", studies)
    mitoq = next(r for r in ranking if r.direction_id == "mitoq")
    assert mitoq.score >= 65
    assert mitoq.label == DirectionLabel.PROMISING


def test_registry_only_cannot_be_promising() -> None:
    studies = [
        _study(
            source="clinicaltrials",
            source_id="NCT00000001",
            title="MitoQ Phase 2",
            url="https://clinicaltrials.gov/study/NCT00000001",
            intervention="MitoQ",
            study_type=StudyType.OTHER,
            evidence_level=EvidenceLevel.U,
            effect_direction="benefit",
            extraction_confidence=0.9,
            phase="PHASE2",
        )
    ]
    ranking, _ = score_directions("lhon", studies)
    mitoq = next(r for r in ranking if r.direction_id == "mitoq")
    assert mitoq.score <= 45
    assert mitoq.label != DirectionLabel.PROMISING


def test_nad_matches_nmn_token() -> None:
    studies = [
        _study(
            source_id="44",
            title="NMN supplementation in aging muscle",
            intervention="NMN",
            study_type=StudyType.RCT,
            evidence_level=EvidenceLevel.B,
        )
    ]
    ranking, _ = score_directions("sarcopenia", studies)
    nad = next(r for r in ranking if r.direction_id == "nad_precursors")
    assert nad.n_studies == 1


def test_sanitize_does_not_break_prescription_word() -> None:
    from mito_harness.agents.reviewer import sanitize_report_text
    from mito_harness.schemas import ReviewIssue

    text = "Не medical recommendation. This prescription note mentions prescribe carefully."
    issues = [
        ReviewIssue(
            severity="error",
            claim="prescribe",
            reason="forbidden",
            action="remove",
        )
    ]
    out = sanitize_report_text(text, issues)
    assert "prescription" in out
    assert "[removed: unsafe/unverified]" in out


def test_publication_type_case_report() -> None:
    from mito_harness.tools.parse import _classify_type

    rec = StudyRecord(
        source="pubmed",
        source_id="34491178",
        title="Bilateral improvement after gene therapy",
        abstract="A patient showed bilateral improvement.",
        url="https://pubmed.ncbi.nlm.nih.gov/34491178/",
        raw={"publication_types": ["Case Reports", "Journal Article"]},
    )
    st = _classify_type(rec, f"{rec.title}\n{rec.abstract}".lower())
    assert st == StudyType.CASE_REPORT


def test_infographic_is_other_not_review() -> None:
    from mito_harness.tools.parse import _classify_type

    rec = StudyRecord(
        source="pubmed",
        source_id="40670631",
        title="Infographic: landmark trials in neuro-ophthalmology",
        abstract="Summary of REVERSE trial.",
        url="https://pubmed.ncbi.nlm.nih.gov/40670631/",
        raw={"publication_types": ["Review"]},
    )
    st = _classify_type(rec, f"{rec.title}\n{rec.abstract}".lower())
    assert st == StudyType.OTHER


def test_clinical_observation_bilateral_improvement() -> None:
    from mito_harness.tools.parse import _classify_type

    rec = StudyRecord(
        source="pubmed",
        source_id="34491178",
        title="Leber hereditary optic neuropathy: Bilateral improvement of visual acuity following gene therapy by unilateral injection",
        abstract="Visual acuity improved in patients.",
        url="https://pubmed.ncbi.nlm.nih.gov/34491178/",
        raw={"publication_types": ["Journal Article"]},
    )
    st = _classify_type(rec, f"{rec.title}\n{rec.abstract}".lower())
    assert st == StudyType.CASE_REPORT


def test_journal_quality_and_coi() -> None:
    from mito_harness.tools.quality import classify_journal, extract_conflicts, nct_status_bucket

    assert classify_journal("Nature Medicine") == "trusted"
    assert classify_journal("OMICS International Fake Journal") == "suspect"
    assert classify_journal("Some Local Journal") == "unknown"
    coi = extract_conflicts("Conflicts of interest: authors are employees of PharmaCo.")
    assert coi and "employees" in coi.lower()
    assert nct_status_bucket("Terminated") == "terminal"
    assert nct_status_bucket("Recruiting") == "active"
    assert nct_status_bucket("Completed") == "completed"


def test_terminal_nct_cannot_be_promising() -> None:
    studies = [
        _study(
            source="clinicaltrials",
            source_id="NCT09999999",
            title="MitoQ Phase 3",
            url="https://clinicaltrials.gov/study/NCT09999999",
            intervention="MitoQ",
            study_type=StudyType.OTHER,
            evidence_level=EvidenceLevel.U,
            phase="PHASE3",
            nct_status="Terminated",
            nct_status_bucket="terminal",
            nct_is_terminal=True,
            extraction_confidence=0.9,
        )
    ]
    ranking, _ = score_directions("lhon", studies)
    mitoq = next(r for r in ranking if r.direction_id == "mitoq")
    assert mitoq.label != DirectionLabel.PROMISING
    assert mitoq.score <= 45


def test_gold_extraction_metrics() -> None:
    from mito_harness.eval_metrics import evaluate_extraction

    result = evaluate_extraction(use_llm=False)
    assert result.n >= 5
    assert result.accuracy_study_type >= 0.66
    assert result.accuracy_intervention_kind >= 0.5


def test_terminal_nct_title_efficacy_not_review_error() -> None:
    """Слово Efficacy в названии terminated NCT не должно валить review_ok."""
    from mito_harness.agents.reviewer import review_report

    studies = [
        _study(
            source="clinicaltrials",
            source_id="NCT05820152",
            title="Evaluate Efficacy of Gene Therapy",
            url="https://clinicaltrials.gov/study/NCT05820152",
            intervention="gene therapy",
            study_type=StudyType.OTHER,
            evidence_level=EvidenceLevel.U,
            nct_status="Terminated",
            nct_status_bucket="terminal",
            nct_is_terminal=True,
            extraction_confidence=0.9,
        )
    ]
    report = (
        "# Demo\n\n"
        "- [NCT05820152](https://clinicaltrials.gov/study/NCT05820152) — "
        "Evaluate the Efficacy of Gene Therapy (nct_status=TERMINATED/terminal)\n\n"
        "Это исследовательский обзор, не медицинская рекомендация.\n"
    )
    rev = review_report(report, studies, ranking=[])
    assert rev.ok, [i.model_dump() for i in rev.issues if i.severity == "error"]
    assert any(i.claim.startswith("nct_terminal:") for i in rev.issues)


def test_pubmed_ungrounded_effect_is_cleared() -> None:
    """Опровержение ревью #5: для PubMed effect_direction очищается, CT.gov-ветка не мешает."""
    rec = StudyRecord(
        source="pubmed",
        source_id="555",
        title="MitoQ in mice with LHON-like phenotype",
        abstract="Animal model study without clinical outcomes wording.",
        url="https://pubmed.ncbi.nlm.nih.gov/555/",
    )
    fake = _study(
        source_id="555",
        title=rec.title,
        effect_summary="patients showed dramatic clinical benefit in phase 3",
        effect_direction="benefit",
        study_type=StudyType.PRECLINICAL,
        evidence_level=EvidenceLevel.D,
        extraction_confidence=0.95,
    )
    cleaned = sanitize_extraction(fake, rec)
    assert cleaned.effect_direction is None


def test_effect_grounded_not_substring() -> None:
    from mito_harness.tools.parse import _effect_grounded

    assert _effect_grounded("clinical benefit observed", "unbeneficial signal in assay") is False
    assert _effect_grounded("visual acuity improved", "visual acuity improved in patients") is True


def test_comparator_na_not_comparative() -> None:
    from mito_harness.agents.compare import _has_human_comparative_signal

    bad = [
        _study(
            source_id="1",
            study_type=StudyType.RCT,
            evidence_level=EvidenceLevel.B,
            effect_direction="benefit",
            comparator="n/a",
            intervention="MitoQ",
        )
    ]
    good = [
        _study(
            source_id="2",
            study_type=StudyType.RCT,
            evidence_level=EvidenceLevel.B,
            effect_direction="benefit",
            comparator="placebo",
            intervention="MitoQ",
        )
    ]
    assert _has_human_comparative_signal(bad) is False
    assert _has_human_comparative_signal(good) is True


def test_clinical_trial_pubtype_without_random_is_other_or_cohort() -> None:
    from mito_harness.tools.parse import _classify_type

    rec = StudyRecord(
        source="pubmed",
        source_id="777",
        title="Open-label gene therapy study",
        abstract="Single-arm clinical trial without randomization mentioned.",
        url="https://pubmed.ncbi.nlm.nih.gov/777/",
        raw={"publication_types": ["Clinical Trial"]},
    )
    st = _classify_type(rec, f"{rec.title}\n{rec.abstract}".lower())
    assert st in {StudyType.OTHER, StudyType.COHORT}
    assert st != StudyType.RCT


def test_nad_nr_not_nrf2_false_positive() -> None:
    """«NR» как токен ок; NRF2 / NR4A1 не должны матчить nad_precursors."""
    from mito_harness.agents.compare import _match_therapy
    from mito_harness.catalog import THERAPIES

    therapy = THERAPIES["nad_precursors"]
    nrf = _study(
        source_id="1",
        title="NRF2 activation in Parkinson disease",
        intervention="NRF2 agonist",
    )
    nr = _study(
        source_id="2",
        title="Nicotinamide riboside (NR) trial in PD",
        intervention="NR",
    )
    assert _match_therapy(nrf, therapy, "parkinson") is False
    assert _match_therapy(nr, therapy, "parkinson") is True


def test_sanitize_keeps_both_clear_reasons() -> None:
    rec = StudyRecord(
        source="pubmed",
        source_id="888",
        title="Editorial note",
        abstract="No outcomes.",
        url="https://pubmed.ncbi.nlm.nih.gov/888/",
    )
    fake = _study(
        source_id="888",
        title=rec.title,
        effect_summary="mortality reduced by 47% in phase 3",
        effect_direction="benefit",
        study_type=StudyType.OTHER,
        extraction_confidence=0.9,
    )
    cleaned = sanitize_extraction(fake, rec)
    assert cleaned.effect_direction is None
    assert cleaned.effect_summary is None
    assert "effect_ungrounded_cleared" in (cleaned.notes or "")
    assert "numeric_effect_ungrounded_cleared" in (cleaned.notes or "")


def test_query_sanitize_keeps_curiosity() -> None:
    from mito_harness.agents.report import _sanitize_query_for_report

    q = _sanitize_query_for_report("curiosity about MitoQ safety profile")
    assert "curiosity" in q.lower()
    assert "[removed: unsafe-query]" not in q
    bad = _sanitize_query_for_report("MitoQ cures Parkinson guaranteed")
    assert "cures" not in bad.lower() or "[removed" in bad


def main() -> int:
    tests = [
        test_no_data_is_insufficient,
        test_preclinical_cannot_be_promising,
        test_forbidden_medical_advice_caught,
        test_unknown_pmid_rejected,
        test_effect_ungrounded_cleared,
        test_ctgov_no_efficacy,
        test_gene_match_not_loose_nd4_alone,
        test_rct_with_comparator_scores_high,
        test_registry_only_cannot_be_promising,
        test_nad_matches_nmn_token,
        test_sanitize_does_not_break_prescription_word,
        test_publication_type_case_report,
        test_infographic_is_other_not_review,
        test_clinical_observation_bilateral_improvement,
        test_journal_quality_and_coi,
        test_terminal_nct_cannot_be_promising,
        test_gold_extraction_metrics,
        test_terminal_nct_title_efficacy_not_review_error,
        test_pubmed_ungrounded_effect_is_cleared,
        test_effect_grounded_not_substring,
        test_comparator_na_not_comparative,
        test_clinical_trial_pubtype_without_random_is_other_or_cohort,
        test_nad_nr_not_nrf2_false_positive,
        test_sanitize_keeps_both_clear_reasons,
        test_query_sanitize_keeps_curiosity,
    ]
    failed = 0
    for fn in tests:
        try:
            fn()
            print(f"OK  {fn.__name__}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"FAIL {fn.__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
