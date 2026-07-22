import asyncio
import logging
import unittest
from pathlib import Path

from adapters.chatgpt_web import ChatGPTWebAdapter
from server import DEFAULT_CONFIG, _select_web_profile, build_adapter


class ModelProfileRoutingTests(unittest.TestCase):
    def test_default_server_adapter_is_web_adapter(self):
        adapter = build_adapter(DEFAULT_CONFIG, Path.cwd(), logger=logging.getLogger(__name__))
        self.assertIsInstance(adapter, ChatGPTWebAdapter)

    def test_ordinary_question_uses_general_profile(self):
        self.assertEqual(_select_web_profile(DEFAULT_CONFIG, "解释这个报错", None), "general")

    def test_planning_question_uses_planning_profile(self):
        self.assertEqual(_select_web_profile(DEFAULT_CONFIG, "请给出架构设计方案和实施计划", None), "planning")

    def test_explicit_profile_wins_over_automatic_routing(self):
        self.assertEqual(_select_web_profile(DEFAULT_CONFIG, "请给出架构设计方案", "fast"), "fast")

    def test_legacy_profile_aliases_resolve_to_capability_profiles(self):
        adapter = ChatGPTWebAdapter(str(Path.cwd()), DEFAULT_CONFIG, logger=None)
        self.assertEqual(adapter._get_model_strategy("fast")["resolved_profile"], "general")
        self.assertEqual(adapter._get_model_strategy("deep")["resolved_profile"], "planning")
        self.assertEqual(adapter._get_model_strategy("general")["capability_order"][0][0], "极高")
        self.assertEqual(adapter._get_model_strategy("planning")["capability_order"][0][0], "Pro")


class ModelCapabilitySelectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_capability_menu_targets_current_reasoning_level_control(self):
        adapter = ChatGPTWebAdapter(str(Path.cwd()), DEFAULT_CONFIG, logger=None)
        observed: list[str] = []

        class Page:
            async def evaluate(self, _script, labels):
                observed.extend(labels)
                return True

            async def wait_for_timeout(self, _milliseconds):
                return None

        self.assertTrue(await adapter._open_capability_menu(Page(), "capability-menu"))
        self.assertIn("中", observed)
        self.assertIn("极高", observed)
        self.assertIn("Pro", observed)

    async def test_choose_model_opens_capability_menu_before_model_menu(self):
        adapter = ChatGPTWebAdapter(str(Path.cwd()), DEFAULT_CONFIG, logger=None)
        calls: list[str] = []

        async def capability_menu(_page, _call_id):
            calls.append("capability")
            return True

        async def model_menu(_page, _call_id):
            calls.append("model")
            return True

        class Locator:
            async def count(self):
                return 0

        class Page:
            def locator(self, _selector):
                return Locator()

            async def evaluate(self, _script, _target):
                return False

        adapter._open_capability_menu = capability_menu
        adapter._open_model_menu = model_menu
        self.assertFalse(await adapter._choose_model(Page(), "极高", "capability-first"))
        self.assertEqual(calls, ["capability"])

    async def test_general_and_planning_try_the_correct_capability_first(self):
        adapter = ChatGPTWebAdapter(str(Path.cwd()), DEFAULT_CONFIG, logger=None)
        attempted: list[str] = []

        async def current_model(_page, _call_id):
            return "current"

        async def choose_model(_page, label, _call_id):
            attempted.append(label)
            return True

        adapter._read_current_model_text = current_model
        adapter._choose_model = choose_model

        await adapter._apply_model_policy(object(), "general-call", profile="general")
        self.assertEqual(attempted, ["极高"])

        attempted.clear()
        await adapter._apply_model_policy(object(), "planning-call", profile="planning")
        self.assertEqual(attempted, ["Pro"])

    async def test_planning_falls_back_to_current_model_when_pro_is_unavailable(self):
        adapter = ChatGPTWebAdapter(str(Path.cwd()), DEFAULT_CONFIG, logger=None)
        attempted: list[str] = []

        async def current_model(_page, _call_id):
            return "Current ChatGPT model"

        async def choose_model(_page, label, _call_id):
            attempted.append(label)
            return False

        adapter._read_current_model_text = current_model
        adapter._choose_model = choose_model

        result = await adapter._apply_model_policy(object(), "fallback-call", profile="planning")

        self.assertEqual(result, "Current ChatGPT model")
        self.assertEqual(attempted[0], "Pro")
        self.assertIn("极高", attempted)


if __name__ == "__main__":
    unittest.main()
