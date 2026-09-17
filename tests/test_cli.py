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
        self.calls: list[tuple] = []

    def _result(self, path: str, params: dict) -> SimpleNamespace:
        if self.error is not None:
            raise self.error
        return SimpleNamespace(
            path=path,
            params=params,
            status_code=200,
            payload=self.payload,
        )

    def get(self, path, params=None, *, max_bytes=None):
        self.calls.append(("get", path, params or {}, max_bytes))
        return self._result(path, params or {})

    def shop(self, language="en"):
        return self._result("/v2/shop", {"language": language})

    def aes(self, key_format="hex"):
        self.calls.append(("aes", key_format))
        return self._result("/v2/aes", {"keyFormat": key_format})


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


class AesCommandTests(unittest.TestCase):
    def test_aes_uses_the_v2_route_and_keeps_the_format(self):
        client = FakeClient(payload={"status": 200, "data": {"build": "42.10"}})
        with tempfile.TemporaryDirectory() as temporary:
            with (
                patch("fortnite_research.cli.Settings.load", return_value=_settings(Path(temporary))),
                patch("fortnite_research.cli._client", return_value=client),
            ):
                exit_code = cli.main(["aes", "--key-format", "base64"])

            files = list(Path(temporary).glob("*.json"))
            document = json.loads(files[0].read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0)
        self.assertEqual(client.calls, [("aes", "base64")])
        self.assertEqual(document["investigation"]["path"], "/v2/aes")
        self.assertEqual(document["investigation"]["params"], {"keyFormat": "base64"})

    def test_aes_defaults_to_hex(self):
        client = FakeClient()
        with tempfile.TemporaryDirectory() as temporary:
            with (
                patch("fortnite_research.cli.Settings.load", return_value=_settings(Path(temporary))),
                patch("fortnite_research.cli._client", return_value=client),
            ):
                self.assertEqual(cli.main(["aes"]), 0)

        self.assertEqual(client.calls, [("aes", "hex")])


class ResponseLimitTests(unittest.TestCase):
    def test_max_mb_is_forwarded_to_the_client(self):
        client = FakeClient()
        with tempfile.TemporaryDirectory() as temporary:
            with (
                patch("fortnite_research.cli.Settings.load", return_value=_settings(Path(temporary))),
                patch("fortnite_research.cli._client", return_value=client),
            ):
                exit_code = cli.main(["get", "/v2/cosmetics/br", "--max-mb", "60"])

        self.assertEqual(exit_code, 0)
        self.assertEqual(client.calls, [("get", "/v2/cosmetics/br", {}, 60_000_000)])

    def test_without_max_mb_the_client_default_applies(self):
        client = FakeClient()
        with tempfile.TemporaryDirectory() as temporary:
            with (
                patch("fortnite_research.cli.Settings.load", return_value=_settings(Path(temporary))),
                patch("fortnite_research.cli._client", return_value=client),
            ):
                self.assertEqual(cli.main(["get", "/v1/playlists"]), 0)

        self.assertIsNone(client.calls[0][3])

    def test_non_positive_max_mb_is_rejected(self):
        client = FakeClient()
        with tempfile.TemporaryDirectory() as temporary:
            with (
                patch("fortnite_research.cli.Settings.load", return_value=_settings(Path(temporary))),
                patch("fortnite_research.cli._client", return_value=client),
            ):
                exit_code = cli.main(["get", "/v1/playlists", "--max-mb", "0"])

        self.assertEqual(exit_code, 1)
        self.assertEqual(client.calls, [])


class ServersDiagnosisTests(unittest.TestCase):
    def test_retired_and_missing_routes_are_reported_with_their_status(self):
        class ProbeClient:
            base_url = "https://fortnite-api.com"

            def get(self, path, params=None, *, max_bytes=None):
                raise FortniteAPIError("no disponible", status_code=410)

        ping = {
            "replies": 4,
            "packetLossPercent": 0,
            "minMs": 20,
            "avgMs": 25,
            "maxMs": 31,
        }
        with tempfile.TemporaryDirectory() as temporary:
            with (
                patch("fortnite_research.cli.Settings.load", return_value=_settings(Path(temporary))),
                patch("fortnite_research.cli._client", return_value=ProbeClient()),
                # Sin esto la prueba haría DNS y ping reales a los endpoints de Epic.
                patch("fortnite_research.regions._ping", return_value=dict(ping)),
                patch("fortnite_research.regions._resolve_ipv4", return_value=(["203.0.113.1"], None)),
            ):
                exit_code = cli.main(["servers"])

            files = list(Path(temporary).glob("*.json"))
            document = json.loads(files[0].read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0)
        checks = document["apiScope"]["liveEndpointChecks"]
        self.assertEqual(set(checks), {"/v1/status", "/v1/servers", "/v1/regions"})
        self.assertEqual(checks["/v1/status"]["httpStatus"], 410)
        self.assertEqual(checks["/v1/status"]["kind"], "retired")
        self.assertFalse(checks["/v1/status"]["available"])


if __name__ == "__main__":
    unittest.main()
