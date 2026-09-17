import json
import unittest
from unittest.mock import patch

from fortnite_research.client import DEFAULT_MAX_BYTES, FortniteAPIClient
from fortnite_research.telegram import TelegramDocumentSender, _multipart
from fortnite_research.transport import HTTPResponse


class FakeResponse:
    status = 200
    headers = {}

    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self, size=-1):
        return self.payload if size < 0 else self.payload[:size]


class ResponseLimitTests(unittest.TestCase):
    def _patch_fetch(self):
        return patch(
            "fortnite_research.client.fetch",
            return_value=HTTPResponse(
                status_code=200,
                headers={},
                body=json.dumps({"status": 200, "data": {}}).encode(),
            ),
        )

    def test_default_limit_allows_the_full_catalog(self):
        self.assertGreaterEqual(FortniteAPIClient().max_bytes, 32_000_000)

    def test_per_request_limit_overrides_the_default(self):
        client = FortniteAPIClient()
        with self._patch_fetch() as mocked:
            client.get("/v2/cosmetics/br", {"language": "es"}, max_bytes=64_000_000)

        self.assertEqual(mocked.call_args.kwargs["max_bytes"], 64_000_000)

    def test_default_limit_is_used_when_not_overridden(self):
        client = FortniteAPIClient()
        with self._patch_fetch() as mocked:
            client.get("/v2/shop")

        self.assertEqual(mocked.call_args.kwargs["max_bytes"], DEFAULT_MAX_BYTES)

    def test_rejects_non_positive_limits(self):
        with self.assertRaises(ValueError):
            FortniteAPIClient(max_bytes=0)

        client = FortniteAPIClient()
        with self.assertRaises(ValueError):
            client.get("/v2/shop", max_bytes=-1)

    def test_aes_helper_uses_the_current_route(self):
        client = FortniteAPIClient()
        with self._patch_fetch() as mocked:
            result = client.aes("base64")

        url = mocked.call_args.args[0]
        self.assertIn("/v2/aes", url)
        self.assertIn("keyFormat=base64", url)
        self.assertEqual(result.path, "/v2/aes")

    def test_aes_rejects_unknown_format(self):
        with self.assertRaises(ValueError):
            FortniteAPIClient().aes("binario")

    def test_full_catalog_helper_hits_v2_cosmetics_br(self):
        client = FortniteAPIClient()
        with self._patch_fetch() as mocked:
            result = client.cosmetics_br("es")

        self.assertIn("/v2/cosmetics/br", mocked.call_args.args[0])
        self.assertEqual(result.status_code, 200)


class ClientTests(unittest.TestCase):
    @patch(
        "fortnite_research.transport._open",
        return_value=FakeResponse(
            json.dumps({"status": 200, "data": {"ok": True}}).encode()
        ),
    )
    def test_get_builds_query_and_parses_json(self, mocked_open):
        result = FortniteAPIClient(api_key="secret").get("/v2/shop", {"language": "es"})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.payload["data"]["ok"], True)
        request = mocked_open.call_args.args[0]
        self.assertIn("language=es", request.full_url)
        self.assertEqual(request.get_header("X-api-key"), "secret")

    def test_multipart_contains_original_bytes(self):
        body, content_type = _multipart({"chat_id": "123"}, "document", "resultado.json", b"{\"x\":1}", "application/json")
        self.assertIn("multipart/form-data; boundary=", content_type)
        self.assertIn(b"filename=\"resultado.json\"", body)
        self.assertIn(b"{\"x\":1}", body)

    @patch(
        "fortnite_research.transport._open",
        return_value=FakeResponse(json.dumps({"ok": True, "result": {}}).encode()),
    )
    def test_send_photo_posts_utf8_caption_and_public_url(self, mocked_open):
        sender = TelegramDocumentSender("secret", "123")
        result = sender.send_photo(
            "https://fortnite-api.com/images/cosmetics/test.png",
            "🧩 Contenido nuevo: canción",
        )

        self.assertTrue(result["ok"])
        request = mocked_open.call_args.args[0]
        self.assertIn(b"photo=https%3A%2F%2Ffortnite-api.com%2Fimages%2Fcosmetics%2Ftest.png", request.data)
        self.assertIn("%F0%9F%A7%A9", request.data.decode("ascii"))
        self.assertIn("%C3%B3n", request.data.decode("ascii"))

    @patch(
        "fortnite_research.transport._open",
        return_value=FakeResponse(
            json.dumps(
                {
                    "ok": True,
                    "result": [
                        {"message": {"text": "/start", "chat": {"id": 987654321}}}
                    ],
                }
            ).encode()
        ),
    )
    def test_discovers_chat_from_start_without_printing_it(self, mocked_open):
        chat_id = TelegramDocumentSender("secret", None).find_recent_start_chat_id()
        self.assertEqual(chat_id, "987654321")

    @patch(
        "fortnite_research.transport._open",
        return_value=FakeResponse(
            json.dumps(
                {
                    "ok": True,
                    "result": [
                        {
                            "message": {
                                "text": "/stop",
                                "chat": {"id": 987654322, "type": "private"},
                            }
                        }
                    ],
                }
            ).encode()
        ),
    )
    def test_discovers_recent_private_chat_when_start_was_consumed(self, mocked_open):
        chat_id = TelegramDocumentSender("secret", None).find_recent_private_chat_id()
        self.assertEqual(chat_id, "987654322")


if __name__ == "__main__":
    unittest.main()
