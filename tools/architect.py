"""Architect agent wrapper."""

from __future__ import annotations

import logging

from core.context_manager import ContextManager
from core.prompt_router import build_architect_prompt


def _flush_log_handlers() -> None:
    for handler in logging.getLogger().handlers:
        try:
            handler.flush()
        except Exception:
            pass


def _log_stage(stage: str) -> None:
    logging.info("[STAGE] %s", stage)
    _flush_log_handlers()


class ArchitectAgent:
    def __init__(self, context_manager: ContextManager, adapter, prompt_router=build_architect_prompt):
        self.context_manager = context_manager
        self.adapter = adapter
        self.prompt_router = prompt_router
        self.last_stage = "architect.init"

    def _set_stage(self, stage: str) -> None:
        self.last_stage = stage
        _log_stage(stage)

    async def run(
        self,
        question: str,
        context_hints: list[str] | None = None,
        include_workspace_context: bool = False,
        conversation_mode: str = "reuse_or_create",
        request_origin: str = "interactive",
    ) -> str:
        logging.info("[ARCH] run enter")
        self._set_stage("architect.run.enter")

        if include_workspace_context and self.context_manager.context_transport == "workspace_text":
            logging.info("[ARCH] before context collect")
            self._set_stage("context.collect.start")
            context = self.context_manager.collect(question, context_hints=context_hints, include_diff=False)
            self._set_stage("context.collect.done")
        else:
            logging.info("[ARCH] using repository link context")
            self._set_stage("context.repo_link")
            context = (await self.context_manager.repository_context_async()).to_prompt_text()

        logging.info("[ARCH] before prompt build")
        self._set_stage("architect.prompt.build.start")
        prompt = self.prompt_router(question, context)
        self._set_stage("architect.prompt.build.done")
        logging.info("[ARCH] before adapter.query")
        self._set_stage("adapter.query.start")
        logging.info("[ARCH] adapter_type=%s", type(self.adapter).__name__)
        answer = await self.adapter.query(
            prompt,
            project_root=str(self.context_manager.root),
            conversation_mode=conversation_mode,
            request_origin=request_origin,
        )
        self._set_stage("adapter.query.done")
        logging.info("[ARCH] after adapter.query")
        self._set_stage("architect.run.done")
        logging.info("[ARCH] answer_length=%s", len(answer))
        return answer
