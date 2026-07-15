"""MCP server entry for Codex-ChatGPTWeb bridge."""

from __future__ import annotations

import argparse
import asyncio
import io
import logging
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG_PATH = BASE_DIR / "config.yaml"
DEFAULT_LOG_PATH = Path(
    os.path.expandvars(
        os.path.expanduser(os.getenv("WEB_BRIDGE_LOG_PATH", str(BASE_DIR / "bridge_mcp.log")))
    )
)

logging.basicConfig(
    filename=str(DEFAULT_LOG_PATH),
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)


def _flush_log_handlers() -> None:
    for handler in logging.getLogger().handlers:
        try:
            handler.flush()
        except Exception:
            pass


def _log_stage(stage: str, extra: dict[str, object] | None = None) -> None:
    if extra:
        details = ", ".join([f"{k}={v}" for k, v in sorted(extra.items())])
        logging.info("[STAGE] %s %s", stage, details)
    else:
        logging.info("[STAGE] %s", stage)
    _flush_log_handlers()


def _log_adapter_init(**fields: object) -> None:
    if fields:
        details = ", ".join([f"{k}={v}" for k, v in sorted(fields.items())])
        logging.info("[ADAPTER_INIT] %s", details)
    else:
        logging.info("[ADAPTER_INIT]")
    _flush_log_handlers()


from adapters.gpt_api import GPTAPIAdapter
from adapters.chatgpt_web import ChatGPTWebAdapter
from core.context_manager import ContextManager
from core.prompt_router import build_web_first_prompt
from core.session_manager import SessionManager
from tools.architect import ArchitectAgent
from tools.reviewer import ReviewerAgent
from tools.debugger import DebuggerAgent

try:
    import yaml
    from mcp.server.fastmcp import FastMCP
except Exception as exc:
    raise RuntimeError("Missing dependencies: run pip install -r requirements.txt") from exc


DEFAULT_CONFIG = {
    "schema_version": 2,
    "adapter": "web",
    "git": {"max_diff_chars": 12000},
    "bridge": {"personal_mode": True, "allow_workspace_context": True},
    "workflow": {
        "mode": "web_first",
        "codex_role": "executor",
        "web_lead_role": "planner",
        "default_route_all_natural_language_to_web": True,
        "local_execution_prefix": "本地执行：",
        "require_web_plan_before_implementation": True,
        "route_user_corrections_to_web": True,
    },
    "web_lead": {
        "default_tool": "route_to_web_lead",
        "fallback_tool": "ask_web_architect",
        "default_profile": "balanced",
        "vague_requirement_profile": "balanced",
        "complex_requirement_profile": "deep_lite",
        "strongest_profile": "deep",
    },
    "context": {
        "enabled": True,
        "max_file_chars": 6000,
        "max_related_files": 6,
        "max_logs": 3,
        "max_log_chars": 8000,
    },
    "browser_broker": {
        "enabled": True,
        "startup_timeout_seconds": 20,
        "request_timeout_seconds": 660,
        "idle_timeout_seconds": 1800,
        "state_dir": "",
    },
    "project": {
        "allowed_extensions": [".cpp", ".hpp", ".cc", ".c", ".h", ".cu", ".py", ".yaml", ".yml", ".md", ".txt", "CMakeLists.txt"],
        "ignore_paths": [".git", "build", "log", "data", "weights", "__pycache__"],
        "sensitive_patterns": ["*.bag", "*.pcd"],
    },
    "web_adapter": {
        "base_url": "https://chatgpt.com",
        "profile_dir": ".chatgpt-web-browser",
        "user_data_dir": "",
        "channel": "chrome",
        "headless": False,
        "timeout_ms": 120000,
        "model_strategy": {
            "mode": "best_available",
            "capability_order": [
                ["professional", "pro", "专业"],
                ["very high", "extra high", "超高"],
                ["high", "高级"],
                ["balanced", "均衡"],
                ["fast", "极速"],
            ],
            "fallback_to_current_model": True,
            "fail_if_preferred_unavailable": False,
        },
        "input_selectors": [
            "#prompt-textarea",
            "textarea[data-testid='composer-tray-text-input']",
            "textarea[placeholder*='Message']",
            "textarea[placeholder*='Send a message']",
            "div[contenteditable='true']",
        ],
        "send_selectors": [
            "button[data-testid='send-button']",
            "button[data-testid='send-button-annotation']",
            "button:has-text('Send')",
            "button[aria-label='Send prompt']",
            "button[aria-label='Send message']",
        ],
        "response_selectors": [
            "[data-message-author-role='assistant']",
            "article[data-message-author-role='assistant']",
            "article[data-testid='conversation-turn-2']",
            "article",
            "div[data-testid='markdown']",
        ],
        "response_wait": {
            "first_response_timeout_seconds": 60,
            "no_progress_timeout_seconds": 30,
            "max_response_wall_time_seconds": 600,
            "poll_interval_seconds": 1,
            "completion_stable_seconds": 2,
        },
    },
    "browser_tabs": {
        "cleanup_before_query": True,
        "cleanup_after_query": True,
        "keep_latest_chatgpt_tabs": 0,
        "close_about_blank": True,
        "close_chatgpt_tabs": True,
        "max_tabs_warning_threshold": 5,
    },
    "api_adapter": {
        "model": "",
        "temperature": 0.2,
        "max_tokens": 4096,
        "response_wait_seconds": 60,
    },
    "memory_file": ".bridge_memory.json",
    "runtime": {
        "tool_timeout_seconds": 660,
        "web_query_timeout_seconds": 630,
        "browser_launch_timeout_seconds": 45,
        "auto_kill_stale_ai_chrome": False,
    },
}


