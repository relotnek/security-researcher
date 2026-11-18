"""Append-only audit log for boundary decisions (JSON lines)."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class AuditLog:
    def __init__(self, path: str | os.PathLike[str]) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def record(self, event: str, **details: Any) -> dict[str, Any]:
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "event": event,
            **details,
        }
        line = json.dumps(entry, sort_keys=True, default=str) + "\n"
        # O_APPEND keeps concurrent writers from interleaving within a line.
        fd = os.open(self.path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        try:
            os.write(fd, line.encode())
            os.fsync(fd)
        finally:
            os.close(fd)
        return entry

    def entries(self, event: str | None = None) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        rows = [json.loads(line) for line in self.path.read_text().splitlines() if line.strip()]
        return [r for r in rows if event is None or r["event"] == event]
