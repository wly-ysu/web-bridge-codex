#!/usr/bin/env python3
"""Build a source-free, one-folder native MCP release archive."""

from __future__ import annotations

import argparse
import json
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


ROOT = Path(__file__).resolve().parents[2]


def default_target() -> str:
    names = {"Windows": "windows", "Darwin": "macos", "Linux": "linux"}
    name = names.get(platform.system())
    if not name:
        raise SystemExit(f"Unsupported build platform: {platform.system()}")
    machine = platform.machine().lower()
    return f"{name}-{'arm64' if machine in {'arm64', 'aarch64'} else 'x64'}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", default=default_target())
    parser.add_argument("--output", type=Path, default=ROOT / "release-output")
    args = parser.parse_args()
    output = args.output.resolve()
    work, dist = output / "work", output / "dist"
    stage_root = output / args.target
    stage = stage_root / f"web-bridge-codex-{args.target}"
    for path in (work, dist, stage_root):
        shutil.rmtree(path, ignore_errors=True)
    command = [
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir",
        "--name", "web-bridge-codex", "--distpath", str(dist), "--workpath", str(work),
        "--specpath", str(work), "--collect-submodules", "mcp.server",
        "--collect-submodules", "mcp.shared", "--collect-submodules", "mcp.types",
        "--collect-all", "playwright",
        "--collect-submodules", "adapters", "--collect-submodules", "core",
        "--collect-submodules", "tools", "--collect-submodules", "utils",
        "--collect-submodules", "deploy", str(ROOT / "server.py"),
    ]
    subprocess.run(command, cwd=ROOT, check=True)
    shutil.copytree(dist / "web-bridge-codex", stage)
    shutil.copy2(ROOT / "config.example.yaml", stage / "config.example.yaml")
    (stage / "manifest.json").write_text(
        json.dumps({"name": "web-bridge-codex", "version": (ROOT / "VERSION").read_text().strip(), "target": args.target}, indent=2) + "\n",
        encoding="utf-8",
    )
    executable = stage / ("web-bridge-codex.exe" if args.target.startswith("windows-") else "web-bridge-codex")
    if not executable.is_file():
        raise SystemExit(f"Missing native executable: {executable.name}")
    forbidden = ("server.py", "adapters", "core", "tools", "deploy")
    if any((stage / item).exists() for item in forbidden):
        raise SystemExit("Release must not contain project Python source files.")
    archive = output / f"web-bridge-codex-{args.target}.zip"
    with ZipFile(archive, "w", ZIP_DEFLATED) as zip_file:
        for path in stage.rglob("*"):
            if path.is_file():
                zip_file.write(path, path.relative_to(stage_root))
    print("RELEASE_ARTIFACT_OK")
    print(f"artifact={archive}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
