"""Configuración segura desde entorno y un archivo .env local."""

from __future__ import annotations

import math
import os
import re
from dataclasses import dataclass
from pathlib import Path

from .transport import validate_https_url

# Formatos aceptados para las credenciales de Telegram. Se validan al cargar
# para que un token mal copiado falle con un mensaje claro en vez de con un 401
# de la Bot API a mitad de una ejecución.
_TELEGRAM_TOKEN_RE = re.compile(r"^\d{5,}:[A-Za-z0-9_-]{20,}$")
_TELEGRAM_CHAT_ID_RE = re.compile(r"^(?:-?\d{1,20}|@[A-Za-z0-9_]{5,32})$")


def _read_dotenv(path: Path) -> dict[str, str]:
    """Lee un .env sencillo sin sustituir variables ya presentes en el entorno."""
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if value[:1] in {'"', "'"}:
            quote = value[0]
            end = value.find(quote, 1)
            if end != -1:
                value = value[1:end]
        else:
            # Un '#' precedido de espacio abre un comentario al final de línea.
            comment = value.find("#")
            if comment > 0 and value[comment - 1].isspace():
                value = value[:comment].rstrip()
        if key:
            values[key] = value
    return values


def _env(name: str, dotenv: dict[str, str], default: str = "") -> str:
    value = os.environ.get(name)
    if value is not None:
        return value
    return dotenv.get(name, default)


def _project_root(root: Path | None) -> Path:
    if root is not None:
        return root.resolve()
    current = Path.cwd().resolve()
    candidates = [current, *current.parents, Path(__file__).resolve().parents[1]]
    for candidate in candidates:
        if (candidate / "pyproject.toml").is_file():
            return candidate
    return current


def _parse_hosts(value: str) -> tuple[str, ...]:
    hosts = tuple(
        item.strip().casefold()
        for item in value.split(",")
        if item.strip()
    )
    if not hosts:
        raise ValueError("FORTNITE_API_TRUSTED_HOSTS no puede estar vacío")
    for host in hosts:
        if "/" in host or ":" in host or "://" in host:
            raise ValueError(
                "FORTNITE_API_TRUSTED_HOSTS debe contener solo hostnames separados por comas"
            )
    return tuple(dict.fromkeys(hosts))


def _parse_bool(name: str, value: str) -> bool:
    normalized = value.strip().casefold()
    if normalized in {"1", "true", "yes", "si", "sí", "on"}:
        return True
    if normalized in {"0", "false", "no", "off", ""}:
        return False
    raise ValueError(f"{name} debe ser true/false")


def _parse_positive_float(name: str, value: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise ValueError(f"{name} debe ser numérico") from exc
    if parsed <= 0 or not math.isfinite(parsed):
        raise ValueError(f"{name} debe ser mayor que cero")
    return parsed


def _validate_telegram_token(value: str) -> str:
    if not _TELEGRAM_TOKEN_RE.match(value):
        raise ValueError(
            "TELEGRAM_BOT_TOKEN no tiene el formato esperado "
            "(ejemplo: 123456789:AAH...); revisa que la copia esté completa"
        )
    return value


def _validate_telegram_chat_id(value: str) -> str:
    if not _TELEGRAM_CHAT_ID_RE.match(value):
        raise ValueError(
            "TELEGRAM_CHAT_ID debe ser un identificador numérico (por ejemplo "
            "-1001234567890) o un @usuario de canal"
        )
    return value


@dataclass(frozen=True)
class Settings:
    api_base_url: str
    api_key: str | None
    api_timeout: float
    telegram_bot_token: str | None
    telegram_chat_id: str | None
    auto_send_telegram: bool
    output_dir: Path
    api_trusted_hosts: tuple[str, ...] = ("fortnite-api.com", "www.fortnite-api.com")
    telegram_allow_chat_discovery: bool = False
    penny_api_base_url: str = "https://pennydb.net"
    penny_poll_interval: float = 600.0
    new_content_max_age_hours: float = 24.0

    @classmethod
    def load(cls, root: Path | None = None) -> "Settings":
        project_root = _project_root(root)
        dotenv = _read_dotenv(project_root / ".env")
        api_key = _env("FORTNITE_API_KEY", dotenv).strip() or None
        bot_token = _env("TELEGRAM_BOT_TOKEN", dotenv).strip() or None
        chat_id = _env("TELEGRAM_CHAT_ID", dotenv).strip() or None
        if bot_token:
            bot_token = _validate_telegram_token(bot_token)
        if chat_id:
            chat_id = _validate_telegram_chat_id(chat_id)
        timeout = _parse_positive_float(
            "FORTNITE_API_TIMEOUT",
            _env("FORTNITE_API_TIMEOUT", dotenv, "30").strip(),
        )
        api_base_url = _env(
            "FORTNITE_API_BASE_URL",
            dotenv,
            "https://fortnite-api.com",
        ).strip().rstrip("/")
        api_host = validate_https_url(api_base_url)
        trusted_hosts = _parse_hosts(
            _env(
                "FORTNITE_API_TRUSTED_HOSTS",
                dotenv,
                "fortnite-api.com,www.fortnite-api.com",
            )
        )
        if api_key and api_host not in trusted_hosts:
            raise ValueError(
                "La API key solo se enviará a un hostname incluido en "
                "FORTNITE_API_TRUSTED_HOSTS"
            )
        auto_send = _parse_bool(
            "AUTO_SEND_TELEGRAM",
            _env("AUTO_SEND_TELEGRAM", dotenv, "false"),
        )
        allow_chat_discovery = _parse_bool(
            "TELEGRAM_ALLOW_CHAT_DISCOVERY",
            _env("TELEGRAM_ALLOW_CHAT_DISCOVERY", dotenv, "false"),
        )
        if auto_send and allow_chat_discovery:
            raise ValueError(
                "AUTO_SEND_TELEGRAM=true no puede combinarse con "
                "TELEGRAM_ALLOW_CHAT_DISCOVERY=true: el envío automático acabaría "
                "eligiendo el chat por descubrimiento. Define TELEGRAM_CHAT_ID o "
                "desactiva una de las dos opciones"
            )
        penny_api_base_url = _env(
            "PENNY_API_BASE_URL",
            dotenv,
            "https://pennydb.net",
        ).strip().rstrip("/")
        validate_https_url(
            penny_api_base_url,
            allowed_hosts={"pennydb.net", "beta.pennydb.net"},
        )
        penny_poll_interval = _parse_positive_float(
            "PENNY_POLL_INTERVAL_SECONDS",
            _env("PENNY_POLL_INTERVAL_SECONDS", dotenv, "600").strip(),
        )
        new_content_max_age_hours = _parse_positive_float(
            "PENNY_NEW_CONTENT_MAX_AGE_HOURS",
            _env("PENNY_NEW_CONTENT_MAX_AGE_HOURS", dotenv, "24").strip(),
        )
        output_text = _env("FORTNITE_OUTPUT_DIR", dotenv, "salidas").strip()
        output_dir = Path(output_text or "salidas")
        if not output_dir.is_absolute():
            output_dir = project_root / output_dir
        return cls(
            api_base_url=api_base_url,
            api_key=api_key,
            api_timeout=timeout,
            telegram_bot_token=bot_token,
            telegram_chat_id=chat_id,
            auto_send_telegram=auto_send,
            output_dir=output_dir,
            api_trusted_hosts=trusted_hosts,
            telegram_allow_chat_discovery=allow_chat_discovery,
            penny_api_base_url=penny_api_base_url,
            penny_poll_interval=penny_poll_interval,
            new_content_max_age_hours=new_content_max_age_hours,
        )