def setup_logging(verbose: bool = False) -> logging.Logger:
    level = logging.DEBUG if verbose else logging.INFO
    logger = logging.getLogger("codex-bridge")
    logger.setLevel(level)
    return logger


def _resolve_config_path(path: str | Path) -> Path:
    config_path = Path(path)
    if not config_path.is_absolute():
        config_path = BASE_DIR / config_path
    return config_path


def load_config(path: str | Path) -> dict[str, Any]:
    config_path = _resolve_config_path(path)
    if not config_path.exists():
        return DEFAULT_CONFIG.copy()

    content = config_path.read_text(encoding="utf-8")
    loaded = yaml.safe_load(content)
    if not isinstance(loaded, dict):
        return DEFAULT_CONFIG.copy()

    config = DEFAULT_CONFIG.copy()
    for key, value in loaded.items():
        if isinstance(value, dict) and key in config and isinstance(config[key], dict):
            config[key].update(value)
        else:
            config[key] = value
    return config


def validate_install_config(path: str | Path) -> Path:
    """Validate the externally managed install config before Codex registers it."""
    config_path = _resolve_config_path(path)
    if not config_path.exists():
        raise RuntimeError(f"CONFIG_INVALID: missing config file: {config_path}")
    loaded = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise RuntimeError(f"CONFIG_INVALID: config root must be a mapping: {config_path}")
    if loaded.get("schema_version") != 2:
        raise RuntimeError(f"CONFIG_INVALID: expected schema_version=2: {config_path}")
    web = loaded.get("web_adapter")
    if not isinstance(web, dict) or not str(web.get("user_data_dir", "")).strip():
        raise RuntimeError(f"CONFIG_INVALID: web_adapter.user_data_dir is required: {config_path}")
    return config_path


def _tool_timeout_error(tool_name: str, stage: str, timeout_seconds: int) -> str:
    return (
        "[BRIDGE_TIMEOUT]\n"
        f"tool={tool_name}\n"
        f"stage={stage}\n"
        f"timeout_seconds={timeout_seconds}\n"
        "Please check bridge_mcp.log"
    )


def build_adapter(config: dict[str, Any], workspace_root: Path, logger: logging.Logger):
    env_adapter = os.getenv("GPTPRO_ADAPTER")
    configured = env_adapter if env_adapter else config.get("adapter", "web")
    _log_adapter_init(
        cwd=Path.cwd(),
        base_dir=BASE_DIR,
        adapter_env=env_adapter if env_adapter else "<unset>",
        configured_adapter=configured,
    )
    mode = str(configured).lower()
    if mode == "api":
        logger.info("Using GPT API adapter")
        _log_adapter_init(adapter_type="GPTAPIAdapter")
        return GPTAPIAdapter(config, logger)
    try:
        from playwright.async_api import async_playwright  # noqa: F401

        del async_playwright
        logger.info("Trying GPT web adapter first (default)")
        adapter = ChatGPTWebAdapter(str(workspace_root), config, logger)
        _log_adapter_init(adapter_type=type(adapter).__name__)
        return adapter
    except Exception as exc:
        logger.warning("Web adapter init failed, fallback to api adapter: %s", exc)
        _log_adapter_init(adapter_type="GPTAPIAdapter (fallback)")
        return GPTAPIAdapter(config, logger)


