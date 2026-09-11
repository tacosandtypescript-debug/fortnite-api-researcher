"""Configuración segura desde entorno y un archivo .env local."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _read_dotenv(path: Path) -> dict[str, str]:
    """Lee un .env sencillo sin sustituir variables ya presentes en el entorno."""
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            values[key] = value
    return values


def _env(name: str, dotenv: dict[str, str], default: str = "") -> str:
    value = os.environ.get(name)
    if value is not None:
        return value
    return dotenv.get(name, default)


@dataclass(frozen=True)
class Settings:
    api_base_url: str
    api_key: str | None
    api_timeout: float
    telegram_bot_token: str | None
    telegram_chat_id: str | None
    auto_send_telegram: bool
    output_dir: Path

    @classmethod
    def load(cls, root: Path | None = None) -> "Settings":
        project_root = (root or Path.cwd()).resolve()
        dotenv = _read_dotenv(project_root / ".env")
        api_key = _env("FORTNITE_API_KEY", dotenv).strip() or None
        bot_token = _env("TELEGRAM_BOT_TOKEN", dotenv).strip() or None
        chat_id = _env("TELEGRAM_CHAT_ID", dotenv).strip() or None
        timeout_text = _env("FORTNITE_API_TIMEOUT", dotenv, "30").strip()
        try:
            timeout = float(timeout_text)
        except ValueError as exc:
            raise ValueError("FORTNITE_API_TIMEOUT debe ser numérico") from exc
        if timeout <= 0:
            raise ValueError("FORTNITE_API_TIMEOUT debe ser mayor que cero")
        auto_send = _env("AUTO_SEND_TELEGRAM", dotenv, "false").strip().lower()
        return cls(
            api_base_url=_env("FORTNITE_API_BASE_URL", dotenv, "https://fortnite-api.com").rstrip("/"),
            api_key=api_key,
            api_timeout=timeout,
            telegram_bot_token=bot_token,
            telegram_chat_id=chat_id,
            auto_send_telegram=auto_send in {"1", "true", "yes", "si", "sí"},
            output_dir=project_root / "salidas",
        )

