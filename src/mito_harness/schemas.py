from __future__ import annotations

from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator


class StudyType(str, Enum):
    RCT = "rct"
    COHORT = "cohort"
    CASE_SERIES = "case_series"
    CASE_REPORT = "case_report"
    PRECLINICAL = "preclinical"
    REVIEW = "review"
    META_ANALYSIS = "meta_analysis"
    OTHER = "other"
    UNKNOWN = "unknown"


class EvidenceLevel(str, Enum):
    """Уровни по skill evidence_levels (упрощённая шкала)."""

    A = "A"  # метаанализ РКИ / крупные РКИ
    B = "B"  # РКИ / качественные когорты
    C = "C"  # малые когорты / серии случаев
    D = "D"  # доклиника / кейсы / мнения
    U = "U"  # неизвестно


class ArmKind(str, Enum):
    MITO = "mito_therapy"
    STANDARD = "standard_of_care"
    OTHER = "other"
    UNKNOWN = "unknown"


class StudyRecord(BaseModel):
    """Сырая запись из официального источника (истина по ссылке)."""

    source: Literal["pubmed", "clinicaltrials"]
    source_id: str = Field(..., description="PMID или NCT ID")
    title: str
    year: Optional[int] = None
    abstract: Optional[str] = None
    doi: Optional[str] = None
    url: str
    journal_or_status: Optional[str] = None
    raw: dict[str, Any] = Field(default_factory=dict)


class ExtractedStudy(BaseModel):
    """Структурированное извлечение. Пустые поля = null, без домыслов."""

    source: Literal["pubmed", "clinicaltrials"]
    source_id: str
    title: str
    url: str
    doi: Optional[str] = None
    year: Optional[int] = None
    disease: Optional[str] = None
    intervention: Optional[str] = None
    intervention_kind: ArmKind = ArmKind.UNKNOWN
    comparator: Optional[str] = None
    study_type: StudyType = StudyType.UNKNOWN
    phase: Optional[str] = None
    n_participants: Optional[int] = None
    primary_outcome: Optional[str] = None
    effect_summary: Optional[str] = None
    effect_direction: Optional[
        Literal["benefit", "neutral", "harm", "mixed", "unclear"]
    ] = None
    evidence_level: EvidenceLevel = EvidenceLevel.U
    population: Optional[str] = None
    notes: Optional[str] = None
    extraction_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    # Сигналы качества / безопасности интерпретации
    conflicts_of_interest: Optional[str] = None
    journal_name: Optional[str] = None
    journal_quality: Optional[Literal["trusted", "suspect", "unknown"]] = None
    nct_status: Optional[str] = None
    nct_status_bucket: Optional[
        Literal["active", "completed", "terminal", "other", "unknown", "missing", "error"]
    ] = None
    nct_is_terminal: bool = False
    nct_is_active: bool = False

    @field_validator("source_id")
    @classmethod
    def non_empty_id(cls, v: str) -> str:
        if not v or not str(v).strip():
            raise ValueError("source_id required")
        return str(v).strip()


class DirectionLabel(str, Enum):
    PROMISING = "promising"
    UNCERTAIN = "uncertain"
    INSUFFICIENT = "insufficient"
    NOT_PROMISING = "not_promising"


class DirectionScore(BaseModel):
    direction_id: str
    direction_name: str
    disease_id: str
    score: float = Field(..., ge=0.0, le=100.0)
    evidence_level_best: EvidenceLevel = EvidenceLevel.U
    n_studies: int = 0
    label: DirectionLabel = DirectionLabel.INSUFFICIENT
    rationale: str
    supporting_ids: list[str] = Field(default_factory=list)
    claims_superior_to_soc: bool = False


class ReviewIssue(BaseModel):
    severity: Literal["error", "warning", "info"]
    claim: str
    reason: str
    action: Literal["remove", "fix", "flag", "keep"] = "flag"


class ReviewResult(BaseModel):
    ok: bool
    issues: list[ReviewIssue] = Field(default_factory=list)
    verified_source_ids: list[str] = Field(default_factory=list)


class LlmCompareResult(BaseModel):
    n_compared: int = 0
    agreement_study_type: float = 0.0
    agreement_effect_direction: float = 0.0
    primary_model: str = ""
    fallback_model: str = ""
    samples: list[dict[str, Any]] = Field(default_factory=list)


class ExtractionEvalResult(BaseModel):
    n: int = 0
    accuracy_study_type: float = 0.0
    accuracy_intervention_kind: float = 0.0
    details: list[dict[str, Any]] = Field(default_factory=list)


class HarnessResult(BaseModel):
    query: str
    disease_id: str
    disease_name: str
    plan: list[str]
    studies_raw_count: int
    studies_extracted: list[ExtractedStudy]
    ranking: list[DirectionScore]
    figure_path: Optional[str] = None
    report_path: Optional[str] = None
    review: Optional[ReviewResult] = None
    limitations: list[str] = Field(default_factory=list)
    skills_used: list[str] = Field(default_factory=list)
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    llm_compare: Optional[LlmCompareResult] = None
    extraction_eval: Optional[ExtractionEvalResult] = None
