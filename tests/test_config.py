import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fortnite_research.config import Settings


class SettingsTests(unittest.TestCase):
    def test_loads_relative_output_dir_from_explicit_project_root(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / ".env").write_text(
                "FORTNITE_OUTPUT_DIR=reports\n"
                "AUTO_SEND_TELEGRAM=yes\n"
                "TELEGRAM_ALLOW_CHAT_DISCOVERY=false\n",
                encoding="utf-8",
            )
            with patch.dict(os.environ, {}, clear=True):
                settings = Settings.load(root)
        self.assertEqual(settings.output_dir, root / "reports")
        self.assertTrue(settings.auto_send_telegram)
        self.assertFalse(settings.telegram_allow_chat_discovery)

    def test_api_key_rejects_untrusted_base_host(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / ".env").write_text(
                "FORTNITE_API_KEY=secret\n"
                "FORTNITE_API_BASE_URL=https://example.test\n"
                "FORTNITE_API_TRUSTED_HOSTS=fortnite-api.com\n",
                encoding="utf-8",
            )
            with patch.dict(os.environ, {}, clear=True):
                with self.assertRaisesRegex(ValueError, "hostname"):
                    Settings.load(root)

    def test_invalid_boolean_is_reported(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / ".env").write_text(
                "AUTO_SEND_TELEGRAM=maybe\n",
                encoding="utf-8",
            )
            with patch.dict(os.environ, {}, clear=True):
                with self.assertRaisesRegex(ValueError, "AUTO_SEND_TELEGRAM"):
                    Settings.load(root)

    def test_loads_new_content_freshness_window(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / ".env").write_text(
                "PENNY_NEW_CONTENT_MAX_AGE_HOURS=6\n",
                encoding="utf-8",
            )
            with patch.dict(os.environ, {}, clear=True):
                settings = Settings.load(root)
        self.assertEqual(settings.new_content_max_age_hours, 6.0)


if __name__ == "__main__":
    unittest.main()
