"""Debug agent wrapper."""

from __future__ import annotations

from pathlib import Path
from core.context_manager import ContextManager
from core.prompt_router import build_debug_prompt


class DebuggerAgent:
    def __init__(self, context_manager: ContextManager, adapter, prompt_router=build_debug_prompt):
        self.context_manager = context_manager
        self.adapter = adapter
        self.prompt_router = prompt_router

    async def run(self, error_text: str, log_path: str | None = None, context_hints: list[str] | None = None) -> str:
        context_text = error_text
        if log_path:
            try:
                context_text = f"{context_text}\n\nLog from {log_path}:\n{Path(log_path).read_text(encoding='utf-8', errors='replace')}"
            except Exception:
                pass
        context = self.context_manager.collect(context_text, context_hints=context_hints, include_diff=False)
        prompt = self.prompt_router(error_text, context)
        return await self.adapter.query(prompt)
