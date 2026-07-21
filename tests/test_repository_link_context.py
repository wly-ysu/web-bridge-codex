"""Tests for link-only Web Lead context transport."""

from __future__ import annotations

import time
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.context_manager import ContextManager, RepositoryLinkBundle
from tools.reviewer import ReviewerAgent


class RepositoryLinkContextTests(unittest.IsolatedAsyncioTestCase):
    def _manager(self, root: Path) -> ContextManager:
        return ContextManager(
            root,
            {
                "context": {"transport": "repo_link"},
                "bridge": {"personal_mode": True, "allow_workspace_context": False},
            },
        )

    def test_repo_link_context_contains_github_commit_without_local_path_or_diff(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            manager = self._manager(root)
            with (
                patch("core.context_manager.git_utils.get_repo_root", return_value=root),
                patch("core.context_manager.git_utils.get_repository_url", return_value="https://github.com/example/demo"),
                patch("core.context_manager.git_utils.get_branch", return_value="main"),
                patch("core.context_manager.git_utils.get_commit", return_value="abc123"),
                patch("core.context_manager.git_utils.get_status", return_value=""),
            ):
                context = manager.collect("Review the repository.")

            self.assertIn("https://github.com/example/demo/commit/abc123", context)
            self.assertNotIn(str(root), context)
            self.assertNotIn("Git diff:", context)
            self.assertIn("No local source, diff, logs, or machine paths", context)

    async def test_repo_link_timeout_returns_a_safe_unavailable_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = self._manager(Path(temp_dir))

            def block() -> RepositoryLinkBundle:
                time.sleep(0.1)
                raise AssertionError("should not be awaited after timeout")

            with patch.object(manager, "repository_context", side_effect=block):
                bundle = await manager.repository_context_async(timeout_seconds=0.01)

            self.assertFalse(bundle.reviewable)
            self.assertNotIn(str(temp_dir), bundle.to_prompt_text())

    async def test_dirty_review_stops_locally_without_calling_web(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)

            class DirtyContext:
                def __init__(self) -> None:
                    self.root = root

                async def repository_context_async(self) -> RepositoryLinkBundle:
                    return RepositoryLinkBundle(
                        repository_url="https://github.com/example/demo",
                        branch="main",
                        commit="abc123",
                        commit_url="https://github.com/example/demo/commit/abc123",
                        working_tree_clean=False,
                    )

            class Adapter:
                called = False

                async def query(self, *_args, **_kwargs):
                    self.called = True
                    return "unexpected"

            adapter = Adapter()
            result = await ReviewerAgent(DirtyContext(), adapter).run()

            self.assertIn("REPOSITORY_LINK_REQUIRED", result)
            self.assertFalse(adapter.called)

    async def test_clean_review_sends_link_target_not_diff_text(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)

            class CleanContext:
                def __init__(self) -> None:
                    self.root = root

                async def repository_context_async(self) -> RepositoryLinkBundle:
                    return RepositoryLinkBundle(
                        repository_url="https://github.com/example/demo",
                        branch="main",
                        commit="abc123",
                        commit_url="https://github.com/example/demo/commit/abc123",
                        working_tree_clean=True,
                    )

            class Adapter:
                prompt = ""

                async def query(self, prompt, **_kwargs):
                    self.prompt = prompt
                    return "WEB_OK"

            adapter = Adapter()
            result = await ReviewerAgent(CleanContext(), adapter).run(focus="reliability")

            self.assertEqual("WEB_OK", result)
            self.assertIn("https://github.com/example/demo/commit/abc123", adapter.prompt)
            self.assertNotIn("Diff:", adapter.prompt)
            self.assertNotIn(str(root), adapter.prompt)

