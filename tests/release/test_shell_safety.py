#!/usr/bin/env python3
"""Static guard for shell, path, and config safety in release-critical files."""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

SCAN_FILES = [
    ".github/workflows/validate.yml",
    ".github/workflows/release.yml",
    ".github/workflows/release-windows.yml",
    "scripts/windows/BridgeInstaller.Common.psm1",
    "scripts/windows/bootstrap.ps1",
    "scripts/windows/bootstrap.cmd",
    "scripts/release/bootstrap-windows.ps1",
    "scripts/release/install-windows.ps1",
    "scripts/release/repair-windows.ps1",
    "deploy/common/configure_user.py",
    "config.example.yaml",
]

LEGACY_TOKENS = [
    "ask_pro_architect",
    "review_pro_code",
    "debug_pro_error",
    "pro_deep",
    "pro_review",
    "pro_debug",
    "pro_profile",
    "pro_budget_policy",
    "prefer_gpt55",
    "gptpro",
    "GPT-5.5",
]

SUSPICIOUS_PATTERNS = [
    (
        re.compile(r"powershell(?:\.exe)?\s+[^\\n]*(?:-Command|/c)", re.IGNORECASE),
        "avoid inline PowerShell -Command; prefer -File or a checked-in helper script",
    ),
    (
        re.compile(r"python(?:\.exe)?\s+[^\\n]*-c\s", re.IGNORECASE),
        "avoid inline python -c in release paths; prefer a helper script",
    ),
    (
        re.compile(r"cmd\s+/c\s+[^\\n]*[\"'].*[\"']", re.IGNORECASE),
        "CMD quoted inline commands are fragile; prefer a .cmd helper with args",
    ),
]

ALLOW_MARKER = "shell-safety: allow"


def lines_with_numbers(path: Path) -> list[tuple[int, str]]:
    return list(enumerate(path.read_text(encoding="utf-8").splitlines(), start=1))


def allowed_near(lines: list[tuple[int, str]], index: int) -> bool:
    start = max(0, index - 3)
    end = min(len(lines), index + 2)
    return any(ALLOW_MARKER in text for _, text in lines[start:end])


def main() -> int:
    failures: list[str] = []
    for relative in SCAN_FILES:
        path = ROOT / relative
        if not path.exists():
            failures.append(f"{relative}: missing release-critical file")
            continue
        lines = lines_with_numbers(path)
        text = "\n".join(line for _, line in lines)

        if relative == "config.example.yaml":
            for token in LEGACY_TOKENS:
                if token in text:
                    failures.append(f"{relative}: legacy token remains in generated config template: {token}")

        for idx, (line_no, line) in enumerate(lines):
            for pattern, reason in SUSPICIOUS_PATTERNS:
                if pattern.search(line) and not allowed_near(lines, idx):
                    failures.append(f"{relative}:{line_no}: {reason}: {line.strip()}")

    if failures:
        print("SHELL_SAFETY_CHECK_FAILED")
        for failure in failures:
            print(failure)
        return 1
    print("SHELL_SAFETY_CHECK_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

