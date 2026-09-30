"""Сигналы качества источника: COI, журнал, статус NCT (не замена peer-review)."""

from __future__ import annotations

import logging
import re
from typing import Any, Optional

import httpx

from mito_harness.tools.cache import JsonCache

logger = logging.getLogger(__name__)

CTGOV = "https://clinicaltrials.gov/api/v2/studies"

# Положительный белый список известных клинических/научных площадок (не IF API)
TRUSTED_JOURNAL_MARKERS = (
    "n engl j med",
    "new england journal of medicine",
    "lancet",
    "jama",
    "bmj",
    "nature medicine",
    "nature",
    "science translational medicine",
    "sci transl med",
    "cell metabolism",
    "brain",
    "neurology",
    "ophthalmology",
    "genetics in medicine",
    "annals of neurology",
    "circulation",
    "european heart journal",
    "plos medicine",
    "cochrane",
)

# Небольшой curated-список/паттерны риска (не полный Beall's list; эвристика осторожности)
PREDATORY_SUSPECT_MARKERS = (
    "omics international",
    "omics publishing",
    "scientific research publishing",
    "scirp",
    "world academy of science engineering",
    "herald scholar",
    "longdom",
    "imedpub",
    "austin publishing",
)

_COI_MARKERS = (
    "conflict of interest",
    "conflicts of interest",
    "competing interest",
    "competing interests",
    "disclosure",
    "financial disclosure",
    "employee of",
    "consultant for",
    "received funding from",
    "sponsored by",
    "конфликт интересов",
)

_TERMINAL_NCT = {
    "terminated",
    "withdrawn",
    "suspended",
    "withheld",
    "no longer available",
    "temporarily not available",
}

_ACTIVE_NCT = {
    "recruiting",
    "active, not recruiting",
    "enrolling by invitation",
    "not yet recruiting",
}


def classify_journal(journal_name: str | None) -> str:
    """Возвращает: trusted | suspect | unknown."""
    if not journal_name:
        return "unknown"
    j = journal_name.lower().strip()
    if any(m in j for m in PREDATORY_SUSPECT_MARKERS):
        return "suspect"
    if any(m in j for m in TRUSTED_JOURNAL_MARKERS):
        return "trusted"
    return "unknown"


def extract_conflicts(text: str | None) -> Optional[str]:
    """Достаёт предложение с возможным COI из abstract/notes; без домыслов."""
    if not text:
        return None
    lowered = text.lower()
    if not any(m in lowered for m in _COI_MARKERS):
        return None
    # режем по предложениям грубо
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    for sent in parts:
        s_l = sent.lower()
        if any(m in s_l for m in _COI_MARKERS):
            return sent.strip()[:500]
    # fallback: короткий фрагмент вокруг маркера
    for m in _COI_MARKERS:
        idx = lowered.find(m)
        if idx >= 0:
            start = max(0, idx - 40)
            end = min(len(text), idx + 160)
            return text[start:end].strip()
    return None


def fetch_nct_status(nct_id: str) -> dict[str, Any]:
    """Живой статус NCT из ClinicalTrials.gov API v2 (с кэшем)."""
    nct = nct_id.upper().strip()
    cache = JsonCache("nct_status_v1", ttl_seconds=60 * 60 * 24 * 3)

    def _fetch() -> dict[str, Any]:
        with httpx.Client(timeout=30.0) as client:
            r = client.get(f"{CTGOV}/{nct}")
            if r.status_code != 200:
                return {"exists": False, "nct": nct, "status": None, "bucket": "missing"}
            data = r.json()
            status = (
                data.get("protocolSection", {})
                .get("statusModule", {})
                .get("overallStatus")
            )
            return {
                "exists": True,
                "nct": nct,
                "status": status,
                "bucket": nct_status_bucket(status),
                "phases": data.get("protocolSection", {}).get("designModule", {}).get("phases"),
            }

    try:
        return cache.get_or_set(nct, _fetch)
    except Exception as e:  # noqa: BLE001
        logger.warning("NCT status fetch failed for %s: %s", nct, e)
        return {"exists": False, "nct": nct, "status": None, "bucket": "error", "error": str(e)}


def nct_status_bucket(status: str | None) -> str:
    if not status:
        return "unknown"
    s = status.strip().lower()
    if s in _TERMINAL_NCT or "terminated" in s or "withdrawn" in s:
        return "terminal"
    if s in _ACTIVE_NCT or "recruiting" in s:
        return "active"
    if s in {"completed", "approved for marketing"}:
        return "completed"
    return "other"


def enrich_nct_fields(status: str | None) -> dict[str, Any]:
    bucket = nct_status_bucket(status)
    return {
        "nct_status": status,
        "nct_status_bucket": bucket,
        "nct_is_terminal": bucket == "terminal",
        "nct_is_active": bucket == "active",
    }
