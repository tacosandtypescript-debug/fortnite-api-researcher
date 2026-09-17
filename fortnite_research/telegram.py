"""Entrega de archivos mediante Telegram Bot API sendDocument."""

from __future__ import annotations

import json
import mimetypes
import secrets
import time
from pathlib import Path
from urllib.parse import urlencode

from .transport import (
    HTTPFetchError,
    fetch,
    redact_secrets,
    retry_after_seconds,
    validate_https_url,
)

# Límite de la Bot API para pies de foto y documentos, contado en unidades
# UTF-16: un emoji ocupa dos, así que se mide y se recorta con esa unidad.
CAPTION_LIMIT = 1024
MESSAGE_LIMIT = 4096
DOCUMENT_LIMIT_BYTES = 49_000_000


class TelegramError(RuntimeError):
    """Error de configuración o respuesta del Bot API."""


def _truncate_utf16(text: str, limit: int) -> str:
    """Recorta el texto para que quepa en ``limit`` unidades UTF-16."""
    if len(text.encode("utf-16-le")) // 2 <= limit:
        return text
    budget = max(limit - 1, 0)
    kept: list[str] = []
    used = 0
    for character in text:
        width = len(character.encode("utf-16-le")) // 2
        if used + width > budget:
            break
        kept.append(character)
        used += width
    return "".join(kept).rstrip() + "…"


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

    def _post_json(
        self,
        endpoint: str,
        body: bytes,
        content_type: str,
        action: str,
    ) -> dict:
        """Publica en la Bot API y valida la respuesta.

        Un HTTP 429 significa que Telegram no procesó la petición, así que se
        reintenta una vez respetando ``Retry-After``. El resto de errores no se
        reintentan para no duplicar mensajes que ya se enviaron.
        """
        if not self.bot_token:
            raise TelegramError("Falta TELEGRAM_BOT_TOKEN")
        url = f"https://api.telegram.org/bot{self.bot_token}/{endpoint}"
        attempt = 0
        while True:
            try:
                response = fetch(
                    url,
                    data=body,
                    headers={"Content-Type": content_type},
                    method="POST",
                    timeout=self.timeout,
                    max_bytes=1_000_000,
                    allowed_hosts={"api.telegram.org"},
                )
            except HTTPFetchError as exc:
                detail = redact_secrets(
                    exc.body.decode("utf-8", errors="replace")[:500]
                )
                if exc.status_code == 429 and attempt == 0:
                    attempt += 1
                    time.sleep(retry_after_seconds(exc.headers) or 1.0)
                    continue
                if exc.status_code is not None:
                    raise TelegramError(
                        f"Telegram respondió HTTP {exc.status_code} al enviar "
                        f"{action}: {detail}"
                    ) from exc
                raise TelegramError(
                    f"No se pudo conectar con Telegram para {action}: {detail}"
                ) from exc
            try:
                result = json.loads(response.body.decode("utf-8", errors="replace"))
            except json.JSONDecodeError as exc:
                raise TelegramError("Telegram devolvió una respuesta no válida") from exc
            if not isinstance(result, dict):
                raise TelegramError("Telegram devolvió un formato de respuesta no válido")
            if not result.get("ok"):
                raise TelegramError(
                    f"Telegram rechazó {action}: "
                    f"{result.get('description', 'error desconocido')}"
                )
            return result

    def _get_updates(self) -> list[dict]:
        if not self.bot_token:
            raise TelegramError("Falta TELEGRAM_BOT_TOKEN")
        url = f"https://api.telegram.org/bot{self.bot_token}/getUpdates"
        try:
            response = fetch(
                url,
                headers={"Accept": "application/json"},
                timeout=self.timeout,
                max_bytes=2_000_000,
                retries=1,
                allowed_hosts={"api.telegram.org"},
            )
        except HTTPFetchError as exc:
            if exc.status_code is not None:
                raise TelegramError(
                    f"Telegram respondió HTTP {exc.status_code} al leer actualizaciones"
                ) from exc
            raise TelegramError(
                "No se pudieron leer las actualizaciones de Telegram"
            ) from exc
        try:
            result = json.loads(response.body.decode("utf-8", errors="replace"))
        except json.JSONDecodeError as exc:
            raise TelegramError("Telegram devolvió actualizaciones no válidas") from exc
        if not isinstance(result, dict):
            raise TelegramError("Telegram devolvió un formato de actualizaciones no válido")
        if not result.get("ok"):
            raise TelegramError(
                f"Telegram rechazó getUpdates: {result.get('description', 'error desconocido')}"
            )
        updates = result.get("result")
        return [update for update in updates if isinstance(update, dict)] if isinstance(updates, list) else []

    def find_recent_start_chat_id(self) -> str | None:
        """Obtiene el chat del último /start sin mostrar ni persistir el identificador."""
        for update in reversed(self._get_updates()):
            message = update.get("message") or update.get("edited_message") or {}
            text = message.get("text") or ""
            chat = message.get("chat") or {}
            if text.startswith("/start") and chat.get("id") is not None:
                return str(chat["id"])
        return None

    def find_recent_private_chat_id(self) -> str | None:
        """Obtiene el chat privado más reciente si el polling ya consumió /start."""
        for update in reversed(self._get_updates()):
            message = update.get("message") or update.get("edited_message") or {}
            chat = message.get("chat") or {}
            if chat.get("type") == "private" and chat.get("id") is not None:
                return str(chat["id"])
        return None

    def send_message(self, text: str) -> dict:
        """Envía un mensaje de texto mediante Telegram Bot API."""
        if not self.bot_token or not self.chat_id:
            raise TelegramError("Faltan TELEGRAM_BOT_TOKEN o TELEGRAM_CHAT_ID")
        if not text or len(text) > MESSAGE_LIMIT:
            raise TelegramError(
                f"El mensaje de Telegram debe tener entre 1 y {MESSAGE_LIMIT} caracteres"
            )
        body = urlencode(
            {
                "chat_id": self.chat_id,
                "text": text,
                "disable_web_page_preview": "true",
            }
        ).encode("utf-8")
        return self._post_json(
            "sendMessage",
            body,
            "application/x-www-form-urlencoded",
            "el mensaje",
        )

    def send_photo(self, photo_url: str, caption: str | None = None) -> dict:
        """Envía una imagen pública por URL y conserva el pie en UTF-8.

        Telegram descarga la imagen directamente desde el CDN. Solo se
        aceptan los hosts de imágenes que devuelven las fuentes de Fortnite;
        así una respuesta manipulada no puede convertir este método en un
        reenviador hacia un destino arbitrario.
        """
        if not self.bot_token or not self.chat_id:
            raise TelegramError("Faltan TELEGRAM_BOT_TOKEN o TELEGRAM_CHAT_ID")
        if not isinstance(photo_url, str) or not photo_url.strip():
            raise TelegramError("La imagen no tiene una URL válida")
        try:
            validate_https_url(
                photo_url,
                allowed_hosts={
                    "fortnite-api.com",
                    "www.fortnite-api.com",
                    "cdn.fortnite-api.com",
                    "cdn-live.prm.ol.epicgames.com",
                    "cdn2.unrealengine.com",
                },
            )
        except ValueError as exc:
            raise TelegramError(f"La URL de imagen no está autorizada: {exc}") from exc
        if caption:
            caption = _truncate_utf16(caption, CAPTION_LIMIT)
        body = urlencode(
            {
                "chat_id": self.chat_id,
                "photo": photo_url,
                **({"caption": caption} if caption else {}),
            }
        ).encode("utf-8")
        return self._post_json(
            "sendPhoto",
            body,
            "application/x-www-form-urlencoded",
            "la imagen",
        )

    def send_document(self, path: Path, caption: str | None = None) -> dict:
        if not self.bot_token or not self.chat_id:
            raise TelegramError("Faltan TELEGRAM_BOT_TOKEN o TELEGRAM_CHAT_ID")
        if not path.is_file():
            raise TelegramError(f"El documento no existe: {path}")
        if path.stat().st_size > DOCUMENT_LIMIT_BYTES:
            raise TelegramError("El documento supera el límite seguro de 49 MB")
        content = path.read_bytes()
        fields = {"chat_id": self.chat_id}
        if caption:
            fields["caption"] = _truncate_utf16(caption, CAPTION_LIMIT)
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        body, content_header = _multipart(fields, "document", path.name, content, content_type)
        return self._post_json("sendDocument", body, content_header, "el documento")
