import json
import tempfile
import unittest
from pathlib import Path

from adapters.gptpro_web import GPTProWebAdapter
from core.project_sessions import ProjectSessionRegistry, project_key, sanitize_conversation_url


class ProjectSessionTests(unittest.TestCase):
    def test_same_path_is_stable_and_different_paths_are_isolated(self):
        self.assertEqual(project_key("./example"), project_key(Path.cwd() / "example"))
        self.assertNotEqual(project_key("./example-a"), project_key("./example-b"))

    def test_registry_persists_only_canonical_conversation_url(self):
        with tempfile.TemporaryDirectory() as temp:
            registry = ProjectSessionRegistry(Path(temp) / "sessions.json")
            saved = registry.put("./project", "https://chatgpt.com/c/abc-123?foo=secret#fragment")
            self.assertEqual(saved.conversation_url, "https://chatgpt.com/c/abc-123")
            data = json.loads((Path(temp) / "sessions.json").read_text(encoding="utf-8"))
            self.assertNotIn("secret", json.dumps(data))
            self.assertEqual(registry.get(saved.project_key).conversation_url, saved.conversation_url)

    def test_non_conversation_url_is_rejected(self):
        self.assertIsNone(sanitize_conversation_url("https://chatgpt.com/"))

    def test_reuse_does_not_bump_generation(self):
        with tempfile.TemporaryDirectory() as temp:
            registry = ProjectSessionRegistry(Path(temp) / "sessions.json")
            first = registry.put("./project", "https://chatgpt.com/c/a")
            second = registry.put("./project", "https://chatgpt.com/c/a", prior=first)
            self.assertEqual(second.generation, 1)


class AdapterConversationTests(unittest.IsolatedAsyncioTestCase):
    async def test_second_project_request_uses_saved_conversation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            adapter = GPTProWebAdapter(
                str(root),
                {"web_adapter": {"base_url": "https://chatgpt.com", "user_data_dir": str(root / "profile")},
                 "conversation_reuse": {"enabled": True, "state_file": str(root / "sessions.json")},
                 "runtime": {}},
                logger=None,
            )
            observed_targets = []
            adapter.run_chrome_preflight = lambda: {"profile_in_use": False, "executable_exists": True, "user_data_dir_writable": True}

            async def fake_query_inner(prompt, target, timeout, call_id, preflight):
                observed_targets.append(target)
                return "OK", "https://chatgpt.com/c/project-conversation"

            adapter._query_inner = fake_query_inner
            self.assertEqual(await adapter.query("first", project_root=str(root / "project")), "OK")
            self.assertEqual(await adapter.query("second", project_root=str(root / "project")), "OK")
            self.assertEqual(observed_targets, ["https://chatgpt.com", "https://chatgpt.com/c/project-conversation"])

    async def test_marker_mismatch_is_not_reported_as_success(self):
        with tempfile.TemporaryDirectory() as temp:
            adapter = GPTProWebAdapter(str(temp), {"web_adapter": {"response_wait": {"first_response_timeout_seconds": 1, "no_progress_timeout_seconds": 1, "max_response_wall_time_seconds": 1, "poll_interval_seconds": 0.01}}, "runtime": {}}, logger=None)

            class Page:
                async def wait_for_timeout(self, _):
                    return None

            async def state(*_):
                return {"assistant_count": 2, "generating_indicator_found": False}

            async def last(*_):
                return "OLD_SUCCESS"

            adapter._dump_response_debug_state = state
            adapter._last_node_text = last
            adapter._body_text_preview = last
            answer, error = await adapter._wait_for_assistant_response(Page(), "call", [], [], 1, "OLD_SUCCESS", "NEW_SUCCESS")
            self.assertIsNone(answer)
            self.assertIn("expected_marker_missing", error)


if __name__ == "__main__":
    unittest.main()