def create_server(config_path: str | Path = DEFAULT_CONFIG_PATH, verbose: bool = False) -> FastMCP:
    logger = setup_logging(verbose)
    resolved_config_path = _resolve_config_path(config_path)
    _log_stage("server.config.resolve.start", {"path": str(resolved_config_path)})
    config = load_config(resolved_config_path)
    _log_stage("server.config.loaded", {"path": str(resolved_config_path)})
    workspace_root = Path.cwd().resolve()
    config["_config_path"] = str(resolved_config_path)
    config["_server_entry_path"] = str(Path(__file__).resolve())
    config["_workspace_root"] = str(workspace_root)

    web_cfg = config.get("web_adapter", {})
    model_strategy = web_cfg.get("model_strategy", {})
    if web_cfg.get("enabled", True):
        logger.info("[Bridge] Web Tech Lead adapter: enabled")
        logger.info("[Bridge] Model policy: %s", model_strategy.get("mode", "best_available"))
        logger.info("[Bridge] Fallback to current web model: %s", model_strategy.get("fallback_to_current_model", True))

    _log_adapter_init(cwd=Path.cwd(), base_dir=BASE_DIR, config_path=resolved_config_path)
    adapter = build_adapter(config, workspace_root, logger)
    adapter_type = "ChatGPTWebAdapter" if isinstance(adapter, ChatGPTWebAdapter) else type(adapter).__name__
    web_user_data_dir = "<not_web_adapter>"
    if isinstance(adapter, ChatGPTWebAdapter):
        web_user_data_dir, _ = adapter.get_runtime_profile()
    _log_adapter_init(
        adapter_type=adapter_type,
        web_user_data_dir=web_user_data_dir,
        web_executable_path=web_cfg.get("executable_path", "<unset>"),
        web_base_url=web_cfg.get("base_url", "https://chatgpt.com"),
        model_strategy=model_strategy.get("mode", "best_available"),
        fallback_to_current_model=model_strategy.get("fallback_to_current_model", True),
        fail_if_preferred_unavailable=model_strategy.get("fail_if_preferred_unavailable", False),
    )

    context_manager = ContextManager(workspace_root, config)
    session_manager = SessionManager(str(workspace_root / config.get("memory_file", ".bridge_memory.json")))

    architect = ArchitectAgent(context_manager=context_manager, adapter=adapter)
    web_lead = ArchitectAgent(context_manager=context_manager, adapter=adapter, prompt_router=build_web_first_prompt)
    reviewer = ReviewerAgent(context_manager=context_manager, adapter=adapter)
    debugger = DebuggerAgent(context_manager=context_manager, adapter=adapter)

    runtime_cfg = config.get("runtime", {})
    tool_timeout_seconds = int(runtime_cfg.get("tool_timeout_seconds", 180))

    server = FastMCP("web-bridge-codex")

    def _current_stage(fallback: str) -> str:
        if isinstance(adapter, ChatGPTWebAdapter):
            adapter_stage = getattr(adapter, "last_stage_name", getattr(adapter, "last_stage", None))
            if isinstance(adapter_stage, str) and adapter_stage:
                return adapter_stage
        architect_stage = getattr(architect, "last_stage", None)
        if isinstance(architect_stage, str) and architect_stage:
            return architect_stage
        return fallback

    def _format_preflight_result() -> str:
        if not isinstance(adapter, ChatGPTWebAdapter):
            return (
                "BRIDGE_CHROME_PREFLIGHT_FAILED\n"
                "reason=unsupported_adapter\n"
                "adapter_type=GPTAPIAdapter\n"
                "recommended_action=use web adapter"
            )
        preflight = adapter.run_chrome_preflight()
        formatter = getattr(adapter, "_format_preflight_result_text", None)
        if callable(formatter):
            return formatter(preflight)  # type: ignore[misc]
        return "\n".join(
            [
                "BRIDGE_CHROME_PREFLIGHT_OK"
                if not preflight.get("profile_in_use")
                else "BRIDGE_CHROME_PREFLIGHT_FAILED",
                f"executable_path={preflight.get('executable_path')}",
                f"executable_exists={preflight.get('executable_exists')}",
                f"user_data_dir={preflight.get('user_data_dir')}",
                f"user_data_dir_exists={preflight.get('user_data_dir_exists')}",
                f"user_data_dir_writable={preflight.get('user_data_dir_writable')}",
                f"profile_in_use={preflight.get('profile_in_use')}",
                f"matching_pids={preflight.get('matching_pids')}",
                f"lock_files={preflight.get('lock_files')}",
                f"launch_args={preflight.get('launch_args')}",
                f"recommended_action={'ready_to_launch' if not preflight.get('profile_in_use') else 'close AI Bridge Chrome or kill only processes with --user-data-dir=web_bridge_profile'}",
            ]
        )

    async def _run_smoke_test(
        target_url: str | None = None,
        user_data_dir_override: str | None = None,
    ) -> str:
        if not isinstance(adapter, ChatGPTWebAdapter):
            return (
                "BRIDGE_CHROME_SMOKE_TEST_FAILED\n"
                "reason=unsupported_adapter\n"
                "adapter_type=GPTAPIAdapter\n"
                "recommended_action=use web adapter"
            )
        return await adapter.chrome_smoke_test(
            target_url=target_url,
            user_data_dir_override=user_data_dir_override,
        )

    async def _run_lifecycle_test(
        launch_mode: str = "persistent_executable",
        skip_goto: bool = True,
        hold_seconds: int = 10,
        target_url: str | None = None,
        minimal_args: bool = True,
        user_data_dir_override: str | None = None,
    ) -> str:
        if not isinstance(adapter, ChatGPTWebAdapter):
            return (
                "BRIDGE_CHROME_LIFECYCLE_TEST_FAILED\n"
                "reason=unsupported_adapter\n"
                "adapter_type=GPTAPIAdapter\n"
                "recommended_action=use web adapter"
            )
        return await adapter.chrome_lifecycle_test(
            launch_mode=launch_mode,
            skip_goto=skip_goto,
            hold_seconds=hold_seconds,
            target_url=target_url,
            minimal_args=minimal_args,
            user_data_dir_override=user_data_dir_override,
        )

    async def _run_tab_health_check(user_data_dir_override: str | None = None) -> str:
        if not isinstance(adapter, ChatGPTWebAdapter):
            return (
                "BRIDGE_TAB_HEALTH_CHECK_FAILED\n"
                "reason=unsupported_adapter\n"
                "adapter_type=GPTAPIAdapter\n"
                "recommended_action=use web adapter"
            )
        return await adapter.bridge_tab_health_check(user_data_dir_override=user_data_dir_override)

    async def _run_close_extra_tabs(
        keep_latest: int = 1,
        dry_run: bool = True,
        user_data_dir_override: str | None = None,
    ) -> str:
        if not isinstance(adapter, ChatGPTWebAdapter):
            return (
                "BRIDGE_CLOSE_EXTRA_TABS_FAILED\n"
                "reason=unsupported_adapter\n"
                "adapter_type=GPTAPIAdapter\n"
                "recommended_action=use web adapter"
            )
        return await adapter.bridge_close_extra_tabs(
            keep_latest=keep_latest,
            dry_run=dry_run,
            user_data_dir_override=user_data_dir_override,
        )

    @server.tool(
        description="""Route a natural-language user request to ChatGPT Web Lead first.

Use this for vague requirements, architecture questions, implementation planning,
and user corrections during execution. Codex should execute only after this tool
returns a concrete Web Lead plan. Use ask_web_architect as fallback if this tool
is unavailable.
"""
    )
    async def route_to_web_lead(
        message: str,
        mode: str | None = None,
        profile: str | None = None,
        execute_after_plan: bool = True,
        conversation_mode: str = "reuse_or_create",
    ) -> str:
        """
        Ask Web Lead to refine a vague request and produce Codex execution steps.
        """
        selected_profile = profile or str(config.get("web_lead", {}).get("default_profile", "balanced"))
        selected_mode = mode or str(config.get("workflow", {}).get("mode", "web_first"))
        _log_stage(
            "mcp.route_to_web_lead.enter",
            {
                "mode": selected_mode,
                "profile": selected_profile,
                "execute_after_plan": execute_after_plan,
            },
        )
        logging.info("[MCP] route_to_web_lead enter")
        routed_message = "\n".join(
            [
                f"mode={selected_mode}",
                f"profile={selected_profile}",
                f"execute_after_plan={execute_after_plan}",
                "",
                "User natural-language request:",
                message,
                "",
                "Required output:",
                "Refine the requirement and produce concrete Codex execution instructions.",
                "Do not assume Codex should implement before this plan is reviewed.",
            ]
        )
        try:
            answer = await asyncio.wait_for(
                web_lead.run(
                    routed_message,
                    context_hints=None,
                    include_workspace_context=False,
                    conversation_mode=conversation_mode,
                ),
                timeout=tool_timeout_seconds,
            )
        except asyncio.TimeoutError:
            stage = _current_stage("mcp.route_to_web_lead.timeout")
            _log_stage("mcp.route_to_web_lead.timeout", {"stage": stage})
            timeout_msg = _tool_timeout_error("route_to_web_lead", stage, tool_timeout_seconds)
            logging.info("[MCP RETURN] %s %s", type(timeout_msg), len(timeout_msg))
            return timeout_msg

        session_manager.append("web_lead", message, answer)
        logging.info("[MCP RETURN] %s %s", type(answer), len(answer))
        _log_stage("mcp.route_to_web_lead.return")
        return answer

    async def _run_architect_guidance(
        tool_name: str,
        question: str,
        context_hints: list[str] | None = None,
        include_workspace_context: bool = False,
        profile: str | None = None,
        conversation_mode: str = "reuse_or_create",
    ) -> str:
        selected_profile = profile or str(config.get("web_lead", {}).get("default_profile", "balanced"))
        _log_stage(
            f"mcp.{tool_name}.enter",
            {
                "include_workspace_context": include_workspace_context,
                "profile": selected_profile,
                "conversation_mode": conversation_mode,
            },
        )
        logging.info("[MCP] %s enter", tool_name)
        last_stage = f"mcp.{tool_name}.enter"
        try:
            if include_workspace_context:
                _log_stage("context.collect.start")
                last_stage = "context.collect.start"
            else:
                _log_stage("context.collect.skipped")
                last_stage = "context.collect.skipped"
            _log_stage("architect.prompt.build.start")
            answer = await asyncio.wait_for(
                architect.run(
                    question,
                    context_hints=context_hints or None,
                    include_workspace_context=include_workspace_context,
                    conversation_mode=conversation_mode,
                ),
                timeout=tool_timeout_seconds,
            )
        except asyncio.TimeoutError:
            stage = _current_stage(f"mcp.{tool_name}.timeout")
            _log_stage(f"mcp.{tool_name}.timeout", {"stage": stage})
            timeout_msg = _tool_timeout_error(tool_name, stage, tool_timeout_seconds)
            logging.info("[MCP RETURN] %s %s", type(timeout_msg), len(timeout_msg))
            return timeout_msg

        logging.info("[MCP] %s return", tool_name)
        logging.info("[MCP] answer_length=%s", len(answer))
        session_manager.append("architect", question, answer)
        logging.info("[MCP RETURN] %s %s", type(answer), len(answer))
        logging.info(answer[:100])
        _log_stage(f"mcp.{tool_name}.return")
        return answer

    @server.tool(
        description="""Ask the user's ChatGPT Web session for AI Tech Lead guidance.

By default this tool sends only the explicit question text and does not read or
send local workspace files. Set include_workspace_context=true only when the
user explicitly wants repository context included in the ChatGPT Web request.
The adapter uses the best available model in the user's ChatGPT Web account and
falls back to the currently selected web model when preferred models are not
available.
"""
    )
    async def ask_web_architect(
        question: str,
        context_hints: list[str] | None = None,
        include_workspace_context: bool = False,
        profile: str | None = None,
        conversation_mode: str = "reuse_or_create",
    ) -> str:
        """
        Ask ChatGPT Web to provide architectural guidance for a technical question.
        """
        return await _run_architect_guidance(
            "ask_web_architect",
            question,
            context_hints=context_hints,
            include_workspace_context=include_workspace_context,
            profile=profile,
            conversation_mode=conversation_mode,
        )

    async def _run_review_tool(
        tool_name: str,
        files: list[str] | None = None,
        diff: bool = True,
        focus: str | None = None,
    ) -> str:
        _log_stage(f"mcp.{tool_name}.enter")
        logging.info("[MCP] %s enter", tool_name)
        last_stage = f"mcp.{tool_name}.enter"
        try:
            answer = await asyncio.wait_for(
                reviewer.run(files=files, diff=diff, focus=focus),
                timeout=tool_timeout_seconds,
            )
        except asyncio.TimeoutError:
            _log_stage(f"mcp.{tool_name}.timeout")
            timeout_msg = _tool_timeout_error(tool_name, last_stage, tool_timeout_seconds)
            logging.info("[MCP RETURN] %s %s", type(timeout_msg), len(timeout_msg))
            return timeout_msg
        session_manager.append("reviewer", f"review diff={diff}, files={files}, focus={focus}", answer)
        logging.info("[MCP RETURN] %s %s", type(answer), len(answer))
        logging.info(answer[:100])
        _log_stage(f"mcp.{tool_name}.return")
        return answer

    @server.tool(
        description="""Review local code changes with the user-provided repository context.

When this MCP server runs in personal mode with context enabled, the provided
local context is merged into the prompt sent to the current ChatGPT Web model.
"""
    )
    async def review_web_code(
        files: list[str] | None = None,
        diff: bool = True,
        focus: str | None = None,
    ) -> str:
        """
        Review code using local git diff and repository context.
        """
        return await _run_review_tool("review_web_code", files=files, diff=diff, focus=focus)

    async def _run_debug_tool(
        tool_name: str,
        error_text: str,
        log_path: str | None = None,
        context_hints: list[str] | None = None,
    ) -> str:
        _log_stage(f"mcp.{tool_name}.enter")
        logging.info("[MCP] %s enter", tool_name)
        last_stage = f"mcp.{tool_name}.enter"
        try:
            answer = await asyncio.wait_for(
                debugger.run(error_text=error_text, log_path=log_path, context_hints=context_hints),
                timeout=tool_timeout_seconds,
            )
        except asyncio.TimeoutError:
            _log_stage(f"mcp.{tool_name}.timeout")
            timeout_msg = _tool_timeout_error(tool_name, last_stage, tool_timeout_seconds)
            logging.info("[MCP RETURN] %s %s", type(timeout_msg), len(timeout_msg))
            return timeout_msg
        session_manager.append("debugger", error_text, answer)
        logging.info("[MCP RETURN] %s %s", type(answer), len(answer))
        logging.info(answer[:100])
        _log_stage(f"mcp.{tool_name}.return")
        return answer

    @server.tool(
        description="""Debug compile/runtime errors with optional local repo context.

When context is enabled in personal mode, the provided local context is merged
into the prompt sent to the current ChatGPT Web model.
"""
    )
    async def debug_web_error(
        error_text: str,
        log_path: str | None = None,
        context_hints: list[str] | None = None,
    ) -> str:
        """
        Analyze a compiler/runtime error with local context.
        """
        return await _run_debug_tool(
            "debug_web_error",
            error_text=error_text,
            log_path=log_path,
            context_hints=context_hints,
        )

    @server.tool(
        description="""Check bridge runtime status and adapter configuration.

No browser or heavy workspace read is used. Returns a compact health summary.
"""
    )
    async def bridge_health_check() -> str:
        _log_stage("mcp.bridge_health_check.enter")
        lines = [
            "BRIDGE_HEALTH_CHECK_OK",
            f"server_path={Path(__file__).resolve()}",
            f"cwd={Path.cwd()}",
            f"config_path={resolved_config_path}",
            f"adapter_type={adapter_type}",
            f"web_base_url={web_cfg.get('base_url', 'https://chatgpt.com')}",
            f"user_data_dir={web_user_data_dir}",
            f"web_executable_path={web_cfg.get('executable_path', '<unset>')}",
            f"model_strategy={model_strategy.get('mode', 'best_available')}",
            f"fallback_to_current_model={model_strategy.get('fallback_to_current_model', True)}",
            f"tool_timeout_seconds={tool_timeout_seconds}",
            f"web_query_timeout_seconds={runtime_cfg.get('web_query_timeout_seconds', 150)}",
            f"conversation_reuse_enabled={config.get('conversation_reuse', {}).get('enabled', True)}",
            f"browser_broker_enabled={config.get('browser_broker', {}).get('enabled', True)}",
            "tools_loaded=route_to_web_lead,ask_web_architect,review_web_code,debug_web_error,bridge_health_check,bridge_chrome_preflight,bridge_chrome_smoke_test,bridge_chrome_lifecycle_test,bridge_tab_health_check,bridge_close_extra_tabs,bridge_browser_status,bridge_browser_shutdown",
        ]
        result = "\n".join(lines)
        _log_stage("mcp.bridge_health_check.return")
        return result

    @server.tool(
        description="""Show whether the ChatGPT Web browser worker is currently alive and how many tabs it owns."""
    )
    async def bridge_browser_status() -> str:
        _log_stage("mcp.bridge_browser_status.enter")
        try:
            if not hasattr(adapter, "browser_status"):
                return "BRIDGE_BROWSER_STATUS_UNAVAILABLE\nreason=adapter does not expose browser_status"
            result = adapter.browser_status()
            _log_stage("mcp.bridge_browser_status.return")
            return result
        except Exception as exc:
            _log_stage("mcp.bridge_browser_status.error")
            return f"BRIDGE_BROWSER_STATUS_FAILED\nreason={type(exc).__name__}: {exc}"

    @server.tool(
        description="""Manually close the persistent ChatGPT Web browser worker and release the AI Chrome profile."""
    )
    async def bridge_browser_shutdown() -> str:
        _log_stage("mcp.bridge_browser_shutdown.enter")
        try:
            if not hasattr(adapter, "shutdown_browser"):
                return "BRIDGE_BROWSER_SHUTDOWN_UNAVAILABLE\nreason=adapter does not expose shutdown_browser"
            result = await asyncio.wait_for(adapter.shutdown_browser(), timeout=tool_timeout_seconds)
            _log_stage("mcp.bridge_browser_shutdown.return")
            return result
        except asyncio.TimeoutError:
            _log_stage("mcp.bridge_browser_shutdown.timeout")
            return _tool_timeout_error("bridge_browser_shutdown", "mcp.bridge_browser_shutdown.timeout", tool_timeout_seconds)
        except Exception as exc:
            _log_stage("mcp.bridge_browser_shutdown.error")
            return f"BRIDGE_BROWSER_SHUTDOWN_FAILED\nreason={type(exc).__name__}: {exc}"

    @server.tool(
        description="""Check Chrome executable and profile readiness for ChatGPT Web launch."""
    )
    async def bridge_chrome_preflight() -> str:
        _log_stage("mcp.bridge_chrome_preflight.enter")
        logging.info("[MCP] bridge_chrome_preflight enter")
        last_stage = "mcp.bridge_chrome_preflight.enter"
        try:
            result = await asyncio.wait_for(asyncio.to_thread(_format_preflight_result), timeout=tool_timeout_seconds)
            _log_stage("mcp.bridge_chrome_preflight.return")
            logging.info("[MCP RETURN] %s %s", type(result), len(result))
            return result
        except asyncio.TimeoutError:
            _log_stage("mcp.bridge_chrome_preflight.timeout")
            timeout_msg = _tool_timeout_error("bridge_chrome_preflight", last_stage, tool_timeout_seconds)
            logging.info("[MCP RETURN] %s %s", type(timeout_msg), len(timeout_msg))
            return timeout_msg

    @server.tool(
        description="""Run a minimal ChatGPT Web launch smoke test (launch + goto + close)."""
    )
    async def bridge_chrome_smoke_test(
        target_url: str | None = None,
        user_data_dir_override: str | None = None,
    ) -> str:
        _log_stage("mcp.bridge_chrome_smoke_test.enter")
        logging.info("[MCP] bridge_chrome_smoke_test enter")
        last_stage = "mcp.bridge_chrome_smoke_test.enter"
        try:
            result = await asyncio.wait_for(
                _run_smoke_test(
                    target_url=target_url,
                    user_data_dir_override=user_data_dir_override,
                ),
                timeout=tool_timeout_seconds,
            )
            _log_stage("mcp.bridge_chrome_smoke_test.return")
            logging.info("[MCP RETURN] %s %s", type(result), len(result))
            return result
        except asyncio.TimeoutError:
            _log_stage("mcp.bridge_chrome_smoke_test.timeout")
            timeout_msg = _tool_timeout_error("bridge_chrome_smoke_test", last_stage, tool_timeout_seconds)
            logging.info("[MCP RETURN] %s %s", type(timeout_msg), len(timeout_msg))
            return timeout_msg

    @server.tool(
        description="""Count tabs in the ChatGPT Web AI profile without sending prompts or reading workspace files."""
    )
    async def bridge_tab_health_check(user_data_dir_override: str | None = None) -> str:
        _log_stage("mcp.bridge_tab_health_check.enter")
        logging.info("[MCP] bridge_tab_health_check enter")
        last_stage = "mcp.bridge_tab_health_check.enter"
        try:
            result = await asyncio.wait_for(
                _run_tab_health_check(user_data_dir_override=user_data_dir_override),
                timeout=tool_timeout_seconds,
            )
            _log_stage("mcp.bridge_tab_health_check.return")
            logging.info("[MCP RETURN] %s %s", type(result), len(result))
            return result
        except asyncio.TimeoutError:
            _log_stage("mcp.bridge_tab_health_check.timeout")
            timeout_msg = _tool_timeout_error("bridge_tab_health_check", last_stage, tool_timeout_seconds)
            logging.info("[MCP RETURN] %s %s", type(timeout_msg), len(timeout_msg))
            return timeout_msg

    @server.tool(
        description="""Dry-run or close extra ChatGPT/about:blank tabs in the AI profile. Defaults to dry_run=true."""
    )
    async def bridge_close_extra_tabs(
        keep_latest: int = 1,
        dry_run: bool = True,
        user_data_dir_override: str | None = None,
    ) -> str:
        _log_stage("mcp.bridge_close_extra_tabs.enter", {"keep_latest": keep_latest, "dry_run": dry_run})
        logging.info("[MCP] bridge_close_extra_tabs enter")
        last_stage = "mcp.bridge_close_extra_tabs.enter"
        try:
            result = await asyncio.wait_for(
                _run_close_extra_tabs(
                    keep_latest=keep_latest,
                    dry_run=dry_run,
                    user_data_dir_override=user_data_dir_override,
                ),
                timeout=tool_timeout_seconds,
            )
            _log_stage("mcp.bridge_close_extra_tabs.return")
            logging.info("[MCP RETURN] %s %s", type(result), len(result))
            return result
        except asyncio.TimeoutError:
            _log_stage("mcp.bridge_close_extra_tabs.timeout")
            timeout_msg = _tool_timeout_error("bridge_close_extra_tabs", last_stage, tool_timeout_seconds)
            logging.info("[MCP RETURN] %s %s", type(timeout_msg), len(timeout_msg))
            return timeout_msg

    @server.tool(
        description="""Run focused Chrome lifecycle diagnostics without forcing a specific page navigation.

This tool distinguishes launch, hold, and close stages and helps identify
environmental failures when Playwright launches close too quickly.
"""
    )
    async def bridge_chrome_lifecycle_test(
        launch_mode: str = "persistent_executable",
        skip_goto: bool = True,
        hold_seconds: int = 10,
        target_url: str | None = None,
        minimal_args: bool = True,
        user_data_dir_override: str | None = None,
    ) -> str:
        _log_stage("mcp.bridge_chrome_lifecycle_test.enter")
        logging.info("[MCP] bridge_chrome_lifecycle_test enter")
        last_stage = "mcp.bridge_chrome_lifecycle_test.enter"
        try:
            result = await asyncio.wait_for(
                _run_lifecycle_test(
                    launch_mode=launch_mode,
                    skip_goto=skip_goto,
                    hold_seconds=hold_seconds,
                    target_url=target_url,
                    minimal_args=minimal_args,
                    user_data_dir_override=user_data_dir_override,
                ),
                timeout=tool_timeout_seconds,
            )
            _log_stage("mcp.bridge_chrome_lifecycle_test.return")
            logging.info("[MCP RETURN] %s %s", type(result), len(result))
            return result
        except asyncio.TimeoutError:
            _log_stage("mcp.bridge_chrome_lifecycle_test.timeout")
            timeout_msg = _tool_timeout_error("bridge_chrome_lifecycle_test", last_stage, tool_timeout_seconds)
            logging.info("[MCP RETURN] %s %s", type(timeout_msg), len(timeout_msg))
            return timeout_msg

    return server


