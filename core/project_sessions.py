"""Privacy-preserving project to ChatGPT conversation mapping."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path


_CONVERSATION_RE = re.compile(r"^https://chatgpt\.com/c/([^/?#]+)$", re.IGNORECASE)


def canonical_project_path(path: str | Path) -> str:
    resolved = Path(os.path.expandvars(os.path.expanduser(str(path)))).resolve()
    text = resolved.as_posix().rstrip("/")
    return text.lower() if os.name == "nt" else text


def project_key(path: str | Path) -> str:
    return "p1_" + hashlib.sha256(canonical_project_path(path).encode("utf-8")).hexdigest()[:24]


def sanitize_conversation_url(url: str | None) -> str | None:
    if not url:
        return None
    match = _CONVERSATION_RE.match(str(url).split("?", 1)[0].split("#", 1)[0])
    return f"https://chatgpt.com/c/{match.group(1)}" if match else None


@dataclass
class ProjectConversation:
    project_key: str
    project_path_hint: str
    conversation_url: str
    created_at: str
    last_used_at: str
    status: str = "active"
    generation: int = 1


class ProjectSessionRegistry:
    """Small, atomically-written local registry. It never stores prompt content."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def get(self, key: str) -> ProjectConversation | None:
        raw = self._load().get("projects", {}).get(key)
        if not isinstance(raw, dict):
            return None
        url = sanitize_conversation_url(raw.get("conversation_url"))
        if not url:
            return None
        return ProjectConversation(
            project_key=key,
            project_path_hint=str(raw.get("project_path_hint", "project")),
            conversation_url=url,
            created_at=str(raw.get("created_at", "")),
            last_used_at=str(raw.get("last_used_at", "")),
            status=str(raw.get("status", "active")),
            generation=int(raw.get("generation", 1)),
        )

    def put(self, path: str | Path, conversation_url: str, prior: ProjectConversation | None = None) -> ProjectConversation:
        clean_url = sanitize_conversation_url(conversation_url)
        if not clean_url:
            raise ValueError("conversation_url must be a canonical ChatGPT conversation URL")
        key = project_key(path)
        now = datetime.now(tz=timezone.utc).isoformat()
        record = ProjectConversation(
            project_key=key,
            project_path_hint=Path(canonical_project_path(path)).name or "project",
            conversation_url=clean_url,
            created_at=prior.created_at if prior else now,
            last_used_at=now,
            status="active",
            generation=(prior.generation + 1) if prior and prior.conversation_url != clean_url else (prior.generation if prior else 1),
        )
        data = self._load()
        projects = data.setdefault("projects", {})
        projects[key] = asdict(record)
        self._write(data)
        return record

    def mark_invalid(self, key: str) -> None:
        data = self._load()
        record = data.get("projects", {}).get(key)
        if isinstance(record, dict):
            record["status"] = "invalid"
            self._write(data)

    def _load(self) -> dict:
        if not self.path.exists():
            return {"schema_version": 1, "projects": {}}
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(value, dict) and isinstance(value.get("projects", {}), dict):
                return value
        except Exception:
            corrupt = self.path.with_suffix(self.path.suffix + ".corrupt")
            try:
                self.path.replace(corrupt)
            except Exception:
                pass
        return {"schema_version": 1, "projects": {}}

    def _write(self, data: dict) -> None:
        data["schema_version"] = 1
        handle, temp_name = tempfile.mkstemp(prefix=self.path.name + ".", suffix=".tmp", dir=str(self.path.parent))
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as output:
                json.dump(data, output, ensure_ascii=False, indent=2)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temp_name, self.path)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)
