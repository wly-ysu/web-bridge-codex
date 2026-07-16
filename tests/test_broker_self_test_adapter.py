import asyncio
import unittest

from server import _BrokerSelfTestAdapter


class BrokerSelfTestAdapterTests(unittest.TestCase):
    def test_accepts_the_broker_query_contract(self):
        adapter = _BrokerSelfTestAdapter()

        result = asyncio.run(
            adapter.query(
                "MARKER",
                project_root=".",
                conversation_mode="reuse_or_create",
                request_origin="release_smoke",
            )
        )

        self.assertEqual(result, "BROKER_SELF_TEST:MARKER")
        self.assertIn("self_test_query_count=1", adapter.browser_status())