class _BrokerSelfTestAdapter:
    def __init__(self):
        self.active = 0
        self.max_concurrency = 0
        self.query_count = 0

    async def query(self, prompt: str, project_root: str | None = None, conversation_mode: str = "reuse_or_create") -> str:
        del project_root, conversation_mode
        self.active += 1
        self.max_concurrency = max(self.max_concurrency, self.active)
        try:
            await asyncio.sleep(0.25)
            self.query_count += 1
            return f"BROKER_SELF_TEST:{prompt}"
        finally:
            self.active -= 1

    def browser_status(self) -> str:
        return "\n".join(
            [
                "BROKER_SELF_TEST_ADAPTER_STATUS",
                f"self_test_query_count={self.query_count}",
                f"self_test_max_concurrency={self.max_concurrency}",
            ]
        )

    async def shutdown_browser(self) -> str:
        return "BRIDGE_BROWSER_SHUTDOWN_OK"


def _load_broker_config(config_path: str | Path) -> dict[str, Any]:
    resolved = _resolve_config_path(config_path)
    config = load_config(resolved)
    config["_config_path"] = str(resolved)
    config["_server_entry_path"] = str(Path(__file__).resolve())
    config["_workspace_root"] = str(Path.cwd().resolve())
    return config


def _self_command() -> list[str]:
    return [sys.executable] if getattr(sys, "frozen", False) else [sys.executable, str(Path(__file__).resolve())]


