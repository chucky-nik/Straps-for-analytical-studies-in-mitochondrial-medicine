#!/usr/bin/env python3
"""Сравнение двух LLM на одинаковых PubMed abstracts (бонус ТЗ)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mito_harness.catalog import DISEASES
from mito_harness.eval_metrics import compare_two_llms_on_records
from mito_harness.tools.pubmed import pubmed_search


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--disease", default="lhon")
    parser.add_argument("--limit", type=int, default=3)
    args = parser.parse_args()
    disease = DISEASES[args.disease]
    records = pubmed_search(disease["pubmed_query"], max_results=max(args.limit, 5))
    result = compare_two_llms_on_records(
        records, limit=args.limit, disease_hint=disease["name_en"]
    )
    print(json.dumps(result.model_dump(), ensure_ascii=False, indent=2))
    return 0 if result.n_compared else 1


if __name__ == "__main__":
    raise SystemExit(main())
