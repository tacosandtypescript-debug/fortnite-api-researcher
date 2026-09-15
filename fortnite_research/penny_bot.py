"""Monitor de alertas STW de Penny y entrega por Telegram."""

from __future__ import annotations

import hashlib
import json
import sys
import time
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from .client import FortniteAPIClient, FortniteAPIError
from .config import Settings
from .telegram import TelegramDocumentSender, TelegramError
from .transport import HTTPFetchError, fetch, write_text_atomic


class PennyAPIError(RuntimeError):
    """Error al leer los datos públicos de Penny."""


class NewContentAPIError(RuntimeError):
    """Error al leer el feed de contenido añadido recientemente."""


@dataclass(frozen=True)
class VbucksAlert:
    zone: str
    power_level: str
    mission: str
    quantity: int
    modifiers: tuple[str, ...]


@dataclass(frozen=True)
class FreeLlama:
    name: str
    daily_limit: int | None
    weekly_limit: int | None
    monthly_limit: int | None


@dataclass(frozen=True)
class NewContentItem:
    """Elemento que aparece en el feed de cosméticos añadidos recientemente."""

    key: str
    category: str
    item_id: str
    name: str
    item_type: str
    rarity: str
    added: str
    image_url: str = ""


@dataclass(frozen=True)
class NewContentSnapshot:
    build: str
    feed_date: str
    items: tuple[NewContentItem, ...]


@dataclass(frozen=True)
class NewsItem:
    """Anuncio nuevo de un feed de noticias de Fortnite."""

    key: str
    mode: str
    title: str
    body: str
    added: str
    image_url: str = ""


@dataclass(frozen=True)
class NewsSnapshot:
    items: tuple[NewsItem, ...]


@dataclass(frozen=True)
class PennySnapshot:
    reset_date: str
    vbucks: tuple[VbucksAlert, ...]
    free_llamas: tuple[FreeLlama, ...]

    @property
    def has_alerts(self) -> bool:
        return bool(self.vbucks or self.free_llamas)


_ZONE_NAMES_ES = {
    "stonewood": "Bosque Calcinado",
    "plankerton": "Plankerton",
    "canny valley": "Valle Latoso",
    "canny_valley": "Valle Latoso",
    "twine peaks": "Picos Trenzados",
    "twine_peaks": "Picos Trenzados",
    "ventures": "Aventuras",
}

_MISSION_NAMES_ES = {
    "build the radar grid": "Construye la red de radares",
    "deliver the bomb": "Entrega la bomba",
    "destroy the encampments": "Destruye los campamentos",
    "eliminate and collect": "Elimina y recoge",
    "evacuate the shelter": "Evacúa el refugio",
    "fight category 1 storm": "Lucha contra la tormenta de categoría 1",
    "fight category 2 storm": "Lucha contra la tormenta de categoría 2",
    "fight category 3 storm": "Lucha contra la tormenta de categoría 3",
    "fight category 4 storm": "Lucha contra la tormenta de categoría 4",
    "fight the storm": "Lucha contra la tormenta",
    "launch the rocket": "Lanza el cohete",
    "refuel the homebase": "Reabastece la base",
    "repair the shelter": "Repara el refugio",
    "resupply": "Reabastecimiento",
    "retrieve the data": "Recupera los datos",
    "ride the lightning": "Cabalgando el rayo",
    "the portal": "El portal",
}

_MODIFIER_NAMES_ES = {
    "epic mini-boss": "Minijefe épico",
    "epic miniboss": "Minijefe épico",
    "legendary mini-boss": "Minijefe legendario",
    "legendary miniboss": "Minijefe legendario",
    "mini-boss": "Minijefe",
    "miniboss": "Minijefe",
}

_LLAMA_NAMES_ES = {
    "birthday llama": "Llama de cumpleaños",
    "founder's llama": "Llama de fundador",
    "fortnitemares llama": "Llama de Fortnitemares",
    "legendary troll stash llama": "Llama de alijo de troll legendario",
    "mini reward llama": "Mini llama de recompensa",
    "upgrade llama": "Llama de mejora",
}