def _run_broker_self_test(config_path: str | Path) -> int:
    from core.browser_broker import BrowserBrokerClient

    previous_state = os.environ.get("WEB_BRIDGE_BROKER_STATE_DIR")
    previous_mode = os.environ.get("WEB_BRIDGE_BROKER_SELF_TEST")
    with tempfile.TemporaryDirectory(prefix="web-bridge-broker-test-") as temporary:
        os.environ["WEB_BRIDGE_BROKER_STATE_DIR"] = temporary
        os.environ["WEB_BRIDGE_BROKER_SELF_TEST"] = "1"
        client = None
        try:
            base = _self_command()
            environment = os.environ.copy()
            probes = []
            for marker, project in (("PROCESS_A", "project-a"), ("PROCESS_B", "project-b")):
                probes.append(
                    subprocess.Popen(
                        [
                            *base,
                            "--broker-probe",
                            "--config",
                            str(config_path),
                            "--probe-prompt",
                            marker,
                            "--probe-project",
                            project,
                        ],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                        encoding="utf-8",
                        env=environment,
                    )
                )
            outputs = [probe.communicate(timeout=35) for probe in probes]
            config = _load_broker_config(config_path)
            client = BrowserBrokerClient(config)
            status = client.status()
            failures = []
            for index, ((stdout, stderr), marker) in enumerate(zip(outputs, ("PROCESS_A", "PROCESS_B")), start=1):
                if probes[index - 1].returncode != 0 or f"BROKER_SELF_TEST:{marker}" not in stdout:
                    failures.append(f"probe_{index}=returncode:{probes[index - 1].returncode},stdout:{stdout.strip()},stderr:{stderr.strip()}")
            if "self_test_max_concurrency=1" not in status:
                failures.append("global_queue_not_serialized")
            if "processed_requests=2" not in status:
                failures.append("processed_request_count_not_two")
            if failures:
                print("BROKER_SELF_TEST_FAILED")
                print("\n".join(failures))
                print(status)
                return 1
            print("BROKER_SELF_TEST_OK")
            print("independent_client_processes=2")
            print("singleton_broker=true")
            print("global_queue_serialized=true")
            print(status)
            return 0
        except Exception as exc:
            print("BROKER_SELF_TEST_FAILED")
            print(f"reason={type(exc).__name__}: {exc}")
            return 1
        finally:
            if client is not None:
                try:
                    asyncio.run(client.shutdown())
                except Exception:
                    pass
            if previous_state is None:
                os.environ.pop("WEB_BRIDGE_BROKER_STATE_DIR", None)
            else:
                os.environ["WEB_BRIDGE_BROKER_STATE_DIR"] = previous_state
            if previous_mode is None:
                os.environ.pop("WEB_BRIDGE_BROKER_SELF_TEST", None)
            else:
                os.environ["WEB_BRIDGE_BROKER_SELF_TEST"] = previous_mode


