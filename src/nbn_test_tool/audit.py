"""Append-only audit trail.

Every LLM call and every executed command is recorded as a single JSON line.
Usable evidence for change-control review.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class AuditLog:
    def __init__(self, path: str, enabled: bool = True, redact_keys: list[str] | None = None):
        self._path = Path(path)
        self._enabled = enabled
        self._redact = set(redact_keys or [])
        if self._enabled:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.touch(exist_ok=True)

    def _redact_dict(self, d: Any) -> Any:
        if isinstance(d, dict):
            return {k: ("***REDACTED***" if k in self._redact else self._redact_dict(v)) for k, v in d.items()}
        if isinstance(d, list):
            return [self._redact_dict(v) for v in d]
        return d

    def record(self, event_type: str, payload: dict[str, Any]) -> None:
        if not self._enabled:
            return
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "pid": os.getpid(),
            "event": event_type,
            "payload": self._redact_dict(payload),
        }
        with self._path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, default=str) + "\n")

    def tail(self, n: int = 50) -> list[dict[str, Any]]:
        if not self._enabled or not self._path.exists():
            return []
        lines = self._path.read_text(encoding="utf-8").splitlines()[-n:]
        out: list[dict[str, Any]] = []
        for line in lines:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return out
