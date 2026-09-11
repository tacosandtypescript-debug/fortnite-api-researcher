"""Entrega de archivos mediante Telegram Bot API sendDocument."""

from __future__ import annotations

import json
import mimetypes
import secrets
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class TelegramError(RuntimeError):
    """Error de configuración o respuesta del Bot API."""


def _multipart(fields: dict[str, str], file_field: str, filename: str, content: bytes, content_type: str) -> tuple[bytes, str]:
    boundary = f"----FortniteResearch{secrets.token_hex(16)}"
    chunks: list[bytes] = []
    for name, value in fields.items():
        chunks.extend([
            f"--{boundary}\r\n".encode(),
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(),
            value.encode("utf-8"),
            b"\r\n",
        ])
    chunks.extend([
        f"--{boundary}\r\n".encode(),
        f'Content-Disposition: form-data; name="{file_field}"; filename="{filename}"\r\n'.encode(),
        f"Content-Type: {content_type}\r\n\r\n".encode(),
        content,
        b"\r\n",
        f"--{boundary}--\r\n".encode(),
    ])
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


class TelegramDocumentSender:
    def __init__(self, bot_token: str | None, chat_id: str | None, timeout: float = 60):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.timeout = timeout

    def find_recent_start_chat_id(self) -> str | None:
        """Obtiene el chat del último /start sin mostrar ni persistir el identificador."""
        if not self.bot_token:
            raise TelegramError("Falta TELEGRAM_BOT_TOKEN")
        url = f"https://api.telegram.org/bot{self.bot_token}/getUpdates"
        request = Request(url, headers={"Accept": "application/json"}, method="GET")
        try:
            with urlopen(request, timeout=self.timeout) as response:
                response_body = response.read().decode("utf-8", errors="replace")
        except HTTPError as exc:
            raise TelegramError(f"Telegram respondió HTTP {exc.code} al leer actualizaciones") from exc
        except URLError as exc:
            raise TelegramError(f"No se pudieron leer las actualizaciones de Telegram: {exc.reason}") from exc
        try:
            result = json.loads(response_body)
        except json.JSONDecodeError as exc:
            raise TelegramError("Telegram devolvió actualizaciones no válidas") from exc
        if not result.get("ok"):
            raise TelegramError(f"Telegram rechazó getUpdates: {result.get('description', 'error desconocido')}")
        for update in reversed(result.get("result", [])):
            message = update.get("message") or update.get("edited_message") or {}
            text = message.get("text") or ""
            chat = message.get("chat") or {}
            if text.startswith("/start") and chat.get("id") is not None:
                return str(chat["id"])
        return None

    def find_recent_private_chat_id(self) -> str | None:
        """Obtiene el chat privado más reciente si el polling ya consumió /start."""
        if not self.bot_token:
            raise TelegramError("Falta TELEGRAM_BOT_TOKEN")
        url = f"https://api.telegram.org/bot{self.bot_token}/getUpdates"
        request = Request(url, headers={"Accept": "application/json"}, method="GET")
        try:
            with urlopen(request, timeout=self.timeout) as response:
                response_body = response.read().decode("utf-8", errors="replace")
        except HTTPError as exc:
            raise TelegramError(f"Telegram respondió HTTP {exc.code} al leer actualizaciones") from exc
        except URLError as exc:
            raise TelegramError(f"No se pudieron leer las actualizaciones de Telegram: {exc.reason}") from exc
        try:
            result = json.loads(response_body)
        except json.JSONDecodeError as exc:
            raise TelegramError("Telegram devolvió actualizaciones no válidas") from exc
        if not result.get("ok"):
            raise TelegramError(f"Telegram rechazó getUpdates: {result.get('description', 'error desconocido')}")
        for update in reversed(result.get("result", [])):
            message = update.get("message") or update.get("edited_message") or {}
            chat = message.get("chat") or {}
            if chat.get("type") == "private" and chat.get("id") is not None:
                return str(chat["id"])
        return None

    def send_document(self, path: Path, caption: str | None = None) -> dict:
        if not self.bot_token or not self.chat_id:
            raise TelegramError("Faltan TELEGRAM_BOT_TOKEN o TELEGRAM_CHAT_ID")
        if not path.is_file():
            raise TelegramError(f"El documento no existe: {path}")
        content = path.read_bytes()
        fields = {"chat_id": self.chat_id}
        if caption:
            fields["caption"] = caption[:1024]
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        body, content_header = _multipart(fields, "document", path.name, content, content_type)
        url = f"https://api.telegram.org/bot{self.bot_token}/sendDocument"
        request = Request(url, data=body, headers={"Content-Type": content_header}, method="POST")
        try:
            with urlopen(request, timeout=self.timeout) as response:
                response_body = response.read().decode("utf-8", errors="replace")
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            raise TelegramError(f"Telegram respondió HTTP {exc.code}: {detail}") from exc
        except URLError as exc:
            raise TelegramError(f"No se pudo conectar con Telegram: {exc.reason}") from exc
        try:
            result = json.loads(response_body)
        except json.JSONDecodeError as exc:
            raise TelegramError("Telegram devolvió una respuesta no válida") from exc
        if not result.get("ok"):
            raise TelegramError(f"Telegram rechazó el documento: {result.get('description', 'error desconocido')}")
        return result
