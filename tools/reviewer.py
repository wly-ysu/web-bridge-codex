"""Reviewer agent wrapper."""

from __future__ import annotations

from utils import git_utils
from core.context_manager import ContextManager
from core.prompt_router import build_review_prompt


class ReviewerAgent:
    def __init__(
        self,
        context_manager: ContextManager,
        adapter,
        prompt_router=build_review_prompt,
    ):
        self.context_manager = context_manager
        self.adapter = adapter
        self.prompt_router = prompt_router

    async def run(
        self,
        files: list[str] | None = None,
        diff: bool = True,
        focus: str | None = None,
    ) -> str:
        workspace = git_utils.get_repo_root(self.context_manager.root) or self.context_manager.root
        file_hint_text = " ".join(files or [])
        question = "Review current code changes."
        if focus:
            question += f" Focus: {focus}."
        if file_hint_text:
            question += f" Target files: {file_hint_text}"

        context = self.context_manager.collect(
            question,
            context_hints=files,
            include_diff=diff,
        )
        prompt = self.prompt_router(git_utils.get_diff(workspace), context, focus=focus)
        return await self.adapter.query(prompt, project_root=str(workspace))
