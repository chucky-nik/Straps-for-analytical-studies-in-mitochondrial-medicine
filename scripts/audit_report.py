#!/usr/bin/env python3
"""Доп. аудит готового отчёта: живая проверка PMID/NCT + статус NCT."""

from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mito_harness.tools.quality import fetch_nct_status  # noqa: E402

PUBMED_ESUMMARY = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"


def check_pmid(pmid: str) -> bool:
    try:
        r = httpx.get(
            PUBMED_ESUMMARY,
            params={"db": "pubmed", "id": pmid, "retmode": "json"},
            timeout=30.0,
        )
        r.raise_for_status()
        result = r.json().get("result", {})
        return pmid in result and isinstance(result.get(pmid), dict)
    except Exception:  # noqa: BLE001
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit PMID/NCT in a markdown report")
    parser.add_argument("report", type=Path)
    args = parser.parse_args()
    text = args.report.read_text(encoding="utf-8")

    pmids = sorted(set(re.findall(r"PMID:?\s*(\d+)", text, flags=re.I)))
    pmids += re.findall(r"pubmed\.ncbi\.nlm\.nih\.gov/(\d+)", text)
    pmids += re.findall(r"\[(\d{6,9})\]\(https://pubmed", text)
    pmids = sorted(set(pmids))

    ncts = sorted(set(re.findall(r"\b(NCT\d{8})\b", text, flags=re.I)))
    ncts = [n.upper() for n in ncts]

    issues: list[str] = []
    warnings: list[str] = []
    print(f"Checking {len(pmids)} PMID(s) and {len(ncts)} NCT(s)...")

    for pmid in pmids:
        ok = check_pmid(pmid)
        print(f"  PMID:{pmid} -> {'OK' if ok else 'FAIL'}")
        if not ok:
            issues.append(f"PMID:{pmid} could not be verified")
        time.sleep(0.34)

    for nct in ncts:
        info = fetch_nct_status(nct)
        exists = bool(info.get("exists"))
        status = info.get("status")
        bucket = info.get("bucket")
        print(f"  {nct} -> {'OK' if exists else 'FAIL'} status={status} bucket={bucket}")
        if not exists:
            issues.append(f"{nct} could not be verified")
        elif bucket == "terminal":
            warnings.append(f"{nct} is terminal ({status}) — not efficacy evidence")
        time.sleep(0.2)

    if warnings:
        print("WARNINGS:")
        for w in warnings:
            print("-", w)

    if issues:
        print("AUDIT FAILED")
        for i in issues:
            print("-", i)
        return 1

    print("AUDIT PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