_CATEGORY_NAMES_ES = {
    "br": "Battle Royale",
    "banners": "Banners",
    "tracks": "Canciones",
    "instruments": "Instrumentos",
    "cars": "Vehículos",
    "lego": "LEGO",
    "legokits": "Lotes de LEGO",
    "beans": "Beans",
}

_TYPE_NAMES_ES = {
    "banner": "Banner",
    "bannericon": "Banner",
    "backpack": "Accesorio mochilero",
    "body": "Carrocería",
    "emote": "Gesto",
    "guitar": "Guitarra",
    "outfit": "Atuendo",
    "pickaxe": "Pico",
    "wrap": "Envoltura",
}

_MODE_NAMES_ES = {
    "br": "Battle Royale",
    "stw": "Salvar el Mundo",
    "creative": "Creativo",
}


def _string(value: Any, default: str = "") -> str:
    if value is None:
        return default
    text = str(value).strip()
    return text or default


def _meaningful_string(value: Any, default: str = "") -> str:
    text = _string(value, default)
    return default if text.casefold() in {"null", "none", "undefined"} else text


def _normalized_text(value: Any) -> str:
    return " ".join(
        _string(value).casefold().replace("‑", "-").split()
    )


def _translated(value: Any, translations: dict[str, str], default: str = "") -> str:
    text = _string(value, default)
    return translations.get(_normalized_text(text), text)


def _localized_value(value: Any, default: str = "") -> str:
    if isinstance(value, dict):
        for key in ("displayValue", "value", "name", "title"):
            candidate = _meaningful_string(value.get(key))
            if candidate:
                return candidate
        return default
    return _meaningful_string(value, default)


def _image_url(record: dict[str, Any]) -> str:
    """Obtiene la primera imagen pública útil que ofrece un registro."""
    candidates: list[Any] = [
        record.get("image"),
        record.get("tileImage"),
        record.get("albumArt"),
    ]
    images = record.get("images")
    if isinstance(images, dict):
        for key in ("featured", "large", "wide", "icon", "small", "smallIcon"):
            candidates.append(images.get(key))
    for candidate in candidates:
        value = _string(candidate)
        if value.startswith("https://"):
            return value
    return ""


def _integer(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _positive_limit(value: Any) -> int | None:
    parsed = _integer(value, default=-1)
    return parsed if parsed > 0 else None


def _zone_label(zone: str) -> str:
    raw = _string(zone, "Zona desconocida")
    return _ZONE_NAMES_ES.get(_normalized_text(raw), raw.replace("_", " ").title())


def _mission_name(mission: dict[str, Any]) -> str:
    mission_type = mission.get("missionType")
    if isinstance(mission_type, dict):
        return _translated(mission_type.get("name"), _MISSION_NAMES_ES, "Misión STW")
    return _translated(mission_type, _MISSION_NAMES_ES, "Misión STW")


def _modifier_names(mission: dict[str, Any]) -> tuple[str, ...]:
    modifiers = mission.get("modifiers")
    if not isinstance(modifiers, list):
        return ()
    names = []
    for modifier in modifiers:
        if isinstance(modifier, dict):
            name = _string(modifier.get("name"))
        else:
            name = _string(modifier)
        if name:
            names.append(_translated(name, _MODIFIER_NAMES_ES, name))
    return tuple(names)


def _is_vbucks_reward(reward: dict[str, Any]) -> bool:
    item_type = _string(reward.get("itemType")).casefold()
    name = _string(reward.get("name")).casefold().replace("‑", "-")
    return (
        item_type == "accountresource:currency_mtxswap"
        or "v-buck" in name
        or "vbucks" in name
    )


def _translate_llama_name(name: str) -> str:
    return _translated(name, _LLAMA_NAMES_ES, name)


def _date_label(value: Any) -> str:
    """Presenta fechas ISO del estado en el formato habitual en español."""
    text = _string(value)
    if not text:
        return "fecha desconocida"
    if isinstance(value, (int, float)) or text.isdigit():
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc).strftime(
                "%d/%m/%Y %H:%M UTC"
            )
        except (TypeError, ValueError, OverflowError, OSError):
            return text
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return text
    if parsed.tzinfo is not None and ("T" in text or "+" in text):
        return parsed.strftime("%d/%m/%Y %H:%M UTC")
    return parsed.strftime("%d/%m/%Y")


