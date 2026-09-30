from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Callable

from mito_harness.config import settings


def _key(namespace: str, payload: str) -> str:
    h = hashlib.sha256(f"{namespace}:{payload}".encode("utf-8")).hexdigest()[:24]
    return f"{namespace}_{h}.json"


class JsonCache:
    def __init__(self, namespace: str, ttl_seconds: int = 60 * 60 * 24 * 7) -> None:
        self.namespace = namespace
        self.ttl = ttl_seconds
        self.dir = settings()["cache_dir"]
        self.dir.mkdir(parents=True, exist_ok=True)

    def get(self, payload: str) -> Any | None:
        path = self.dir / _key(self.namespace, payload)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None
        if time.time() - data.get("_cached_at", 0) > self.ttl:
            return None
        return data.get("value")

    def set(self, payload: str, value: Any) -> None:
        path = self.dir / _key(self.namespace, payload)
        path.write_text(
            json.dumps(
                {"_cached_at": time.time(), "value": value},
                ensure_ascii=False,
                default=str,
            ),
            encoding="utf-8",
        )

    def get_or_set(self, payload: str, factory: Callable[[], Any]) -> Any:
        hit = self.get(payload)
        if hit is not None:
            return hit
        value = factory()
        self.set(payload, value)
        return value
