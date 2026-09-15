import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fortnite_research.config import Settings
from fortnite_research.penny_bot import (
    FreeLlama,
    NewContentClient,
    NewContentItem,
    NewContentSnapshot,
    NewsItem,
    NewsSnapshot,
    PennySnapshot,
    VbucksAlert,
    _fresh_items,
    format_alert_message,
    format_new_content_message,
    run_penny_bot,
)


class FakeFortniteClient:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def get(self, path, params):
        self.calls.append((path, params))
        return SimpleNamespace(payload=self.payload)


class FakePennyClient:
    def __init__(self, snapshot):
        self._snapshot = snapshot

    def snapshot(self):
        return self._snapshot


class FakeNewContentClient:
    def __init__(self, snapshot):
        self._snapshot = snapshot

    def snapshot(self):
        return self._snapshot


class FakeNewsClient:
    def __init__(self, snapshot):
        self._snapshot = snapshot

    def snapshot(self):
        return self._snapshot


class FakeSender:
    def __init__(self, *_args, **_kwargs):
        self.messages = []
        self.photos = []

    def send_message(self, message):
        self.messages.append(message)
        return {"ok": True}

    def send_photo(self, photo_url, caption=None):
        self.photos.append((photo_url, caption))
        return {"ok": True}


class PennyBotTests(unittest.TestCase):
    def test_new_content_client_reads_catalog_in_spanish(self):
        payload = {
            "status": 200,
            "data": {
                "build": "build-42",
                "date": "13/09/2026",
                "items": {
                    "br": [
                        {
                            "id": "Outfit_Test",
                            "name": "Héroe nuevo",
                            "type": {"displayValue": "Atuendo"},
                            "rarity": {"displayValue": "Legendario"},
                            "added": "2026-09-13T00:00:00Z",
                            "images": {"featured": "https://fortnite-api.com/images/test.png"},
                        }
                    ]
                },
            },
        }
        client = FakeFortniteClient(payload)

        snapshot = NewContentClient(client).snapshot()

        self.assertEqual(snapshot.build, "build-42")
        self.assertEqual(snapshot.items[0].name, "Héroe nuevo")
        self.assertEqual(snapshot.items[0].item_type, "Atuendo")
        self.assertEqual(snapshot.items[0].image_url, "https://fortnite-api.com/images/test.png")
        self.assertEqual(client.calls, [("/v2/cosmetics/new", {"language": "es"})])

    def test_news_client_reads_br_and_stw_in_spanish(self):
        payloads = {
            "/v2/news/br": {
                "data": {
                    "date": "2026-09-13T00:00:00Z",
                    "motds": [{
                        "id": "cup-1",
                        "title": "Copa nueva",
                        "body": "Compite para conseguir un premio.",
                        "image": "https://cdn-live.prm.ol.epicgames.com/cup.jpg",
                    }],
                }
            },
            "/v2/news/stw": {
                "data": {
                    "date": "2026-09-13T00:00:00Z",
                    "messages": [{
                        "title": "Mensaje STW",
                        "body": "Una noticia.",
                        "image": "https://cdn2.unrealengine.com/stw.jpg",
                    }],
                }
            },
        }

        class NewsFakeClient:
            def __init__(self):
                self.calls = []

            def get(self, path, params):
                self.calls.append((path, params))
                return SimpleNamespace(payload=payloads[path])

        from fortnite_research.penny_bot import NewsClient

        client = NewsFakeClient()
        snapshot = NewsClient(client).snapshot()

        self.assertEqual(len(snapshot.items), 2)
        self.assertEqual(snapshot.items[0].image_url, "https://cdn-live.prm.ol.epicgames.com/cup.jpg")
        self.assertEqual(
            client.calls,
            [
                ("/v2/news/br", {"language": "es"}),
                ("/v2/news/stw", {"language": "es"}),
            ],
        )

    def test_freshness_rejects_old_invalid_and_future_entries(self):
        now = datetime(2026, 9, 13, 12, 0, tzinfo=timezone.utc)
        items = (
            NewContentItem("fresh", "br", "fresh", "Fresco", "Atuendo", "", "2026-09-13T11:30:00Z"),
            NewContentItem("old", "br", "old", "Antiguo", "Atuendo", "", "2026-09-11T11:30:00Z"),
            NewContentItem("invalid", "br", "invalid", "Sin fecha", "Atuendo", "", ""),
            NewContentItem("future", "br", "future", "Futuro", "Atuendo", "", "2026-09-14T11:30:00Z"),
        )

        fresh = _fresh_items(items, now=now, max_age_hours=24)

        self.assertEqual([item.key for item in fresh], ["fresh"])

    def test_messages_translate_stw_labels_to_spanish(self):
        alerts = PennySnapshot(
            reset_date="2026-09-13",
            vbucks=(
                VbucksAlert(
                    zone="Bosque Calcinado",
                    power_level="108",
                    mission="Repara el refugio",
                    quantity=50,
                    modifiers=("Minijefe épico",),
                ),
            ),
            free_llamas=(FreeLlama("Llama de mejora", 1, None, None),),
        )

        message = format_alert_message(alerts)

        self.assertIn("Misiones de pavos", message)
        self.assertIn("Bosque Calcinado", message)
        self.assertIn("Llama de mejora", message)
        self.assertIn("13/09/2026", message)

    def test_new_content_message_keeps_total_and_limits_details(self):
        items = tuple(
            NewContentItem(
                key=f"br:item-{index}",
                category="br",
                item_id=f"item-{index}",
                name=f"Objeto {index}",
                item_type="Atuendo",
                rarity="Épico",
                added="2026-09-13T00:00:00Z",
            )
            for index in range(30)
        )
        message = format_new_content_message(
            NewContentSnapshot("build-42", "", items),
            items,
        )

        self.assertIn("30 elemento(s) nuevo(s)", message)
        self.assertIn("y 6 entrada(s) más", message)
        self.assertLessEqual(len(message), 4096)

    def test_run_notifies_new_content_once_and_persists_keys(self):
        penny_snapshot = PennySnapshot(
            reset_date="2026-09-13",
            vbucks=(VbucksAlert("Bosque Calcinado", "108", "Repara el refugio", 50, ()),),
            free_llamas=(),
        )
        now = datetime.now(timezone.utc)
        first_item = NewContentItem(
            "br:item-1", "br", "item-1", "Objeto existente", "Atuendo", "Épico",
            (now - timedelta(minutes=10)).isoformat().replace("+00:00", "Z"),
        )
        content_snapshot = NewContentSnapshot(
            "build-42",
            "",
            (first_item,),
        )
        news_snapshot = NewsSnapshot(())

        with tempfile.TemporaryDirectory() as temporary:
            settings = Settings(
                api_base_url="https://fortnite-api.com",
                api_key=None,
                api_timeout=5,
                telegram_bot_token="token",
                telegram_chat_id="chat",
                auto_send_telegram=True,
                output_dir=Path(temporary),
            )
            sender = FakeSender()
            with (
                patch("fortnite_research.penny_bot.PennyClient", return_value=FakePennyClient(penny_snapshot)),
                patch("fortnite_research.penny_bot.FortniteAPIClient", return_value=object()),
                patch("fortnite_research.penny_bot.NewContentClient", return_value=FakeNewContentClient(content_snapshot)),
                patch("fortnite_research.penny_bot.NewsClient", return_value=FakeNewsClient(news_snapshot)),
                patch("fortnite_research.penny_bot.TelegramDocumentSender", return_value=sender),
            ):
                self.assertEqual(run_penny_bot(settings, once=True), 0)

            # La primera ejecución crea la línea base y no reenvía el catálogo
            # que ya estaba publicado.
            self.assertEqual(len(sender.messages), 1)
            self.assertEqual(sender.photos, [])
            state = json.loads((Path(temporary) / "penny-alert-state.json").read_text(encoding="utf-8"))
            self.assertEqual(state["new_content"]["seen_keys"], ["br:item-1"])

            sender.messages.clear()
            new_item = NewContentItem(
                "br:item-2", "br", "item-2", "Objeto nuevo", "Gesto", "Épico",
                (now - timedelta(minutes=2)).isoformat().replace("+00:00", "Z"),
                "https://fortnite-api.com/images/item-2.png",
            )
            content_client = FakeNewContentClient(
                NewContentSnapshot("build-42", "", (first_item, new_item))
            )
            with (
                patch("fortnite_research.penny_bot.PennyClient", return_value=FakePennyClient(penny_snapshot)),
                patch("fortnite_research.penny_bot.FortniteAPIClient", return_value=object()),
                patch("fortnite_research.penny_bot.NewContentClient", return_value=content_client),
                patch("fortnite_research.penny_bot.NewsClient", return_value=FakeNewsClient(news_snapshot)),
                patch("fortnite_research.penny_bot.TelegramDocumentSender", return_value=sender),
            ):
                self.assertEqual(run_penny_bot(settings, once=True), 0)
            self.assertEqual(sender.messages, [])
            self.assertEqual(len(sender.photos), 1)
            self.assertEqual(sender.photos[0][0], "https://fortnite-api.com/images/item-2.png")
            self.assertIn("Objeto nuevo", sender.photos[0][1])
            self.assertIn("Comprobado:", sender.photos[0][1])

            sender.photos.clear()
            with (
                patch("fortnite_research.penny_bot.PennyClient", return_value=FakePennyClient(penny_snapshot)),
                patch("fortnite_research.penny_bot.FortniteAPIClient", return_value=object()),
                patch("fortnite_research.penny_bot.NewContentClient", return_value=content_client),
                patch("fortnite_research.penny_bot.NewsClient", return_value=FakeNewsClient(news_snapshot)),
                patch("fortnite_research.penny_bot.TelegramDocumentSender", return_value=sender),
            ):
                self.assertEqual(run_penny_bot(settings, once=True), 0)
            self.assertEqual(sender.messages, [])
            self.assertEqual(sender.photos, [])


if __name__ == "__main__":
    unittest.main()
