"""Playwright adapter for ChatGPT web UI.

Historically named GPTProWebAdapter for backward compatibility. The actual behavior
is ChatGPT Web Tech Lead Adapter: it does not require GPT-5.5 Pro availability.
"""

from __future__ import annotations

import asyncio
import json
import hashlib
import logging
import os
import re
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path


class GPTProWebAdapter:
    def __init__(self, workspace: str, config: dict, logger):
        self.cfg = config.get("web_adapter", {})
        self.config = config
        self.logger = logger
        self.workspace = Path(workspace)
        self.runtime_cfg = config.get("runtime", {})
        self.browser_tabs_cfg = config.get("browser_tabs", {})
        self.last_stage = "initialized"

    def _set_stage(self, stage: str, **extra: object) -> None:
        self.last_stage = stage
        if extra:
            details = ", ".join([f"{k}={v}" for k, v in sorted(extra.items())])
            logging.info("[STAGE] %s %s", stage, details)
        else:
            logging.info("[STAGE] %s", stage)
        self._flush_log_handlers()

    def get_runtime_profile(self) -> tuple[str, str]:
        return self._resolve_profile_dir()

    @property
    def last_stage_name(self) -> str:
        return self.last_stage

    def _get_model_strategy(self) -> dict:
        strategy = self.cfg.get("model_strategy", {})
        if not isinstance(strategy, dict):
            strategy = {}
        return {
            "mode": str(strategy.get("mode", "best_available")),
            "preferred_models": list(strategy.get("preferred_models", [])),
            "fallback_to_current_model": bool(strategy.get("fallback_to_current_model", True)),
            "fail_if_preferred_unavailable": bool(strategy.get("fail_if_preferred_unavailable", False)),
        }

    @staticmethod
    def _normalize_model_text(text: str) -> str:
        return re.sub(r"\s+", " ", text.strip()).lower()

    def _runtime_seconds(self, key: str, default: int, minimum: int = 1) -> int:
        raw = self.runtime_cfg.get(key)
        try:
            value = int(raw) if raw is not None else default
        except Exception:
            value = default
        if value < minimum:
            return default
        return value

    def _flush_log_handlers(self) -> None:
        for handler in logging.getLogger().handlers:
            try:
                handler.flush()
            except Exception:
                pass

    def _log(self, level: str, message: str, extra: dict[str, object] | None = None) -> None:
        if not self.logger:
            return
        kv = ""
        if extra:
            pairs = [f"{k}={v}" for k, v in sorted(extra.items())]
            kv = " [" + ", ".join(pairs) + "]"
        getattr(self.logger, level)(f"[WEB]{kv} {message}")
        self._flush_log_handlers()

    def _raise_web_error(self, stage: str, reason: object, extra: dict[str, object] | None = None) -> str:
        lines = [f"[WEB_ERROR]", f"stage={stage}", f"reason={reason}"]
        if extra:
            for key, value in sorted(extra.items()):
                lines.append(f"{key}={value}")
        msg = "\n".join(lines)
        self._log("error", "web stage error", {"stage": stage, "reason": reason, **(extra or {})})
        return msg

    def _log_chrome_preflight(
        self,
        executable_path: str,
        executable_exists: bool,
        user_data_dir: str,
        user_data_dir_exists: bool,
        user_data_dir_writable: bool,
        profile_in_use: bool,
        matching_pids: list[str],
        launch_args: list[str] | None,
        lock_files: list[str],
        stale_lock_suspected: bool,
        auto_remove_stale_lock: bool,
        removed_stale_lock_files: list[str] | None = None,
    ) -> None:
        self._set_stage("web.chrome_preflight.log")
        logging.info(
            "[CHROME_PREFLIGHT] executable_path=%s executable_exists=%s user_data_dir=%s user_data_dir_exists=%s user_data_dir_writable=%s profile_in_use=%s stale_lock_suspected=%s auto_remove_stale_lock=%s matching_pids=%s lock_files=%s removed_stale_lock_files=%s launch_args=%s",
            executable_path,
            executable_exists,
            user_data_dir,
            user_data_dir_exists,
            user_data_dir_writable,
            profile_in_use,
            stale_lock_suspected,
            auto_remove_stale_lock,
            matching_pids,
            lock_files,
            removed_stale_lock_files if removed_stale_lock_files is not None else [],
            launch_args,
        )
        self._flush_log_handlers()

    def _resolve_profile_dir(self, user_data_dir_override: str | None = None) -> tuple[Path, str]:
        if user_data_dir_override:
            override_path = Path(os.path.expandvars(os.path.expanduser(str(user_data_dir_override)))).expanduser()
            if override_path.is_absolute():
                return override_path, "override"
            return (self.workspace / override_path).resolve(), "relative-override"
        explicit = self.cfg.get("user_data_dir")
        if explicit:
            explicit_path = Path(os.path.expandvars(os.path.expanduser(str(explicit)))).expanduser()
            if explicit_path.is_absolute():
                return explicit_path, "explicit"
            return (self.workspace / explicit_path).resolve(), "relative-explicit"

        local_app_data = Path(os.environ.get("LOCALAPPDATA", ""))
        preferred = [
            ("chrome", local_app_data / "Google" / "Chrome" / "User Data"),
            ("edge", local_app_data / "Microsoft" / "Edge" / "User Data"),
        ]
        for kind, path in preferred:
            if path.exists():
                return path, f"real-{kind}"

        fallback_name = self.cfg.get("profile_dir", ".gptpro-browser")
        return (self.workspace / fallback_name).resolve(), "fallback-local"

    def _build_launch_kwargs(self, user_data_dir_override: str | None = None) -> tuple[dict, list[str], str]:
        profile_dir, _ = self._resolve_profile_dir(user_data_dir_override)
        if not profile_dir.exists():
            profile_dir.mkdir(parents=True, exist_ok=True)
        base_args = [str(arg) for arg in self.cfg.get("launch_args", []) if arg != "--no-sandbox"]
        for required in (
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-blink-features=AutomationControlled",
        ):
            if required not in base_args:
                base_args.append(required)
        launch_kwargs: dict[str, object] = {
            "user_data_dir": str(profile_dir),
            "headless": bool(self.cfg.get("headless", False)),
            "args": base_args,
        }
        channel = self.cfg.get("channel")
        if channel:
            launch_kwargs["channel"] = channel
        executable_path = self.cfg.get("executable_path")
        if executable_path:
            launch_kwargs["executable_path"] = executable_path
            self._log("info", "launch kwargs has executable_path", {"executable_path": executable_path})
        return launch_kwargs, base_args, str(profile_dir)

    def _build_launch_kwargs_variant(
        self,
        user_data_dir_override: str | None = None,
        launch_mode: str = "persistent_channel",
        minimal_args: bool = False,
    ) -> tuple[dict, list[str], str]:
        profile_dir, _ = self._resolve_profile_dir(user_data_dir_override)
        if not profile_dir.exists():
            profile_dir.mkdir(parents=True, exist_ok=True)

        if minimal_args:
            base_args = ["--no-first-run", "--no-default-browser-check"]
        else:
            base_args = [str(arg) for arg in self.cfg.get("launch_args", []) if arg != "--no-sandbox"]
            for required in (
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-blink-features=AutomationControlled",
            ):
                if required not in base_args:
                    base_args.append(required)

        launch_kwargs: dict[str, object] = {
            "headless": bool(self.cfg.get("headless", False)),
            "args": base_args,
        }

        mode = launch_mode or "persistent_channel"
        if mode in {"persistent_executable", "persistent_channel"}:
            launch_kwargs["user_data_dir"] = str(profile_dir)

        if mode == "persistent_executable":
            executable_path = self.cfg.get("executable_path")
            if executable_path:
                launch_kwargs["executable_path"] = executable_path
                self._log("info", "lifecycle launch executable_path", {"launch_mode": mode, "executable_path": executable_path})
        elif mode == "persistent_channel":
            launch_kwargs["channel"] = str(self.cfg.get("channel", "chrome"))
            self._log("info", "lifecycle launch channel", {"launch_mode": mode, "channel": launch_kwargs["channel"]})
        elif mode == "nonpersistent_executable":
            executable_path = self.cfg.get("executable_path")
            if executable_path:
                launch_kwargs["executable_path"] = executable_path
                self._log("info", "lifecycle launch executable_path", {"launch_mode": mode, "executable_path": executable_path})
        elif mode == "nonpersistent_channel":
            launch_kwargs["channel"] = str(self.cfg.get("channel", "chrome"))
            self._log("info", "lifecycle launch channel", {"launch_mode": mode, "channel": launch_kwargs["channel"]})

        return launch_kwargs, base_args, str(profile_dir)

    def get_chrome_processes(self, filter_user_data_dir: str | None = None) -> list[dict[str, str]]:
        target = None
        if filter_user_data_dir:
            try:
                target = str(Path(filter_user_data_dir).resolve())
            except Exception:
                target = str(Path(filter_user_data_dir))

        script = r"""
$procs = Get-CimInstance Win32_Process -Filter "name='chrome.exe'" |
Select-Object ProcessId, CommandLine |
ConvertTo-Json -Depth 3
if ($null -eq $procs) { "[]" } else { $procs }
"""
        try:
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", script],
                capture_output=True,
                text=True,
                check=False,
                timeout=10,
            )
            if result.returncode != 0:
                self._log(
                    "warning",
                    "chrome process scan command failed",
                    {"returncode": result.returncode, "stderr": (result.stderr or "").strip()},
                )
                return []

            raw = (result.stdout or "").strip()
            if not raw:
                return []

            parsed: object = json.loads(raw)
            if isinstance(parsed, dict):
                parsed = [parsed]
            if not isinstance(parsed, list):
                return []

            all_records: list[dict[str, str]] = []
            for item in parsed:
                if not isinstance(item, dict):
                    continue
                pid = item.get("ProcessId")
                cmd = item.get("CommandLine", "") or ""
                if isinstance(pid, int):
                    pid = str(pid)
                if not isinstance(pid, str):
                    continue
                all_records.append({"pid": pid, "command_line": str(cmd)})

            if not target:
                return all_records
            target_norm = target.lower().replace("/", "\\")
            return [
                record
                for record in all_records
                if target_norm in (record.get("command_line", "").replace("/", "\\").lower())
            ]
        except Exception as exc:
            self._log("warning", "chrome process scan failed", {"error": str(exc)})
            return []

    @staticmethod
    def _normalize_path_for_match(path: str) -> str:
        return str(Path(path).resolve())

    def _find_ai_profile_pids(self, user_data_dir: str) -> list[str]:
        return [record.get("pid", "") for record in self.get_chrome_processes(filter_user_data_dir=user_data_dir) if record.get("pid")]

    def _collect_lock_files(self, user_data_dir: str) -> list[str]:
        candidate_names = ["SingletonLock", "SingletonCookie", "SingletonSocket", "lock", "lockfile"]
        dirs = [Path(user_data_dir)]
        dirs.append(Path(user_data_dir) / "Default")
        lock_files: list[str] = []
        for base in dirs:
            for name in candidate_names:
                candidate = base / name
                if candidate.exists():
                    lock_files.append(str(candidate))
        return lock_files

    def _cleanup_stale_lock_files(self, lock_files: list[str], call_id: str | None = None) -> list[str]:
        removed: list[str] = []
        if not lock_files:
            return removed
        self._set_stage("web.chrome_preflight.lock.cleanup.start", call_id=call_id, lock_count=len(lock_files))
        for lock_file in lock_files:
            path = Path(lock_file)
            try:
                if not path.exists():
                    continue
                if path.is_file():
                    path.unlink()
                elif path.is_dir():
                    try:
                        path.rmdir()
                    except Exception:
                        # best effort: some lock artifacts may remain as file-like entries
                        try:
                            for child in path.iterdir():
                                if child.is_file():
                                    child.unlink()
                        except Exception as exc:
                            self._log(
                                "warning",
                                "lock dir cleanup partial failure",
                                {"call_id": call_id or "<none>", "lock": lock_file, "error": str(exc)},
                            )
                            continue
                        path.rmdir()
                removed.append(lock_file)
            except Exception as exc:
                self._log(
                    "warning",
                    "stale lock cleanup failed",
                    {"call_id": call_id or "<none>", "lock": lock_file, "error": str(exc)},
                )
        self._set_stage("web.chrome_preflight.lock.cleanup.done", call_id=call_id, removed_count=len(removed))
        return removed

    def _check_writable(self, path: Path) -> bool:
        try:
            path.mkdir(parents=True, exist_ok=True)
            probe = path / f".bridge_mcp_write_probe_{uuid.uuid4().hex}"
            with probe.open("w", encoding="utf-8") as f:
                f.write("probe")
            probe.unlink()
            return True
        except Exception:
            return False

    def _kill_stale_profile_processes(self, matching_pids: list[str], call_id: str | None = None) -> list[str]:
        killed: list[str] = []
        if not matching_pids:
            return killed
        for pid in matching_pids:
            pid = str(pid).strip()
            if not pid.isdigit():
                continue
            try:
                result = subprocess.run(
                    ["taskkill", "/PID", pid, "/F"],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                if result.returncode == 0:
                    killed.append(pid)
                    self._log(
                        "warning",
                        "killed stale AI profile process",
                        {"call_id": call_id or "<none>", "pid": pid},
                    )
                else:
                    self._log(
                        "warning",
                        "failed to kill stale AI profile process",
                        {
                            "call_id": call_id or "<none>",
                            "pid": pid,
                            "returncode": result.returncode,
                            "stderr": (result.stderr or "").strip(),
                        },
                    )
            except Exception as exc:
                self._log(
                    "warning",
                    "taskkill exception",
                    {"call_id": call_id or "<none>", "pid": pid, "error": str(exc)},
                )
        return killed

    def _log_lifecycle(self, msg: str, **extra: object) -> None:
        if extra:
            details = ", ".join([f"{k}={v}" for k, v in sorted(extra.items())])
            logging.info("[CHROME_LIFECYCLE] %s %s", msg, details)
        else:
            logging.info("[CHROME_LIFECYCLE] %s", msg)
        self._flush_log_handlers()

    def _chrome_process_snapshot(self, profile_dir: str | None = None) -> dict[str, object]:
        all_processes = self.get_chrome_processes()
        matched_processes = self.get_chrome_processes(profile_dir) if profile_dir else []
        return {
            "chrome_processes_count": len(all_processes),
            "chrome_processes": all_processes,
            "matched_count": len(matched_processes),
            "matched_pids": [p.get("pid", "") for p in matched_processes],
            "matched_processes": [p.get("command_line", "") for p in matched_processes],
        }

    async def _safe_close_context(self, browser, call_id: str | None = None, stage_prefix: str = "web") -> str | None:
        if browser is None:
            return None
        try:
            await browser.close()
            self._log("info", "context closed", {"call_id": call_id or "<none>", "stage_prefix": stage_prefix})
            self._set_stage(f"{stage_prefix}.close", call_id=call_id or "<none>", status="ok")
            return None
        except Exception as exc:
            close_error = f"{type(exc).__name__}: {exc}"
            self._log("warning", "context close failed", {"call_id": call_id or "<none>", "stage_prefix": stage_prefix, "error": close_error})
            self._set_stage(f"{stage_prefix}.close", call_id=call_id or "<none>", status="error")
            return close_error

    async def _safe_close_page(self, page, call_id: str | None = None, stage_prefix: str = "web.page") -> tuple[bool, str | None]:
        if page is None:
            return False, None
        try:
            if page.is_closed():
                self._set_stage(f"{stage_prefix}.close.done", call_id=call_id or "<none>", fresh_page_closed=True, already_closed=True)
                return True, None
        except Exception as exc:
            close_error = f"{type(exc).__name__}: {exc}"
            self._set_stage(f"{stage_prefix}.close.warning", call_id=call_id or "<none>", error=close_error)
            return False, close_error

        try:
            await page.close()
            pages_after = "<unknown>"
            try:
                pages_after = len(page.context.pages)
            except Exception:
                pass
            logging.info(
                "[TAB_STATE] call_id=%s pages_after_fresh_page_close=%s fresh_page_closed=true",
                call_id or "<none>",
                pages_after,
            )
            self._set_stage(f"{stage_prefix}.close.done", call_id=call_id or "<none>", fresh_page_closed=True)
            return True, None
        except Exception as exc:
            close_error = f"{type(exc).__name__}: {exc}"
            self._log("warning", "fresh page close failed", {"call_id": call_id or "<none>", "stage_prefix": stage_prefix, "error": close_error})
            self._set_stage(f"{stage_prefix}.close.warning", call_id=call_id or "<none>", error=close_error)
            return False, close_error

    async def _safe_prepare_keepalive_page(self, page, call_id: str | None = None, stage_prefix: str = "web.page") -> tuple[bool, str | None]:
        if page is None:
            return False, None
        try:
            if page.is_closed():
                return False, None
            await page.goto("about:blank", wait_until="domcontentloaded", timeout=5000)
            logging.info("[TAB_STATE] call_id=%s fresh_page_kept_as_about_blank=true", call_id or "<none>")
            self._set_stage(f"{stage_prefix}.keepalive.done", call_id=call_id or "<none>", fresh_page_kept_as_about_blank=True)
            return True, None
        except Exception as exc:
            keepalive_error = f"{type(exc).__name__}: {exc}"
            self._log("warning", "fresh page keepalive prepare failed", {"call_id": call_id or "<none>", "stage_prefix": stage_prefix, "error": keepalive_error})
            self._set_stage(f"{stage_prefix}.keepalive.warning", call_id=call_id or "<none>", error=keepalive_error)
            return False, keepalive_error

    async def _safe_ensure_keepalive_page(self, context, call_id: str | None = None, stage_prefix: str = "web") -> tuple[bool, str | None]:
        try:
            for page in context.pages:
                try:
                    if not page.is_closed() and self._tab_kind(page.url) == "about_blank":
                        self._set_stage(f"{stage_prefix}.keepalive.exists", call_id=call_id or "<none>")
                        return True, None
                except Exception:
                    continue
            page = await context.new_page()
            await page.goto("about:blank", wait_until="domcontentloaded", timeout=5000)
            logging.info("[TAB_STATE] call_id=%s ensured_about_blank_keepalive=true", call_id or "<none>")
            self._set_stage(f"{stage_prefix}.keepalive.created", call_id=call_id or "<none>", ensured_about_blank_keepalive=True)
            return True, None
        except Exception as exc:
            keepalive_error = f"{type(exc).__name__}: {exc}"
            self._log("warning", "ensure keepalive page failed", {"call_id": call_id or "<none>", "stage_prefix": stage_prefix, "error": keepalive_error})
            self._set_stage(f"{stage_prefix}.keepalive.warning", call_id=call_id or "<none>", error=keepalive_error)
            return False, keepalive_error

    def _tab_cleanup_config(self) -> dict[str, object]:
        cfg = self.browser_tabs_cfg if isinstance(self.browser_tabs_cfg, dict) else {}
        return {
            "cleanup_before_query": bool(cfg.get("cleanup_before_query", True)),
            "cleanup_after_query": bool(cfg.get("cleanup_after_query", True)),
            "keep_latest_chatgpt_tabs": max(0, int(cfg.get("keep_latest_chatgpt_tabs", 0))),
            "close_about_blank": bool(cfg.get("close_about_blank", True)),
            "close_chatgpt_tabs": bool(cfg.get("close_chatgpt_tabs", True)),
            "max_tabs_warning_threshold": max(1, int(cfg.get("max_tabs_warning_threshold", 5))),
        }

    def _is_cleanup_candidate(self, url: str, cfg: dict[str, object]) -> bool:
        kind = self._tab_kind(url)
        if kind == "chatgpt":
            return bool(cfg["close_chatgpt_tabs"])
        if kind == "about_blank":
            return bool(cfg["close_about_blank"])
        return False

    async def _cleanup_browser_tabs(self, context, call_id: str, phase: str) -> dict[str, object]:
        cfg = self._tab_cleanup_config()
        pages = list(context.pages)
        page_records: list[tuple[int, object, str, str]] = []
        for index, page in enumerate(pages):
            try:
                if page.is_closed():
                    continue
            except Exception:
                continue
            try:
                url = page.url
            except Exception:
                url = ""
            page_records.append((index, page, url, self._tab_kind(url)))

        chatgpt_records = [record for record in page_records if record[3] == "chatgpt"]
        about_blank_records = [record for record in page_records if record[3] == "about_blank"]
        keep_latest = int(cfg["keep_latest_chatgpt_tabs"])
        kept_chatgpt = chatgpt_records[-keep_latest:] if keep_latest else []
        kept_page_ids = {id(record[1]) for record in kept_chatgpt}
        to_close = [
            record
            for record in page_records
            if self._is_cleanup_candidate(record[2], cfg) and id(record[1]) not in kept_page_ids
        ]
        keepalive_preserved = False
        if page_records and len(to_close) == len(page_records):
            keepalive_record = about_blank_records[-1] if about_blank_records else to_close[-1]
            keepalive_page_id = id(keepalive_record[1])
            to_close = [record for record in to_close if id(record[1]) != keepalive_page_id]
            keepalive_preserved = True
        closed = 0
        warnings: list[str] = []

        logging.info(
            "[TAB_CLEANUP] call_id=%s phase=%s pages_before=%s chatgpt_pages_before=%s about_blank_pages_before=%s keep_latest_chatgpt_tabs=%s to_close=%s keepalive_preserved=%s",
            call_id,
            phase,
            len(page_records),
            len(chatgpt_records),
            len(about_blank_records),
            keep_latest,
            len(to_close),
            keepalive_preserved,
        )
        self._set_stage(
            f"web.tabs.cleanup.{phase}.start",
            call_id=call_id,
            pages_before=len(page_records),
            chatgpt_pages_before=len(chatgpt_records),
            about_blank_pages_before=len(about_blank_records),
            to_close=len(to_close),
            keepalive_preserved=keepalive_preserved,
        )

        for index, page, url, kind in to_close:
            try:
                if not page.is_closed():
                    if kind == "chatgpt":
                        try:
                            await page.goto("about:blank", wait_until="domcontentloaded", timeout=3000)
                        except Exception:
                            pass
                    await page.close(run_before_unload=False)
                    closed += 1
            except Exception as exc:
                warnings.append(f"{index}:{kind}:{type(exc).__name__}:{exc}")

        if closed:
            await asyncio.sleep(1.0)

        remaining_urls = []
        for page in context.pages:
            try:
                if not page.is_closed():
                    remaining_urls.append(page.url)
            except Exception:
                pass
        pages_after = len(remaining_urls)
        chatgpt_after = sum(1 for url in remaining_urls if self._tab_kind(url) == "chatgpt")
        about_blank_after = sum(1 for url in remaining_urls if self._tab_kind(url) == "about_blank")
        warning = "tab leak risk" if pages_after > int(cfg["max_tabs_warning_threshold"]) else "<none>"

        logging.info(
            "[TAB_CLEANUP] call_id=%s phase=%s closed=%s pages_after=%s chatgpt_pages_after=%s about_blank_pages_after=%s warning=%s close_warnings=%s",
            call_id,
            phase,
            closed,
            pages_after,
            chatgpt_after,
            about_blank_after,
            warning,
            warnings[:5],
        )
        self._set_stage(
            f"web.tabs.cleanup.{phase}.done",
            call_id=call_id,
            closed=closed,
            pages_after=pages_after,
            chatgpt_pages_after=chatgpt_after,
            about_blank_pages_after=about_blank_after,
            warning=warning,
        )
        return {
            "pages_before": len(page_records),
            "chatgpt_pages_before": len(chatgpt_records),
            "about_blank_pages_before": len(about_blank_records),
            "to_close": len(to_close),
            "closed": closed,
            "pages_after": pages_after,
            "chatgpt_pages_after": chatgpt_after,
            "about_blank_pages_after": about_blank_after,
            "warning": warning,
            "close_warnings": warnings,
            "keepalive_preserved": keepalive_preserved,
        }

    async def _safe_cleanup_browser_tabs(self, context, call_id: str, phase: str) -> dict[str, object]:
        try:
            return await self._cleanup_browser_tabs(context, call_id, phase)
        except Exception as exc:
            warning = f"{type(exc).__name__}: {exc}"
            logging.warning("[TAB_CLEANUP] call_id=%s phase=%s cleanup_warning=%s", call_id, phase, warning)
            self._set_stage(f"web.tabs.cleanup.{phase}.warning", call_id=call_id, error=warning)
            return {"warning": warning, "closed": 0}

    def run_chrome_preflight(self, user_data_dir_override: str | None = None) -> dict[str, object]:
        executable_path = self.cfg.get("executable_path", "")
        executable_exists = bool(executable_path and Path(os.path.expandvars(os.path.expanduser(executable_path))).exists())
        profile_dir, _ = self._resolve_profile_dir(user_data_dir_override)
        profile_dir_str = str(profile_dir)
        profile_dir_exists = profile_dir.exists()
        user_data_dir_writable = self._check_writable(profile_dir)
        matching_pids = self._find_ai_profile_pids(profile_dir_str)
        profile_in_use = len(matching_pids) > 0
        lock_files = self._collect_lock_files(profile_dir_str)
        _, launch_args, _ = self._build_launch_kwargs()
        auto_remove_stale_lock = bool(self.runtime_cfg.get("auto_remove_stale_lock", False))
        removed_stale_lock_files: list[str] = []
        stale_lock_suspected = (not profile_in_use) and len(lock_files) > 0
        if stale_lock_suspected and auto_remove_stale_lock:
            removed_stale_lock_files = self._cleanup_stale_lock_files(lock_files, call_id=None)
            lock_files = [f for f in lock_files if f not in removed_stale_lock_files]
        self._log_chrome_preflight(
            executable_path,
            executable_exists,
            profile_dir_str,
            profile_dir_exists,
            user_data_dir_writable,
            profile_in_use,
            matching_pids,
            launch_args,
            lock_files,
            stale_lock_suspected=stale_lock_suspected,
            auto_remove_stale_lock=auto_remove_stale_lock,
            removed_stale_lock_files=removed_stale_lock_files,
        )
        return {
            "executable_path": executable_path,
            "executable_exists": executable_exists,
            "user_data_dir": profile_dir_str,
            "user_data_dir_exists": profile_dir_exists,
            "user_data_dir_writable": user_data_dir_writable,
            "profile_in_use": profile_in_use,
            "matching_pids": matching_pids,
            "lock_files": lock_files,
            "stale_lock_suspected": stale_lock_suspected,
            "auto_remove_stale_lock": auto_remove_stale_lock,
            "lock_files_cleaned": removed_stale_lock_files,
            "removed_stale_lock_files": removed_stale_lock_files,
            "launch_args": launch_args,
        }

    def _format_preflight_result_text(self, preflight: dict[str, object]) -> str:
        if preflight.get("profile_in_use"):
            return (
                "BRIDGE_CHROME_PREFLIGHT_FAILED\n"
                f"executable_path={preflight.get('executable_path')}\n"
                f"executable_exists={preflight.get('executable_exists')}\n"
                f"user_data_dir={preflight.get('user_data_dir')}\n"
                f"user_data_dir_exists={preflight.get('user_data_dir_exists')}\n"
                f"user_data_dir_writable={preflight.get('user_data_dir_writable')}\n"
                f"profile_in_use={preflight.get('profile_in_use')}\n"
                f"matching_pids={preflight.get('matching_pids')}\n"
                "recommended_action=close AI Bridge Chrome or kill only processes with --user-data-dir=gptpro_profile"
            )
        if preflight.get("stale_lock_suspected"):
            return (
                "BRIDGE_CHROME_PREFLIGHT_OK\n"
                f"executable_path={preflight.get('executable_path')}\n"
                f"executable_exists={preflight.get('executable_exists')}\n"
                f"user_data_dir={preflight.get('user_data_dir')}\n"
                f"user_data_dir_exists={preflight.get('user_data_dir_exists')}\n"
                f"user_data_dir_writable={preflight.get('user_data_dir_writable')}\n"
                f"profile_in_use={preflight.get('profile_in_use')}\n"
                f"matching_pids={preflight.get('matching_pids')}\n"
                f"lock_files={preflight.get('lock_files')}\n"
                f"stale_lock_files_removed={preflight.get('removed_stale_lock_files')}\n"
                f"stale_lock_suspected={preflight.get('stale_lock_suspected')}\n"
                f"auto_remove_stale_lock={preflight.get('auto_remove_stale_lock')}\n"
                f"launch_args={preflight.get('launch_args')}\n"
                "recommended_action=delete stale lock files or recreate AI profile"
            )
        return (
            "BRIDGE_CHROME_PREFLIGHT_OK\n"
            f"executable_path={preflight.get('executable_path')}\n"
            f"executable_exists={preflight.get('executable_exists')}\n"
            f"user_data_dir={preflight.get('user_data_dir')}\n"
            f"user_data_dir_exists={preflight.get('user_data_dir_exists')}\n"
            f"user_data_dir_writable={preflight.get('user_data_dir_writable')}\n"
            f"profile_in_use={preflight.get('profile_in_use')}\n"
            f"matching_pids={preflight.get('matching_pids')}\n"
            f"lock_files={preflight.get('lock_files')}\n"
            f"stale_lock_suspected={preflight.get('stale_lock_suspected')}\n"
            f"auto_remove_stale_lock={preflight.get('auto_remove_stale_lock')}\n"
            f"launch_args={preflight.get('launch_args')}\n"
            "recommended_action=ready_to_launch"
        )

    async def _launch_context(
        self,
        p,
        call_id: str,
        preflight: dict[str, object],
        user_data_dir_override: str | None = None,
    ) -> tuple[object, list[str], str]:
        browser_launch_timeout = self._runtime_seconds("browser_launch_timeout_seconds", 45)
        launch_kwargs, launch_args, user_data_dir = self._build_launch_kwargs(user_data_dir_override)
        launch_kwargs["timeout"] = browser_launch_timeout * 1000
        self._set_stage("web.browser.launch.start", call_id=call_id, timeout_sec=browser_launch_timeout, user_data_dir=user_data_dir)
        self._log(
            "info",
            "launch kwargs",
            {"call_id": call_id, "launch_kwargs": launch_kwargs},
        )
        self._log(
            "info",
            "launch args final",
            {"call_id": call_id, "args": launch_args},
        )

        if not preflight["executable_path"]:
            raise RuntimeError(self._raise_web_error("browser.launch", "executable_path_missing"))
        if not preflight["executable_exists"]:
            raise RuntimeError(
                self._raise_web_error("browser.launch", "executable_missing", {"path": preflight["executable_path"]})
            )
        if not preflight["user_data_dir_exists"]:
            raise RuntimeError(self._raise_web_error("browser.launch", "user_data_dir_missing"))
        if not preflight["user_data_dir_writable"]:
            raise RuntimeError(
                self._raise_web_error("browser.launch", "user_data_dir_not_writable", {"user_data_dir": preflight["user_data_dir"]})
            )

        auto_kill = bool(self.runtime_cfg.get("auto_kill_stale_ai_chrome", False))
        if preflight["profile_in_use"] and not auto_kill:
            raise RuntimeError(
                self._raise_web_error(
                    "browser.launch",
                    "profile_in_use",
                    {"matching_pids": preflight["matching_pids"]},
                )
            )
        if preflight["profile_in_use"] and auto_kill:
            self._set_stage("web.chrome_preflight.kill_stale", call_id=call_id)
            matching_pids = [str(p) for p in (preflight.get("matching_pids") or [])]
            killed_pids = self._kill_stale_profile_processes(matching_pids, call_id=call_id)
            self._set_stage(
                "web.chrome_preflight.kill_stale.done",
                call_id=call_id,
                killed= ",".join(killed_pids) if killed_pids else "<none>",
            )

        browser = await asyncio.wait_for(
            p.chromium.launch_persistent_context(**launch_kwargs),
            timeout=browser_launch_timeout + 5,
        )
        self._set_stage(
            "web.browser.launch.done",
            call_id=call_id,
            status="ok",
            context_created=True,
            page_count=len(browser.pages),
        )
        return browser, launch_args, user_data_dir

    async def _open_fresh_page(
        self,
        context,
        target_url: str,
        call_id: str,
        page_stage_prefix: str = "web.query",
        goto_stage_prefix: str = "web",
        goto_timeout_ms: int | None = None,
        ) -> tuple[object, int, bool, bool, str, bool, str, str]:
        existing_pages_count = len(context.pages)
        logging.info("[TAB_STATE] call_id=%s existing_pages_before=%s", call_id, existing_pages_count)
        self._set_stage(
            f"{page_stage_prefix}.new_page.start",
            call_id=call_id,
            existing_pages_count=existing_pages_count,
        )

        page = await context.new_page()
        logging.info("[TAB_STATE] call_id=%s existing_pages_after_new_page=%s", call_id, len(context.pages))
        fresh_page_created = page is not None
        fresh_page_url = ""
        fresh_page_is_closed = True
        page_url_before_goto = ""
        page_url_after_goto = ""

        if page is not None:
            fresh_page_url = page.url
            fresh_page_is_closed = page.is_closed()
            try:
                page_url_before_goto = page.url
            except Exception:
                page_url_before_goto = ""

        self._set_stage(
            f"{page_stage_prefix}.new_page.done",
            call_id=call_id,
            fresh_page_created=fresh_page_created,
            fresh_page_url=fresh_page_url,
            fresh_page_closed_before_goto=fresh_page_is_closed,
            existing_pages_count=existing_pages_count,
        )

        if page is None:
            raise RuntimeError(self._raise_web_error("page.create", "no available page"))

        page_closed_before_goto = page.is_closed()
        self._set_stage(
            f"{page_stage_prefix}.page_closed_before_goto",
            call_id=call_id,
            page_closed_before_goto=page_closed_before_goto,
        )
        if page_closed_before_goto:
            raise RuntimeError(self._raise_web_error("page.create", "page is closed before goto"))

        if goto_timeout_ms is None:
            goto_timeout_ms = self._runtime_seconds("web_query_timeout_seconds", 150) * 1000

        self._set_stage(f"{goto_stage_prefix}.goto.start", call_id=call_id, target_url=target_url)
        await asyncio.wait_for(
            page.goto(target_url, wait_until="domcontentloaded", timeout=goto_timeout_ms),
            timeout=(goto_timeout_ms / 1000) + 2,
        )
        try:
            page_url_after_goto = page.url
        except Exception:
            page_url_after_goto = ""

        self._set_stage(
            f"{goto_stage_prefix}.goto.done",
            call_id=call_id,
            url=page_url_after_goto,
            status="ok",
        )

        return (
            page,
            existing_pages_count,
            fresh_page_created,
            fresh_page_is_closed,
            fresh_page_url,
            page_closed_before_goto,
            page_url_before_goto,
            page_url_after_goto,
        )

    async def _query_inner(self, prompt: str, base_url: str, prompt_timeout_ms: int, call_id: str, preflight: dict[str, object]) -> str:
        browser = None
        page = None
        close_error: str | None = None
        page_close_error: str | None = None
        result_text: str | None = None
        error_text: str | None = None
        try:
            from playwright.async_api import async_playwright

            async with async_playwright() as p:
                browser, launch_args, _ = await self._launch_context(p, call_id, preflight)
                self._log(
                    "info",
                    "launch persistent context config",
                    {
                        "call_id": call_id,
                        "user_data_dir": preflight["user_data_dir"],
                        "headless": bool(self.cfg.get("headless", False)),
                        "channel": self.cfg.get("channel"),
                        "launch_args": launch_args,
                    },
                )

                if self._tab_cleanup_config()["cleanup_before_query"]:
                    await self._safe_cleanup_browser_tabs(browser, call_id, phase="before_query")

                (
                    page,
                    _,
                    _,
                    _,
                    _,
                    _,
                    _,
                    _,
                ) = await self._open_fresh_page(
                    browser,
                    base_url,
                    call_id,
                    page_stage_prefix="web.query",
                    goto_stage_prefix="web",
                    goto_timeout_ms=120000,
                )

                self._set_stage("web.model_selection.start", call_id=call_id)
                selected_model = await self._select_best_available_model(page, call_id)
                self._log("info", "Selected / current model", {"call_id": call_id, "model": selected_model})
                self._set_stage("web.model_selection.done", call_id=call_id, model=selected_model)

                input_selectors = self._merge_selectors(
                    list(self.cfg.get("input_selectors", [])),
                    [
                        "#prompt-textarea",
                        "textarea",
                        'div[contenteditable="true"]',
                        '[contenteditable="true"]',
                    ],
                )
                send_selectors = self._merge_selectors(
                    list(self.cfg.get("send_selectors", [])),
                    [
                        'button[data-testid="send-button"]',
                        'button[aria-label*="Send"]',
                        'button[aria-label*="发送"]',
                    ],
                )
                response_selectors = self._merge_selectors(
                    list(self.cfg.get("response_selectors", [])),
                    [
                        '[data-message-author-role="assistant"]',
                        '[data-testid*="conversation-turn"] [data-message-author-role="assistant"]',
                        'div[data-message-author-role="assistant"]',
                        'article:has([data-message-author-role="assistant"])',
                        "div.markdown",
                        ".markdown",
                    ],
                )
                user_selectors = [
                    '[data-message-author-role="user"]',
                    'div[data-message-author-role="user"]',
                ]
                self._log(
                    "debug",
                    "selectors loaded",
                    {
                        "call_id": call_id,
                        "input": input_selectors,
                        "send": send_selectors,
                        "response": response_selectors,
                    },
                )

                expected_marker = self._extract_expected_marker(prompt)
                assistant_count_before = await self._count_nodes(page, response_selectors)
                user_count_before = await self._count_nodes(page, user_selectors)
                last_assistant_text_before = await self._last_node_text(page, response_selectors)
                logging.info(
                    "[RESPONSE_WAIT] call_id=%s assistant_count_before=%s last_assistant_len_before=%s expected_marker=%s",
                    call_id,
                    assistant_count_before,
                    len(last_assistant_text_before),
                    expected_marker or "<none>",
                )

                self._set_stage("web.prompt.send.start", call_id=call_id)
                self._log("info", "typing prompt", {"call_id": call_id})
                self._log("info", "Sending prompt to ChatGPT Web", {"call_id": call_id})
                input_box = await self._find_element(page, input_selectors, call_id, timeout_ms=prompt_timeout_ms)
                if input_box is None:
                    self._log("error", "input selector not found", {"call_id": call_id})
                    error_text = self._raise_web_error("input.selector", "cannot find chat input field")
                else:
                    await asyncio.wait_for(input_box.fill(prompt), timeout=prompt_timeout_ms / 1000)
                    await input_box.press("Enter")
                    self._log("info", "send clicked", {"call_id": call_id, "method": "press_enter"})
                    self._set_stage("web.prompt.send.done", call_id=call_id, method="press_enter")

                    if send_btn := await self._find_element(page, send_selectors, call_id, timeout_ms=5000):
                        try:
                            await asyncio.wait_for(send_btn.click(timeout=1200), timeout=5)
                            self._log("info", "send clicked", {"call_id": call_id, "method": "send_button"})
                        except Exception as exc:
                            self._log("warning", "send clicked failed, ignored", {"call_id": call_id, "error": str(exc)})

                    await page.wait_for_timeout(1500)
                    user_count_after = await self._count_nodes(page, user_selectors)
                    body_preview_after_send = await self._body_text_preview(page)
                    input_cleared = await self._input_is_cleared(input_box)
                    prompt_marker_visible = bool(expected_marker and expected_marker in body_preview_after_send)
                    send_verified = user_count_after > user_count_before or prompt_marker_visible or input_cleared
                    logging.info(
                        "[PROMPT_SEND_VERIFY] call_id=%s user_count_before=%s user_count_after=%s input_cleared=%s prompt_marker_visible=%s send_verified=%s",
                        call_id,
                        user_count_before,
                        user_count_after,
                        input_cleared,
                        prompt_marker_visible,
                        send_verified,
                    )
                    self._flush_log_handlers()
                    if not send_verified:
                        error_text = self._raise_web_error(
                            "prompt.send.verify",
                            "user_message_not_detected",
                            {
                                "user_count_before": user_count_before,
                                "user_count_after": user_count_after,
                                "input_cleared": input_cleared,
                                "prompt_marker_visible": prompt_marker_visible,
                            },
                        )
                    else:
                        self._set_stage("web.response.wait.start", call_id=call_id)
                        self._log("info", "waiting assistant response", {"call_id": call_id})
                        final, wait_error = await self._wait_for_assistant_response(
                            page,
                            call_id,
                            response_selectors,
                            user_selectors,
                            assistant_count_before,
                            last_assistant_text_before,
                            expected_marker,
                        )
                        if wait_error is not None:
                            self._set_stage("web.response.wait.done", call_id=call_id, status="failed")
                            error_text = wait_error
                        else:
                            final = (final or "").strip()
                            self._set_stage("web.response.wait.done", call_id=call_id, status="ok")
                            self._log(
                                "info",
                                "response length",
                                {
                                    "call_id": call_id,
                                    "response_len": len(final),
                                    "selector": "multi-selector-watchdog",
                                },
                            )
                            logging.info("[WEB] response received")
                            self._log("info", "response received", {"call_id": call_id, "len": len(final)})
                            result_text = final
        except Exception as exc:
            if isinstance(exc, RuntimeError) and str(exc).startswith("[WEB_ERROR]"):
                raise
            if error_text is None:
                error_text = self._raise_web_error("web.query", exc)
        finally:
            if page is not None:
                self._log("info", "prepare fresh page as keepalive", {"call_id": call_id})
                _, page_close_error = await self._safe_prepare_keepalive_page(page, call_id=call_id, stage_prefix="web.query.page")
            if browser is not None:
                await self._safe_ensure_keepalive_page(browser, call_id=call_id, stage_prefix="web.query")
                if self._tab_cleanup_config()["cleanup_after_query"]:
                    await self._safe_cleanup_browser_tabs(browser, call_id, phase="after_query")
                self._log("info", "close context", {"call_id": call_id})
                self._set_stage("web.close.start", call_id=call_id, status="start")
                close_error = await self._safe_close_context(browser, call_id=call_id, stage_prefix="web.query")
                self._set_stage("web.close.done", call_id=call_id, status="done", close_warning=close_error or "<none>")

        if close_error and result_text is None and error_text is None:
            return self._raise_web_error("web.close", close_error, {"check_log": "bridge_mcp.log", "stage": "web.close"})

        if error_text is not None:
            warnings = []
            if page_close_error:
                warnings.append(f"page_close_warning={page_close_error}")
            if close_error:
                warnings.append(f"close_warning={close_error}")
            if warnings:
                return "\n".join([error_text, *warnings])
            return error_text

        if result_text is None:
            return self._raise_web_error("web.query", "No response")
        logging.info("[WEB_RETURN] %s", result_text[:120])
        return result_text

    async def query(self, prompt: str) -> str:
        logging.info("[WEB] query enter")
        self._set_stage("web.query.enter")
        self._log("info", "ChatGPT Web adapter enabled")
        call_id = str(uuid.uuid4())
        started_at = datetime.now(tz=timezone.utc).isoformat()
        self._log(
            "info",
            "query start",
            {
                "call_id": call_id,
                "started_at": started_at,
                "prompt_preview": prompt[:120].replace("\n", " "),
            },
        )
        self._log(
            "debug",
            "prompt fingerprint",
            {"call_id": call_id, "sha1": hashlib.sha1(prompt.encode("utf-8", errors="replace")).hexdigest()},
        )
        self._set_stage("web.query.start", call_id=call_id)

        preflight = self.run_chrome_preflight()
        self._set_stage("web.chrome_preflight.done", call_id=call_id, executable_exists=preflight["executable_exists"], user_data_dir_writable=preflight["user_data_dir_writable"])
        self._log("info", "preflight", {"call_id": call_id, "pref": preflight})

        base_url = self.cfg.get("base_url", "https://chatgpt.com")
        prompt_timeout_ms = self._runtime_seconds("web_query_timeout_seconds", 150) * 1000

        browser_launch_timeout = self._runtime_seconds("browser_launch_timeout_seconds", 45)

        try:
            return await self._query_inner(prompt, base_url, prompt_timeout_ms, call_id, preflight)
        except Exception as exc:
            if isinstance(exc, RuntimeError) and str(exc).startswith("[WEB_ERROR]"):
                return str(exc)
            if "timeout" in str(exc).lower():
                self._set_stage("web.browser.launch.done", call_id=call_id, status="timeout")
                return self._raise_web_error(
                    "browser.launch",
                    "timeout",
                    {
                        "timeout_seconds": browser_launch_timeout,
                        "profile_in_use": preflight.get("profile_in_use"),
                        "check_log": "bridge_mcp.log",
                    },
                )
            return self._raise_web_error("query", str(exc))

    async def chrome_smoke_test(
        self,
        target_url: str | None = None,
        user_data_dir_override: str | None = None,
    ) -> str:
        self._set_stage("web.smoke_test.enter")
        base_url = target_url or self.cfg.get("base_url", "https://chatgpt.com")
        preflight = self.run_chrome_preflight(user_data_dir_override=user_data_dir_override)
        user_data_dir = str(preflight.get("user_data_dir") or "")
        stale_lock_suspected = bool(preflight.get("stale_lock_suspected"))
        if preflight["profile_in_use"]:
            lines = [
                "BRIDGE_CHROME_SMOKE_TEST_FAILED",
                "stage=preflight",
                "reason=profile_in_use",
                f"profile_in_use={preflight['profile_in_use']}",
                f"matching_pids={preflight['matching_pids']}",
            ]
            if stale_lock_suspected:
                lines.extend(
                    [
                        "stale_lock_suspected=true",
                        "recommended_action:",
                        "1. Close AI Bridge Chrome if open.",
                        '2. Run: "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe" --user-data-dir="%USERPROFILE%\\gptpro_profile_2"',
                        f"3. Delete {user_data_dir}/Default/lock",
                        "4. Or create a new profile %USERPROFILE%\\gptpro_profile_2 and login ChatGPT again.",
                        '5. Then set web_adapter.user_data_dir to that new profile path.',
                    ]
                )
            return "\n".join(lines)
        if not preflight["executable_exists"] or not preflight["user_data_dir_exists"] or not preflight["user_data_dir_writable"]:
            lines = [
                "BRIDGE_CHROME_SMOKE_TEST_FAILED",
                "stage=preflight",
                "reason=environment_not_ready",
                f"executable_exists={preflight['executable_exists']}",
                f"user_data_dir_exists={preflight['user_data_dir_exists']}",
                f"user_data_dir_writable={preflight['user_data_dir_writable']}",
            ]
            if stale_lock_suspected:
                lines.extend(
                    [
                        "stale_lock_suspected=true",
                        "recommended_action:",
                        "1. Close AI Bridge Chrome if open.",
                        '2. Run: "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe" --user-data-dir="%USERPROFILE%\\gptpro_profile_2"',
                        f"3. Delete {user_data_dir}/Default/lock",
                        "4. Or create a new profile %USERPROFILE%\\gptpro_profile_2 and login ChatGPT again.",
                        '5. Then set web_adapter.user_data_dir to that new profile path.',
                    ]
                )
            return "\n".join(lines)

        start = time.time()
        call_id = str(uuid.uuid4())
        stage = "browser.launch"
        browser = None
        page: object | None = None
        close_error: str | None = None
        page_close_error: str | None = None
        launch_args: list[str] = []
        launch_done = False
        context_created = False
        context_is_alive = False
        pages_count = 0
        existing_pages_count = 0
        page_created = False
        page_closed_before_goto = False
        fresh_page_url = ""
        fresh_page_is_closed = False
        page_url_before_goto = ""
        page_url_after_goto = ""
        result_text: str | None = None
        error_text: str | None = None
        fresh_page_closed = False
        fresh_page_kept_as_keepalive = False
        try:
            self._set_stage("web.smoke_test.launch_start", call_id=call_id)
            from playwright.async_api import async_playwright
            async with async_playwright() as p:
                browser, launch_args, _ = await self._launch_context(p, call_id, preflight, user_data_dir_override=user_data_dir_override)
                launch_done = True
                stage = "browser.launch.done"
                self._set_stage("web.smoke_test.browser.launch", call_id=call_id, status="ok", launch_args=launch_args)
                context_created = browser is not None
                self._set_stage("web.smoke_test.launch_done", call_id=call_id, context_created=context_created, page_count=len(browser.pages) if browser else 0)
                try:
                    context_is_alive = not browser.is_closed()
                except Exception:
                    context_is_alive = True
                self._set_stage(
                    "web.smoke_test.context_created",
                    call_id=call_id,
                    context_created=context_is_alive,
                    page_count=len(browser.pages) if browser else 0,
                )
                self._log(
                    "info",
                    "smoke test launch",
                    {"call_id": call_id, "launch_args": launch_args, "target_url": base_url},
                )
                if self._tab_cleanup_config()["cleanup_before_query"]:
                    await self._safe_cleanup_browser_tabs(browser, call_id, phase="before_smoke_test")
                stage = "page.goto"
                (
                    page,
                    pages_count,
                    page_created,
                    fresh_page_is_closed,
                    fresh_page_url,
                    page_closed_before_goto,
                    page_url_before_goto,
                    page_url_after_goto,
                ) = await self._open_fresh_page(
                    browser,
                    base_url,
                    call_id,
                    page_stage_prefix="web.smoke_test",
                    goto_stage_prefix="web.smoke_test",
                    goto_timeout_ms=self._runtime_seconds("web_query_timeout_seconds", 150) * 1000,
                )
                existing_pages_count = pages_count
                stage = "page.goto.done"
                elapsed = round(time.time() - start, 2)
                result_text = "\n".join(
                    [
                        "BRIDGE_CHROME_SMOKE_TEST_OK",
                        "browser_launched=true",
                        "launch_done=true",
                        f"context_created={context_created}",
                        f"context_is_alive={context_is_alive}",
                        f"pages_count={pages_count}",
                        f"page_created={page_created}",
                        f"page_closed_before_goto={page_closed_before_goto}",
                        f"existing_pages_count={existing_pages_count}",
                        f"fresh_page_created={page_created}",
                        f"fresh_page_created_success={page_created}",
                        f"fresh_page_url={fresh_page_url}",
                        f"fresh_page_is_closed={fresh_page_is_closed}",
                        f"fresh_page_closed_before_goto={page_closed_before_goto}",
                        f"page_url_before_goto={page_url_before_goto}",
                        "goto_done=true",
                        f"goto_target={base_url}",
                        f"page_url_after_goto={page_url_after_goto}",
                        f"target_url={base_url}",
                        f"profile_dir={user_data_dir}",
                        f"current_url={page_url_after_goto}",
                        f"elapsed_seconds={elapsed}",
                    ]
                )
        except Exception as exc:
            if isinstance(exc, RuntimeError) and str(exc).startswith("[WEB_ERROR]"):
                raw_error = str(exc).strip()
                lines = raw_error.splitlines()
                # expected format:
                # [WEB_ERROR]
                # stage=<...>
                # reason=<...>
                for line in lines:
                    if line.startswith("stage="):
                        stage = line.split("=", 1)[1].strip()
                        break
                filtered = [line for line in lines if line and not line.startswith("[WEB_ERROR]") and not line.startswith("stage=")]
                message = " | ".join(filtered) if filtered else raw_error
            else:
                message = str(exc).replace("\n", " | ")
            close_warning = close_error or "<none>"
            error_text = "\n".join(
                [
                    "BRIDGE_CHROME_SMOKE_TEST_FAILED",
                    f"stage={stage}",
                    f"reason={message}",
                    f"target_url={base_url}",
                    f"launch_done={launch_done}",
                    f"context_created={context_created}",
                    f"context_is_alive={context_is_alive}",
                    f"pages_count={pages_count}",
                    f"page_created={page_created}",
                    f"page_closed_before_goto={page_closed_before_goto}",
                    f"existing_pages_count={existing_pages_count}",
                    f"fresh_page_created={page_created}",
                    f"page_url_before_goto={page_url_before_goto}",
                    f"page_url_after_goto={page_url_after_goto}",
                    f"profile_dir={user_data_dir}",
                ]
            )
        finally:
            if page is not None:
                fresh_page_kept_as_keepalive, page_close_error = await self._safe_prepare_keepalive_page(page, call_id=call_id, stage_prefix="web.smoke_test.page")
                fresh_page_closed = False
            if browser is not None:
                await self._safe_ensure_keepalive_page(browser, call_id=call_id, stage_prefix="web.smoke_test")
                if self._tab_cleanup_config()["cleanup_after_query"]:
                    await self._safe_cleanup_browser_tabs(browser, call_id, phase="after_smoke_test")
                stage = "browser.close"
                self._log("info", "smoke test close context", {"call_id": call_id})
                close_error = await self._safe_close_context(browser, call_id=call_id, stage_prefix="web.smoke_test")
        self._set_stage("web.smoke_test.done", call_id=call_id)

        if error_text is not None:
            lines = [error_text]
            if not close_error:
                lines.append("close_warning_type=none")
            elif stage in {"page.create", "page.goto", "page.goto.done", "browser.launch.done"} and "Target page, context or browser has been closed" in close_error:
                lines.append("close_warning_type=close_only_warning")
            else:
                lines.append("close_warning_type=close_error")
            lines.append(f"fresh_page_closed={fresh_page_closed}")
            lines.append(f"fresh_page_kept_as_keepalive={fresh_page_kept_as_keepalive}")
            lines.append(f"fresh_page_close_warning={page_close_error or '<none>'}")
            lines.append(f"close_warning={close_error or '<none>'}")
            if preflight.get("stale_lock_suspected"):
                lines.extend(
                    [
                        "stale_lock_suspected=true",
                        "recommended_action:",
                        "1. Close AI Bridge Chrome if open.",
                        '2. Run: "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe" --user-data-dir="%USERPROFILE%\\gptpro_profile_2"',
                        f"3. Delete {user_data_dir}/Default/lock",
                        "4. Or create a new profile %USERPROFILE%\\gptpro_profile_2 and login ChatGPT again.",
                        '5. Then set web_adapter.user_data_dir to that new profile path.',
                    ]
                )
            lines.append("check_log=bridge_mcp.log")
            return "\n".join(lines)

        if result_text is not None:
            result_lines = [
                result_text,
                f"fresh_page_closed={fresh_page_closed}",
                f"fresh_page_kept_as_keepalive={fresh_page_kept_as_keepalive}",
                f"fresh_page_close_warning={page_close_error or '<none>'}",
            ]
            if close_error:
                if "Target page, context or browser has been closed" in close_error:
                    return "\n".join([*result_lines, "close_warning_type=close_only_warning", f"context_close_warning={close_error}", "check_log=bridge_mcp.log"])
                return "\n".join([*result_lines, "close_warning_type=close_error", f"context_close_warning={close_error}", "check_log=bridge_mcp.log"])
            return "\n".join([*result_lines, "close_warning_type=none", "context_close_warning=<none>", "check_log=bridge_mcp.log"])

        return "\n".join(["BRIDGE_CHROME_SMOKE_TEST_FAILED", "stage=unknown", "reason=No result produced"])

    @staticmethod
    def _tab_kind(url: str) -> str:
        normalized = (url or "").lower()
        if "chatgpt.com" in normalized:
            return "chatgpt"
        if normalized.startswith("about:blank"):
            return "about_blank"
        return "other"

    async def bridge_tab_health_check(self, user_data_dir_override: str | None = None) -> str:
        self._set_stage("web.tab_health.enter")
        preflight = self.run_chrome_preflight(user_data_dir_override=user_data_dir_override)
        if preflight["profile_in_use"]:
            return "\n".join(
                [
                    "BRIDGE_TAB_HEALTH_CHECK_FAILED",
                    "stage=preflight",
                    "reason=profile_in_use",
                    f"matching_pids={preflight['matching_pids']}",
                ]
            )

        call_id = str(uuid.uuid4())
        browser = None
        context_close_warning: str | None = None
        pages_count = 0
        chatgpt_pages_count = 0
        about_blank_pages_count = 0
        try:
            from playwright.async_api import async_playwright

            async with async_playwright() as p:
                browser, _, _ = await self._launch_context(p, call_id, preflight, user_data_dir_override=user_data_dir_override)
                urls = []
                for page in browser.pages:
                    try:
                        if page.is_closed():
                            continue
                    except Exception:
                        continue
                    try:
                        urls.append(page.url)
                    except Exception:
                        urls.append("")
                pages_count = len(urls)
                chatgpt_pages_count = sum(1 for url in urls if self._tab_kind(url) == "chatgpt")
                about_blank_pages_count = sum(1 for url in urls if self._tab_kind(url) == "about_blank")
        except Exception as exc:
            return "\n".join(
                [
                    "BRIDGE_TAB_HEALTH_CHECK_FAILED",
                    f"stage={self.last_stage}",
                    f"reason={str(exc).replace(chr(10), ' | ')}",
                    "check_log=bridge_mcp.log",
                ]
            )
        finally:
            if browser is not None:
                context_close_warning = await self._safe_close_context(browser, call_id=call_id, stage_prefix="web.tab_health")

        warning = "tab leak risk" if pages_count > 10 else "<none>"
        return "\n".join(
            [
                "BRIDGE_TAB_HEALTH_CHECK_OK",
                f"pages_count={pages_count}",
                f"chatgpt_pages_count={chatgpt_pages_count}",
                f"about_blank_pages_count={about_blank_pages_count}",
                f"warning={warning}",
                f"context_close_warning={context_close_warning or '<none>'}",
            ]
        )

    async def bridge_close_extra_tabs(
        self,
        keep_latest: int = 1,
        dry_run: bool = True,
        user_data_dir_override: str | None = None,
    ) -> str:
        self._set_stage("web.close_extra_tabs.enter", keep_latest=keep_latest, dry_run=dry_run)
        keep_latest = max(0, int(keep_latest))
        preflight = self.run_chrome_preflight(user_data_dir_override=user_data_dir_override)
        if preflight["profile_in_use"]:
            return "\n".join(
                [
                    "BRIDGE_CLOSE_EXTRA_TABS_FAILED",
                    "stage=preflight",
                    "reason=profile_in_use",
                    f"matching_pids={preflight['matching_pids']}",
                ]
            )

        call_id = str(uuid.uuid4())
        browser = None
        context_close_warning: str | None = None
        pages_total_before = 0
        pages_total_after = 0
        chatgpt_pages_before = 0
        chatgpt_pages_after = 0
        about_blank_pages_before = 0
        about_blank_pages_after = 0
        tabs_to_close: list[tuple[int, object, str, str]] = []
        closed = 0
        close_warnings: list[str] = []
        try:
            from playwright.async_api import async_playwright

            async with async_playwright() as p:
                browser, _, _ = await self._launch_context(p, call_id, preflight, user_data_dir_override=user_data_dir_override)
                page_records: list[tuple[int, object, str, str]] = []
                for index, page in enumerate(browser.pages):
                    try:
                        if page.is_closed():
                            continue
                    except Exception:
                        continue
                    try:
                        url = page.url
                    except Exception:
                        url = ""
                    page_records.append((index, page, url, self._tab_kind(url)))

                pages_total_before = len(page_records)
                chatgpt_records = [record for record in page_records if record[3] == "chatgpt"]
                about_blank_records = [record for record in page_records if record[3] == "about_blank"]
                chatgpt_pages_before = len(chatgpt_records)
                about_blank_pages_before = len(about_blank_records)
                kept_chatgpt = chatgpt_records[-keep_latest:] if keep_latest else []
                kept_ids = {id(record[1]) for record in kept_chatgpt}
                tabs_to_close = [
                    record
                    for record in page_records
                    if record[3] in {"chatgpt", "about_blank"} and id(record[1]) not in kept_ids
                ]
                keepalive_preserved = False
                if page_records and len(tabs_to_close) == len(page_records):
                    keepalive_candidates = [record for record in page_records if record[3] == "about_blank"] or page_records
                    keepalive_record = keepalive_candidates[-1]
                    keepalive_page_id = id(keepalive_record[1])
                    tabs_to_close = [record for record in tabs_to_close if id(record[1]) != keepalive_page_id]
                    keepalive_preserved = True

                if not dry_run:
                    for index, page, url, kind in tabs_to_close:
                        try:
                            if not page.is_closed():
                                if kind == "chatgpt":
                                    try:
                                        await page.goto("about:blank", wait_until="domcontentloaded", timeout=3000)
                                    except Exception:
                                        pass
                                await page.close(run_before_unload=False)
                                closed += 1
                        except Exception as exc:
                            close_warnings.append(f"{index}:{kind}:{type(exc).__name__}:{exc}")

                    if closed:
                        await asyncio.sleep(1.0)

                remaining_urls = []
                for page in browser.pages:
                    try:
                        if not page.is_closed():
                            remaining_urls.append(page.url)
                    except Exception:
                        pass
                pages_total_after = len(remaining_urls)
                chatgpt_pages_after = sum(1 for url in remaining_urls if self._tab_kind(url) == "chatgpt")
                about_blank_pages_after = sum(1 for url in remaining_urls if self._tab_kind(url) == "about_blank")
        except Exception as exc:
            return "\n".join(
                [
                    "BRIDGE_CLOSE_EXTRA_TABS_FAILED",
                    f"stage={self.last_stage}",
                    f"reason={str(exc).replace(chr(10), ' | ')}",
                    "check_log=bridge_mcp.log",
                ]
            )
        finally:
            if browser is not None:
                context_close_warning = await self._safe_close_context(browser, call_id=call_id, stage_prefix="web.close_extra_tabs")

        planned = [f"{index}:{kind}:{url}" for index, _, url, kind in tabs_to_close]
        return "\n".join(
            [
                "BRIDGE_CLOSE_EXTRA_TABS_RESULT",
                f"dry_run={str(dry_run).lower()}",
                f"keep_latest={keep_latest}",
                f"pages_total_before={pages_total_before}",
                f"chatgpt_pages_before={chatgpt_pages_before}",
                f"about_blank_pages_before={about_blank_pages_before}",
                f"tabs_to_close={len(tabs_to_close)}",
                f"tabs_to_close_preview={planned[:20]}",
                f"keepalive_preserved={keepalive_preserved}",
                f"closed={closed}",
                f"pages_total_after={pages_total_after}",
                f"chatgpt_pages_after={chatgpt_pages_after}",
                f"about_blank_pages_after={about_blank_pages_after}",
                f"close_warnings={close_warnings[:10]}",
                f"context_close_warning={context_close_warning or '<none>'}",
            ]
        )

    async def chrome_lifecycle_test(
        self,
        launch_mode: str = "persistent_executable",
        skip_goto: bool = True,
        hold_seconds: int = 10,
        target_url: str | None = None,
        minimal_args: bool = True,
        user_data_dir_override: str | None = None,
    ) -> str:
        launch_mode = str(launch_mode).strip() or "persistent_executable"
        if launch_mode not in {
            "persistent_executable",
            "persistent_channel",
            "nonpersistent_executable",
            "nonpersistent_channel",
        }:
            launch_mode = "persistent_executable"

        base_url = target_url or self.cfg.get("base_url", "https://chatgpt.com")
        resolved_mode = launch_mode
        preflight = self.run_chrome_preflight(user_data_dir_override=user_data_dir_override)
        user_data_dir = str(preflight.get("user_data_dir") or "")
        start = time.time()
        call_id = str(uuid.uuid4())
        stage = "preflight"
        close_error: str | None = None
        page_closed_before_goto = False
        launch_done = False
        launch_returned = False
        context_created = False
        context_is_alive = False
        page_created = False
        pages_count = 0
        page0_url = ""
        page0_is_closed = False
        page_url_before_goto = ""
        page_url_after_goto = ""
        goto_done = False
        browser_stayed_alive_10s = False
        close_warning = "<none>"
        error_text: str | None = None
        page = None
        context = None
        browser = None
        close_warning = "<none>"
        processes_after_launch: dict[str, object] | None = None
        processes_after_sleep: dict[str, object] | None = None

        self._log_lifecycle(
            "lifecycle test start",
            launch_mode=resolved_mode,
            user_data_dir=user_data_dir,
            target_url=base_url,
            skip_goto=skip_goto,
            hold_seconds=hold_seconds,
            minimal_args=minimal_args,
        )
        processes_before = self._chrome_process_snapshot(user_data_dir if "persistent" in resolved_mode else None)
        self._log_lifecycle(
            "chrome processes before",
            chrome_processes_count=processes_before["chrome_processes_count"],
            matched_count=processes_before["matched_count"],
            has_user_data_dir=bool(processes_before["matched_count"] or user_data_dir_override),
        )
        self._log_lifecycle(
            "chrome processes include user profile",
            pids=";".join(processes_before.get("matched_pids", []))
        )

        if preflight["profile_in_use"] and resolved_mode.startswith("persistent"):
            return (
                "BRIDGE_CHROME_LIFECYCLE_TEST_FAILED\n"
                "stage=preflight\n"
                "reason=profile_in_use\n"
                f"profile_in_use={preflight['profile_in_use']}\n"
                f"matching_pids={preflight['matching_pids']}\n"
                f"launch_mode={resolved_mode}"
            )

        if not preflight["executable_exists"] and resolved_mode not in {"persistent_channel", "nonpersistent_channel"}:
            return (
                "BRIDGE_CHROME_LIFECYCLE_TEST_FAILED\n"
                "stage=preflight\n"
                "reason=executable_missing\n"
                f"launch_mode={resolved_mode}\n"
                f"executable_exists={preflight['executable_exists']}"
            )
        if not preflight["user_data_dir_exists"]:
            return (
                "BRIDGE_CHROME_LIFECYCLE_TEST_FAILED\n"
                "stage=preflight\n"
                "reason=user_data_dir_missing\n"
                f"launch_mode={resolved_mode}\n"
                f"user_data_dir={user_data_dir}"
            )
        if not preflight["user_data_dir_writable"] and resolved_mode.startswith("persistent"):
            return (
                "BRIDGE_CHROME_LIFECYCLE_TEST_FAILED\n"
                "stage=preflight\n"
                "reason=user_data_dir_not_writable\n"
                f"launch_mode={resolved_mode}\n"
                f"user_data_dir={user_data_dir}"
            )

        browser_launch_timeout = self._runtime_seconds("browser_launch_timeout_seconds", 45)

        try:
            from playwright.async_api import async_playwright

            async with async_playwright() as p:
                launch_kwargs, launch_args, launch_user_data_dir = self._build_launch_kwargs_variant(
                    user_data_dir_override=user_data_dir_override,
                    launch_mode=resolved_mode,
                    minimal_args=minimal_args,
                )
                launch_kwargs["timeout"] = browser_launch_timeout * 1000
                self._log_lifecycle("launch kwargs", launch_kwargs=launch_kwargs, launch_args=";".join(launch_args))
                stage = "browser.launch"
                if resolved_mode.startswith("persistent"):
                    context = await asyncio.wait_for(
                        p.chromium.launch_persistent_context(**launch_kwargs),
                        timeout=browser_launch_timeout + 5,
                    )
                else:
                    browser = await asyncio.wait_for(
                        p.chromium.launch(**launch_kwargs),
                        timeout=browser_launch_timeout + 5,
                    )
                    context = await browser.new_context()
                launch_returned = True
                launch_done = True
                stage = "browser.launch.done"
                context_created = context is not None
                processes_after_launch = self._chrome_process_snapshot(launch_user_data_dir if "persistent" in resolved_mode else None)
                self._log_lifecycle(
                    "launch_returned",
                    launch_mode=resolved_mode,
                    launch_returned=launch_returned,
                    context_created=context_created,
                    page_count=len(context.pages) if context else 0,
                )
                if context:
                    try:
                        context_is_alive = not context.is_closed()
                    except Exception:
                        context_is_alive = True
                pages = context.pages if context else []
                pages_count = len(pages)
                if pages:
                    page0_url = pages[0].url
                    page0_is_closed = pages[0].is_closed()
                self._log_lifecycle(
                    "page state after launch",
                    pages_count=pages_count,
                    first_page_url=page0_url,
                    first_page_closed=page0_is_closed,
                )
                if pages and not pages[0].is_closed():
                    page = pages[0]
                    self._log_lifecycle("using existing first page", page_url=page.url)
                else:
                    page_created = True
                    self._log_lifecycle("creating new page for lifecycle test")
                    if context is None:
                        raise RuntimeError(self._raise_web_error("page.create", "context is none"))
                    page = await context.new_page()
                    if page is not None:
                        page_url_after_goto = page.url

                if page is None:
                    raise RuntimeError(self._raise_web_error("page.create", "no available page"))

                try:
                    page_url_before_goto = page.url
                except Exception:
                    page_url_before_goto = ""
                page_closed_before_goto = page.is_closed()
                if page_closed_before_goto:
                    raise RuntimeError(self._raise_web_error("page.create", "page is closed before goto"))

                if hold_seconds > 0:
                    stage = "browser.hold"
                    self._log_lifecycle("hold window", hold_seconds=hold_seconds)
                    await asyncio.sleep(hold_seconds)
                    try:
                        browser_stayed_alive_10s = context is not None and (not context.is_closed())
                    except Exception:
                        browser_stayed_alive_10s = False
                    try:
                        page_after_sleep_count = len(context.pages) if context else 0
                        page_after_sleep_closed = page.is_closed() if page else True
                    except Exception:
                        page_after_sleep_count = 0
                        page_after_sleep_closed = True
                    processes_after_sleep = self._chrome_process_snapshot(
                        launch_user_data_dir if "persistent" in resolved_mode else None
                    )
                    self._log_lifecycle(
                        "after hold",
                        browser_stayed_alive_10s=browser_stayed_alive_10s,
                        page_count=page_after_sleep_count,
                        page_closed=page_after_sleep_closed,
                        chrome_processes_count=processes_after_sleep["chrome_processes_count"],
                        matched_count=processes_after_sleep["matched_count"],
                    )

                if not skip_goto:
                    stage = "page.goto"
                    goto_timeout = self._runtime_seconds("web_query_timeout_seconds", 150) * 1000
                    await asyncio.wait_for(
                        page.goto(base_url, wait_until="domcontentloaded", timeout=goto_timeout),
                        timeout=(goto_timeout / 1000) + 2,
                    )
                    goto_done = True
                    try:
                        page_url_after_goto = page.url
                    except Exception:
                        page_url_after_goto = ""

                self._log_lifecycle(
                    "lifecycle test done",
                    launch_mode=resolved_mode,
                    launch_done=launch_done,
                    context_created=context_created,
                    goto_done=goto_done,
                    browser_stayed_alive_10s=browser_stayed_alive_10s,
                )
        except Exception as exc:
            if isinstance(exc, RuntimeError) and str(exc).startswith("[WEB_ERROR]"):
                message = str(exc).replace("\n", " | ")
            else:
                message = str(exc).replace("\n", " | ")
            error_text = "\n".join(
                [
                    "BRIDGE_CHROME_LIFECYCLE_TEST_FAILED",
                    f"stage={stage}",
                    f"reason={message}",
                    f"launch_mode={resolved_mode}",
                    f"launch_returned={launch_returned}",
                    f"context_created={context_created}",
                    f"context_is_alive={context_is_alive}",
                    f"launch_done={launch_done}",
                    f"goto_done={goto_done}",
                    f"page_created={page_created}",
                    f"page_closed_before_goto={page_closed_before_goto}",
                    f"page_url_before_goto={page_url_before_goto}",
                    f"page_url_after_goto={page_url_after_goto}",
                    f"target_url={base_url}",
                    f"profile_dir={user_data_dir}",
                ]
            )
            if preflight.get("stale_lock_suspected"):
                error_text = f"{error_text}\nstale_lock_suspected=true"
        finally:
            if context is not None:
                stage = "browser.close"
                self._log_lifecycle("closing context", launch_mode=resolved_mode)
                close_error = await self._safe_close_context(context, call_id=call_id, stage_prefix="web.lifecycle")
            if browser is not None:
                browser_close_error = await self._safe_close_context(browser, call_id=call_id, stage_prefix="web.lifecycle.browser")
                if browser_close_error and not close_error:
                    close_error = browser_close_error
            if close_error:
                close_warning = close_error

        processes_after = self._chrome_process_snapshot(user_data_dir if "persistent" in resolved_mode else None)
        processes_after_launch = processes_after_launch or processes_after
        processes_after_sleep = processes_after_sleep or processes_after
        self._log_lifecycle(
            "chrome processes after test",
            launch_mode=resolved_mode,
            chrome_processes_count=processes_after["chrome_processes_count"],
            matched_count=processes_after["matched_count"],
            matched_pids=";".join(processes_after.get("matched_pids", [])),
        )
        elapsed = round(time.time() - start, 2)

        if error_text is not None:
            lines = [
                error_text,
                f"chrome_processes_before_count={processes_before['chrome_processes_count']}",
                f"chrome_processes_after_launch_count={processes_after_launch['chrome_processes_count'] if isinstance(processes_after_launch, dict) else 0}",
                f"chrome_processes_after_sleep_count={processes_after_sleep['chrome_processes_count'] if isinstance(processes_after_sleep, dict) else 0}",
                f"chrome_pids_before={';'.join(processes_before.get('matched_pids', []))}",
                f"chrome_pids_after_launch={';'.join(processes_after_launch.get('matched_pids', processes_after.get('matched_pids', [])))}",
                f"chrome_pids_after_sleep={';'.join(processes_after_sleep.get('matched_pids', processes_after.get('matched_pids', [])))}",
                f"close_warning={close_warning}",
                f"elapsed_seconds={elapsed}",
            ]
            return "\n".join(lines)

        return "\n".join(
            [
                "BRIDGE_CHROME_LIFECYCLE_TEST_OK",
                "stage=done",
                f"launch_mode={resolved_mode}",
                f"launch_returned={launch_returned}",
                f"launch_done={launch_done}",
                f"context_created={context_created}",
                f"context_is_alive={context_is_alive}",
                f"pages_count={pages_count}",
                f"page_created={page_created}",
                f"page_closed_before_goto={page_closed_before_goto}",
                f"page0_url={page0_url}",
                f"page0_is_closed={page0_is_closed}",
                f"page_url_before_goto={page_url_before_goto}",
                f"goto_done={goto_done}",
                f"page_url_after_goto={page_url_after_goto}",
                f"browser_stayed_alive_10s={browser_stayed_alive_10s}",
                f"target_url={base_url}",
                f"profile_dir={user_data_dir}",
                f"chrome_processes_before_count={processes_before['chrome_processes_count']}",
                f"chrome_processes_after_launch_count={processes_after_launch['chrome_processes_count'] if isinstance(processes_after_launch, dict) else 0}",
                f"chrome_processes_after_sleep_count={processes_after_sleep['chrome_processes_count'] if isinstance(processes_after_sleep, dict) else 0}",
                f"chrome_pids_before={';'.join(processes_before.get('matched_pids', []))}",
                f"chrome_pids_after_launch={';'.join(processes_after_launch.get('matched_pids', processes_after.get('matched_pids', [])))}",
                f"chrome_pids_after_sleep={';'.join(processes_after_sleep.get('matched_pids', processes_after.get('matched_pids', [])))}",
                f"close_warning={close_warning}",
                f"elapsed_seconds={elapsed}",
            ]
        )

    async def _find_element(self, page, selectors: list[str], call_id: str, timeout_ms: int | None = None) -> None | object:
        timeout = timeout_ms if timeout_ms is not None else 3000
        for selector in selectors:
            locator = page.locator(selector)
            try:
                await locator.first.wait_for(state="attached", timeout=timeout)
                if await locator.count() > 0:
                    self._log("info", "input selector found", {"call_id": call_id, "selector": selector})
                    return locator.first
            except Exception:
                self._log("warning", "input selector not found", {"call_id": call_id, "selector": selector})
                continue
        return None

    async def _count_assistant_nodes(self, page, response_selectors: list[str], call_id: str) -> int:
        for selector in response_selectors:
            try:
                locator = page.locator(selector)
                count = await locator.count()
                if count > 0:
                    self._log("debug", "assistant node count sample", {"call_id": call_id, "selector": selector, "count": count})
                    return int(count)
            except Exception:
                self._log("debug", "assistant node count selector error", {"call_id": call_id, "selector": selector})
                continue
        return 0

    def _merge_selectors(self, configured: list[str], defaults: list[str]) -> list[str]:
        merged: list[str] = []
        for selector in list(configured or []) + defaults:
            selector = str(selector).strip()
            if selector and selector not in merged:
                merged.append(selector)
        return merged

    def _extract_expected_marker(self, prompt: str) -> str | None:
        markers = re.findall(r"\b[A-Z][A-Z0-9_]{6,}\b", prompt or "")
        for marker in markers:
            if marker.endswith("_SUCCESS"):
                return marker
        return markers[-1] if markers else None

    async def _count_nodes(self, page, selectors: list[str]) -> int:
        best_count = 0
        for selector in selectors:
            try:
                count = await page.locator(selector).count()
                if count > best_count:
                    best_count = int(count)
            except Exception:
                continue
        return best_count

    async def _last_node_text(self, page, selectors: list[str]) -> str:
        for selector in selectors:
            try:
                locator = page.locator(selector)
                count = await locator.count()
                if count > 0:
                    text = await locator.nth(count - 1).inner_text(timeout=1200)
                    if text and text.strip():
                        return text.strip()
            except Exception:
                continue
        return ""

    async def _body_text_preview(self, page, limit: int = 1000) -> str:
        try:
            text = await page.locator("body").inner_text(timeout=1200)
            return re.sub(r"\s+", " ", (text or "")).strip()[:limit]
        except Exception:
            return ""

    async def _is_generating(self, page) -> bool:
        selectors = [
            'button[aria-label*="Stop"]',
            'button[aria-label*="stop"]',
            'button[aria-label*="停止"]',
            'button:has-text("Stop")',
            'button:has-text("停止")',
            '[data-testid*="stop"]',
            '[aria-label*="Stop generating"]',
            '[aria-label*="停止生成"]',
        ]
        for selector in selectors:
            try:
                if await page.locator(selector).count() > 0:
                    return True
            except Exception:
                continue
        try:
            body = (await page.locator("body").inner_text(timeout=1200)).lower()
            return any(token in body for token in ["generating", "thinking", "正在生成", "思考中", "停止生成"])
        except Exception:
            return False

    async def _input_is_cleared(self, input_box) -> bool:
        try:
            value = await input_box.input_value(timeout=1200)
            return not bool(value.strip())
        except Exception:
            try:
                text = await input_box.inner_text(timeout=1200)
                return not bool(text.strip())
            except Exception:
                return False

    async def _dump_response_debug_state(
        self,
        page,
        call_id: str,
        assistant_selectors: list[str],
        user_selectors: list[str],
    ) -> dict[str, object]:
        assistant_count = await self._count_nodes(page, assistant_selectors)
        user_count = await self._count_nodes(page, user_selectors)
        last_assistant = await self._last_node_text(page, assistant_selectors)
        generating = await self._is_generating(page)
        try:
            title = await page.title()
        except Exception:
            title = ""
        try:
            url = page.url
        except Exception:
            url = ""
        state = {
            "url": url,
            "title": title,
            "assistant_count": assistant_count,
            "user_count": user_count,
            "stop_button_found": generating,
            "generating_indicator_found": generating,
            "last_assistant_len": len(last_assistant),
            "last_assistant_preview": last_assistant[:200].replace("\n", " "),
        }
        logging.info(
            "[RESPONSE_DEBUG] call_id=%s url=%s title=%s assistant_count=%s user_count=%s stop_button_found=%s generating_indicator_found=%s last_assistant_len=%s last_assistant_preview=%s",
            call_id,
            state["url"],
            state["title"],
            state["assistant_count"],
            state["user_count"],
            state["stop_button_found"],
            state["generating_indicator_found"],
            state["last_assistant_len"],
            state["last_assistant_preview"],
        )
        self._flush_log_handlers()
        return state

    async def _wait_for_assistant_response(
        self,
        page,
        call_id: str,
        assistant_selectors: list[str],
        user_selectors: list[str],
        assistant_count_before: int,
        last_assistant_text_before: str,
        expected_marker: str | None,
    ) -> tuple[str | None, str | None]:
        wait_cfg = self.cfg.get("response_wait", {})
        if not isinstance(wait_cfg, dict):
            wait_cfg = {}
        first_response_timeout = max(1, int(wait_cfg.get("first_response_timeout_seconds", 60)))
        no_progress_timeout = max(1, int(wait_cfg.get("no_progress_timeout_seconds", 30)))
        max_wall_time = max(first_response_timeout, int(wait_cfg.get("max_response_wall_time_seconds", 600)))
        poll_interval_ms = max(250, int(float(wait_cfg.get("poll_interval_seconds", 1)) * 1000))
        stable_seconds = max(1, int(wait_cfg.get("completion_stable_seconds", 2)))
        start = time.monotonic()
        last_text = last_assistant_text_before.strip()
        last_progress_at = start
        response_started = False
        assistant_count_current = assistant_count_before
        body_preview = ""

        self._set_stage(
            "web.response.wait.policy",
            call_id=call_id,
            first_response_timeout_seconds=first_response_timeout,
            no_progress_timeout_seconds=no_progress_timeout,
            max_response_wall_time_seconds=max_wall_time,
            poll_interval_ms=poll_interval_ms,
        )

        while time.monotonic() - start < max_wall_time:
            state = await self._dump_response_debug_state(page, call_id, assistant_selectors, user_selectors)
            assistant_count_current = int(state.get("assistant_count") or 0)
            current_text = await self._last_node_text(page, assistant_selectors)
            body_preview = await self._body_text_preview(page)
            new_assistant = assistant_count_current > assistant_count_before or (
                bool(current_text) and current_text != last_assistant_text_before
            )
            generating = bool(state.get("generating_indicator_found"))
            now = time.monotonic()
            elapsed_seconds = int(now - start)
            text_changed = current_text != last_text
            if text_changed:
                last_text = current_text
                last_progress_at = now
            if new_assistant:
                response_started = True
            logging.info(
                "[RESPONSE_WAIT] call_id=%s elapsed_seconds=%s assistant_count_before=%s assistant_count_current=%s new_assistant_detected=%s response_started=%s generating=%s current_text_len=%s text_changed=%s seconds_since_progress=%s",
                call_id,
                elapsed_seconds,
                assistant_count_before,
                assistant_count_current,
                new_assistant,
                response_started,
                generating,
                len(current_text),
                text_changed,
                int(now - last_progress_at),
            )

            if expected_marker and expected_marker in current_text:
                logging.info(
                    "[WATCHDOG] call_id=%s expected_marker=%s expected_marker_seen=true fast_profile_early_return=true",
                    call_id,
                    expected_marker,
                )
                self._flush_log_handlers()
                return current_text, None

            if response_started and current_text.strip() and not generating and now - last_progress_at >= stable_seconds:
                logging.info(
                    "[WATCHDOG] call_id=%s expected_marker=%s expected_marker_seen=false response_completed=true",
                    call_id,
                    expected_marker or "<none>",
                )
                self._flush_log_handlers()
                return current_text.strip(), None

            if not response_started and not generating and now - start >= first_response_timeout:
                error = self._raise_web_error(
                    "response.wait.first_response_timeout",
                    "no_assistant_response_started",
                    {
                        "assistant_count_before": assistant_count_before,
                        "assistant_count_after": assistant_count_current,
                        "first_response_timeout_seconds": first_response_timeout,
                        "body_preview": body_preview,
                    },
                )
                return None, error

            if response_started and now - last_progress_at >= no_progress_timeout:
                if current_text.strip() and not generating:
                    logging.info(
                        "[WATCHDOG] call_id=%s response_completed_after_no_progress=true no_progress_timeout_seconds=%s",
                        call_id,
                        no_progress_timeout,
                    )
                    self._flush_log_handlers()
                    return current_text.strip(), None
                error = self._raise_web_error(
                    "response.wait.no_progress_timeout",
                    "assistant_response_stalled",
                    {
                        "assistant_count_before": assistant_count_before,
                        "assistant_count_after": assistant_count_current,
                        "no_progress_timeout_seconds": no_progress_timeout,
                        "generating": generating,
                        "current_text_length": len(current_text),
                        "body_preview": body_preview,
                    },
                )
                return None, error

            await page.wait_for_timeout(poll_interval_ms)

        logging.info(
            "[WATCHDOG] call_id=%s expected_marker=%s expected_marker_seen=false response_total_timeout=true max_response_wall_time_seconds=%s",
            call_id,
            expected_marker or "<none>",
            max_wall_time,
        )
        error = self._raise_web_error(
            "response.wait.total_timeout",
            "assistant_response_exceeded_max_wall_time",
            {
                "assistant_count_before": assistant_count_before,
                "assistant_count_after": assistant_count_current,
                "response_started": response_started,
                "max_response_wall_time_seconds": max_wall_time,
                "body_preview": body_preview,
            },
        )
        return None, error

    async def _read_current_model_text(self, page, call_id: str) -> str | None:
        selectors = [
            "button[data-testid='model-switcher']",
            "button[data-testid='model-switcher-mobile']",
            "button:has-text('GPT-5.5')",
            "button[aria-label*='Model']",
            "[data-testid*='model'] button",
            "button:has-text('Model')",
        ]
        for selector in selectors:
            locator = page.locator(selector)
            try:
                if await locator.count() > 0:
                    text = await locator.first.inner_text()
                    if text and text.strip():
                        model = text.strip()
                        self._log("info", "current model detected", {"call_id": call_id, "model": model})
                        return model
            except Exception:
                continue

        try:
            script = r"""
            () => {
              const normalized = (text) => (text || '').replace(/\s+/g, ' ').trim();
              const candidates = Array.from(document.querySelectorAll('button, [role="button"]'));
              for (const el of candidates) {
                const text = normalized(el.innerText);
                if (!text) {
                  continue;
                }
                if (/(gpt|pro|model|chatgpt)/i.test(text) && text.length < 120) {
                  return text;
                }
              }
              return null;
            }
            """
            found = await page.evaluate(script)
            if isinstance(found, str) and found.strip():
                model = found.strip()
                self._log("warning", "current model detected by fallback script", {"call_id": call_id, "model": model})
                return model
        except Exception as exc:
            self._log("warning", "failed to detect current model by script", {"call_id": call_id, "error": str(exc)})

        return None

    async def _open_model_menu(self, page, call_id: str) -> bool:
        selectors = [
            "button[data-testid='model-switcher']",
            "button[data-testid='model-switcher-mobile']",
            "button[aria-label*='Model']",
            "[data-testid*='model'] button",
            "button:has-text('Model')",
            "button:has-text('模型')",
        ]
        for selector in selectors:
            locator = page.locator(selector)
            try:
                if await locator.count() > 0:
                    await locator.first.click(timeout=1200)
                    await page.wait_for_timeout(300)
                    self._log("info", "model selector opened", {"call_id": call_id, "selector": selector})
                    return True
            except Exception as exc:
                self._log("debug", "model selector click failed", {"call_id": call_id, "selector": selector, "error": str(exc)})
                continue

        self._log("warning", "unable to open model selector", {"call_id": call_id})
        return False

    async def _choose_model(self, page, target_model: str, call_id: str) -> bool:
        target = self._normalize_model_text(target_model)
        if not target:
            return False

        if not await self._open_model_menu(page, call_id):
            return False

        selectors = [
            f"[role='menuitem']:has-text('{target_model}')",
            f"[role='option']:has-text('{target_model}')",
            f"button:has-text('{target_model}')",
            f"li:has-text('{target_model}')",
        ]
        for selector in selectors:
            locator = page.locator(selector)
            try:
                if await locator.count() > 0:
                    await locator.first.click(timeout=1200)
                    await page.wait_for_timeout(300)
                    self._log("info", "selected model by selector", {"call_id": call_id, "model": target_model, "selector": selector})
                    return True
            except Exception as exc:
                self._log("debug", "model selection by selector failed", {"call_id": call_id, "selector": selector, "error": str(exc)})
                continue

        try:
            script = r"""
            (target) => {
              const normalized = (text) => (text || '').replace(/\s+/g, ' ').trim().toLowerCase();
              const candidates = Array.from(document.querySelectorAll('button, li, div, [role="menuitem"], [role="option"]'));
              for (const el of candidates) {
                if (!el || !el.isConnected || el.offsetParent === null) {
                  continue;
                }
                const text = normalized(el.innerText);
                if (!text) {
                  continue;
                }
                if (text.includes(target)) {
                  el.click();
                  return true;
                }
              }
              return false;
            }
            """
            ok = await page.evaluate(script, target)
            if ok:
                await page.wait_for_timeout(300)
                self._log("info", "selected model by fallback script", {"call_id": call_id, "model": target_model})
            return bool(ok)
        except Exception as exc:
            self._log("debug", "fallback model selection failed", {"call_id": call_id, "model": target_model, "error": str(exc)})
            return False

    async def _select_best_available_model(self, page, call_id: str) -> str:
        strategy = self._get_model_strategy()
        mode = strategy.get("mode", "best_available")

        self._log("info", "Model strategy", {"call_id": call_id, "mode": mode})
        self._set_stage("web.model_selection.start", call_id=call_id, mode=mode)

        if mode != "best_available":
            current = await self._read_current_model_text(page, call_id)
            self._set_stage("web.model_selection.done", call_id=call_id, model=(current or "unknown"))
            return current or "unknown"

        preferred_models = strategy.get("preferred_models", [])
        if preferred_models:
            self._log(
                "info",
                "Preferred model candidates:",
                {"call_id": call_id, "models": ", ".join(preferred_models)},
            )
            current_model = await self._read_current_model_text(page, call_id)
            if current_model is None:
                self._log("warning", "Unable to detect current model, continue with current ChatGPT web selection", {"call_id": call_id})
                current_model = "unknown"

            for model in preferred_models:
                self._log("info", "try select model", {"call_id": call_id, "model": model})
                if await self._choose_model(page, model, call_id):
                    self._log("info", "Selected model:", {"call_id": call_id, "model": model})
                    self._set_stage("web.model_selection.done", call_id=call_id, model=model)
                    return model
                self._log("warning", "model not available", {"call_id": call_id, "model": model})

            if strategy.get("fallback_to_current_model", True):
                self._log("warning", "Pro model unavailable, fallback to current available web model", {"call_id": call_id})
                self._set_stage("web.model_selection.done", call_id=call_id, model=current_model)
                return current_model

            if strategy.get("fail_if_preferred_unavailable", False):
                self._set_stage("web.model_selection.done", call_id=call_id, model="failed")
                raise RuntimeError("Failed to select a preferred model.")

            self._set_stage("web.model_selection.done", call_id=call_id, model=current_model)
            return current_model

        final = (await self._read_current_model_text(page, call_id)) or "unknown"
        self._set_stage("web.model_selection.done", call_id=call_id, model=final)
        return final


ChatGPTWebAdapter = GPTProWebAdapter
