"""Context collection helpers for ChatGPT Web context requests."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

from utils import file_utils, git_utils


@dataclass
class ContextBundle:
    task: str
    git_branch: str
    git_status: str
    git_diff: str
    related_files: dict[str, str]
    recent_logs: dict[str, str]
    collected_at: str
    source: str

    def to_prompt_text(self, max_related_files: int, max_file_chars: int) -> str:
        lines = [
            f"Task: {self.task}",
            f"Time: {self.collected_at}",
            f"Workspace: {self.source}",
            f"Branch: {self.git_branch}",
            "Git status:",
            self.git_status or "(no status output)",
            "Git diff:",
            self.git_diff or "(no diff)",
            "",
            f"Related files (max {max_related_files}):",
        ]

        for file_path, content in list(self.related_files.items())[:max_related_files]:
            snippet = file_utils.truncate_text(content, max_file_chars)
            lines.append(f"### {file_path}")
            lines.append(snippet or "(binary or unreadable)")
            lines.append("")

        lines.append("Recent logs:")
        if not self.recent_logs:
            lines.append("(no log files found)")
        for path, content in self.recent_logs.items():
            snippet = file_utils.truncate_text(content, max_file_chars)
            lines.append(f"### {path}")
            lines.append(snippet or "(binary or unreadable)")

        return "\n".join(lines)


class ContextManager:
    def __init__(self, workspace_root: str | Path, config: dict[str, Any]):
        self.root = Path(workspace_root).resolve()
        self.bridge_cfg = config.get("bridge", {})
        self.project_cfg = config.get("project", {})
        self.context_cfg = config.get("context", {})
        self.git_cfg = config.get("git", {})

        self.allowed_exts = set(self.project_cfg.get("allowed_extensions", []))
        self.ignore_paths = set(self.project_cfg.get("ignore_paths", []))
        self.sensitive_patterns = set(self.project_cfg.get("sensitive_patterns", []))

        self.context_enabled = bool(self.context_cfg.get("enabled", True))
        self.personal_mode = bool(self.bridge_cfg.get("personal_mode", True))
        self.allow_workspace_context = bool(
            self.personal_mode and self.context_enabled and self.bridge_cfg.get("allow_workspace_context", True)
        )

        self.max_file_chars = int(self.context_cfg.get("max_file_chars", 6000))
        self.max_related_files = int(self.context_cfg.get("max_related_files", 6))
        self.max_logs = int(self.context_cfg.get("max_logs", 3))
        self.max_log_chars = int(self.context_cfg.get("max_log_chars", 8000))
        self.max_diff_chars = int(self.git_cfg.get("max_diff_chars", 12000))

    def _extract_keywords(self, text: str) -> list[str]:
        raw_words = re.findall(r"[A-Za-z0-9_./-]{3,}", text.lower())
        stopwords = {
            "the",
            "and",
            "for",
            "with",
            "from",
            "that",
            "this",
            "design",
            "please",
            "analysis",
            "error",
            "issue",
        }
        dedup: list[str] = []
        for word in raw_words:
            if word in stopwords or len(word) < 3:
                continue
            if word not in dedup:
                dedup.append(word)
        return dedup[:12]

    def _candidate_paths(self, workspace: Path, keywords: Sequence[str]) -> list[Path]:
        candidates: list[Path] = []
        for candidate in file_utils.iter_project_files(
            workspace, self.allowed_exts, self.ignore_paths
        ):
            if file_utils.is_sensitive(candidate.name, self.sensitive_patterns):
                continue

            path_text = str(candidate).lower()
            if any(word in path_text for word in keywords):
                candidates.append(candidate)
                continue

            content = file_utils.read_file_text(candidate, 12000)
            if content and any(word in content.lower() for word in keywords):
                candidates.append(candidate)

        # stable deterministic order
        candidates = sorted(set(candidates))
        return candidates[: self.max_related_files * 3]

    def _collect_logs(self, workspace: Path) -> dict[str, str]:
        logs: dict[str, str] = {}
        log_names = [
            "build.log",
            "colcon_build.log",
            "cmake_build.log",
            "CMakeOutput.log",
            "CMakeError.log",
        ]
        for name in log_names:
            path = workspace / name
            if path.exists() and path.is_file():
                logs[str(path)] = file_utils.read_file_text(path, self.max_log_chars)

        if len(logs) >= self.max_logs:
            return logs

        for path in workspace.rglob("*.log"):
            if file_utils.should_ignore_path(path, self.ignore_paths):
                continue
            if any(part.startswith(".") for part in path.parts):
                continue
            logs[str(path)] = file_utils.read_file_text(path, self.max_log_chars)
            if len(logs) >= self.max_logs:
                break

        return logs

    def _resolve_hints(self, workspace: Path, task: str, hints: Iterable[str] | None) -> list[str]:
        selected: list[str] = []
        if hints:
            for raw in hints:
                if not raw:
                    continue
                candidate = (workspace / raw).resolve()
                if candidate.exists() and candidate.is_file():
                    selected.append(str(candidate))
                else:
                    # keep unresolved hints for downstream keyword matching
                    selected.append(raw.strip())

        keyword_hits = self._candidate_paths(workspace, self._extract_keywords(task))
        for p in keyword_hits:
            selected.append(str(p))

        # remove duplicates while preserving order
        dedup: list[str] = []
        for item in selected:
            if item not in dedup:
                dedup.append(item)
        return dedup

    def collect(self, task: str, context_hints: Sequence[str] | None = None, include_diff: bool = True) -> str:
        if not self.allow_workspace_context:
            return (
                "Local workspace context transfer is disabled by configuration. "
                "Returning local analysis only from the provided question and explicit inputs."
            )

        workspace = git_utils.get_repo_root(self.root) or self.root
        git_status = git_utils.get_status(workspace)
        git_branch = git_utils.get_branch(workspace)
        git_diff = ""
        if include_diff:
            git_diff = file_utils.truncate_text(git_utils.get_diff(workspace), self.max_diff_chars)

        related_files: dict[str, str] = {}
        for candidate in self._resolve_hints(workspace, task, context_hints)[: self.max_related_files]:
            path = Path(candidate)
            if path.exists() and path.is_file() and not file_utils.should_ignore_path(path, self.ignore_paths):
                related_files[str(path)] = file_utils.read_file_text(path, self.max_file_chars)
            elif not path.exists():
                # hint may be keyword; resolved later from search
                continue

        # fill potential misses with keyword results
        if len(related_files) < self.max_related_files:
            keywords = self._extract_keywords(task)
            for fp in self._candidate_paths(workspace, keywords):
                if str(fp) not in related_files and len(related_files) < self.max_related_files:
                    related_files[str(fp)] = file_utils.read_file_text(fp, self.max_file_chars)

        logs = self._collect_logs(workspace)
        bundle = ContextBundle(
            task=task,
            git_branch=git_branch or "unknown",
            git_status=git_status or "",
            git_diff=git_diff or "",
            related_files=related_files,
            recent_logs=logs,
            collected_at=datetime.now(tz=timezone.utc).isoformat(),
            source=str(workspace),
        )
        return bundle.to_prompt_text(self.max_related_files, self.max_file_chars)