def _new_content_key(category: str, record: dict[str, Any]) -> str:
    item_id = _string(record.get("id"))
    added = _string(record.get("added"))
    if added:
        return f"{category}:{item_id}:{added}"
    return f"{category}:{item_id}:{_string(record.get('name'), 'sin-nombre')}"


def _new_content_items(data: dict[str, Any]) -> tuple[NewContentItem, ...]:
    items = data.get("items")
    if not isinstance(items, dict):
        raise NewContentAPIError("Fortnite-API.com no devolvió el catálogo de novedades esperado")
    result: list[NewContentItem] = []
    seen: set[str] = set()
    for category, records in items.items():
        if not isinstance(records, list):
            continue
        category_name = _string(category).strip()
        if not category_name:
            continue
        for record in records:
            if not isinstance(record, dict):
                continue
            item_id = _meaningful_string(record.get("id"))
            name = _meaningful_string(record.get("name") or record.get("title"))
            if not item_id or not name:
                continue
            key = _new_content_key(category_name, record)
            if key in seen:
                continue
            seen.add(key)
            result.append(
                NewContentItem(
                    key=key,
                    category=category_name,
                    item_id=item_id,
                    name=name,
                    item_type=_translated(
                        _localized_value(record.get("type")),
                        _TYPE_NAMES_ES,
                    ),
                    rarity=_localized_value(record.get("rarity")),
                    added=_meaningful_string(record.get("added")),
                    image_url=_image_url(record),
                )
            )
    result.sort(key=lambda item: (item.added, item.category, item.item_id), reverse=True)
    return tuple(result)


