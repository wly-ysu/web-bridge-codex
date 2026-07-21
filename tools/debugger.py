"""Debug agent wrapper."""

from __future__ import annotations

from core.context_manager import ContextManager
from core.prompt_router import build_debug_prompt


class DebuggerAgent:
    def __init__(self, context_manager: ContextManager, adapter, prompt_router=build_debug_prompt):
        self.context_manager = context_manager
        self.adapter = adapter
        self.prompt_router = prompt_router

    async def run(self, error_text: str, log_path: str | None = None, context_hints: list[str] | None = None) -> str:
        context = (await self.context_manager.repository_context_async()).to_prompt_text()
        if log_path:
            context += "\nA local log path was supplied but its contents were not transferred."
        prompt = self.prompt_router(error_text, context)
        return await self.adapter.query(prompt, project_root=str(self.context_manager.root))
