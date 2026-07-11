"""Local Chrome launch lifecycle matrix for web-bridge-codex."""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path

import yaml

ROOT_DIR = Path(__file__).resolve().parent.parent
WORKSPACE_ROOT = ROOT_DIR

if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from adapters.gptpro_web import GPTProWebAdapter


def _load_config(config_path: Path) -> dict:
    if not config_path.exists():
        return {}
    raw = config_path.read_text(encoding="utf-8")
    data = yaml.safe_load(raw)
    if isinstance(data, dict):
        return data
    return {}


def _parse_result_text(result_text: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for line in result_text.splitlines():
        if "=" not in line:
            continue
        if line.startswith("BRIDGE_CHROME") and line.count("=") == 0:
            continue
        key, value = line.split("=", 1)
        fields[key.strip()] = value.strip()
    return fields


def _to_bool(value: str | bool | None, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    v = str(value).strip().lower()
    return v in {"1", "true", "yes", "y", "ok"}


async def run_case(adapter: GPTProWebAdapter, name: str, params: dict) -> dict[str, object]:
    result = await adapter.chrome_lifecycle_test(**params)
    fields = _parse_result_text(result)
    passed = "BRIDGE_CHROME_LIFECYCLE_TEST_OK" in result
    launch_returned = _to_bool(fields.get("launch_returned"))
    goto_done = _to_bool(fields.get("goto_done"))
    browser_stayed = _to_bool(fields.get("browser_stayed_alive_10s"))
    launch_mode = params.get("launch_mode")
    return {
        "case": name,
        "launch_mode": launch_mode,
        "passed": passed,
        "launch_returned": launch_returned,
        "browser_stayed_alive_10s": browser_stayed,
        "goto_done": goto_done,
        "stage": fields.get("stage"),
        "error": fields.get("reason"),
        "chrome_pids": fields.get("chrome_pids_after_launch", ""),
        "chrome_processes_after_launch_count": fields.get("chrome_processes_after_launch_count"),
        "chrome_processes_after_sleep_count": fields.get("chrome_processes_after_sleep_count"),
        "raw": result,
    }


async def main() -> int:
    config_path = ROOT_DIR / "config.yaml"
    config = _load_config(config_path)
    logging.basicConfig(
        filename=str(ROOT_DIR / "bridge_launch_matrix.log"),
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    logger = logging.getLogger("bridge-launch-matrix")

    adapter = GPTProWebAdapter(str(WORKSPACE_ROOT), config, logger)
    temp_profile = str(Path.home() / "gptpro_profile_tmp_smoke")

    cases = [
        (
            "A persistent_executable + temp profile + skip goto + hold10",
            {
                "launch_mode": "persistent_executable",
                "skip_goto": True,
                "hold_seconds": 10,
                "minimal_args": True,
                "user_data_dir_override": temp_profile,
            },
        ),
        (
            "B persistent_channel + temp profile + skip goto + hold10",
            {
                "launch_mode": "persistent_channel",
                "skip_goto": True,
                "hold_seconds": 10,
                "minimal_args": True,
                "user_data_dir_override": temp_profile,
            },
        ),
        (
            "C nonpersistent_executable + skip goto + hold10",
            {
                "launch_mode": "nonpersistent_executable",
                "skip_goto": True,
                "hold_seconds": 10,
                "minimal_args": True,
            },
        ),
        (
            "D nonpersistent_channel + skip goto + hold10",
            {
                "launch_mode": "nonpersistent_channel",
                "skip_goto": True,
                "hold_seconds": 10,
                "minimal_args": True,
            },
        ),
        (
            "E persistent_channel + about:blank",
            {
                "launch_mode": "persistent_channel",
                "skip_goto": False,
                "hold_seconds": 3,
                "target_url": "about:blank",
                "minimal_args": True,
                "user_data_dir_override": temp_profile,
            },
        ),
        (
            "F nonpersistent_channel + about:blank",
            {
                "launch_mode": "nonpersistent_channel",
                "skip_goto": False,
                "hold_seconds": 3,
                "target_url": "about:blank",
                "minimal_args": True,
            },
        ),
    ]

    all_results = []
    for name, params in cases:
        print(f"\n=== Case {name} ===")
        try:
            result = await run_case(adapter, name, params)
        except Exception as exc:
            result = {
                "case": name,
                "launch_mode": params.get("launch_mode"),
                "passed": False,
                "launch_returned": False,
                "browser_stable": False,
                "goto_done": False,
                "error": str(exc),
                "raw": str(exc),
            }
        all_results.append(result)
        print(json.dumps(result, ensure_ascii=False, indent=2))

    # Summarize for humans
    print("\n=== Chrome Launch Matrix Summary ===")
    print("Case | passed | launch_returned | browser_stayed_alive_10s | goto_done | error")
    print("-" * 86)
    for item in all_results:
        print(
            f"{item['case']} | {item.get('passed')} | {item.get('launch_returned')} | "
            f"{item.get('browser_stayed_alive_10s', False)} | {item.get('goto_done', False)} | {item.get('error')}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))


