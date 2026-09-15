import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.error import URLError

from fortnite_research.transport import (
    ResponseTooLargeError,
    atomic_zipfile,
    fetch,
    validate_https_url,
    write_text_atomic,
)
from fortnite_research.schedule_assets import _download_image


class FakeResponse:
    status = 200
    headers = {}

    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self, size=-1):
        return self.body if size < 0 else self.body[:size]


class TransportTests(unittest.TestCase):
    def test_retries_transient_transport_error(self):
        with patch(
            "fortnite_research.transport._open",
            side_effect=[URLError("temporary"), FakeResponse(b"ok")],
        ), patch("fortnite_research.transport.time.sleep") as sleep:
            response = fetch(
                "https://example.test/data",
                allowed_hosts={"example.test"},
                retries=1,
            )
        self.assertEqual(response.body, b"ok")
        sleep.assert_called_once()

    def test_rejects_oversized_response(self):
        response = FakeResponse(b"1234")
        with patch("fortnite_research.transport._open", return_value=response):
            with self.assertRaises(ResponseTooLargeError):
                fetch(
                    "https://example.test/data",
                    allowed_hosts={"example.test"},
                    max_bytes=3,
                )

    def test_validates_https_and_host(self):
        with self.assertRaises(ValueError):
            validate_https_url("http://example.test")
        with self.assertRaises(ValueError):
            validate_https_url(
                "https://other.test",
                allowed_hosts={"example.test"},
            )

    def test_atomic_text_write_creates_parent_and_content(self):
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "nested" / "result.txt"
            write_text_atomic(destination, "resultado")
            self.assertEqual(destination.read_text(encoding="utf-8"), "resultado")
            self.assertEqual(list(destination.parent.glob("*.tmp")), [])

    def test_image_download_preserves_observed_http_status(self):
        png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
        response = SimpleNamespace(
            status_code=206,
            headers={"Content-Type": "image/png"},
            body=png,
        )
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "image.png"
            with patch("fortnite_research.schedule_assets.fetch", return_value=response):
                result = _download_image("https://cdn.example.test/image.png", destination, 5)
        self.assertEqual(result["httpStatus"], 206)
        self.assertTrue(result["downloaded"])

    def test_atomic_zip_is_published_after_writer_closes(self):
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "nested" / "result.zip"
            with atomic_zipfile(destination) as archive:
                archive.writestr("result.txt", "ok")
            import zipfile

            with zipfile.ZipFile(destination) as archive:
                self.assertEqual(archive.read("result.txt"), b"ok")
            self.assertEqual(list(destination.parent.glob("*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
