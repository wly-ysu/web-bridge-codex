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

        class Locator:
            def __init__(self, label):
                self.label = label

            async def count(self):
                return 1 if self.label == "中" else 0

            @property
            def first(self):
                return self

            async def click(self, timeout):
                observed.append(f"click:{self.label}:{timeout}")

        class Page:
            def get_by_role(self, role, name, exact):
                observed.append(f"role:{role}:{name}:{exact}")
                return Locator(name)

            async def wait_for_timeout(self, _milliseconds):
                return None

        self.assertTrue(await adapter._open_capability_menu(Page(), "capability-menu"))
        self.assertIn("role:button:中:True", observed)
        self.assertIn("click:中:1200", observed)

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

    async def test_select_capability_clicks_verified_radio_option(self):
        adapter = ChatGPTWebAdapter(str(Path.cwd()), DEFAULT_CONFIG, logger=None)
        observed: list[str] = []

        async def open_menu(_page, _call_id):
            return True

        class Locator:
            async def count(self):
                return 1

            @property
            def first(self):
                return self

            async def click(self, timeout):
                observed.append(f"click:{timeout}")

        class Page:
            def get_by_role(self, role, name, exact):
                observed.append(f"{role}:{name}:{exact}")
                return Locator()

            async def wait_for_timeout(self, milliseconds):
                observed.append(f"wait:{milliseconds}")

        adapter._open_capability_menu = open_menu
        self.assertTrue(await adapter._select_capability(Page(), "very_high", "radio-option"))
        self.assertEqual(observed, ["menuitemradio:极高:True", "click:1200", "wait:450"])

    async def test_general_and_planning_try_the_correct_capability_first(self):
        adapter = ChatGPTWebAdapter(str(Path.cwd()), DEFAULT_CONFIG, logger=None)
        attempted: list[str] = []
        current = {"value": "medium"}

        async def current_capability(_page, _call_id):
            return current["value"]

        async def select_capability(_page, capability, _call_id):
            attempted.append(capability)
            current["value"] = capability
            return True

        adapter._read_current_capability = current_capability
        adapter._select_capability = select_capability

        selected, error = await adapter._apply_model_policy(object(), "general-call", profile="general")
        self.assertEqual((selected, error), ("very_high", None))
        self.assertEqual(attempted, ["very_high"])

        attempted.clear()
        current["value"] = "medium"
        selected, error = await adapter._apply_model_policy(object(), "planning-call", profile="planning")
        self.assertEqual((selected, error), ("pro", None))
        self.assertEqual(attempted, ["pro"])

    async def test_planning_falls_back_to_current_model_when_pro_is_unavailable(self):
        adapter = ChatGPTWebAdapter(str(Path.cwd()), DEFAULT_CONFIG, logger=None)
        attempted: list[str] = []
        current = {"value": "medium"}

        async def current_capability(_page, _call_id):
            return current["value"]

        async def select_capability(_page, capability, _call_id):
            attempted.append(capability)
            if capability == "pro":
                return False
            current["value"] = capability
            return True

        adapter._read_current_capability = current_capability
        adapter._select_capability = select_capability

        selected, error = await adapter._apply_model_policy(object(), "fallback-call", profile="planning")

        self.assertEqual((selected, error), ("very_high", None))
        self.assertEqual(attempted, ["pro", "very_high"])

    async def test_unconfirmed_general_capability_fails_closed(self):
        adapter = ChatGPTWebAdapter(str(Path.cwd()), DEFAULT_CONFIG, logger=None)

        async def current_capability(_page, _call_id):
            return "medium"

        async def select_capability(_page, _capability, _call_id):
            return True

        adapter._read_current_capability = current_capability
        adapter._select_capability = select_capability

        selected, error = await adapter._apply_model_policy(object(), "fail-closed", profile="general")

        self.assertIsNone(selected)
        self.assertIn("stage=capability.selection", error)
        self.assertIn("web_prompt_sent=False", error)


if __name__ == "__main__":
    unittest.main()
