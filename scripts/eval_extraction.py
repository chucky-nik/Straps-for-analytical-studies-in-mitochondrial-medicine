#!/usr/bin/env python3
"""Метрики качества извлечения на ручной разметке data/gold_extraction.json."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mito_harness.eval_metrics import evaluate_extraction


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--with-llm", action="store_true")
    args = parser.parse_args()
    result = evaluate_extraction(use_llm=args.with_llm)
    print(json.dumps(result.model_dump(), ensure_ascii=False, indent=2))
    if result.n == 0:
        print("No gold items found", file=sys.stderr)
        return 1
    # мягкий порог для эвристик
    if result.accuracy_study_type < 0.5:
        print("WARN: study_type accuracy < 0.5", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
