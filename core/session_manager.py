"""Simple local memory file for interaction history."""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class SessionRecord:
    timestamp: str
    role: str
    prompt: str
    response: str


class SessionManager:
    def __init__(self, path: str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.write_text("[]", encoding="utf-8")

    def append(self, role: str, prompt: str, response: str) -> None:
        records = self._load()
        records.append(
            asdict(
                SessionRecord(
                    timestamp=datetime.now(tz=timezone.utc).isoformat(),
                    role=role,
                    prompt=prompt,
                    response=response,
                )
            )
        )
        if len(records) > 200:
            records = records[-200:]
        self.path.write_text(
            json.dumps(records, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _load(self) -> list[dict[str, str]]:
        try:
            raw = self.path.read_text(encoding="utf-8")
            data = json.loads(raw)
            return data if isinstance(data, list) else []
        except Exception:
            return []

    def recent(self, limit: int = 5) -> list[dict[str, str]]:
        records = self._load()
        return records[-limit:]
