import json
import unittest
from unittest.mock import patch

from fortnite_research.client import FortniteAPIClient
from fortnite_research.telegram import TelegramDocumentSender, _multipart


class FakeResponse:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps({"status": 200, "data": {"ok": True}}).encode()


class ClientTests(unittest.TestCase):
    @patch("fortnite_research.client.urlopen", return_value=FakeResponse())
    def test_get_builds_query_and_parses_json(self, mocked_urlopen):
        result = FortniteAPIClient(api_key="secret").get("/v2/shop", {"language": "es"})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.payload["data"]["ok"], True)
        request = mocked_urlopen.call_args.args[0]
        self.assertIn("language=es", request.full_url)
        self.assertEqual(request.get_header("X-api-key"), "secret")

    def test_multipart_contains_original_bytes(self):
        body, content_type = _multipart({"chat_id": "123"}, "document", "resultado.json", b"{\"x\":1}", "application/json")
        self.assertIn("multipart/form-data; boundary=", content_type)
        self.assertIn(b"filename=\"resultado.json\"", body)
        self.assertIn(b"{\"x\":1}", body)

    @patch("fortnite_research.telegram.urlopen", return_value=type("Response", (), {
        "__enter__": lambda self: self,
        "__exit__": lambda self, *args: False,
        "read": lambda self: json.dumps({"ok": True, "result": [
            {"message": {"text": "/start", "chat": {"id": 987654321}}}
        ]}).encode(),
    })())
    def test_discovers_chat_from_start_without_printing_it(self, mocked_urlopen):
        chat_id = TelegramDocumentSender("secret", None).find_recent_start_chat_id()
        self.assertEqual(chat_id, "987654321")

    @patch("fortnite_research.telegram.urlopen", return_value=type("Response", (), {
        "__enter__": lambda self: self,
        "__exit__": lambda self, *args: False,
        "read": lambda self: json.dumps({"ok": True, "result": [
            {"message": {"text": "/stop", "chat": {"id": 987654322, "type": "private"}}}
        ]}).encode(),
    })())
    def test_discovers_recent_private_chat_when_start_was_consumed(self, mocked_urlopen):
        chat_id = TelegramDocumentSender("secret", None).find_recent_private_chat_id()
        self.assertEqual(chat_id, "987654322")


if __name__ == "__main__":
    unittest.main()
