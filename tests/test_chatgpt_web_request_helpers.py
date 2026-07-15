import unittest
from unittest.mock import AsyncMock

from adapters.chatgpt_web import ChatGPTWebAdapter
from core.response_state import PageSnapshot, ResponseRequestState, ResponseState, TurnSnapshot


class ChatGPTWebRequestHelperTests(unittest.TestCase):
    def test_required_request_helpers_exist(self) -> None:
        self.assertTrue(callable(ChatGPTWebAdapter._merge_selectors))
        self.assertTrue(callable(ChatGPTWebAdapter._extract_expected_marker))

    def test_merge_selectors_preserves_order_and_removes_duplicates(self) -> None:
        self.assertEqual(
            ChatGPTWebAdapter._merge_selectors(
                ["#prompt-textarea", "textarea", "#prompt-textarea"],
                ["textarea", '[contenteditable="true"]'],
            ),
            ["#prompt-textarea", "textarea", '[contenteditable="true"]'],
        )

    def test_expected_marker_uses_last_marker_token(self) -> None:
        prompt = "first OLD_TEST_SUCCESS\n请只输出：\nV063_TURN_B_715301"
        self.assertEqual(
            ChatGPTWebAdapter._extract_expected_marker(prompt),
            "V063_TURN_B_715301",
        )


class ChatGPTWebConversationHydrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_existing_conversation_waits_for_turn_dom(self) -> None:
        adapter = object.__new__(ChatGPTWebAdapter)
        adapter.cfg = {"response_wait": {"conversation_hydration_timeout_seconds": 2}}
        adapter._set_stage = lambda *args, **kwargs: None
        page = AsyncMock()

        hydrated = await adapter._wait_for_conversation_hydration(page, "request-1")

        self.assertTrue(hydrated)
        page.wait_for_selector.assert_awaited_once_with(
            '[data-message-author-role="user"], [data-message-author-role="assistant"]',
            state="attached",
            timeout=2000,
        )

    async def test_hydration_failure_is_explicit(self) -> None:
        adapter = object.__new__(ChatGPTWebAdapter)
        adapter.cfg = {"response_wait": {"conversation_hydration_timeout_seconds": 1}}
        adapter._set_stage = lambda *args, **kwargs: None
        page = AsyncMock()
        page.wait_for_selector.side_effect = RuntimeError("not loaded")

        self.assertFalse(await adapter._wait_for_conversation_hydration(page, "request-2"))


class RequestCorrelationTokenTests(unittest.TestCase):
    def test_visible_request_token_binds_collapsed_user_turn(self) -> None:
        baseline = PageSnapshot(
            turns=(),
            generation_active=False,
            composer_ready=True,
        )
        machine = ResponseRequestState.create(
            "request-3",
            "a long submitted prompt that is collapsed by the web UI",
            baseline,
            None,
            0.0,
            600.0,
            1.2,
            20.0,
        )
        machine.observe(
            PageSnapshot(
                turns=(
                    TurnSnapshot(
                        role="user",
                        key="user:request-3",
                        ordinal=0,
                        text_length=24,
                        text_hash="different-visible-fragment-hash",
                        request_match=True,
                    ),
                ),
                generation_active=True,
                composer_ready=True,
            ),
            1.0,
        )

        self.assertEqual(machine.state, ResponseState.ASSISTANT_TURN_PENDING)
        self.assertEqual(machine.user_turn_key, "user:request-3")

    def test_streaming_placeholder_rebinds_to_same_absolute_turn(self) -> None:
        baseline = PageSnapshot(turns=(), generation_active=False, composer_ready=True)
        machine = ResponseRequestState.create(
            "request-4", "prompt", baseline, None, 0.0, 600.0, 1.2, 20.0
        )
        machine.observe(
            PageSnapshot(
                turns=(
                    TurnSnapshot("user", "user:4", 4, 6, "prompt-hash", True),
                    TurnSnapshot("assistant", "assistant:request-placeholder-4", 5, 4, "placeholder"),
                ),
                generation_active=True,
                composer_ready=True,
            ),
            1.0,
        )
        machine.observe(
            PageSnapshot(
                turns=(
                    TurnSnapshot("user", "user:4", 4, 6, "prompt-hash", True),
                    TurnSnapshot("assistant", "assistant:message-4", 5, 12, "answer-hash"),
                ),
                generation_active=True,
                composer_ready=True,
            ),
            2.0,
        )

        self.assertEqual(machine.state, ResponseState.ASSISTANT_TURN_ACTIVE)
        self.assertEqual(machine.assistant_turn_key, "assistant:message-4")
        self.assertEqual(machine.assistant_rebind_count, 1)


if __name__ == "__main__":
    unittest.main()
