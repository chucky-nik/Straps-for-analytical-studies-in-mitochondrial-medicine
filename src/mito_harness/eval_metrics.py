"""Метрики извлечения на небольшой ручной разметке + сравнение двух LLM."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mito_harness.config import settings
from mito_harness.schemas import (
    ArmKind,
    ExtractionEvalResult,
    LlmCompareResult,
    StudyRecord,
    StudyType,
)
from mito_harness.tools.parse import parse_annotation_to_schema


def gold_path() -> Path:
    return Path(settings()["root"]) / "data" / "gold_extraction.json"


def load_gold() -> list[dict[str, Any]]:
    path = gold_path()
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return list(data.get("items", []))


def evaluate_extraction(*, use_llm: bool = False) -> ExtractionEvalResult:
    items = load_gold()
    if not items:
        return ExtractionEvalResult()

    ok_type = 0
    ok_kind = 0
    details: list[dict[str, Any]] = []
    for item in items:
        rec = StudyRecord.model_validate(item["record"])
        pred = parse_annotation_to_schema(rec, use_llm=use_llm)
        exp_type = item["expected"]["study_type"]
        exp_kind = item["expected"]["intervention_kind"]
        type_ok = pred.study_type.value == exp_type
        kind_ok = pred.intervention_kind.value == exp_kind
        ok_type += int(type_ok)
        ok_kind += int(kind_ok)
        details.append(
            {
                "id": rec.source_id,
                "pred_type": pred.study_type.value,
                "exp_type": exp_type,
                "pred_kind": pred.intervention_kind.value,
                "exp_kind": exp_kind,
                "type_ok": type_ok,
                "kind_ok": kind_ok,
            }
        )
    n = len(items)
    return ExtractionEvalResult(
        n=n,
        accuracy_study_type=ok_type / n,
        accuracy_intervention_kind=ok_kind / n,
        details=details,
    )


def compare_two_llms_on_records(
    records: list[StudyRecord],
    *,
    limit: int = 3,
    disease_hint: str | None = None,
) -> LlmCompareResult:
    """Сравнивает primary vs fallback модель на одних и тех же abstracts."""
    from mito_harness.config import settings as get_settings
    from mito_harness.llm.client import LLMClient

    s = get_settings()
    primary_model = s["neural_deep_model"]
    fallback_model = s["llm7_model"]
    subset = [r for r in records if r.abstract][:limit]
    if not subset or not s["neural_deep_api_key"] or not s["llm7_api_key"]:
        return LlmCompareResult(
            n_compared=0,
            primary_model=primary_model or "not_configured",
            fallback_model=fallback_model or "not_configured",
        )

    class _PrimaryOnly(LLMClient):
        def __init__(self) -> None:
            super().__init__()
            self.fallback = None

    class _FallbackOnly(LLMClient):
        def __init__(self) -> None:
            super().__init__()
            self.primary = self.fallback
            self.primary_model = self.fallback_model
            self.fallback = None

    primary_client = _PrimaryOnly()
    fallback_client = _FallbackOnly()

    samples: list[dict[str, Any]] = []
    agree_type = 0
    agree_eff = 0
    for rec in subset:
        a = parse_annotation_to_schema(
            rec, disease_hint=disease_hint, use_llm=True, llm=primary_client
        )
        b = parse_annotation_to_schema(
            rec, disease_hint=disease_hint, use_llm=True, llm=fallback_client
        )
        same_type = a.study_type == b.study_type
        same_eff = a.effect_direction == b.effect_direction
        agree_type += int(same_type)
        agree_eff += int(same_eff)
        samples.append(
            {
                "source_id": rec.source_id,
                "primary": {
                    "study_type": a.study_type.value,
                    "effect_direction": a.effect_direction,
                },
                "fallback": {
                    "study_type": b.study_type.value,
                    "effect_direction": b.effect_direction,
                },
                "agree_type": same_type,
                "agree_effect": same_eff,
            }
        )

    n = len(samples)
    return LlmCompareResult(
        n_compared=n,
        agreement_study_type=(agree_type / n) if n else 0.0,
        agreement_effect_direction=(agree_eff / n) if n else 0.0,
        primary_model=primary_model,
        fallback_model=fallback_model,
        samples=samples,
    )


# re-export enums for gold authoring clarity
__all__ = [
    "evaluate_extraction",
    "compare_two_llms_on_records",
    "load_gold",
    "StudyType",
    "ArmKind",
]
