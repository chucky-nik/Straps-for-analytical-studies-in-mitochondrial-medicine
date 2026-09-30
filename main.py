#!/usr/bin/env python3
"""Воспроизводимый прогон Harness (демо: LHON; можно передать другое заболевание).

Примеры:
  PYTHONPATH=src python main.py
  PYTHONPATH=src python main.py --disease parkinson
  PYTHONPATH=src python main.py --list-diseases
  PYTHONPATH=src python main.py --query "MitoQ при саркопении" --no-llm-extract
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from mito_harness.agents.orchestrator import DEFAULT_QUERY, Orchestrator
from mito_harness.catalog import list_diseases
from mito_harness.config import settings
from mito_harness.logging_util import RunLogger


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Harness: analytical studies in mitochondrial medicine"
    )
    parser.add_argument("--query", type=str, default=None, help="Исследовательский запрос")
    parser.add_argument(
        "--disease",
        type=str,
        default=None,
        help="id заболевания: lhon|primary_mito|parkinson|heart_failure|sarcopenia|iri",
    )
    parser.add_argument("--list-diseases", action="store_true")
    parser.add_argument("--max-pubmed", type=int, default=10)
    parser.add_argument("--max-ctgov", type=int, default=6)
    parser.add_argument(
        "--no-llm-extract",
        action="store_true",
        help="Только эвристическое извлечение (без LLM)",
    )
    parser.add_argument(
        "--with-llm-extract",
        action="store_true",
        help="Принудительно LLM-извлечение",
    )
    parser.add_argument(
        "--compare-llms",
        action="store_true",
        help="Сравнить primary/fallback LLM на нескольких abstracts (бонус ТЗ)",
    )
    parser.add_argument(
        "--skip-extraction-eval",
        action="store_true",
        help="Не считать метрики на data/gold_extraction.json",
    )
    args = parser.parse_args()

    if args.list_diseases:
        for d in list_diseases():
            print(f"{d['id']:16} {d['name_ru']}")
        return 0

    logger = RunLogger()
    orch = Orchestrator(logger)
    use_llm = None
    if args.no_llm_extract:
        use_llm = False
    elif args.with_llm_extract:
        use_llm = True

    result = orch.run(
        args.query or DEFAULT_QUERY,
        disease_id=args.disease,
        max_pubmed=args.max_pubmed,
        max_ctgov=args.max_ctgov,
        use_llm_extract=use_llm,
        compare_llms=args.compare_llms,
        run_extraction_eval=not args.skip_extraction_eval,
    )

    log_path = settings()["reports_dir"] / f"run_log_{result.disease_id}.json"
    logger.save(log_path)

    summary = {
        "disease": result.disease_name,
        "raw_studies": result.studies_raw_count,
        "extracted": len(result.studies_extracted),
        "top": [
            {"name": r.direction_name, "score": r.score, "ids": r.supporting_ids}
            for r in result.ranking[:3]
        ],
        "figure": result.figure_path,
        "report": result.report_path,
        "review_ok": result.review.ok if result.review else None,
        "skills": result.skills_used,
        "log": str(log_path),
        "extraction_eval": result.extraction_eval.model_dump() if result.extraction_eval else None,
        "llm_compare": result.llm_compare.model_dump() if result.llm_compare else None,
    }
    print("\n=== SUMMARY ===")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
