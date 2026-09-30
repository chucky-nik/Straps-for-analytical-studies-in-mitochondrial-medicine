from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env", override=True)


@lru_cache(maxsize=1)
def settings() -> dict:
    return {
        "root": ROOT,
        "neural_deep_api_key": os.getenv("NEURAL_DEEP_API_KEY", "").strip(),
        "neural_deep_base_url": os.getenv(
            "NEURAL_DEEP_BASE_URL", "https://api.neuraldeep.tech/v1"
        ).strip(),
        "neural_deep_model": os.getenv("NEURAL_DEEP_MODEL", "qwen3.8-27b-noreason").strip(),
        "llm7_api_key": os.getenv("LLM7_API_KEY", "").strip(),
        "llm7_base_url": os.getenv("LLM7_BASE_URL", "https://api.llm7.io/v1").strip(),
        "llm7_model": os.getenv("LLM7_MODEL", "codestral-latest").strip(),
        "ncbi_email": os.getenv("NCBI_EMAIL", "researcher@example.com").strip(),
        "ncbi_tool": os.getenv("NCBI_TOOL", "mito_harness").strip(),
        "ncbi_api_key": os.getenv("NCBI_API_KEY", "").strip(),
        "skills_dir": ROOT / "skills",
        "cache_dir": ROOT / "cache",
        "reports_dir": ROOT / "reports",
        "figures_dir": ROOT / "figures",
        "years_back": int(os.getenv("YEARS_BACK", "5")),
    }


def has_llm_api_key() -> bool:
    s = settings()
    return bool(s["neural_deep_api_key"] or s["llm7_api_key"])
