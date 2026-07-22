"""Playwright adapter for ChatGPT web UI."""

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

from core.project_sessions import ProjectSessionRegistry, project_key, sanitize_conversation_url
from core.request_contract import RequestContractError, normalize_request_contract
from core.response_state import PageSnapshot, ResponseRequestState, ResponseState, text_fingerprint


class ChatGPTWebAdapter:
    def __init__(self, workspace: str, config: dict, logger):
        self.cfg = config.get("web_adapter", {})
        self.config = config
        self.logger = logger
        self.workspace = Path(workspace)
        self.runtime_cfg = config.get("runtime", {})
        self.browser_tabs_cfg = config.get("browser_tabs", {})
        self.conversation_cfg = config.get("conversation_reuse", {})
        self.last_stage = "initialized"
        profile_dir, _ = self._resolve_profile_dir()
        state_file = self.conversation_cfg.get("state_file") or str(profile_dir.parent / "state" / "project-sessions.v1.json")
        self.project_sessions = ProjectSessionRegistry(state_file)
        self._project_locks: dict[str, asyncio.Lock] = {}
        self._browser_context = None
        self._playwright = None
        self._browser_launch_args: list[str] = []
        self._browser_user_data_dir: str | None = None
        self._browser_context_generation = 0
        self._browser_context_invalidated = False
        self._browser_lock = asyncio.Lock()
        self._request_lock = asyncio.Lock()
        self._broker_client = None
        broker_cfg = config.get("browser_broker", {})
        if (
            bool(broker_cfg.get("enabled", True))
            and bool(config.get("_config_path"))
            and bool(config.get("_server_entry_path"))
            and os.getenv("WEB_BRIDGE_BROKER_PROCESS") != "1"
        ):
            from core.browser_broker import BrowserBrokerClient

            self._broker_client = BrowserBrokerClient(config, logger)

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

    def _get_model_strategy(self, profile: str | None = None) -> dict:
        strategy = self.cfg.get("model_strategy", {})
        if not isinstance(strategy, dict):
            strategy = {}
        requested_profile = str(profile or "general").strip() or "general"
        aliases = strategy.get("profile_aliases", {})
        if not isinstance(aliases, dict):
            aliases = {}
        resolved_profile = str(aliases.get(requested_profile, requested_profile))
        profiles = strategy.get("profiles", {})
        if not isinstance(profiles, dict):
            profiles = {}
        profile_strategy = profiles.get(resolved_profile, {})
        if not isinstance(profile_strategy, dict):
            profile_strategy = {}
        if not profile_strategy and resolved_profile != "general":
            resolved_profile = "general"
            profile_strategy = profiles.get(resolved_profile, {})
            if not isinstance(profile_strategy, dict):
                profile_strategy = {}
        return {
            "mode": str(strategy.get("mode", "best_available")).lower(),
            "capability_order": list(profile_strategy.get("capability_order", strategy.get("capability_order", []))),
            "requested_profile": requested_profile,
            "resolved_profile": resolved_profile,
            # Legacy named candidates are accepted but never used as a routing key.
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

        fallback_name = self.cfg.get("profile_dir", ".chatgpt-web-browser")
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

    def _browser_context_alive(self) -> bool:
        return self._browser_context is not None and not self._browser_context_invalidated

    def _on_browser_context_closed(self, generation: int) -> None:
        if generation != self._browser_context_generation:
            return
        self._browser_context_invalidated = True
        self._set_stage(
            "web.browser.context.invalidated",
            context_generation=generation,
            reason="close_event",
        )

    @staticmethod
    def _is_context_closed_error(exc: BaseException) -> bool:
        message = str(exc).lower()
        return "target page, context or browser has been closed" in message or "targetclosed" in message

    def _should_retry_context_recovery(
        self,
        exc: BaseException,
        *,
        prompt_send_attempted: bool,
        recovery_attempt: int,
    ) -> bool:
        return (
            not prompt_send_attempted
            and recovery_attempt == 0
            and self._is_context_closed_error(exc)
        )

    async def _discard_cached_browser_context_locked(self, call_id: str, reason: str) -> None:
        context = self._browser_context
        playwright = self._playwright
        self._browser_context = None
        self._playwright = None
        self._browser_launch_args = []
        self._browser_user_data_dir = None
        self._browser_context_invalidated = True
        self._set_stage("web.browser.context.discard", call_id=call_id, reason=reason)
        await self._safe_close_context(context, call_id, stage_prefix="web.browser.context")
        if playwright is not None:
            try:
                await playwright.stop()
            except Exception as exc:
                self._set_stage(
                    "web.browser.playwright.stop.warning",
                    call_id=call_id,
                    error=f"{type(exc).__name__}: {exc}",
                )

    async def _invalidate_cached_browser_context(self, call_id: str, reason: str) -> None:
        async with self._browser_lock:
            await self._discard_cached_browser_context_locked(call_id, reason)

    async def _ensure_browser_context(self, preflight: dict[str, object], call_id: str):
        async with self._browser_lock:
            if self._browser_context_alive():
                self._set_stage(
                    "web.browser.reuse",
                    call_id=call_id,
                    status="ok",
                    page_count=len(self._browser_context.pages),
                )
                return self._browser_context, self._browser_launch_args, self._browser_user_data_dir or str(preflight.get("user_data_dir", "")), True

            if self._browser_context is not None or self._playwright is not None:
                await self._discard_cached_browser_context_locked(call_id, "cached_context_not_alive")

            from playwright.async_api import async_playwright

            self._set_stage("web.browser.worker.start", call_id=call_id)
            self._playwright = await async_playwright().start()
            try:
                context, launch_args, user_data_dir = await self._launch_context(self._playwright, call_id, preflight)
            except Exception:
                try:
                    await self._playwright.stop()
                except Exception:
                    pass
                self._playwright = None
                self._browser_context = None
                self._browser_launch_args = []
                self._browser_user_data_dir = None
                raise

            self._browser_context = context
            self._browser_launch_args = launch_args
            self._browser_user_data_dir = user_data_dir
            self._browser_context_generation += 1
            self._browser_context_invalidated = False
            generation = self._browser_context_generation
            try:
                context.on("close", lambda: self._on_browser_context_closed(generation))
            except Exception as exc:
                self._set_stage(
                    "web.browser.context.close_listener.warning",
                    call_id=call_id,
                    error=f"{type(exc).__name__}: {exc}",
                )
            self._set_stage(
                "web.browser.worker.ready",
                call_id=call_id,
                user_data_dir=user_data_dir,
                page_count=len(context.pages),
            )
            return context, launch_args, user_data_dir, False

    async def shutdown_browser(self) -> str:
        if self._broker_client is not None:
            return await self._broker_client.shutdown()
        call_id = str(uuid.uuid4())
        context = self._browser_context
        playwright = self._playwright
        self._browser_context = None
        self._playwright = None
        self._browser_launch_args = []
        self._browser_user_data_dir = None
        self._browser_context_invalidated = True
        close_warning = None
        stop_warning = None
        if context is not None:
            close_warning = await self._safe_close_context(context, call_id=call_id, stage_prefix="web.browser_shutdown")
        if playwright is not None:
            try:
                await playwright.stop()
            except Exception as exc:
                stop_warning = f"{type(exc).__name__}: {exc}"
        return "\n".join(
            [
                "BRIDGE_BROWSER_SHUTDOWN_OK",
                f"context_was_alive={context is not None}",
                f"context_close_warning={close_warning or '<none>'}",
                f"playwright_stop_warning={stop_warning or '<none>'}",
            ]
        )

    def browser_status(self) -> str:
        if self._broker_client is not None:
            return self._broker_client.status()
        alive = self._browser_context_alive()
        pages_count = 0
        chatgpt_pages_count = 0
        about_blank_pages_count = 0
        if alive:
            for page in self._browser_context.pages:
                try:
                    if page.is_closed():
                        continue
                    pages_count += 1
                    kind = self._tab_kind(page.url)
                    if kind == "chatgpt":
                        chatgpt_pages_count += 1
                    elif kind == "about_blank":
                        about_blank_pages_count += 1
                except Exception:
                    continue
        return "\n".join(
            [
                "BRIDGE_BROWSER_STATUS_OK",
                f"worker_context_alive={alive}",
                f"user_data_dir={self._browser_user_data_dir or '<not-started>'}",
                f"pages_count={pages_count}",
                f"chatgpt_pages_count={chatgpt_pages_count}",
                f"about_blank_pages_count={about_blank_pages_count}",
            ]
        )

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
        if self._broker_client is not None:
            return self._broker_client.call_sync(
                "run_chrome_preflight", user_data_dir_override=user_data_dir_override
            )
        executable_path = self.cfg.get("executable_path", "")
        executable_exists = bool(executable_path and Path(os.path.expandvars(os.path.expanduser(executable_path))).exists())
        profile_dir, _ = self._resolve_profile_dir(user_data_dir_override)
        profile_dir_str = str(profile_dir)
        profile_dir_exists = profile_dir.exists()
        user_data_dir_writable = self._check_writable(profile_dir)
        matching_pids = self._find_ai_profile_pids(profile_dir_str)
        profile_in_use = len(matching_pids) > 0 and not self._browser_context_alive()
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
                "recommended_action=close AI Bridge Chrome or kill only processes with --user-data-dir=web_bridge_profile"
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

        uses_browser_channel = bool(launch_kwargs.get("channel"))
        if not preflight["executable_path"] and not uses_browser_channel:
            raise RuntimeError(self._raise_web_error("browser.launch", "executable_path_missing"))
        if not preflight["executable_exists"] and not uses_browser_channel:
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

    async def _open_request_page_with_recovery(
        self,
        *,
        call_id: str,
        base_url: str,
        preflight: dict[str, object] | None = None,
    ) -> tuple[object, object, int]:
        """Open one request page, recreating a closed cached context once.

        This helper runs before any input interaction, so recovery can never
        duplicate a prompt whose delivery status is uncertain.
        """

        recovery_attempt = 0
        effective_preflight = preflight or self.run_chrome_preflight()
        while True:
            browser, launch_args, user_data_dir, reused_context = await self._ensure_browser_context(
                effective_preflight,
                call_id,
            )
            self._log(
                "info",
                "persistent context config",
                {
                    "call_id": call_id,
                    "user_data_dir": user_data_dir,
                    "headless": bool(self.cfg.get("headless", False)),
                    "channel": self.cfg.get("channel"),
                    "launch_args": launch_args,
                    "reused_context": reused_context,
                    "recovery_attempt": recovery_attempt,
                },
            )
            try:
                if self._tab_cleanup_config()["cleanup_before_query"]:
                    await self._safe_cleanup_browser_tabs(browser, call_id, phase="before_query")
                page, *_ = await self._open_fresh_page(
                    browser,
                    base_url,
                    call_id,
                    page_stage_prefix="web.query",
                    goto_stage_prefix="web",
                    goto_timeout_ms=120000,
                )
                return browser, page, recovery_attempt
            except Exception as exc:
                if not self._should_retry_context_recovery(
                    exc,
                    prompt_send_attempted=False,
                    recovery_attempt=recovery_attempt,
                ):
                    raise
                self._set_stage(
                    "web.browser.context.recovery.start",
                    call_id=call_id,
                    recovery_attempt=recovery_attempt + 1,
                    reason="context_closed_before_prompt",
                )
                await self._invalidate_cached_browser_context(
                    call_id=call_id,
                    reason="context_closed_before_prompt",
                )
                recovery_attempt += 1
                self._set_stage(
                    "web.browser.context.recovery.done",
                    call_id=call_id,
                    recovery_attempt=recovery_attempt,
                )

    async def _query_inner(self, prompt: str, base_url: str, prompt_timeout_ms: int, call_id: str, preflight: dict[str, object], profile: str | None = None) -> tuple[str, str | None]:
        browser = None
        page = None
        observer_installed = False
        close_error: str | None = None
        page_close_error: str | None = None
        result_text: str | None = None
        error_text: str | None = None
        try:
            browser, page, _ = await self._open_request_page_with_recovery(
                call_id=call_id,
                base_url=base_url,
                preflight=preflight,
            )

            expected_conversation = sanitize_conversation_url(base_url)
            current_conversation = sanitize_conversation_url(getattr(page, "url", ""))
            if expected_conversation and current_conversation != expected_conversation:
                error_text = self._raise_web_error(
                    "conversation.open",
                    "stored_conversation_not_available",
                    {"expected_conversation": expected_conversation},
                )
                return error_text, None
            if expected_conversation and not await self._wait_for_conversation_hydration(page, call_id):
                return self._raise_web_error(
                    "conversation.hydration",
                    "stored_conversation_turns_not_loaded",
                    {"expected_conversation": expected_conversation},
                ), None

            self._set_stage("web.model_selection.start", call_id=call_id)
            selected_model = await self._apply_model_policy(page, call_id, profile=profile)
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
            self._log(
                "debug",
                "selectors loaded",
                {
                    "call_id": call_id,
                    "input": input_selectors,
                    "send": send_selectors,
                },
            )

            expected_marker = self._extract_expected_marker(prompt)
            input_box = await self._find_element(page, input_selectors, call_id, timeout_ms=prompt_timeout_ms)
            if input_box is None:
                self._log("error", "input selector not found", {"call_id": call_id})
                error_text = self._raise_web_error("input.selector", "cannot find chat input field")
            else:
                request_token = f"web-bridge-request-id:{call_id}"
                submitted_prompt = (
                    f"[{request_token}]\n"
                    "Do not echo the request id above.\n\n"
                    f"{prompt}"
                )
                baseline = await self._capture_turn_snapshot(
                    page,
                    call_id,
                    hash_from_ordinal=2**31 - 1,
                    request_token=request_token,
                )
                await self._install_response_observer(page, call_id)
                observer_installed = True
                logging.info(
                    "[RESPONSE_BASELINE] request_id=%s baseline_turn_count=%s expected_marker=%s",
                    call_id,
                    len(baseline.turns),
                    expected_marker or "<none>",
                )
                self._set_stage("web.prompt.send.start", call_id=call_id)
                self._log("info", "typing prompt", {"call_id": call_id})
                self._log("info", "Sending prompt to ChatGPT Web", {"call_id": call_id})
                await asyncio.wait_for(input_box.fill(submitted_prompt), timeout=prompt_timeout_ms / 1000)
                send_method = "press_enter"
                send_btn = await self._find_element(page, send_selectors, call_id, timeout_ms=1500)
                if send_btn is not None:
                    try:
                        await asyncio.wait_for(send_btn.click(timeout=1500), timeout=5)
                        send_method = "send_button"
                    except Exception as exc:
                        self._log("warning", "send button failed; using Enter", {"call_id": call_id, "error": str(exc)})
                        await input_box.press("Enter")
                else:
                    await input_box.press("Enter")
                self._log("info", "send clicked", {"call_id": call_id, "method": send_method})
                self._set_stage("web.prompt.send.done", call_id=call_id, method=send_method)

                self._set_stage("web.response.wait.start", call_id=call_id)
                self._log("info", "waiting assistant response", {"call_id": call_id})
                final, wait_error = await self._wait_for_correlated_response(
                    page,
                    call_id,
                    baseline,
                    submitted_prompt,
                    expected_marker,
                    request_token,
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
                            "selector": "request-bound-assistant-turn",
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
            if page is not None and observer_installed:
                await self._disconnect_response_observer(page, call_id)
            if browser is not None:
                await self._safe_ensure_keepalive_page(browser, call_id=call_id, stage_prefix="web.query")
            if page is not None:
                self._log("info", "close fresh request page", {"call_id": call_id})
                _, page_close_error = await self._safe_close_page(page, call_id=call_id, stage_prefix="web.query.page")
            if browser is not None:
                if self._tab_cleanup_config()["cleanup_after_query"]:
                    await self._safe_cleanup_browser_tabs(browser, call_id, phase="after_query")
                self._set_stage("web.browser.keepalive", call_id=call_id, status="context_preserved", page_count=len(browser.pages))

        if close_error and result_text is None and error_text is None:
            return self._raise_web_error("web.close", close_error, {"check_log": "bridge_mcp.log", "stage": "web.close"}), None

        if error_text is not None:
            warnings = []
            if page_close_error:
                warnings.append(f"page_close_warning={page_close_error}")
            if close_error:
                warnings.append(f"close_warning={close_error}")
            if warnings:
                return "\n".join([error_text, *warnings]), None
            return error_text, None

        if result_text is None:
            return self._raise_web_error("web.query", "No response"), None
        logging.info("[WEB_RETURN] %s", result_text[:120])
        return result_text, sanitize_conversation_url(getattr(page, "url", ""))

    async def query(
        self,
        prompt: str,
        project_root: str | None = None,
        conversation_mode: str = "reuse_or_create",
        request_origin: str = "interactive",
        profile: str | None = None,
    ) -> str:
        try:
            contract = normalize_request_contract(conversation_mode, request_origin)
        except RequestContractError as exc:
            return self._raise_web_error("conversation.mode", str(exc))
        if contract.legacy_mode_normalized:
            self._set_stage("web.request_contract.legacy_mode_normalized", request_origin=contract.request_origin)
        conversation_mode = contract.conversation_mode
        request_origin = contract.request_origin
        if self._broker_client is not None:
            self._set_stage("web.broker.forward.start", project_key=project_key(project_root or self.workspace))
            result = await self._broker_client.query(prompt, project_root, conversation_mode, request_origin, profile)
            self._set_stage(
                "web.broker.forward.done" if not result.startswith("[WEB_ERROR]") else "web.broker.forward.error",
                project_key=project_key(project_root or self.workspace),
            )
            return result
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
        if preflight.get("profile_in_use") and not self._browser_context_alive():
            return self._raise_web_error(
                "browser.owner",
                "profile_in_use_by_another_process",
                {
                    "matching_pids": preflight.get("matching_pids"),
                    "web_prompt_sent": False,
                    "retryable": True,
                },
            )

        base_url = self.cfg.get("base_url", "https://chatgpt.com")
        prompt_timeout_ms = self._runtime_seconds("web_query_timeout_seconds", 150) * 1000

        browser_launch_timeout = self._runtime_seconds("browser_launch_timeout_seconds", 45)

        normalized_mode = conversation_mode
        reuse_enabled = bool(self.conversation_cfg.get("enabled", True)) and normalized_mode != "one_shot" and bool(project_root)
        session = None
        key = ""
        if reuse_enabled:
            key = project_key(project_root or self.workspace)
            session = self.project_sessions.get(key) if normalized_mode == "reuse_or_create" else None
            if session:
                base_url = session.conversation_url
                self._set_stage("web.conversation.reuse", call_id=call_id, project_key=key, generation=session.generation)
            else:
                self._set_stage("web.conversation.new", call_id=call_id, project_key=key, mode=normalized_mode)

        lock = self._project_locks.setdefault(key, asyncio.Lock()) if reuse_enabled else None
        try:
            if lock:
                async with lock:
                    self._set_stage("web.profile_queue.wait", call_id=call_id, project_key=key)
                    async with self._request_lock:
                        self._set_stage("web.profile_queue.enter", call_id=call_id, project_key=key)
                        result, observed_url = await self._query_inner(prompt, base_url, prompt_timeout_ms, call_id, preflight, profile)
                        if result.startswith("[WEB_ERROR]") and session and "stage=conversation.open" in result and bool(self.conversation_cfg.get("recover_once_on_definitive_invalid", True)):
                            self.project_sessions.mark_invalid(key)
                            self._set_stage("web.conversation.recover", call_id=call_id, project_key=key)
                            result, observed_url = await self._query_inner(prompt, self.cfg.get("base_url", "https://chatgpt.com"), prompt_timeout_ms, call_id, preflight, profile)
                        if not result.startswith("[WEB_ERROR]") and observed_url:
                            saved = self.project_sessions.put(project_root or self.workspace, observed_url, prior=session)
                            self._set_stage("web.conversation.saved", call_id=call_id, project_key=saved.project_key, generation=saved.generation)
                        self._set_stage("web.profile_queue.leave", call_id=call_id, project_key=key)
                        return result
            self._set_stage("web.profile_queue.wait", call_id=call_id, project_key="<none>")
            async with self._request_lock:
                self._set_stage("web.profile_queue.enter", call_id=call_id, project_key="<none>")
                result, _ = await self._query_inner(prompt, base_url, prompt_timeout_ms, call_id, preflight, profile)
                self._set_stage("web.profile_queue.leave", call_id=call_id, project_key="<none>")
            return result
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
        if self._broker_client is not None:
            return await self._broker_client.call(
                "chrome_smoke_test",
                target_url=target_url,
                user_data_dir_override=user_data_dir_override,
            )
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
                        '2. Run: "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe" --user-data-dir="%USERPROFILE%\\web_bridge_profile_2"',
                        f"3. Delete {user_data_dir}/Default/lock",
                        "4. Or create a new profile %USERPROFILE%\\web_bridge_profile_2 and login ChatGPT again.",
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
                        '2. Run: "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe" --user-data-dir="%USERPROFILE%\\web_bridge_profile_2"',
                        f"3. Delete {user_data_dir}/Default/lock",
                        "4. Or create a new profile %USERPROFILE%\\web_bridge_profile_2 and login ChatGPT again.",
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
                        '2. Run: "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe" --user-data-dir="%USERPROFILE%\\web_bridge_profile_2"',
                        f"3. Delete {user_data_dir}/Default/lock",
                        "4. Or create a new profile %USERPROFILE%\\web_bridge_profile_2 and login ChatGPT again.",
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
        if self._broker_client is not None:
            return await self._broker_client.call(
                "bridge_tab_health_check", user_data_dir_override=user_data_dir_override
            )
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
        if self._broker_client is not None:
            return await self._broker_client.call(
                "bridge_close_extra_tabs",
                keep_latest=keep_latest,
                dry_run=dry_run,
                user_data_dir_override=user_data_dir_override,
            )
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
        if self._broker_client is not None:
            return await self._broker_client.call(
                "chrome_lifecycle_test",
                launch_mode=launch_mode,
                skip_goto=skip_goto,
                hold_seconds=hold_seconds,
                target_url=target_url,
                minimal_args=minimal_args,
                user_data_dir_override=user_data_dir_override,
            )
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

    @staticmethod
    def _merge_selectors(configured: list[str], defaults: list[str]) -> list[str]:
        merged: list[str] = []
        seen: set[str] = set()
        for selector in [*configured, *defaults]:
            value = str(selector or "").strip()
            if value and value not in seen:
                seen.add(value)
                merged.append(value)
        return merged

    @staticmethod
    def _extract_expected_marker(prompt: str) -> str | None:
        candidates = re.findall(
            r"(?<![A-Za-z0-9_])([A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+)(?![A-Za-z0-9_])",
            str(prompt or ""),
        )
        return candidates[-1] if candidates else None

    async def _wait_for_conversation_hydration(self, page, call_id: str) -> bool:
        wait_config = self.cfg.get("response_wait", {})
        timeout_seconds = max(
            1.0,
            float(wait_config.get("conversation_hydration_timeout_seconds", 30)),
        )
        self._set_stage(
            "web.conversation.hydration.start",
            call_id=call_id,
            timeout_seconds=timeout_seconds,
        )
        try:
            await page.wait_for_selector(
                '[data-message-author-role="user"], [data-message-author-role="assistant"]',
                state="attached",
                timeout=int(timeout_seconds * 1000),
            )
        except Exception as exc:
            self._set_stage(
                "web.conversation.hydration.failed",
                call_id=call_id,
                error=repr(exc),
            )
            return False
        self._set_stage("web.conversation.hydration.done", call_id=call_id)
        return True

    async def _install_response_observer(self, page, call_id: str) -> bool:
        """Install one bounded MutationObserver for this request only."""
        return bool(
            await page.evaluate(
                """
                ({ requestId }) => {
                    const registry = window.__webBridgeResponseObservers ||= {};
                    registry[requestId]?.observer?.disconnect();
                    delete registry[requestId];
                    const root = document.querySelector("main") || document.body;
                    if (!root) return false;
                    const state = { observer: null, root, queue: [], sequence: 0 };
                    const selector = [
                        '[data-message-author-role="user"]',
                        '[data-message-author-role="assistant"]',
                        'article[data-testid^="conversation-turn-"]',
                        '[data-testid^="conversation-turn-"]',
                        '#prompt-textarea',
                        '[contenteditable="true"]',
                        '[role="alert"]',
                        'button[data-testid]',
                        'button[aria-label]'
                    ].join(',');
                    const asElement = (node) => node instanceof Element ? node : node?.parentElement;
                    const relevant = (node) => {
                        const element = asElement(node);
                        return Boolean(element && (
                            element.matches?.(selector) ||
                            element.closest?.(selector) ||
                            element.querySelector?.(selector)
                        ));
                    };
                    const enqueue = (kind) => {
                        state.sequence += 1;
                        state.queue.push({ kind, sequence: state.sequence });
                        if (state.queue.length > 64) {
                            state.queue.splice(0, state.queue.length - 64);
                        }
                    };
                    const observer = new MutationObserver((mutations) => {
                        for (const mutation of mutations) {
                            let changed = relevant(mutation.target);
                            if (!changed && mutation.type === 'childList') {
                                changed = Array.from(mutation.addedNodes).some(relevant);
                            }
                            if (changed) {
                                enqueue('dom_mutation');
                                return;
                            }
                        }
                    });
                    observer.observe(root, {
                        subtree: true,
                        childList: true,
                        characterData: true,
                        attributes: true,
                        attributeFilter: ['aria-label', 'data-testid', 'disabled', 'class']
                    });
                    state.observer = observer;
                    registry[requestId] = state;
                    enqueue('observer_ready');
                    return true;
                }
                """,
                {"requestId": call_id},
            )
        )

    async def _drain_response_observer(self, page, call_id: str) -> dict[str, Any]:
        return await page.evaluate(
            """
            ({ requestId }) => {
                const state = window.__webBridgeResponseObservers?.[requestId];
                if (!state) return { alive: false, sequence: 0, events: [] };
                return {
                    alive: Boolean(state.observer && state.root?.isConnected),
                    sequence: state.sequence || 0,
                    events: state.queue.splice(0, state.queue.length)
                };
            }
            """,
            {"requestId": call_id},
        )

    async def _disconnect_response_observer(self, page, call_id: str) -> None:
        try:
            await page.evaluate(
                """
                ({ requestId }) => {
                    const registry = window.__webBridgeResponseObservers;
                    const state = registry?.[requestId];
                    if (!state) return;
                    state.observer?.disconnect();
                    state.queue.length = 0;
                    delete registry[requestId];
                }
                """,
                {"requestId": call_id},
            )
        except Exception as exc:
            logging.warning(
                "[STAGE] web.response.observer.disconnect.warning request_id=%s error=%r",
                call_id,
                exc,
            )

    async def _capture_turn_snapshot(
        self,
        page,
        call_id: str,
        *,
        hash_from_ordinal: int = 0,
        observer_alive: bool = True,
        observer_sequence: int = 0,
        request_token: str = "",
    ) -> PageSnapshot:
        payload = await page.evaluate(
            """
            async ({ hashFromOrdinal, observerAlive, observerSequence, requestToken }) => {
                const visible = (element) => {
                    if (!element || !element.isConnected) return false;
                    const style = getComputedStyle(element);
                    const rect = element.getBoundingClientRect();
                    return style.display !== 'none' && style.visibility !== 'hidden' &&
                        rect.width > 0 && rect.height > 0;
                };
                const normalize = (value) => (value || '').replace(/\\s+/g, ' ').trim();
                const sha256 = async (value) => {
                    const digest = await crypto.subtle.digest(
                        'SHA-256', new TextEncoder().encode(value)
                    );
                    return Array.from(new Uint8Array(digest))
                        .map((byte) => byte.toString(16).padStart(2, '0')).join('');
                };
                const nodes = Array.from(document.querySelectorAll(
                    '[data-message-author-role="user"], [data-message-author-role="assistant"]'
                ));
                const seen = new Set();
                const turns = [];
                for (const node of nodes) {
                    const role = node.getAttribute('data-message-author-role');
                    if (role !== 'user' && role !== 'assistant') continue;
                    const root = node.closest('article[data-testid^="conversation-turn-"]') ||
                        node.closest('[data-testid^="conversation-turn-"]') || node;
                    const turnTestId = root.getAttribute('data-testid') || '';
                    const ordinalMatch = /^conversation-turn-([0-9]+)$/.exec(turnTestId);
                    const ordinal = ordinalMatch ? Number(ordinalMatch[1]) : turns.length;
                    const stableId = node.getAttribute('data-message-id') ||
                        root.getAttribute('data-message-id') ||
                        root.getAttribute('data-testid') || root.id || `ordinal-${ordinal}`;
                    let key = `${role}:${stableId}`;
                    if (seen.has(key)) key = `${key}:${ordinal}`;
                    seen.add(key);
                    const text = normalize(node.innerText || node.textContent || root.innerText || '');
                    turns.push({
                        role,
                        key,
                        ordinal,
                        textLength: text.length,
                        textHash: ordinal >= hashFromOrdinal ? await sha256(text) : '',
                        requestMatch: Boolean(
                            role === 'user' && requestToken && text.includes(requestToken)
                        )
                    });
                }

                const stopSelectors = [
                    'button[data-testid="stop-button"]',
                    'button[data-testid="stop-button-annotation"]',
                    'button[data-testid*="stop"]',
                    'button[aria-label="Stop generating"]',
                    'button[aria-label="Stop"]',
                    'button[aria-label*="停止"]'
                ];
                const generationActive = stopSelectors.some((selector) =>
                    Array.from(document.querySelectorAll(selector)).some(visible)
                );
                const composer = document.querySelector('#prompt-textarea') ||
                    document.querySelector('textarea') ||
                    document.querySelector('[contenteditable="true"]');
                const composerReady = Boolean(
                    composer && visible(composer) && !composer.hasAttribute('disabled') &&
                    composer.getAttribute('aria-disabled') !== 'true'
                );

                let failureCode = null;
                if (/\\/(auth|login)(\\/|$)/i.test(location.pathname)) {
                    failureCode = 'AUTH_LOGIN_REQUIRED';
                } else if (navigator.onLine === false) {
                    failureCode = 'REMOTE_NETWORK_ERROR';
                }
                const visibleText = (selector) => Array.from(document.querySelectorAll(selector))
                    .filter(visible)
                    .map((element) => normalize(element.innerText || element.textContent || ''))
                    .filter(Boolean).join(' ');
                if (!failureCode) {
                    const alertText = visibleText('[role="alert"], [data-testid*="error"]');
                    if (/too many requests|rate limit|usage limit|quota|达到.*上限|请求过多|额度/i.test(alertText)) {
                        failureCode = 'USAGE_RATE_LIMITED';
                    } else if (/network error|connection error|failed to fetch|网络错误|连接失败/i.test(alertText)) {
                        failureCode = 'REMOTE_NETWORK_ERROR';
                    }
                }
                if (!failureCode) {
                    const retry = Array.from(document.querySelectorAll('button')).filter(visible)
                        .find((button) => /^(retry|try again|重试|再试一次)$/i.test(
                            normalize(button.innerText || button.getAttribute('aria-label') || '')
                        ));
                    if (retry) failureCode = 'REMOTE_RETRY_REQUIRED';
                }
                if (!failureCode && !composerReady) {
                    const login = Array.from(document.querySelectorAll('button, a')).filter(visible)
                        .find((element) => /^(log in|login|登录)$/i.test(
                            normalize(element.innerText || element.textContent || '')
                        ));
                    if (login) failureCode = 'AUTH_LOGIN_REQUIRED';
                }
                return {
                    turns,
                    generationActive,
                    composerReady,
                    observerAlive,
                    observerSequence,
                    failureCode,
                    url: location.href
                };
            }
            """,
            {
                "hashFromOrdinal": max(0, int(hash_from_ordinal)),
                "observerAlive": bool(observer_alive),
                "observerSequence": int(observer_sequence),
                "requestToken": str(request_token or ""),
            },
        )
        return PageSnapshot.from_mapping(payload)

    async def _read_bound_turn_text(
        self,
        page,
        assistant_key: str,
        assistant_ordinal: int,
    ) -> dict[str, str]:
        return await page.evaluate(
            """
            async ({ expectedKey, expectedOrdinal }) => {
                const normalize = (value) => (value || '').replace(/\\s+/g, ' ').trim();
                const sha256 = async (value) => {
                    const digest = await crypto.subtle.digest(
                        'SHA-256', new TextEncoder().encode(value)
                    );
                    return Array.from(new Uint8Array(digest))
                        .map((byte) => byte.toString(16).padStart(2, '0')).join('');
                };
                const nodes = Array.from(document.querySelectorAll(
                    '[data-message-author-role="user"], [data-message-author-role="assistant"]'
                ));
                const seen = new Set();
                const turns = [];
                for (const node of nodes) {
                    const role = node.getAttribute('data-message-author-role');
                    if (role !== 'user' && role !== 'assistant') continue;
                    const root = node.closest('article[data-testid^="conversation-turn-"]') ||
                        node.closest('[data-testid^="conversation-turn-"]') || node;
                    const turnTestId = root.getAttribute('data-testid') || '';
                    const ordinalMatch = /^conversation-turn-([0-9]+)$/.exec(turnTestId);
                    const ordinal = ordinalMatch ? Number(ordinalMatch[1]) : turns.length;
                    const stableId = node.getAttribute('data-message-id') ||
                        root.getAttribute('data-message-id') ||
                        root.getAttribute('data-testid') || root.id || `ordinal-${ordinal}`;
                    let key = `${role}:${stableId}`;
                    if (seen.has(key)) key = `${key}:${ordinal}`;
                    seen.add(key);
                    turns.push({ role, key, ordinal, root, node });
                }
                const turn = turns.find((candidate) =>
                    candidate.role === 'assistant' && candidate.key === expectedKey &&
                    candidate.ordinal === expectedOrdinal
                );
                if (!turn) return { text: '', textHash: '' };
                const text = (
                    turn.node.innerText || turn.node.textContent ||
                    turn.root.innerText || turn.root.textContent || ''
                ).trim();
                return { text, textHash: await sha256(normalize(text)) };
            }
            """,
            {"expectedKey": assistant_key, "expectedOrdinal": int(assistant_ordinal)},
        )

    async def _wait_for_correlated_response(
        self,
        page,
        call_id: str,
        baseline: PageSnapshot,
        prompt: str,
        expected_marker: str | None,
        request_token: str,
    ) -> tuple[str | None, str | None]:
        wait_config = self.cfg.get("response_wait", {})
        deadline_seconds = float(
            wait_config.get(
                "response_deadline_seconds",
                wait_config.get("max_response_wall_time_seconds", 600),
            )
        )
        settle_seconds = max(0.0, float(wait_config.get("settle_debounce_ms", 1200)) / 1000.0)
        poll_seconds = max(0.1, float(wait_config.get("observer_poll_interval_ms", 250)) / 1000.0)
        healthcheck_seconds = max(1.0, float(wait_config.get("observer_healthcheck_seconds", 5)))
        user_turn_seconds = float(wait_config.get("user_turn_confirm_timeout_seconds", 20))
        started_at = time.monotonic()
        machine = ResponseRequestState.create(
            call_id,
            prompt,
            baseline,
            expected_marker,
            started_at,
            deadline_seconds,
            settle_seconds,
            user_turn_seconds,
        )
        page_terminal: dict[str, str | None] = {"code": None}

        def on_page_close() -> None:
            page_terminal["code"] = "BROWSER_PAGE_CLOSED"

        def on_page_crash() -> None:
            page_terminal["code"] = "BROWSER_PAGE_CRASHED"

        page.on("close", on_page_close)
        page.on("crash", on_page_crash)
        last_healthcheck = 0.0
        observer_reinstall_attempted = False
        try:
            while not machine.terminal:
                now = time.monotonic()
                if page_terminal["code"]:
                    machine.fail(str(page_terminal["code"]))
                    continue
                if page.is_closed():
                    machine.fail("BROWSER_PAGE_CLOSED")
                    continue
                try:
                    observer_status = await self._drain_response_observer(page, call_id)
                except Exception as exc:
                    code = "BROWSER_CONTEXT_CLOSED" if "closed" in str(exc).lower() else "OBSERVER_PROTOCOL_ERROR"
                    machine.fail(code, repr(exc))
                    continue

                observer_alive = bool(observer_status.get("alive"))
                if not observer_alive:
                    if observer_reinstall_attempted:
                        machine.fail("OBSERVER_PROTOCOL_ERROR", "response_observer_reinstall_failed")
                        continue
                    observer_reinstall_attempted = True
                    try:
                        observer_alive = await self._install_response_observer(page, call_id)
                        observer_status = await self._drain_response_observer(page, call_id)
                    except Exception:
                        observer_alive = False
                    if not observer_alive:
                        machine.fail("OBSERVER_PROTOCOL_ERROR", "response_observer_not_alive")
                        continue

                events = observer_status.get("events") or []
                should_snapshot = bool(events) or last_healthcheck == 0.0 or (
                    now - last_healthcheck >= healthcheck_seconds
                )
                if should_snapshot:
                    previous_state = machine.state.value
                    try:
                        snapshot = await self._capture_turn_snapshot(
                            page,
                            call_id,
                            hash_from_ordinal=baseline.turns.__len__(),
                            observer_alive=observer_alive,
                            observer_sequence=int(observer_status.get("sequence") or 0),
                            request_token=request_token,
                        )
                    except Exception as exc:
                        code = "BROWSER_CONTEXT_CLOSED" if "closed" in str(exc).lower() else "OBSERVER_PROTOCOL_ERROR"
                        machine.fail(code, repr(exc))
                        continue
                    machine.observe(snapshot, now)
                    last_healthcheck = now
                    new_user_turns = [
                        turn
                        for turn in snapshot.turns
                        if turn.role == "user"
                        and turn.key not in machine.baseline_keys
                        and turn.ordinal >= machine.baseline_turn_count
                    ]
                    logging.info(
                        "[RESPONSE_STATE] request_id=%s previous=%s current=%s events=%s "
                        "observer_sequence=%s user_key=%s assistant_key=%s text_length=%s "
                        "text_hash=%s submitted_hash=%s new_user_candidates=%s "
                        "generating=%s deadline_remaining=%.3f",
                        call_id,
                        previous_state,
                        machine.state.value,
                        ",".join(str(event.get("kind") or "unknown") for event in events) or "healthcheck",
                        snapshot.observer_sequence,
                        machine.user_turn_key or "",
                        machine.assistant_turn_key or "",
                        machine.assistant_text_length,
                        (machine.assistant_text_hash or "")[:12],
                        machine.submitted_hash[:12],
                        ",".join(
                            f"{turn.ordinal}:{turn.text_length}:{turn.text_hash[:12]}:{int(turn.request_match)}"
                            for turn in new_user_turns
                        ) or "<none>",
                        snapshot.generation_active,
                        max(0.0, machine.deadline_at - now),
                    )
                else:
                    machine.check_time(now)

                if not machine.terminal:
                    await asyncio.sleep(poll_seconds)

            if not machine.completed:
                code = machine.error_code or "RESPONSE_STATE_FAILED"
                return None, self._raise_web_error(
                    f"response.state.{machine.state.value.lower()}",
                    code.lower(),
                    {
                        "request_id": call_id,
                        "failure_code": code,
                        "reason": machine.terminal_reason or code,
                    },
                )

            result = await self._read_bound_turn_text(
                page,
                machine.assistant_turn_key or "",
                int(machine.assistant_turn_ordinal or 0),
            )
            response_text = str(result.get("text") or "").strip()
            response_hash = str(result.get("textHash") or "")
            if not response_text or response_hash != machine.assistant_text_hash:
                return None, self._raise_web_error(
                    "response.state.turn_association_failed",
                    "response_association_error",
                    {"request_id": call_id, "assistant_key": machine.assistant_turn_key},
                )
            if expected_marker and expected_marker not in response_text:
                return None, self._raise_web_error(
                    "response.validation",
                    "expected_marker_missing",
                    {"request_id": call_id, "expected_marker": expected_marker},
                )
            logging.info(
                "[WEB_RETURN] request_id=%s assistant_key=%s response_length=%s",
                call_id,
                machine.assistant_turn_key,
                len(response_text),
            )
            return response_text, None
        finally:
            page.remove_listener("close", on_page_close)
            page.remove_listener("crash", on_page_crash)

    async def _read_current_model_text(self, page, call_id: str) -> str | None:
        selectors = [
            "button[data-testid='model-switcher']",
            "button[data-testid='model-switcher-mobile']",
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

    async def _apply_model_policy(self, page, call_id: str, profile: str | None = None) -> str:
        strategy = self._get_model_strategy(profile)
        mode = strategy.get("mode", "best_available")

        self._log("info", "Model strategy", {"call_id": call_id, "mode": mode, "requested_profile": strategy["requested_profile"], "resolved_profile": strategy["resolved_profile"]})
        self._set_stage("web.model_selection.start", call_id=call_id, mode=mode, profile=strategy["resolved_profile"])

        preferred_models = strategy.get("preferred_models", [])
        if preferred_models:
            self._log(
                "warning",
                "legacy named model candidates ignored; retaining current ChatGPT Web model",
                {"call_id": call_id},
            )
        current_model = await self._read_current_model_text(page, call_id)
        if current_model is None:
            self._log("warning", "Unable to detect current model, continue with current ChatGPT web selection", {"call_id": call_id})
            current_model = "unknown"

        if mode == "best_available":
            for tier in strategy.get("capability_order", []):
                labels = [str(label).strip() for label in tier] if isinstance(tier, list) else [str(tier).strip()]
                for label in labels:
                    if not label:
                        continue
                    self._log("info", "try select model capability", {"call_id": call_id, "capability": label})
                    if await self._choose_model(page, label, call_id):
                        observed = await self._read_current_model_text(page, call_id) or label
                        self._log("info", "selected highest available model capability", {"call_id": call_id, "capability": label, "observed_model": observed})
                        self._set_stage("web.model_selection.done", call_id=call_id, model=observed)
                        return observed
            self._log("warning", "no preferred capability available; retaining current ChatGPT Web model", {"call_id": call_id})

        self._log("info", "model switch not requested", {"call_id": call_id, "model_policy": mode})
        self._set_stage("web.model_selection.done", call_id=call_id, model=current_model)
        return current_model
