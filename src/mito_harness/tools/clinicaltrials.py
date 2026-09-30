"""ClinicalTrials.gov API v2 (официальный реестр испытаний)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from mito_harness.config import settings
from mito_harness.schemas import StudyRecord
from mito_harness.tools.cache import JsonCache

CTGOV = "https://clinicaltrials.gov/api/v2/studies"
logger = logging.getLogger(__name__)


def clinicaltrials_search(
    query: str,
    *,
    max_results: int = 15,
    years_back: int | None = None,
) -> list[StudyRecord]:
    years = years_back if years_back is not None else settings()["years_back"]
    ymin = datetime.now(timezone.utc).year - years
    cache = JsonCache("ctgov")
    cache_key = f"{query}|{max_results}|{ymin}"

    def _fetch() -> list[dict[str, Any]]:
        params = {
            "query.term": query,
            "pageSize": str(max_results),
            "format": "json",
            "countTotal": "true",
            "filter.advanced": f"AREA[StartDate]RANGE[{ymin}-01-01,MAX]",
        }
        with httpx.Client(timeout=60.0) as client:
            r = client.get(CTGOV, params=params)
            r.raise_for_status()
            data = r.json()
        out: list[dict[str, Any]] = []
        for st in data.get("studies", []):
            proto = st.get("protocolSection", {})
            ident = proto.get("identificationModule", {})
            status = proto.get("statusModule", {})
            design = proto.get("designModule", {})
            desc = proto.get("descriptionModule", {})
            nct = ident.get("nctId")
            if not nct:
                continue
            title = ident.get("officialTitle") or ident.get("briefTitle") or "(no title)"
            start = (status.get("startDateStruct") or {}).get("date")
            year = None
            if start and len(start) >= 4 and start[:4].isdigit():
                year = int(start[:4])
            phases = design.get("phases") or []
            phase = ", ".join(phases) if phases else None
            abstract = desc.get("briefSummary") or desc.get("detailedDescription")
            url = f"https://clinicaltrials.gov/study/{nct}"
            out.append(
                {
                    "source": "clinicaltrials",
                    "source_id": nct,
                    "title": title,
                    "year": year,
                    "abstract": abstract,
                    "doi": None,
                    "url": url,
                    "journal_or_status": status.get("overallStatus") or phase,
                    "raw": {
                        "nct": nct,
                        "phases": phases,
                        "overallStatus": status.get("overallStatus"),
                    },
                }
            )
        return out

    try:
        raw_list = cache.get_or_set(cache_key, _fetch)
    except httpx.HTTPStatusError as e:
        logger.warning("ClinicalTrials.gov HTTP %s — empty", e.response.status_code)
        return []
    except httpx.RequestError as e:
        logger.warning("ClinicalTrials.gov network error: %s — empty", e)
        return []
    except Exception as e:  # noqa: BLE001
        logger.warning("ClinicalTrials.gov unexpected error: %s — empty", e)
        return []

    return [StudyRecord.model_validate(x) for x in raw_list]
