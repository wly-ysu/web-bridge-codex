"""File-oriented utility functions for the context manager."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, Iterator, Set
import fnmatch


def _normalize_path(path: Path, root: Path) -> Path:
    return path.resolve().relative_to(root.resolve())


def should_ignore_path(path: Path, ignore_paths: Iterable[str]) -> bool:
    normalized = set(normalize(p) for p in ignore_paths)
    parts = set(path.resolve().parts)
    return any(part in normalized for part in parts)


def normalize(path: str | Path) -> str:
    if isinstance(path, Path):
        return str(path)
    return path.strip().replace("\\", "/")


def is_sensitive(name: str, patterns: Iterable[str]) -> bool:
    for pattern in patterns:
        if fnmatch.fnmatch(name, pattern):
            return True
    return False


def read_file_text(path: Path, max_chars: int = 8000) -> str:
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""
    return truncate_text(content, max_chars)


def truncate_text(text: str, max_chars: int) -> str:
    if not text:
        return ""
    if len(text) <= max_chars:
        return text
    head = max_chars // 2
    tail = max_chars - head - 30
    return (
        text[:head]
        + "\n\n... [truncated] ...\n\n"
        + (text[-tail:] if tail > 0 else "")
    )


def iter_project_files(
    workspace: Path,
    allowed_extensions: Set[str],
    ignore_paths: Iterable[str],
) -> Iterator[Path]:
    for path in workspace.rglob("*"):
        if not path.is_file():
            continue
        if should_ignore_path(path, ignore_paths):
            continue
        if path.suffix and path.suffix.lower() in {ext.lower() for ext in allowed_extensions}:
            yield path
            continue
        if path.name in allowed_extensions:
            yield path
