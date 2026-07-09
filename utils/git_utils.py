"""Git helper commands used by context collection."""

from __future__ import annotations

from pathlib import Path
from subprocess import CalledProcessError, TimeoutExpired, run


def _run_git(workdir: Path, args: list[str], timeout: int = 5) -> str:
    try:
        completed = run(
            ["git", "-C", str(workdir), *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (CalledProcessError, TimeoutExpired, FileNotFoundError):
        return ""
    return (completed.stdout or "").strip()


def get_repo_root(path: Path) -> Path | None:
    output = _run_git(path, ["rev-parse", "--show-toplevel"], timeout=4)
    if output:
        return Path(output).resolve()
    return None


def get_status(path: Path) -> str:
    return _run_git(path, ["status", "--short"], timeout=4)


def get_branch(path: Path) -> str:
    return _run_git(path, ["branch", "--show-current"], timeout=4) or "detached"


def get_diff(path: Path) -> str:
    return _run_git(path, ["diff", "--"], timeout=6)
