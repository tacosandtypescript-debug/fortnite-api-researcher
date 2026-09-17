"""Pruebas de robustez: partición de mensajes, bloqueo, reintentos y contabilidad.

Cubren los arreglos que no tenían red de seguridad: avisos largos, instancia
única del bot, claim-then-send, límites de la Bot API, diagnóstico de sondeos,
extensión real de las imágenes y parseo localizado del ping.
"""

import json
import os
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fortnite_research import regions
from fortnite_research.banner_delivery import BannerDelivery, prepare_wolverine_banners
from fortnite_research.config import Settings
from fortnite_research.penny_bot import (
    NewContentItem,
    NewContentSnapshot,
    NewsSnapshot,
    PennySnapshot,
    _InstanceLock,
    _split_message,
    run_penny_bot,
)
from fortnite_research.schedule_assets import (
    _destination_for_format,
    _image_info,
    _is_download,
    _is_failure,
    _public_status,
)
from fortnite_research.telegram import (
    TelegramDocumentSender,
    TelegramError,
    _truncate_utf16,
)
from fortnite_research.transport import HTTPFetchError, HTTPResponse, ResponseTooLargeError


class MessageSplitTests(unittest.TestCase):
    def test_short_message_is_returned_untouched(self):
        self.assertEqual(_split_message("hola"), ["hola"])

    def test_long_message_is_split_within_the_limit(self):
        text = "\n".join(f"• línea {index} " + "x" * 60 for index in range(400))

        parts = _split_message(text)

        self.assertGreater(len(parts), 1)
        for part in parts:
            self.assertLessEqual(len(part), 4096)
        self.assertIn("(1/", parts[0])
        self.assertIn("(2/", parts[1])

    def test_single_huge_line_is_split(self):
        parts = _split_message("z" * 9000)

        self.assertGreater(len(parts), 1)
        self.assertTrue(all(len(part) <= 4096 for part in parts))


