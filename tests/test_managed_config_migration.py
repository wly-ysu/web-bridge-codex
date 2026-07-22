import tempfile
import unittest
from pathlib import Path

import yaml

from server import migrate_managed_config_policy


class ManagedConfigMigrationTests(unittest.TestCase):
    def test_migrates_policy_and_preserves_user_owned_settings(self):
        original = {
            "schema_version": 2,
            "web_lead": {"default_profile": "balanced", "custom_note": "keep"},
            "web_adapter": {
                "user_data_dir": "C:/user/profile",
                "executable_path": "C:/Chrome/chrome.exe",
                "model_strategy": {"mode": "best_available", "custom_strategy_flag": True},
            },
            "context": {"transport": "repo_link"},
            "user_extension": {"keep": True},
        }
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "config.yaml"
            path.write_text(yaml.safe_dump(original, allow_unicode=True, sort_keys=False), encoding="utf-8")

            self.assertTrue(migrate_managed_config_policy(path))
            migrated = yaml.safe_load(path.read_text(encoding="utf-8"))

        self.assertEqual(migrated["web_lead"]["default_profile"], "general")
        self.assertEqual(migrated["web_lead"]["planning_profile"], "planning")
        self.assertEqual(migrated["web_lead"]["custom_note"], "keep")
        self.assertEqual(migrated["web_adapter"]["user_data_dir"], "C:/user/profile")
        self.assertEqual(migrated["web_adapter"]["executable_path"], "C:/Chrome/chrome.exe")
        self.assertEqual(migrated["web_adapter"]["model_strategy"]["profiles"]["general"]["capability_order"][0][0], "极高")
        self.assertEqual(migrated["web_adapter"]["model_strategy"]["profiles"]["planning"]["capability_order"][0][0], "Pro")
        self.assertTrue(migrated["web_adapter"]["model_strategy"]["custom_strategy_flag"])
        self.assertEqual(migrated["context"], original["context"])
        self.assertEqual(migrated["user_extension"], original["user_extension"])


if __name__ == "__main__":
    unittest.main()
