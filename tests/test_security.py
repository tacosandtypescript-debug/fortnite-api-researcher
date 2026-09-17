"""Pruebas de redacción de credenciales y validación de configuración."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fortnite_research.config import Settings
from fortnite_research.transport import redact_secrets

TELEGRAM_TOKEN = "123456789:AAHq_abcdefghijklmnopqrstuvwxyz1234"


class RedactionTests(unittest.TestCase):
    def test_redacts_telegram_token_inside_bot_api_url(self):
        message = f"Error de transporte: https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendDocument"

        redacted = redact_secrets(message)

        self.assertNotIn("AAHq_", redacted)
        self.assertIn("api.telegram.org", redacted)

    def test_redacts_bare_token_without_url(self):
        self.assertNotIn("AAHq_", redact_secrets(f"401 {TELEGRAM_TOKEN}"))

    def test_redacts_header_and_query_values(self):
        redacted = redact_secrets("x-api-key: abc123 y token=deadbeef&chat_id=1")

        self.assertNotIn("abc123", redacted)
        self.assertNotIn("deadbeef", redacted)
        self.assertIn("chat_id=1", redacted)

    def test_redacts_common_credential_formats(self):
        for value in ("sk-abcdefghijklmnop", "ghp_abcdefghijklmnop", "AKIAIOSFODNN7EXAMPLE"):
            with self.subTest(value=value):
                self.assertNotIn(value, redact_secrets(f"clave {value}"))

    def test_keeps_urls_without_credentials(self):
        url = "https://fortnite-api.com/v2/shop?language=es"

        self.assertEqual(redact_secrets(url), url)

    def test_handles_empty_and_none(self):
        self.assertEqual(redact_secrets(""), "")
        self.assertEqual(redact_secrets(None), "")


class SettingsValidationTests(unittest.TestCase):
    def _load(self, temporary: str, **environment: str) -> Settings:
        with patch.dict(os.environ, environment, clear=True):
            return Settings.load(root=Path(temporary))

    def test_accepts_valid_telegram_credentials(self):
        with tempfile.TemporaryDirectory() as temporary:
            settings = self._load(
                temporary,
                TELEGRAM_BOT_TOKEN=TELEGRAM_TOKEN,
                TELEGRAM_CHAT_ID="-1001234567890",
            )

        self.assertEqual(settings.telegram_chat_id, "-1001234567890")

    def test_rejects_malformed_bot_token(self):
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(ValueError, "TELEGRAM_BOT_TOKEN"):
                self._load(temporary, TELEGRAM_BOT_TOKEN="no-es-un-token")

    def test_rejects_malformed_chat_id(self):
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(ValueError, "TELEGRAM_CHAT_ID"):
                self._load(temporary, TELEGRAM_CHAT_ID="chat de prueba")

    def test_rejects_auto_send_with_chat_discovery(self):
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(ValueError, "ALLOW_CHAT_DISCOVERY"):
                self._load(
                    temporary,
                    AUTO_SEND_TELEGRAM="true",
                    TELEGRAM_ALLOW_CHAT_DISCOVERY="true",
                )

    def test_reads_inline_comment_in_dotenv(self):
        with tempfile.TemporaryDirectory() as temporary:
            (Path(temporary) / ".env").write_text(
                "FORTNITE_API_TIMEOUT=45  # segundos\n",
                encoding="utf-8",
            )
            settings = self._load(temporary)

        self.assertEqual(settings.api_timeout, 45.0)

    def test_keeps_hash_inside_unquoted_value(self):
        with tempfile.TemporaryDirectory() as temporary:
            (Path(temporary) / ".env").write_text(
                'FORTNITE_OUTPUT_DIR=salidas#1\n',
                encoding="utf-8",
            )
            settings = self._load(temporary)

        self.assertEqual(settings.output_dir.name, "salidas#1")


if __name__ == "__main__":
    unittest.main()
