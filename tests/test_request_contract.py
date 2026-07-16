"""Regression coverage for the public Web Lead request contract."""

from __future__ import annotations

import unittest

from core.request_contract import RequestContractError, normalize_request_contract


class RequestContractTests(unittest.TestCase):
    def test_supported_conversation_mode_is_preserved(self) -> None:
        contract = normalize_request_contract(
            conversation_mode="reuse_or_create",
            request_origin="interactive",
        )

        self.assertEqual("reuse_or_create", contract.conversation_mode)
        self.assertEqual("interactive", contract.request_origin)
        self.assertFalse(contract.legacy_mode_normalized)

    def test_legacy_automation_mode_normalizes_without_losing_origin(self) -> None:
        contract = normalize_request_contract(
            conversation_mode="automation",
            request_origin="interactive",
        )

        self.assertEqual("reuse_or_create", contract.conversation_mode)
        self.assertEqual("automation", contract.request_origin)
        self.assertTrue(contract.legacy_mode_normalized)

    def test_unknown_mode_is_rejected_before_browser_or_broker_work(self) -> None:
        with self.assertRaises(RequestContractError):
            normalize_request_contract(
                conversation_mode="unsupported_mode",
                request_origin="interactive",
            )

    def test_unknown_request_origin_is_rejected(self) -> None:
        with self.assertRaises(RequestContractError):
            normalize_request_contract(
                conversation_mode="reuse_or_create",
                request_origin="unsupported_origin",
            )