def _news_key(mode: str, record: dict[str, Any]) -> str:
    material = json.dumps(
        {
            "id": _meaningful_string(record.get("id")),
            "title": _meaningful_string(record.get("title")),
            "body": _meaningful_string(record.get("body")),
            "image": _image_url(record),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    digest = hashlib.sha256(material).hexdigest()[:20]
    return f"news:{mode}:{digest}"


def _news_items(data: dict[str, Any], mode: str) -> tuple[NewsItem, ...]:
    records = data.get("motds")
    if not isinstance(records, list):
        records = data.get("messages")
    if not isinstance(records, list):
        raise NewContentAPIError(
            f"Fortnite-API.com no devolvió noticias válidas para {mode}"
        )
    feed_date = _meaningful_string(data.get("date"))
    result: list[NewsItem] = []
    seen: set[str] = set()
    for record in records:
        if not isinstance(record, dict) or record.get("hidden") is True:
            continue
        title = _meaningful_string(record.get("title") or record.get("tabTitle"))
        body = _meaningful_string(record.get("body"))
        if not title and not body:
            continue
        key = _news_key(mode, record)
        if key in seen:
            continue
        seen.add(key)
        result.append(
            NewsItem(
                key=key,
                mode=mode,
                title=title or "Anuncio de Fortnite",
                body=body,
                added=feed_date,
                image_url=_image_url(record),
            )
        )
    result.sort(key=lambda item: (item.added, item.mode, item.key), reverse=True)
    return tuple(result)


def _iter_zone_missions(payload: dict[str, Any]) -> Iterable[tuple[str, dict[str, Any]]]:
    missions = payload.get("missions")
    if not isinstance(missions, dict):
        raise PennyAPIError("Penny no devolvió el objeto missions esperado")
    for zone, entries in missions.items():
        if not isinstance(entries, list):
            continue
        for mission in entries:
            if isinstance(mission, dict):
                yield _zone_label(_string(zone, "Zona desconocida")), mission


def _free_llamas(payload: dict[str, Any]) -> tuple[FreeLlama, ...]:
    storefronts = payload.get("storefronts")
    if not isinstance(storefronts, dict):
        return ()
    entries = storefronts.get("llamas_storefront")
    if not isinstance(entries, list):
        return ()
    llamas = []
    for entry in entries:
        if not isinstance(entry, dict) or _integer(entry.get("price"), default=-1) != 0:
            continue
        llamas.append(
            FreeLlama(
                name=_translate_llama_name(_string(entry.get("name"), "Llama gratis")),
                daily_limit=_positive_limit(entry.get("dailyLimit")),
                weekly_limit=_positive_limit(entry.get("weeklyLimit")),
                monthly_limit=_positive_limit(entry.get("monthlyLimit")),
            )
        )
    return tuple(sorted(llamas, key=lambda item: item.name.casefold()))


class PennyClient:
    """Cliente pequeño y de solo lectura para los endpoints públicos de Penny."""

    def __init__(self, base_url: str = "https://pennydb.net", timeout: float = 30):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _get_json(self, path: str) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        try:
            response = fetch(
                url,
                headers={
                    "Accept": "application/json",
                    "User-Agent": "fortnite-api-researcher-penny-bot/0.1",
                },
                timeout=self.timeout,
                max_bytes=20_000_000,
                retries=2,
                allowed_hosts={"pennydb.net", "beta.pennydb.net"},
            )
        except HTTPFetchError as exc:
            raise PennyAPIError(
                f"Penny respondió con un error HTTP/transporte ({exc.status_code or 'sin estado'})"
            ) from exc
        try:
            payload = json.loads(response.body.decode("utf-8", errors="replace"))
        except json.JSONDecodeError as exc:
            raise PennyAPIError("Penny devolvió JSON no válido") from exc
        if not isinstance(payload, dict):
            raise PennyAPIError("Penny devolvió un formato no válido")
        return payload

    def snapshot(self) -> PennySnapshot:
        missions_payload = self._get_json("/api")
        shop_payload = self._get_json("/api/stw-shop")
        vbucks = []
        for zone, mission in _iter_zone_missions(missions_payload):
            rewards = mission.get("alertRewards")
            if not isinstance(rewards, list):
                continue
            for reward in rewards:
                if not isinstance(reward, dict) or not _is_vbucks_reward(reward):
                    continue
                vbucks.append(
                    VbucksAlert(
                        zone=zone,
                        power_level=_string(mission.get("pl"), "?"),
                        mission=_mission_name(mission),
                        quantity=max(0, _integer(reward.get("quantity"), default=0)),
                        modifiers=_modifier_names(mission),
                    )
                )
        vbucks.sort(
            key=lambda item: (
                item.zone.casefold(),
                item.power_level,
                item.mission.casefold(),
                item.quantity,
            )
        )
        return PennySnapshot(
            reset_date=datetime.now(timezone.utc).date().isoformat(),
            vbucks=tuple(vbucks),
            free_llamas=_free_llamas(shop_payload),
        )


class NewContentClient:
    """Consulta las novedades de catálogo que la API expone como contenido nuevo.

    Fortnite-API.com denomina a esta ruta ``New Cosmetics``. El bot la trata
    como señal de contenido recién añadido al catálogo, no como una promesa de
    que cada registro sea una novedad jugable o una salida en la tienda.
    """

    def __init__(self, client: FortniteAPIClient, language: str = "es"):
        self.client = client
        self.language = language

    def snapshot(self) -> NewContentSnapshot:
        result = self.client.get("/v2/cosmetics/new", {"language": self.language})
        payload = result.payload
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, dict):
            raise NewContentAPIError(
                "Fortnite-API.com no devolvió el objeto data de novedades esperado"
            )
        return NewContentSnapshot(
            build=_string(data.get("build"), "compilación desconocida"),
            feed_date=_string(data.get("date")),
            items=_new_content_items(data),
        )


class NewsClient:
    """Consulta anuncios de BR y STW para eventos, torneos y noticias."""

    def __init__(
        self,
        client: FortniteAPIClient,
        language: str = "es",
        kinds: Iterable[str] = ("br", "stw"),
    ):
        self.client = client
        self.language = language
        self.kinds = tuple(kinds)

    def snapshot(self) -> NewsSnapshot:
        items: list[NewsItem] = []
        for kind in self.kinds:
            result = self.client.get(f"/v2/news/{kind}", {"language": self.language})
            payload = result.payload
            data = payload.get("data") if isinstance(payload, dict) else None
            if not isinstance(data, dict):
                raise NewContentAPIError(
                    f"Fortnite-API.com no devolvió el objeto data de noticias de {kind}"
                )
            items.extend(_news_items(data, kind))
        return NewsSnapshot(tuple(items))


def _snapshot_payload(snapshot: PennySnapshot) -> dict[str, Any]:
    return {
        "reset_date": snapshot.reset_date,
        "vbucks": [asdict(item) for item in snapshot.vbucks],
        "free_llamas": [asdict(item) for item in snapshot.free_llamas],
    }


def snapshot_fingerprint(snapshot: PennySnapshot) -> str:
    encoded = json.dumps(
        _snapshot_payload(snapshot),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def format_alert_message(
    snapshot: PennySnapshot,
    *,
    checked_at: datetime | None = None,
) -> str:
    lines = [f"🚨 Alertas de Salvar el Mundo — {_date_label(snapshot.reset_date)}"]
    if checked_at is not None:
        lines.append(f"Comprobado: {_utc_label(checked_at)}")
    lines.append("")
    if snapshot.vbucks:
        lines.append("💰 Misiones de pavos")
        for alert in snapshot.vbucks:
            line = (
                f"• {alert.quantity} pavos — {alert.zone} · PL {alert.power_level} · "
                f"{alert.mission}"
            )
            if alert.modifiers:
                line += f" · {', '.join(alert.modifiers)}"
            lines.append(line)
        lines.append("")
    if snapshot.free_llamas:
        lines.append("🦙 Llamas gratis")
        for llama in snapshot.free_llamas:
            limits = []
            if llama.daily_limit is not None:
                limits.append(f"diaria: {llama.daily_limit}")
            if llama.weekly_limit is not None:
                limits.append(f"semanal: {llama.weekly_limit}")
            if llama.monthly_limit is not None:
                limits.append(f"mensual: {llama.monthly_limit}")
            suffix = f" ({'; '.join(limits)})" if limits else ""
            lines.append(f"• {llama.name} — gratis{suffix}")
        lines.append("")
    lines.append("Fuente de alertas: PennyDB (pennydb.net)")
    return "\n".join(lines)


def _category_label(category: str) -> str:
    return _CATEGORY_NAMES_ES.get(_normalized_text(category), category)


def _added_label(value: str) -> str:
    if not value:
        return ""
    return _date_label(value)


def format_new_content_message(
    snapshot: NewContentSnapshot,
    items: Iterable[NewContentItem],
    *,
    initial: bool = False,
    build_changed: bool = False,
    previous_build: str = "",
) -> str:
    """Construye un aviso breve y siempre localizado en español."""
    selected = tuple(items)
    lines = ["🧩 Contenido nuevo detectado", ""]
    if initial:
        lines.append(
            "Se ha activado la vigilancia de contenido añadido recientemente. "
            f"El feed contiene {len(selected)} entrada(s) reciente(s)."
        )
    elif selected:
        lines.append(
            f"Se han detectado {len(selected)} elemento(s) nuevo(s) en el catálogo."
        )
    if build_changed:
        lines.append(
            f"Nueva compilación: {previous_build or 'desconocida'} → {snapshot.build}."
        )
    elif snapshot.build:
        lines.append(f"Compilación: {snapshot.build}")

    if selected:
        counts = Counter(_category_label(item.category) for item in selected)
        summary = ", ".join(
            f"{category}: {count}" for category, count in sorted(counts.items())
        )
        lines.append(f"Categorías: {summary}.")
        lines.append("")
        lines.append("Últimas entradas:")
        # Un único mensaje debe caber en sendMessage; el total se conserva
        # aunque el detalle se limite para no superar los 4096 caracteres.
        max_details = 24
        for item in selected[:max_details]:
            details = [f"• {_category_label(item.category)}: {item.name}"]
            if item.item_type:
                details.append(item.item_type)
            if item.rarity:
                details.append(item.rarity)
            if item.added:
                details.append(_added_label(item.added))
            lines.append(" — ".join((details[0], ", ".join(details[1:]))) if len(details) > 1 else details[0])
        if len(selected) > max_details:
            lines.append(f"• … y {len(selected) - max_details} entrada(s) más.")
    elif build_changed:
        lines.append(
            "La API ha cambiado de compilación, pero todavía no muestra "
            "elementos nuevos en este listado."
        )
    lines.extend(
        [
            "",
            "Fuente de novedades: Fortnite-API.com /v2/cosmetics/new",
        ]
    )
    return "\n".join(lines)


def _parse_utc_timestamp(value: Any) -> datetime | None:
    text = _string(value)
    if not text:
        return None
    if isinstance(value, (int, float)) or text.isdigit():
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
        except (TypeError, ValueError, OverflowError, OSError):
            return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _fresh_items(
    items: Iterable[NewContentItem | NewsItem],
    *,
    now: datetime,
    max_age_hours: float,
) -> tuple[NewContentItem | NewsItem, ...]:
    """Devuelve solo entradas fechadas dentro de la ventana notificable.

    No se considera válida una fecha que no se pueda interpretar. Una pequeña
    tolerancia futura absorbe diferencias de reloj entre el servidor y este
    equipo sin permitir que el feed se adelante indefinidamente.
    """
    if max_age_hours <= 0:
        raise ValueError("max_age_hours debe ser mayor que cero")
    current = now.astimezone(timezone.utc)
    oldest = current - timedelta(hours=max_age_hours)
    newest = current + timedelta(minutes=5)
    return tuple(
        item
        for item in items
        if (
            (added := _parse_utc_timestamp(item.added)) is not None
            and oldest <= added <= newest
        )
    )


def _utc_label(value: datetime) -> str:
    return _date_label(value.astimezone(timezone.utc).isoformat())


def format_new_content_caption(
    item: NewContentItem,
    *,
    build: str,
    checked_at: datetime,
) -> str:
    """Construye el pie conciso que acompaña a una imagen de catálogo."""
    lines = [
        "🧩 Contenido nuevo detectado",
        f"Nombre: {item.name}",
        f"Categoría: {_category_label(item.category)}",
    ]
    if item.item_type:
        lines.append(f"Tipo: {item.item_type}")
    if item.rarity:
        lines.append(f"Rareza: {item.rarity}")
    lines.extend(
        [
            f"Añadido: {_added_label(item.added) or 'fecha no válida'}",
            f"Comprobado: {_utc_label(checked_at)}",
            f"ID: {item.item_id}",
            f"Compilación: {build or 'desconocida'}",
            "Fuente: Fortnite-API.com /v2/cosmetics/new",
        ]
    )
    return "\n".join(lines)


def format_news_caption(item: NewsItem, *, checked_at: datetime) -> str:
    """Construye el pie en español para un anuncio con imagen."""
    lines = [
        "📰 Novedad de Fortnite",
        f"{item.title}",
        f"Modo: {_MODE_NAMES_ES.get(item.mode, item.mode)}",
        f"Fecha del feed: {_date_label(item.added) or 'fecha no válida'}",
        f"Comprobado: {_utc_label(checked_at)}",
    ]
    if item.body:
        body = " ".join(item.body.split())
        if len(body) > 650:
            body = body[:647].rstrip() + "…"
        lines.extend(["", body])
    lines.extend(["", "Fuente: Fortnite-API.com /v2/news"])
    return "\n".join(lines)


def _load_state(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _save_state(
    path: Path,
    snapshot: PennySnapshot,
    fingerprint: str,
    *,
    previous_state: dict[str, Any] | None = None,
    new_content: NewContentSnapshot | None = None,
    seen_new_content: Iterable[str] | None = None,
    news: NewsSnapshot | None = None,
    seen_news: Iterable[str] | None = None,
) -> None:
    payload = {
        "reset_date": snapshot.reset_date,
        "fingerprint": fingerprint,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    if isinstance(previous_state, dict):
        for state_key in ("new_content", "news"):
            existing_value = previous_state.get(state_key)
            if isinstance(existing_value, dict):
                payload[state_key] = existing_value
    if new_content is not None and seen_new_content is not None:
        payload["new_content"] = {
            "build": new_content.build,
            "seen_keys": sorted(set(seen_new_content)),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
    if news is not None and seen_news is not None:
        payload["news"] = {
            "seen_keys": sorted(set(seen_news)),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
    write_text_atomic(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def _new_content_state(state: dict[str, Any]) -> tuple[set[str], str, bool]:
    value = state.get("new_content")
    if not isinstance(value, dict):
        return set(), "", False
    raw_keys = value.get("seen_keys")
    keys = {
        _string(item)
        for item in raw_keys
        if _string(item)
    } if isinstance(raw_keys, list) else set()
    return keys, _string(value.get("build")), True


def _news_state(state: dict[str, Any]) -> tuple[set[str], bool]:
    value = state.get("news")
    if not isinstance(value, dict):
        return set(), False
    raw_keys = value.get("seen_keys")
    keys = {
        _string(item)
        for item in raw_keys
        if _string(item)
    } if isinstance(raw_keys, list) else set()
    return keys, True


def _sleep_interruptibly(seconds: float) -> None:
    deadline = time.monotonic() + seconds
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        time.sleep(min(60.0, remaining))


def _console_print(value: str) -> None:
    """Evita que una consola Windows con codificación antigua rompa el bot."""
    try:
        print(value)
    except UnicodeEncodeError:
        encoding = sys.stdout.encoding or "ascii"
        print(value.encode(encoding, errors="replace").decode(encoding))


def _deliver_notification(
    sender: TelegramDocumentSender | None,
    *,
    caption: str,
    image_url: str = "",
    dry_run: bool,
) -> None:
    """Envía una foto con pie o conserva un aviso de texto si no hay imagen."""
    if dry_run:
        _console_print(caption)
        if image_url:
            _console_print(f"Imagen: {image_url}")
        return
    assert sender is not None
    if image_url:
        try:
            sender.send_photo(image_url, caption)
            return
        except TelegramError as exc:
            _console_print(f"AVISO: no se pudo enviar la imagen; se envía el texto ({exc})")
            caption = f"{caption}\n\n🖼️ Imagen no disponible en este momento."
    sender.send_message(caption)


def run_penny_bot(
    settings: Settings,
    *,
    interval: float | None = None,
    once: bool = False,
    dry_run: bool = False,
) -> int:
    """Ejecuta el monitor hasta Ctrl+C o una sola lectura con ``once``."""
    poll_interval = settings.penny_poll_interval if interval is None else interval
    if poll_interval <= 0:
        raise ValueError("El intervalo de Penny debe ser mayor que cero")
    if not dry_run and (not settings.telegram_bot_token or not settings.telegram_chat_id):
        raise TelegramError("Faltan TELEGRAM_BOT_TOKEN o TELEGRAM_CHAT_ID")

    client = PennyClient(settings.penny_api_base_url, settings.api_timeout)
    api_client = FortniteAPIClient(
        settings.api_base_url,
        settings.api_key,
        settings.api_timeout,
        trusted_api_hosts=settings.api_trusted_hosts,
    )
    new_content_client = NewContentClient(api_client, language="es")
    news_client = NewsClient(api_client, language="es")
    sender = (
        TelegramDocumentSender(
            settings.telegram_bot_token,
            settings.telegram_chat_id,
            timeout=max(settings.api_timeout, 30),
        )
        if not dry_run
        else None
    )
    state_path = settings.output_dir / "penny-alert-state.json"
    _console_print(
        f"Penny bot activo; consulta cada {poll_interval:g}s; "
        f"fuentes {settings.penny_api_base_url}/api y "
        f"{settings.api_base_url}/v2/cosmetics/new?language=es, "
        f"/v2/news/br?language=es y /v2/news/stw?language=es; "
        f"ventana de novedades: {settings.new_content_max_age_hours:g}h"
    )
    try:
        while True:
            try:
                snapshot = client.snapshot()
                fingerprint = snapshot_fingerprint(snapshot)
                state = _load_state(state_path)
                checked_at = datetime.now(timezone.utc)

                new_content: NewContentSnapshot | None = None
                try:
                    new_content = new_content_client.snapshot()
                except (FortniteAPIError, NewContentAPIError) as exc:
                    # Penny debe seguir funcionando aunque la API de novedades
                    # esté temporalmente caída o rechace una API key opcional.
                    _console_print(f"ERROR DE NOVEDADES: {exc}")

                news: NewsSnapshot | None = None
                try:
                    news = news_client.snapshot()
                except (FortniteAPIError, NewContentAPIError) as exc:
                    _console_print(f"ERROR DE NOTICIAS: {exc}")

                pending: list[tuple[str, str]] = []
                if snapshot.has_alerts and state.get("fingerprint") != fingerprint:
                    pending.append(
                        (
                            format_alert_message(snapshot, checked_at=checked_at),
                            "",
                        )
                    )

                seen_keys, previous_build, has_content_state = _new_content_state(state)
                fresh_content: tuple[NewContentItem, ...] = ()
                unseen_items: tuple[NewContentItem, ...] = ()
                if new_content is not None:
                    fresh_content = tuple(
                        item
                        for item in _fresh_items(
                            new_content.items,
                            now=checked_at,
                            max_age_hours=settings.new_content_max_age_hours,
                        )
                        if isinstance(item, NewContentItem)
                    )
                    if has_content_state:
                        unseen_items = tuple(
                            item for item in fresh_content if item.key not in seen_keys
                        )
                    else:
                        # La primera consulta solo registra lo que ya existe.
                        # Así la instalación no reenvía cientos de entradas
                        # antiguas que el feed conserva como historial reciente.
                        _console_print(
                            f"LÍNEA BASE DE CONTENIDO: {len(new_content.items)} entradas registradas; "
                            "no se reenvían datos existentes"
                        )
                    for item in unseen_items:
                        pending.append(
                            (
                                format_new_content_caption(
                                    item,
                                    build=new_content.build,
                                    checked_at=checked_at,
                                ),
                                item.image_url,
                            )
                        )

                seen_news, has_news_state = _news_state(state)
                fresh_news: tuple[NewsItem, ...] = ()
                unseen_news: tuple[NewsItem, ...] = ()
                if news is not None:
                    fresh_news = tuple(
                        item
                        for item in _fresh_items(
                            news.items,
                            now=checked_at,
                            max_age_hours=settings.new_content_max_age_hours,
                        )
                        if isinstance(item, NewsItem)
                    )
                    if has_news_state:
                        unseen_news = tuple(
                            item for item in fresh_news if item.key not in seen_news
                        )
                    else:
                        _console_print(
                            f"LÍNEA BASE DE NOTICIAS: {len(news.items)} anuncios registrados; "
                            "no se reenvían datos existentes"
                        )
                    for item in unseen_news:
                        pending.append(
                            (
                                format_news_caption(item, checked_at=checked_at),
                                item.image_url,
                            )
                        )

                if pending:
                    for caption, image_url in pending:
                        _deliver_notification(
                            sender,
                            caption=caption,
                            image_url=image_url,
                            dry_run=dry_run,
                        )
                    _console_print(
                        "SIMULACIÓN: avisos preparados"
                        if dry_run
                        else f"AVISOS ENVIADOS POR TELEGRAM: {len(pending)}"
                    )
                elif not snapshot.has_alerts and not unseen_items and not unseen_news:
                    _console_print(
                        f"[{snapshot.reset_date}] Sin alertas de pavos ni llamas gratis; "
                        "sin novedades recientes"
                    )
                else:
                    _console_print(f"[{snapshot.reset_date}] Sin cambios")

                if not dry_run:
                    next_seen = set(seen_keys)
                    if new_content is not None:
                        next_seen.update(item.key for item in new_content.items)
                    next_seen_news = set(seen_news)
                    if news is not None:
                        next_seen_news.update(item.key for item in news.items)
                    _save_state(
                        state_path,
                        snapshot,
                        fingerprint,
                        previous_state=state,
                        new_content=new_content,
                        seen_new_content=next_seen if new_content is not None else None,
                        news=news,
                        seen_news=next_seen_news if news is not None else None,
                    )
            except (PennyAPIError, TelegramError, OSError) as exc:
                _console_print(f"ERROR DEL BOT: {exc}")
                if once:
                    return 1
            if once:
                return 0
            _sleep_interruptibly(poll_interval)
    except KeyboardInterrupt:
        _console_print("Penny bot detenido")
        return 0
