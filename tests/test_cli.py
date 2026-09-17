"""Pruebas del punto de entrada: parseo, despacho y códigos de salida."""

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fortnite_research import cli
from fortnite_research.client import FortniteAPIError
from fortnite_research.config import Settings


def _settings(output_dir: Path) -> Settings:
    return Settings(
        api_base_url="https://fortnite-api.com",
        api_key=None,
        api_timeout=5,
        telegram_bot_token=None,
        telegram_chat_id=None,
        auto_send_telegram=False,
        output_dir=output_dir,
    )


class ParserTests(unittest.TestCase):
    def test_rejects_unknown_command_with_argparse_exit_code(self):
        with self.assertRaises(SystemExit) as raised:
            cli.build_parser().parse_args(["no-existe"])

        self.assertEqual(raised.exception.code, 2)

    def test_bot_flags_are_parsed(self):
        args = cli.build_parser().parse_args(["bot", "--once", "--dry-run", "--interval", "30"])

        self.assertTrue(args.once)
        self.assertTrue(args.dry_run)
        self.assertEqual(args.interval, 30.0)

    def test_param_requires_key_value(self):
        with self.assertRaises(ValueError):
            cli._params(["solo-clave"])

    def test_param_rejects_empty_key(self):
        with self.assertRaises(ValueError):
            cli._params(["=valor"])

    def test_param_parses_pairs(self):
        self.assertEqual(cli._params(["language=es", "a=1=2"]), {"language": "es", "a": "1=2"})


class FakeClient:
    """Cliente mínimo: solo los métodos que usa el CLI en estas pruebas."""

    base_url = "https://fortnite-api.com"

    def __init__(self, *, error: Exception | None = None, payload=None):
        self.error = error
        self.payload = payload if payload is not None else {"status": 200, "data": {}}

    def _result(self, path: str, params: dict) -> SimpleNamespace:
        if self.error is not None:
            raise self.error
        return SimpleNamespace(
            path=path,
            params=params,
            status_code=200,
            payload=self.payload,
        )

    def get(self, path, params=None):
        return self._result(path, params or {})

    def shop(self, language="en"):
        return self._result("/v2/shop", {"language": language})


class MainDispatchTests(unittest.TestCase):
    def test_get_saves_result_without_sending(self):
        with tempfile.TemporaryDirectory() as temporary:
            payload = {"status": 200, "data": {"ok": True}}
            with (
                patch("fortnite_research.cli.Settings.load", return_value=_settings(Path(temporary))),
                patch("fortnite_research.cli._client", return_value=FakeClient(payload=payload)),
            ):
                exit_code = cli.main(["get", "/v1/playlists", "--param", "language=es"])

            files = list(Path(temporary).glob("*.json"))
            self.assertEqual(exit_code, 0)
            self.assertEqual(len(files), 1)
            document = json.loads(files[0].read_text(encoding="utf-8"))
            self.assertEqual(document["investigation"]["path"], "/v1/playlists")
            self.assertEqual(document["response"], payload)

    def test_api_error_returns_one_and_prints_to_stderr(self):
        client = FakeClient(error=FortniteAPIError("La API no pudo completar la consulta"))
        with tempfile.TemporaryDirectory() as temporary:
            with (
                patch("fortnite_research.cli.Settings.load", return_value=_settings(Path(temporary))),
                patch("fortnite_research.cli._client", return_value=client),
            ):
                exit_code = cli.main(["shop", "--language", "es"])

        self.assertEqual(exit_code, 1)

    def test_error_message_is_redacted(self):
        token = "123456789:AAHq_abcdefghijklmnopqrstuvwxyz1234"
        client = FakeClient(
            error=FortniteAPIError(
                f"Error de transporte: https://api.telegram.org/bot{token}/sendMessage"
            )
        )
        with tempfile.TemporaryDirectory() as temporary:
            with (
                patch("fortnite_research.cli.Settings.load", return_value=_settings(Path(temporary))),
                patch("fortnite_research.cli._client", return_value=client),
                patch("sys.stderr") as stderr,
            ):
                exit_code = cli.main(["shop"])

        self.assertEqual(exit_code, 1)
        printed = "".join(str(call.args[0]) for call in stderr.write.call_args_list)
        self.assertNotIn("AAHq_", printed)

    def test_send_without_credentials_fails_explicitly(self):
        with tempfile.TemporaryDirectory() as temporary:
            settings = _settings(Path(temporary))
            with (
                patch("fortnite_research.cli.Settings.load", return_value=settings),
                patch("fortnite_research.cli._client", return_value=FakeClient()),
            ):
                exit_code = cli.main(["shop", "--send"])

        self.assertEqual(exit_code, 1)


if __name__ == "__main__":
    unittest.main()
