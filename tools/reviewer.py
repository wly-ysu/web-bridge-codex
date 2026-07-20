"""Reviewer agent wrapper."""

from __future__ import annotations

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
        workspace = self.context_manager.root
        repository = await self.context_manager.repository_context_async()
        if not repository.reviewable:
            return "\n".join(
                [
                    "[REPOSITORY_LINK_REQUIRED]",
                    f"reason={repository.review_block_reason}",
                    "Commit the changes or create a GitHub PR before requesting Web review.",
                ]
            )
        question = "Review current code changes."
        if focus:
            question += f" Focus: {focus}."
        context = repository.to_prompt_text()
        prompt = self.prompt_router(question, context, focus=focus)
        return await self.adapter.query(prompt, project_root=str(workspace))