class InstanceLockTests(unittest.TestCase):
    def test_second_instance_cannot_take_the_lock(self):
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary) / "penny-alert-state.json"
            first = _InstanceLock(state, stale_after=900)
            second = _InstanceLock(state, stale_after=900)

            self.assertTrue(first.acquire())
            self.assertFalse(second.acquire())

            first.release()
            self.assertTrue(second.acquire())
            second.release()

    def test_stale_lock_is_reclaimed(self):
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary) / "penny-alert-state.json"
            lock = _InstanceLock(state, stale_after=1)
            lock.lock_path.write_text("999999\n", encoding="utf-8")
            old = time.time() - 3600
            os.utime(lock.lock_path, (old, old))

            self.assertTrue(lock.acquire())
            lock.release()

    def test_run_stops_when_another_instance_holds_the_lock(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            settings = Settings(
                api_base_url="https://fortnite-api.com",
                api_key=None,
                api_timeout=5,
                telegram_bot_token="token",
                telegram_chat_id="chat",
                auto_send_telegram=True,
                output_dir=output,
            )
            holder = _InstanceLock(output / "penny-alert-state.json", stale_after=900)
            self.assertTrue(holder.acquire())
            try:
                with (
                    patch("fortnite_research.penny_bot.PennyClient", return_value=object()),
                    patch("fortnite_research.penny_bot.FortniteAPIClient", return_value=object()),
                ):
                    self.assertEqual(run_penny_bot(settings, once=True), 1)
            finally:
                holder.release()


class FakePennyClient:
    def __init__(self, snapshot):
        self._snapshot = snapshot

    def snapshot(self):
        return self._snapshot


class FakeContentClient:
    def __init__(self, snapshot):
        self._snapshot = snapshot

    def snapshot(self):
        return self._snapshot


class FailingSender:
    def __init__(self, *_args, **_kwargs):
        self.messages = []
        self.photos = []

    def send_message(self, message):
        self.messages.append(message)
        raise TelegramError("HTTP 429 simulado")

    def send_photo(self, photo_url, caption=None):
        self.photos.append((photo_url, caption))
        raise TelegramError("HTTP 429 simulado")


class WorkingSender:
    def __init__(self, *_args, **_kwargs):
        self.messages = []
        self.photos = []

    def send_message(self, message):
        self.messages.append(message)
        return {"ok": True}

    def send_photo(self, photo_url, caption=None):
        self.photos.append((photo_url, caption))
        return {"ok": True}


class ClaimThenSendTests(unittest.TestCase):
    """Un envío fallido queda reclamado y se reintenta una vez."""

    def _settings(self, output: Path) -> Settings:
        return Settings(
            api_base_url="https://fortnite-api.com",
            api_key=None,
            api_timeout=5,
            telegram_bot_token="token",
            telegram_chat_id="chat",
            auto_send_telegram=True,
            output_dir=output,
        )

    def _content(self, now: datetime, *extra: str) -> NewContentSnapshot:
        items = [
            NewContentItem(
                key,
                "br",
                key.split(":")[1],
                f"Objeto {key}",
                "Gesto",
                "Épico",
                (now - timedelta(minutes=2)).isoformat().replace("+00:00", "Z"),
                f"https://fortnite-api.com/images/{key.split(':')[1]}.png",
            )
            for key in ("br:item-1", *extra)
        ]
        return NewContentSnapshot("build-42", "", tuple(items))

    def _run(self, settings: Settings, content, news, sender) -> int:
        with (
            patch("fortnite_research.penny_bot.PennyClient", return_value=FakePennyClient(PennySnapshot("2026-09-13", (), ()))),
            patch("fortnite_research.penny_bot.FortniteAPIClient", return_value=object()),
            patch("fortnite_research.penny_bot.NewContentClient", return_value=FakeContentClient(content)),
            patch("fortnite_research.penny_bot.NewsClient", return_value=FakeContentClient(news)),
            patch("fortnite_research.penny_bot.TelegramDocumentSender", return_value=sender),
        ):
            return run_penny_bot(settings, once=True)

    def test_failed_delivery_is_retried_and_then_cleared(self):
        now = datetime.now(timezone.utc)
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            settings = self._settings(output)
            state_path = output / "penny-alert-state.json"

            # Primera pasada: línea base, sin envíos.
            self.assertEqual(self._run(settings, self._content(now), NewsSnapshot(()), WorkingSender()), 0)

            failing = FailingSender()
            self.assertEqual(
                self._run(
                    settings,
                    self._content(now, "br:item-2"),
                    NewsSnapshot(()),
                    failing,
                ),
                0,
            )
            self.assertTrue(failing.photos or failing.messages)
            state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(len(state["undelivered"]), 1)
            self.assertIn("Objeto br:item-2", state["undelivered"][0]["caption"])

            working = WorkingSender()
            self.assertEqual(
                self._run(
                    settings,
                    self._content(now, "br:item-2"),
                    NewsSnapshot(()),
                    working,
                ),
                0,
            )
            self.assertEqual(len(working.photos), 1)
            state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(state["undelivered"], [])

    def test_claim_is_persisted_before_delivery(self):
        now = datetime.now(timezone.utc)
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            settings = self._settings(output)
            state_path = output / "penny-alert-state.json"
            self._run(settings, self._content(now), NewsSnapshot(()), WorkingSender())

            class InspectingSender(WorkingSender):
                def send_photo(self, photo_url, caption=None):
                    state = json.loads(state_path.read_text(encoding="utf-8"))
                    assert state["new_content"]["seen_keys"] == [
                        "br:item-1",
                        "br:item-2",
                    ], state
                    return super().send_photo(photo_url, caption)

            sender = InspectingSender()
            self.assertEqual(
                self._run(
                    settings,
                    self._content(now, "br:item-2"),
                    NewsSnapshot(()),
                    sender,
                ),
                0,
            )
            self.assertEqual(len(sender.photos), 1)


class TelegramLimitTests(unittest.TestCase):
    def test_truncation_counts_utf16_units(self):
        text = "🧩" * 800

        truncated = _truncate_utf16(text, 1024)

        self.assertLessEqual(len(truncated.encode("utf-16-le")) // 2, 1024)
        self.assertTrue(truncated.endswith("…"))

    def test_short_caption_is_untouched(self):
        self.assertEqual(_truncate_utf16("hola", 1024), "hola")

    def test_retries_once_on_rate_limit(self):
        sender = TelegramDocumentSender("123456789:AAHq_abcdefghijklmnopqrstuvwxyz1234", "1")
        calls = []

        def fake_fetch(*_args, **_kwargs):
            calls.append(1)
            if len(calls) == 1:
                raise HTTPFetchError("HTTP 429", status_code=429, headers={"Retry-After": "0"})
            return HTTPResponse(
                status_code=200,
                headers={},
                body=json.dumps({"ok": True, "result": {}}).encode(),
            )

        with (
            patch("fortnite_research.telegram.fetch", side_effect=fake_fetch),
            patch("fortnite_research.telegram.time.sleep") as sleeper,
        ):
            result = sender.send_message("hola")

        self.assertTrue(result["ok"])
        self.assertEqual(len(calls), 2)
        sleeper.assert_called_once()

    def test_does_not_retry_on_other_errors(self):
        sender = TelegramDocumentSender("123456789:AAHq_abcdefghijklmnopqrstuvwxyz1234", "1")
        calls = []

        def fake_fetch(*_args, **_kwargs):
            calls.append(1)
            raise HTTPFetchError("HTTP 400", status_code=400)

        with patch("fortnite_research.telegram.fetch", side_effect=fake_fetch):
            with self.assertRaises(TelegramError):
                sender.send_message("hola")

        self.assertEqual(len(calls), 1)


class ScheduleAccountingTests(unittest.TestCase):
    def test_duplicates_are_not_counted_as_downloads(self):
        duplicate = {"downloaded": False, "deduplicated": True, "bytes": 0}
        downloaded = {"downloaded": True, "bytes": 10}
        failed = {"downloaded": False, "errorType": "http"}

        self.assertTrue(_is_download(downloaded))
        self.assertFalse(_is_download(duplicate))
        self.assertTrue(_is_failure(failed))
        self.assertFalse(_is_failure(duplicate))

    def test_extension_follows_detected_format(self):
        self.assertEqual(_destination_for_format(Path("a/foto.png"), "WEBP").suffix, ".webp")
        self.assertEqual(_destination_for_format(Path("a/foto.jpeg"), "JPEG").suffix, ".jpeg")
        self.assertEqual(_destination_for_format(Path("a/foto.png"), "PNG").suffix, ".png")

    def test_avif_is_recognized(self):
        content = b"\x00\x00\x00\x18ftypavif" + b"\x00" * 20

        info = _image_info(content, "image/avif")

        self.assertTrue(info["valid"])
        self.assertEqual(info["format"], "AVIF")

    def test_oversized_public_check_is_classified(self):
        with patch(
            "fortnite_research.schedule_assets.fetch",
            side_effect=ResponseTooLargeError("demasiado grande"),
        ):
            result = _public_status("https://example.test/history.json", 5)

        self.assertEqual(result["errorType"], "size_exceeded")
        self.assertFalse(result["available"])


class BannerDeliveryTests(unittest.TestCase):
    def test_partial_delivery_reports_missing_banners(self):
        client = SimpleNamespace(
            get=lambda *_args, **_kwargs: SimpleNamespace(
                payload={
                    "data": [
                        {
                            "id": "BRS14_HighTowerDate",
                            "images": {"icon": "https://fortnite-api.com/images/banner.png"},
                        }
                    ]
                }
            )
        )
        downloaded = {
            "downloaded": True,
            "bytes": 123,
            "path": "x.png",
        }

        with tempfile.TemporaryDirectory() as temporary:
            with patch(
                "fortnite_research.banner_delivery._download_image",
                return_value=downloaded,
            ):
                delivery = prepare_wolverine_banners(client, Path(temporary))

        self.assertEqual(len(delivery.files), 1)
        self.assertEqual(len(delivery.missing), 4)
        self.assertEqual(delivery.bytes_total, 123)

    def test_no_banner_available_raises_value_error(self):
        client = SimpleNamespace(
            get=lambda *_args, **_kwargs: SimpleNamespace(payload={"data": []})
        )

        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(ValueError):
                prepare_wolverine_banners(client, Path(temporary))

    def test_send_requires_matching_lists(self):
        delivery = BannerDelivery((Path("a.png"),), (), 0)
        sender = SimpleNamespace(send_document=lambda *_a, **_k: {"ok": True})

        from fortnite_research.banner_delivery import send_banner_documents

        with self.assertRaises(ValueError):
            send_banner_documents(delivery, sender)


class RegionPingTests(unittest.TestCase):
    ENGLISH = (
        "Packets: Sent = 4, Received = 4, Lost = 0 (0% loss),\n"
        "Approximate round trip times in milli-seconds:\n"
        "    Minimum = 20ms, Maximum = 31ms, Average = 25ms\n"
    )
    SPANISH = (
        "Paquetes: enviados = 4, recibidos = 4, perdidos = 0 (0% perdidos),\n"
        "Tiempos aproximados de ida y vuelta en milisegundos:\n"
        "    Mínimo = 20ms, Máximo = 31ms, Media = 25ms\n"
    )

    def _run_ping(self, output: str) -> dict:
        completed = SimpleNamespace(stdout=output, stderr="", returncode=0)
        with patch("fortnite_research.regions.subprocess.run", return_value=completed):
            return regions._ping("host.test")

    def test_parses_english_summary(self):
        result = self._run_ping(self.ENGLISH)

        self.assertEqual((result["minMs"], result["maxMs"], result["avgMs"]), (20, 31, 25))
        self.assertNotIn("error", result)

    def test_parses_spanish_summary(self):
        result = self._run_ping(self.SPANISH)

        self.assertEqual((result["minMs"], result["maxMs"], result["avgMs"]), (20, 31, 25))

    def test_unlabelled_summary_is_not_guessed(self):
        result = self._run_ping("respuesta rara 10ms 20ms 30ms\n")

        self.assertIsNone(result["minMs"])
        self.assertIsNone(result["avgMs"])
        self.assertIn("error", result)

    def test_ping_command_is_platform_aware(self):
        with patch("fortnite_research.regions.sys.platform", "linux"):
            self.assertEqual(regions._ping_command("host", 4)[0], "ping")
        with patch("fortnite_research.regions.sys.platform", "win32"):
            self.assertEqual(regions._ping_command("host", 4)[0], "ping.exe")


if __name__ == "__main__":
    unittest.main()
