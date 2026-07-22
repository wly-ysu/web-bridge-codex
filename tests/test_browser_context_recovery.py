"""Fault-injection tests for cached browser-context recovery."""

from __future__ import annotations

import tempfile
import unittest
import logging
from pathlib import Path

from adapters.chatgpt_web import ChatGPTWebAdapter


TARGET_CLOSED = "Target page, context or browser has been closed"


class BrowserContextRecoveryTests(unittest.IsolatedAsyncioTestCase):
    def _adapter(self, root: Path) -> ChatGPTWebAdapter:
        return ChatGPTWebAdapter(
            str(root),
            {
                "web_adapter": {
                    "base_url": "https://chatgpt.com",
                    "user_data_dir": str(root / "profile"),
                },
                "browser_broker": {"enabled": False},
                "browser_tabs": {"cleanup_before_query": False},
            },
            logging.getLogger("test.browser_context_recovery"),
        )

    async def test_close_event_marks_the_cached_context_unusable(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            adapter = self._adapter(Path(temp_dir))
            adapter._browser_context = object()
            adapter._browser_context_generation = 7
            adapter._browser_context_invalidated = False

            adapter._on_browser_context_closed(7)

            self.assertTrue(adapter._browser_context_invalidated)
            self.assertFalse(adapter._browser_context_alive())

    async def test_closed_cached_context_recovers_once_before_prompt_send(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            adapter = self._adapter(Path(temp_dir))
            stale_context = object()
            fresh_context = object()
            contexts = [stale_context, fresh_context]
            invalidation_reasons: list[str] = []

            async def ensure_context(*_args, **_kwargs):
                context = contexts.pop(0)
                return context, [], "profile", True

            async def open_page(context, *_args, **_kwargs):
                if context is stale_context:
                    raise RuntimeError(TARGET_CLOSED)
                return object(), 0, True, False, "about:blank", False, False

            async def invalidate_context(*, reason: str, **_kwargs):
                invalidation_reasons.append(reason)

            adapter._ensure_browser_context = ensure_context
            adapter._open_fresh_page = open_page
            adapter._invalidate_cached_browser_context = invalidate_context

            browser, page, recovery_attempt = await adapter._open_request_page_with_recovery(
                call_id="test-call",
                base_url="https://chatgpt.com",
            )

            self.assertIs(fresh_context, browser)
            self.assertIsNotNone(page)
            self.assertEqual(1, recovery_attempt)
            self.assertEqual(["context_closed_before_prompt"], invalidation_reasons)

    async def test_second_pre_send_context_failure_is_reported_without_more_retries(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            adapter = self._adapter(Path(temp_dir))
            contexts = [object(), object()]
            invalidation_count = 0

            async def ensure_context(*_args, **_kwargs):
                return contexts.pop(0), [], "profile", True

            async def open_page(_context, *_args, **_kwargs):
                raise RuntimeError(TARGET_CLOSED)

            async def invalidate_context(**_kwargs):
                nonlocal invalidation_count
                invalidation_count += 1

            adapter._ensure_browser_context = ensure_context
            adapter._open_fresh_page = open_page
            adapter._invalidate_cached_browser_context = invalidate_context

            with self.assertRaises(RuntimeError) as raised:
                await adapter._open_request_page_with_recovery(
                    call_id="test-call",
                    base_url="https://chatgpt.com",
                )

            self.assertIn(TARGET_CLOSED, str(raised.exception))
            self.assertEqual(1, invalidation_count)

    async def test_post_send_failure_is_never_eligible_for_context_replay(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            adapter = self._adapter(Path(temp_dir))

            self.assertFalse(
                adapter._should_retry_context_recovery(
                    RuntimeError(TARGET_CLOSED),
                    prompt_send_attempted=True,
                    recovery_attempt=0,
                )
            )

    async def test_pre_send_recovery_is_limited_to_one_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            adapter = self._adapter(Path(temp_dir))
            closed_error = RuntimeError(TARGET_CLOSED)

            self.assertTrue(
                adapter._should_retry_context_recovery(
                    closed_error,
                    prompt_send_attempted=False,
                    recovery_attempt=0,
                )
            )
            self.assertFalse(
                adapter._should_retry_context_recovery(
                    closed_error,
                    prompt_send_attempted=False,
                    recovery_attempt=1,
                )
            )

    async def test_legacy_automation_mode_is_normalized_before_broker_forward(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            adapter = self._adapter(Path(temp_dir))
            captured: dict[str, str] = {}

            class FakeBroker:
                async def query(self, _prompt, _project_root, conversation_mode, request_origin, profile=None):
                    captured["conversation_mode"] = conversation_mode
                    captured["request_origin"] = request_origin
                    return "BROKER_OK"

            adapter._broker_client = FakeBroker()
            result = await adapter.query(
                "test prompt",
                project_root=str(Path(temp_dir)),
                conversation_mode="automation",
            )

            self.assertEqual("BROKER_OK", result)
            self.assertEqual("reuse_or_create", captured["conversation_mode"])
            self.assertEqual("automation", captured["request_origin"])
