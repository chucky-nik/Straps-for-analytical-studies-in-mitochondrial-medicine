from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _sanitize_log_value(key: str, value: Any) -> Any:
    if key == "raw":
        return "<raw omitted>"
    if isinstance(value, str) and len(value) > 1000:
        return value[:1000] + "...[truncated]"
    if isinstance(value, (list, dict)):
        rendered = json.dumps(value, ensure_ascii=False, default=str)
        if len(rendered) > 1000:
            size = len(value)
            return f"<{type(value).__name__} size={size}>"
    return value


class RunLogger:
    """Простой структурированный лог делегирования / tools / skills."""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def log(self, kind: str, message: str, **data: Any) -> None:
        sanitized = {k: _sanitize_log_value(k, v) for k, v in data.items()}
        self.events.append(
            {
                "ts": datetime.now(timezone.utc).isoformat(),
                "kind": kind,
                "message": message,
                **sanitized,
            }
        )
        extra = ""
        if sanitized:
            extra = f" | {json.dumps(sanitized, ensure_ascii=False, default=str)[:300]}"
        print(f"[{kind}] {message}{extra}")

    def save(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self.events, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        return path
