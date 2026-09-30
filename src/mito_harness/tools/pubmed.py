"""PubMed search via NCBI E-utilities (официальный источник)."""

from __future__ import annotations

import logging
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Any

import httpx

from mito_harness.config import settings
from mito_harness.schemas import StudyRecord
from mito_harness.tools.cache import JsonCache
from mito_harness.tools.quality import classify_journal

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
logger = logging.getLogger(__name__)


def _params_base() -> dict[str, str]:
    s = settings()
    p = {
        "tool": s["ncbi_tool"],
        "email": s["ncbi_email"],
    }
    if s["ncbi_api_key"]:
        p["api_key"] = s["ncbi_api_key"]
    return p


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def pubmed_search(
    query: str,
    *,
    max_results: int = 20,
    years_back: int | None = None,
) -> list[StudyRecord]:
    """Ищет статьи в PubMed и возвращает записи с PMID/DOI/abstract."""
    years = years_back if years_back is not None else settings()["years_back"]
    now = _utc_now()
    ymin = now.year - years
    full_query = f"({query}) AND ({ymin}:{now.year}[dp])"
    cache = JsonCache("pubmed_v2")  # v2: включает publication_types
    cache_key = f"{full_query}|{max_results}"

    def _fetch() -> list[dict[str, Any]]:
        with httpx.Client(timeout=60.0) as client:
            base = _params_base()
            r = client.get(
                f"{EUTILS}/esearch.fcgi",
                params={
                    **base,
                    "db": "pubmed",
                    "term": full_query,
                    "retmax": str(max_results),
                    "retmode": "json",
                    "sort": "relevance",
                },
            )
            r.raise_for_status()
            ids = r.json().get("esearchresult", {}).get("idlist", [])
            if not ids:
                return []
            time.sleep(0.34)
            fr = client.get(
                f"{EUTILS}/efetch.fcgi",
                params={
                    **base,
                    "db": "pubmed",
                    "id": ",".join(ids),
                    "retmode": "xml",
                },
            )
            fr.raise_for_status()
            return _parse_pubmed_xml(fr.text)

    try:
        raw_list = cache.get_or_set(cache_key, _fetch)
    except httpx.HTTPStatusError as e:
        logger.warning("PubMed HTTP %s — empty result", e.response.status_code)
        return []
    except httpx.RequestError as e:
        logger.warning("PubMed network error: %s — empty result", e)
        return []
    except Exception as e:  # noqa: BLE001
        logger.warning("PubMed unexpected error: %s — empty result", e)
        return []

    return [StudyRecord.model_validate(x) for x in raw_list]


def _text(el: ET.Element | None) -> str:
    if el is None:
        return ""
    return "".join(el.itertext()).strip()


def _parse_pubmed_xml(xml_text: str) -> list[dict[str, Any]]:
    root = ET.fromstring(xml_text)
    out: list[dict[str, Any]] = []
    for article in root.findall(".//PubmedArticle"):
        pmid = _text(article.find(".//PMID"))
        if not pmid:
            continue
        title = _text(article.find(".//ArticleTitle")) or "(no title)"
        abstract_bits = [_text(n) for n in article.findall(".//Abstract/AbstractText")]
        abstract = "\n".join(b for b in abstract_bits if b) or None
        year_raw = _text(article.find(".//PubDate/Year")) or _text(
            article.find(".//PubDate/MedlineDate")
        )
        year = None
        if year_raw:
            digits = "".join(ch for ch in year_raw[:4] if ch.isdigit())
            year = int(digits) if len(digits) == 4 else None
        doi = None
        for aid in article.findall(".//ArticleId"):
            if aid.attrib.get("IdType") == "doi":
                doi = (aid.text or "").strip() or None
        journal = _text(article.find(".//Journal/Title")) or None
        pub_types = [
            (pt.text or "").strip()
            for pt in article.findall(".//PublicationType")
            if (pt.text or "").strip()
        ]
        # пропускаем отозванные публикации
        pub_l = " | ".join(p.lower() for p in pub_types)
        if "retracted publication" in pub_l or "retraction of publication" in pub_l:
            logger.warning("Skip retracted PMID %s", pmid)
            continue
        url = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
        out.append(
            {
                "source": "pubmed",
                "source_id": pmid,
                "title": title,
                "year": year,
                "abstract": abstract,
                "doi": doi,
                "url": url,
                "journal_or_status": journal,
                "raw": {
                    "pmid": pmid,
                    "doi": doi,
                    "publication_types": pub_types,
                    "journal_quality": classify_journal(journal),
                },
            }
        )
    return out