def _run_stdio_server(server: FastMCP) -> None:
    """Keep SDK-owned UTF-8 wrappers from closing the process stdio handles."""
    original_stdin = sys.stdin
    original_stdout = sys.stdout
    duplicate_stdin = io.TextIOWrapper(
        os.fdopen(os.dup(original_stdin.fileno()), "rb", closefd=True),
        encoding="utf-8",
        errors="replace",
    )
    duplicate_stdout = io.TextIOWrapper(
        os.fdopen(os.dup(original_stdout.fileno()), "wb", closefd=True),
        encoding="utf-8",
        write_through=True,
    )
    sys.stdin = duplicate_stdin
    sys.stdout = duplicate_stdout
    try:
        server.run(transport="stdio")
    finally:
        sys.stdin = original_stdin
        sys.stdout = original_stdout
        for stream in (duplicate_stdin, duplicate_stdout):
            try:
                stream.close()
            except (OSError, ValueError):
                pass


def main() -> None:
    parser = argparse.ArgumentParser(description="Codex-ChatGPTWeb Bridge MCP server")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="Path to config yaml.")
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging.")
    parser.add_argument("--configure-user", action="store_true", help="Register this binary with Codex.")
    parser.add_argument("--remove-user-config", action="store_true", help="Remove this binary from Codex.")
    parser.add_argument("--codex-config", default="", help="Path to Codex config.toml for user setup.")
    parser.add_argument("--agents-file", default="", help="Path to Codex AGENTS.md for user setup.")
    parser.add_argument("--launcher", default="", help="Compiled bridge executable path for Codex setup.")
    parser.add_argument("--log-path", default="", help="External bridge log path for Codex setup.")
    parser.add_argument("--validate-config", action="store_true", help="Validate an installer-managed config and exit.")
    parser.add_argument("--browser-broker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--shutdown-broker", action="store_true", help="Gracefully stop the user browser broker.")
    parser.add_argument("--broker-self-test", action="store_true", help="Run the cross-process broker self-test.")
    parser.add_argument("--broker-probe", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--probe-prompt", default="", help=argparse.SUPPRESS)
    parser.add_argument("--probe-project", default="", help=argparse.SUPPRESS)
    args = parser.parse_args()

    if args.browser_broker:
        from core.browser_broker import BrowserBrokerServer

        os.environ["WEB_BRIDGE_BROKER_PROCESS"] = "1"
        config = _load_broker_config(args.config)
        if os.getenv("WEB_BRIDGE_BROKER_SELF_TEST") == "1":
            adapter = _BrokerSelfTestAdapter()
        else:
            adapter = build_adapter(config, Path.cwd().resolve(), setup_logging(args.verbose))
        asyncio.run(BrowserBrokerServer(config, adapter).run())
        return

    if args.shutdown_broker:
        from core.browser_broker import BrowserBrokerClient

        print(asyncio.run(BrowserBrokerClient(_load_broker_config(args.config)).shutdown()))
        return

    if args.broker_probe:
        from core.browser_broker import BrowserBrokerClient

        result = asyncio.run(
            BrowserBrokerClient(_load_broker_config(args.config)).query(
                args.probe_prompt,
                args.probe_project or None,
                "reuse_or_create",
            )
        )
        print(result)
        raise SystemExit(0 if result.startswith("BROKER_SELF_TEST:") else 1)

    if args.broker_self_test:
        raise SystemExit(_run_broker_self_test(args.config))

    if args.validate_config:
        validated = validate_install_config(args.config)
        print(f"CONFIG_VALIDATED\nconfig_path={validated}")
        return

    if args.configure_user or args.remove_user_config:
        if not args.codex_config or not args.agents_file:
            parser.error("--codex-config and --agents-file are required for user setup")
        if args.configure_user and not args.launcher:
            parser.error("--launcher is required with --configure-user")
        from deploy.common.configure_user import configure_mcp, configure_rules

        configure_mcp(
            Path(args.codex_config),
            args.launcher,
            ["--config", str(Path(args.config).expanduser().resolve())],
            args.remove_user_config,
            log_path=args.log_path,
        )
        configure_rules(Path(args.agents_file), args.remove_user_config)
        print("CONFIGURE_USER_OK" if args.configure_user else "CONFIGURE_USER_REMOVED")
        return

    server = create_server(config_path=args.config, verbose=args.verbose)
    _run_stdio_server(server)


if __name__ == "__main__":
    main()
