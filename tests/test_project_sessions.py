import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from adapters.chatgpt_web import ChatGPTWebAdapter
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
    async def test_profile_queue_serializes_requests_from_different_projects(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            adapter = ChatGPTWebAdapter(
                str(root),
                {"web_adapter": {"base_url": "https://chatgpt.com", "user_data_dir": str(root / "profile")}, "runtime": {}},
                logger=None,
            )
            adapter.run_chrome_preflight = lambda: {
                "profile_in_use": False,
                "executable_exists": True,
                "user_data_dir_writable": True,
            }
            first_started = asyncio.Event()
            release_first = asyncio.Event()
            observed_prompts = []

            async def fake_query_inner(prompt, target, timeout, call_id, preflight, profile=None):
                observed_prompts.append(prompt)
                if prompt == "first":
                    first_started.set()
                    await release_first.wait()
                return "OK", f"https://chatgpt.com/c/{prompt}-conversation"

            adapter._query_inner = fake_query_inner
            first = asyncio.create_task(adapter.query("first", project_root=str(root / "project-a")))
            await asyncio.wait_for(first_started.wait(), timeout=1)
            second = asyncio.create_task(adapter.query("second", project_root=str(root / "project-b")))
            await asyncio.sleep(0.02)
            self.assertEqual(observed_prompts, ["first"])
            release_first.set()
            self.assertEqual(await first, "OK")
            self.assertEqual(await second, "OK")
            self.assertEqual(observed_prompts, ["first", "second"])

    async def test_shutdown_browser_closes_cached_context_and_playwright(self):
        with tempfile.TemporaryDirectory() as temp:
            adapter = ChatGPTWebAdapter(str(temp), {"web_adapter": {}, "runtime": {}}, logger=None)

            class Context:
                def __init__(self):
                    self.pages = []
                    self.closed = False

                async def close(self):
                    self.closed = True

            class Playwright:
                def __init__(self):
                    self.stopped = False

                async def stop(self):
                    self.stopped = True

            context = Context()
            playwright = Playwright()
            adapter._browser_context = context
            adapter._playwright = playwright

            result = await adapter.shutdown_browser()

            self.assertIn("BRIDGE_BROWSER_SHUTDOWN_OK", result)
            self.assertTrue(context.closed)
            self.assertTrue(playwright.stopped)
            self.assertIsNone(adapter._browser_context)
            self.assertIsNone(adapter._playwright)

    async def test_second_project_request_uses_saved_conversation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            adapter = ChatGPTWebAdapter(
                str(root),
                {"web_adapter": {"base_url": "https://chatgpt.com", "user_data_dir": str(root / "profile")},
                 "conversation_reuse": {"enabled": True, "state_file": str(root / "sessions.json")},
                 "runtime": {}},
                logger=None,
            )
            observed_targets = []
            adapter.run_chrome_preflight = lambda: {"profile_in_use": False, "executable_exists": True, "user_data_dir_writable": True}

            async def fake_query_inner(prompt, target, timeout, call_id, preflight, profile=None):
                observed_targets.append(target)
                return "OK", "https://chatgpt.com/c/project-conversation"

            adapter._query_inner = fake_query_inner
            self.assertEqual(await adapter.query("first", project_root=str(root / "project")), "OK")
            self.assertEqual(await adapter.query("second", project_root=str(root / "project")), "OK")
            self.assertEqual(observed_targets, ["https://chatgpt.com", "https://chatgpt.com/c/project-conversation"])

if __name__ == "__main__":
    unittest.main()
