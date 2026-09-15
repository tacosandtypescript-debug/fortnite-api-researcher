"""Investigacion profunda y entrega de recursos de la Weezy Icon Cup.

Este modulo amplía la primera consulta de la Icon Cup. La API puede publicar
los cosméticos por tandas: por eso conserva la hora ``added`` de cada registro,
revisa todas las categorías de ``/v2/cosmetics/new`` y descarga también las
variantes, las canciones de Festival y el instrumento asociado.

El expediente separa cuidadosamente:

* evidencia del post comunitario de la copa;
* datos actuales de Fortnite-API.com;
* páginas públicas oficiales de Epic;
* inferencias y rumores que todavía no son un reglamento del torneo.

No se guardan API keys, tokens de Telegram ni chat IDs en el snapshot.
"""

from __future__ import annotations

import json
import shutil
import tempfile
import urllib.parse
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .client import FortniteAPIClient, FortniteAPIError
from .icon_cup_research import (
    BEEBOM_URL,
    EPIC_ITEM_SHOP_CUPS_URL,
    EPIC_RULES_LIBRARY_URL,
    FORTNITE_API_COSMETICS_DOCS,
    FORTNITE_API_HOME,
    OFFICIAL_TEASER_URL,
    ORIGINAL_POST_URL,
    _copy_reference_image,
    _download_binary,
    _jpeg_dimensions,
    _read_public_post,
    _safe_public_json,
    _tweet_payload,
)
from .schedule_assets import _data, _download_image, _image_info, _slug
from .transport import atomic_zipfile, write_bytes_atomic, write_text_atomic


OFFICIAL_TEASER_ID = "2097762184587825499"
OFFICIAL_TEASER_VIDEO_FALLBACK = (
    "https://video.twimg.com/amplify_video/2097761968476360704/vid/avc1/1920x1080/"
    "OZRPeSNNMMb-PEsk.mp4?tag=16"
)
OFFICIAL_TEASER_THUMB_FALLBACK = (
    "https://pbs.twimg.com/amplify_video_thumb/2097761968476360704/img/"
    "Tc5ElhML0P2i0LSl.jpg"
)
POSTER_FALLBACK_URL = "https://pbs.twimg.com/media/HR3hcAJaUAAcaUN.jpg?name=orig"
EPIC_COMPETITIVE_NAC_URL = "https://www.fortnite.com/competitive/?lang=en-US&region=NAC"


@dataclass(frozen=True)
class DeepIconCupArtifacts:
    report_path: Path
    snapshot_path: Path
    manifest_path: Path
    archive_path: Path
    asset_paths: tuple[Path, ...]
    asset_entries: tuple[dict[str, Any], ...]
    api_probes: tuple[dict[str, Any], ...]


def _records(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        for key in ("items", "br", "tracks", "instruments", "cosmetics", "entries", "data"):
            nested = value.get(key)
            if isinstance(nested, list):
                return [item for item in nested if isinstance(item, dict)]
    return []


def _category_items(value: Any) -> dict[str, list[dict[str, Any]]]:
    root = _data(value)
    if not isinstance(root, dict):
        return {}
    items = root.get("items")
    if not isinstance(items, dict):
        return {}
    return {
        str(category): [item for item in values if isinstance(item, dict)]
        for category, values in items.items()
        if isinstance(values, list)
    }


def _probe(
    client: FortniteAPIClient,
    name: str,
    path: str,
    params: dict[str, str],
) -> tuple[dict[str, Any], Any | None]:
    try:
        result = client.get(path, params)
    except FortniteAPIError as exc:
        return {
            "name": name,
            "path": path,
            "params": params,
            "httpStatus": exc.status_code,
            "available": False,
            "errorType": "api_error",
        }, None
    value = _data(result.payload)
    count = len(value) if isinstance(value, (list, dict)) else None
    return {
        "name": name,
        "path": path,
        "params": params,
        "httpStatus": result.status_code,
        "available": True,
        "dataType": type(value).__name__,
        "topLevelKeys": list(value.keys()) if isinstance(value, dict) else [],
        "count": count,
    }, value


def _text(record: dict[str, Any]) -> str:
    return json.dumps(record, ensure_ascii=False, separators=(",", ":")).casefold()


def _is_lil_wayne_record(record: dict[str, Any], category: str) -> bool:
    encoded = _text(record)
    terms = ("noiseclue", "lil wayne", "weezy", "young money", "ym burner", "tha guitar")
    if any(term in encoded for term in terms):
        return True
    if category == "tracks" and "lil wayne" in encoded:
        return True
    return False


def _record_summary(record: dict[str, Any], category: str) -> dict[str, Any]:
    keys = (
        "id",
        "name",
        "devName",
        "title",
        "artist",
        "releaseYear",
        "bpm",
        "duration",
        "difficulty",
        "albumArt",
        "description",
        "type",
        "rarity",
        "series",
        "set",
        "introduction",
        "images",
        "variants",
        "dynamicPakId",
        "added",
        "lastAppearance",
    )
    result = {"sourceCategory": category}
    result.update({key: record[key] for key in keys if key in record})
    return result


def _walk_urls(value: Any, prefix: str) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    if isinstance(value, str) and value.startswith(("http://", "https://")):
        return [(prefix, value)]
    if isinstance(value, dict):
        for key, child in value.items():
            found.extend(_walk_urls(child, f"{prefix}.{key}"))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.extend(_walk_urls(child, f"{prefix}[{index}]"))
    return found


def _media_urls(record: dict[str, Any], category: str) -> list[tuple[str, str]]:
    """Devuelve imagenes de item, variantes, album art o instrumento."""
    nodes: list[tuple[str, Any]] = []
    if isinstance(record.get("images"), dict):
        nodes.append(("images", record["images"]))
    if isinstance(record.get("variants"), list):
        nodes.append(("variants", record["variants"]))
    if category == "tracks" and isinstance(record.get("albumArt"), str):
        nodes.append(("albumArt", record["albumArt"]))
    urls: list[tuple[str, str]] = []
    seen: set[str] = set()
    for prefix, node in nodes:
        for field, url in _walk_urls(node, prefix):
            if url not in seen:
                seen.add(url)
                urls.append((field, url))
    return urls


def _extension(url: str, default: str = ".png") -> str:
    suffix = Path(urllib.parse.urlparse(url).path).suffix.lower()
    return suffix if suffix in {".png", ".jpg", ".jpeg", ".webp", ".gif"} else default


def _fix_dimensions(entry: dict[str, Any], content: bytes, content_type: str | None) -> None:
    """Completa dimensiones JPEG que el helper común deja indeterminadas."""
    if entry.get("width") is not None and entry.get("height") is not None:
        return
    info = _image_info(content, content_type)
    width, height = info.get("width"), info.get("height")
    if width is None:
        width, height = _jpeg_dimensions(content)
    if width is not None:
        entry["width"] = width
        entry["height"] = height


def _download_public_image(url: str, destination: Path, timeout: float) -> dict[str, Any]:
    result = _download_image(url, destination, timeout)
    if result.get("downloaded") and destination.is_file():
        content = destination.read_bytes()
        _fix_dimensions(result, content, result.get("contentType"))
    return result


def _download_public_video(url: str, destination: Path, timeout: float) -> dict[str, Any]:
    return _download_binary(
        url,
        destination,
        timeout,
        expected="video",
        max_bytes=75_000_000,
    )


def _type_value(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("displayValue") or value.get("value") or "sin tipo")
    return str(value or "sin tipo")


def _spanish_type(category: str, record: dict[str, Any]) -> str:
    value = _type_value(record.get("type"))
    translated = {
        "Outfit": "Atuendo / skin",
        "Back Bling": "Accesorio mochilero",
        "Pickaxe": "Pico",
        "Emote": "Emote",
        "Emoticon": "Emoticono",
        "Glider": "Ala delta / planeador",
        "Loading Screen": "Pantalla de carga",
        "Wrap": "Envoltura",
        "Guitar": "Guitarra de Festival",
    }
    if value in translated:
        return translated[value]
    if category == "tracks":
        return "Canción de Fortnite Festival"
    return value


def _variant_rows(record: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    variants = record.get("variants")
    if not isinstance(variants, list):
        return rows
    for variant in variants:
        if not isinstance(variant, dict):
            continue
        options = variant.get("options") if isinstance(variant.get("options"), list) else []
        rows.append(
            {
                "id": record.get("id"),
                "name": record.get("name"),
                "channel": variant.get("channel"),
                "type": variant.get("type"),
                "options": [
                    {
                        key: option[key]
                        for key in ("tag", "name", "image")
                        if isinstance(option, dict) and key in option
                    }
                    for option in options
                    if isinstance(option, dict)
                ],
            }
        )
    return rows


def _best_priority(field: str) -> int:
    field = field.casefold()
    if field.endswith(".featured") or field.endswith(".large") or field.endswith(".background"):
        return 0
    if field.endswith(".icon"):
        return 1
    if field.endswith(".smallicon") or field.endswith(".small"):
        return 2
    if "albumart" in field:
        return 0
    return 3


def _status(probe: dict[str, Any]) -> str:
    status = probe.get("httpStatus")
    return f"HTTP {status}" if status is not None else "sin respuesta"


def _md_link(label: str, url: str) -> str:
    return f"[{label}]({url})"


def _format_date(value: Any) -> str:
    return str(value or "n/d")


def _build_report(
    retrieved_at: str,
    snapshot: dict[str, Any],
    asset_entries: list[dict[str, Any]],
) -> str:
    related_br = snapshot.get("related", {}).get("br", [])
    related_tracks = snapshot.get("related", {}).get("tracks", [])
    related_instruments = snapshot.get("related", {}).get("instruments", [])
    categories = snapshot.get("newCategoryCounts", {})
    probes = snapshot.get("queries", [])
    successful = [item for item in asset_entries if item.get("downloaded")]
    failed = [item for item in asset_entries if not item.get("downloaded")]
    delivery = [item for item in successful if item.get("telegramDelivery")]
    type_counts = Counter(_spanish_type("br", record) for record in related_br)
    catalog_summary = ", ".join(
        f"{label}: {count}" for label, count in sorted(type_counts.items())
    ) or "sin registros"
    outfit_names = ", ".join(
        str(record.get("name") or "sin nombre")
        for record in related_br
        if _type_value(record.get("type")) == "Outfit"
    ) or "ninguno"
    post = snapshot.get("publicSources", {}).get("originalPostNormalized") or {}
    teaser = snapshot.get("publicSources", {}).get("officialTeaserNormalized") or {}
    post_date = str(post.get("createdAt") or "fecha no disponible")
    teaser_date = str(teaser.get("createdAt") or "fecha no disponible")
    outfit_count = sum(
        1 for record in related_br if _type_value(record.get("type")) == "Outfit"
    )
    track_names = ", ".join(
        str(record.get("title") or "sin título") for record in related_tracks
    ) or "ninguna"
    instrument_names = ", ".join(
        str(record.get("name") or "sin nombre")
        for record in related_instruments
    ) or "ninguno"

    lines = [
        "# Investigación profunda: Weezy Icon Cup / Lil Wayne",
        "",
        f"**Snapshot de la API:** {retrieved_at}",
        f"**Post investigado:** {_md_link('FNcompReport en X', ORIGINAL_POST_URL)}",
        "**Catálogo consultado:** Fortnite-API.com, API comunitaria no oficial.",
        "",
        "## Resultado nuevo respecto a la consulta anterior",
        "",
        f"La API devuelve **{len(related_br)} registros de Battle Royale del set `Lil Wayne`**, **{len(related_tracks)} canciones de Fortnite Festival** y **{len(related_instruments)} instrumento(s)** relacionado(s). El desglose actual es {catalog_summary}. Si existen valores `added`, se conservan en el inventario; esta ejecución documenta el estado observado y no promete disponibilidad en tienda.",
        "",
        "### Conteo actual de Battle Royale",
        "",
        " | ".join([]) if False else "",
        "| Tipo | Cantidad |",
        "|---|---:|",
    ]
    for item_type, count in sorted(type_counts.items()):
        lines.append(f"| {item_type} | {count} |")
    lines.extend(
        [
            "",
            f"**Lectura importante:** hay {sum(1 for record in related_br if _type_value(record.get('type')) == 'Outfit')} atuendo(s) catalogado(s): {outfit_names}. La API no asigna por sí sola esos atuendos como premio de la copa ni confirma su precio o fecha de tienda.",
            "",
            "## Qué está confirmado y qué no",
            "",
            "| Dato | Nivel | Evidencia |",
            "|---|---|---|",
            "| Colaboración de Lil Wayne / Weezy | Alto | Teaser de Epic + registros `Lil Wayne` en la API |",
            f"| Atuendos distintos | Alto como catálogo | {outfit_names} |",
            f"| Emotes | Alto como catálogo | {type_counts.get('Emote', 0)} registro(s) en este snapshot |",
            f"| Canciones de Festival | Alto como catálogo | {len(related_tracks)} registro(s) relacionados |",
            "| Copa y fecha concreta | Pendiente | Post comunitario; falta revalidación oficial automática |",
            "| Modos indicados por el post | Pendiente | Texto de la imagen/post; falta el reglamento |",
            "| Premio exacto | Desconocido | No hay mapeo de recompensa en Fortnite-API.com |",
            "| Hora, regiones, duración, puntos y partidas | Desconocido | No hay endpoint público de torneos en esta API |",
            "| Fecha de salida en tienda | Desconocido | `/v2/shop` no mostró coincidencias en este snapshot |",
            "",
            "## Inventario completo del set `Lil Wayne`",
            "",
            "| # | Nombre | Tipo en español | ID | Añadido | Pak dinámico | Variantes |",
            "|---:|---|---|---|---|---:|---|",
        ]
    )
    for index, record in enumerate(related_br, start=1):
        item_type = _spanish_type("br", record)
        variants = record.get("variants") if isinstance(record.get("variants"), list) else []
        variant_text = ", ".join(
            str(item.get("type") or item.get("channel") or "variante")
            for item in variants
            if isinstance(item, dict)
        ) or "—"
        lines.append(
            f"| {index} | **{record.get('name') or 'sin nombre'}** | {item_type} | `{record.get('id', 'n/d')}` | `{_format_date(record.get('added'))}` | `{record.get('dynamicPakId', 'n/d')}` | {variant_text} |"
        )
    lines.extend(["", "### Detalle de atuendos y variantes", ""])
    for record in related_br:
        if _type_value(record.get("type")) != "Outfit":
            continue
        lines.append(f"#### {record.get('name')} — `{record.get('id')}`")
        lines.append("")
        lines.append(f"Descripción de la API: `{str(record.get('description') or 'n/d').replace(chr(10), ' / ')}`.")
        lines.append("")
        for row in _variant_rows(record):
            options = ", ".join(str(option.get("name") or option.get("tag") or "n/d") for option in row["options"])
            lines.append(f"- **{row.get('type') or row.get('channel')}:** {options or 'sin opciones'}.")
        lines.append("")
    lines.extend(["#### Variantes adicionales", ""])
    for record in related_br:
        if _type_value(record.get("type")) == "Outfit":
            continue
        for row in _variant_rows(record):
            options = ", ".join(str(option.get("name") or option.get("tag") or "n/d") for option in row["options"])
            lines.append(f"- **{record.get('name')} — {row.get('type') or row.get('channel')}:** {options or 'sin opciones'}.")
    lines.extend(
        [
            "",
            "## Música e instrumento detectados",
            "",
            f"La respuesta de novedades contiene {len(related_tracks)} registro(s) de Festival. En el catálogo consultado aparecen como `tracks`, no como cosméticos BR; por eso los separo de skins, picos y accesorios.",
            "",
            "| Canción | Artista | Año | BPM | Duración | ID de catálogo |",
            "|---|---|---:|---:|---:|---|",
        ]
    )
    for record in related_tracks:
        duration = int(record.get("duration", 0) or 0)
        minutes, seconds = divmod(duration, 60)
        lines.append(
            f"| **{record.get('title', 'sin título')}** | {record.get('artist', 'n/d')} | {record.get('releaseYear', 'n/d')} | {record.get('bpm', 'n/d')} | {minutes}:{seconds:02d} | `{record.get('id', 'n/d')}` |"
        )
    for record in related_instruments:
        lines.extend(
            [
                "",
                f"- **Instrumento:** `{record.get('name', 'sin nombre')}` — `{record.get('id', 'n/d')}` — {_spanish_type('instruments', record)}; añadido `{record.get('added', 'n/d')}`.",
            ]
        )
    lines.extend(
        [
            "",
            "## Lectura temática de nombres y contenido",
            "",
            f"- Los atuendos actuales del inventario son: {outfit_names}. Sus variantes y canales se detallan a partir de los datos de esta ejecución.",
            f"- El inventario observado se resume en: {catalog_summary}. Los nombres compartidos entre categorías no implican que sean el mismo objeto.",
            f"- Las canciones relacionadas son: {track_names}; los instrumentos relacionados son: {instrument_names}. Se conservan como categorías separadas del catálogo BR.",
            "- La semántica de los nombres puede sugerir una temática, pero no constituye un anuncio de recompensas.",
            "",
            "## Estado competitivo del torneo",
            "",
            f"El {_md_link('post de FNcompReport', ORIGINAL_POST_URL)} recuperado en el espejo público dice: `{str(post.get('text') or 'no disponible').replace(chr(10), ' / ')}` y figura con fecha `{post_date}`. La imagen aportada se conserva como evidencia comunitaria; sus modos y fechas no se tratan como reglamento de Epic.",
            "",
            f"La {_md_link('página oficial de Item Shop Cups', EPIC_ITEM_SHOP_CUPS_URL)} explica que estas copas son torneos especiales de un día, que cada una puede tener modo y tamaño de equipo propio, que pueden ser multiplataforma o restringidas a consola/móvil y que cada copa tiene su propio reglamento y premios cosméticos. Es el marco oficial aplicable a este tipo de evento, no la confirmación de la Weezy Cup.",
            "",
            f"La {_md_link('agenda competitiva oficial', EPIC_COMPETITIVE_NAC_URL)} y la {_md_link('biblioteca oficial de reglas', EPIC_RULES_LIBRARY_URL)} se conservan como fuentes de revalidación. Esta ejecución no convierte la ausencia o presencia de una ficha pública en prueba de disponibilidad dentro del cliente.",
            "",
            "### Lo que no voy a inventar a partir del catálogo",
            "",
            "No asigno a la copa un atuendo ganador, umbral de puntos, número de partidas, región, hora o precio solo porque esos objetos aparezcan en la API. La API confirma existencia/indexación de recursos; el reglamento o la pestaña Competir deben confirmar la recompensa y el formato.",
            "",
            "## Teaser y fuentes externas",
            "",
            f"La {_md_link('publicación oficial de Fortnite', OFFICIAL_TEASER_URL)} tiene un teaser; el espejo público lo fecha como `{teaser_date}` y normaliza {len(teaser.get('videos') or [])} recurso(s) de vídeo. {_md_link('Beebom', BEEBOM_URL)} se trata como cobertura secundaria. El catálogo actual aporta {outfit_count} atuendo(s) y {len(related_tracks)} canción(es), pero no convierte en oficiales los precios, fechas o premios.",
            "",
            "## Auditoría de endpoints",
            "",
            "| Consulta | Ruta | Estado | Hallazgo |",
            "|---|---|---:|---|",
        ]
    )
    for probe in probes:
        name = probe.get("name")
        if name == "newCosmetics":
            finding = f"Novedades por categoría: {categories}"
        elif name == "setLilWayne":
            finding = f"Set completo: {len(related_br)} registros BR"
        elif name in {"nameLilWayne", "nameWeezy", "nameYoungMoney", "nameThaGuitar", "nameYMburner"}:
            finding = "Búsqueda nominal de catálogo"
        elif name in {"eventsV1", "eventsV2", "tournamentsV1", "tournamentsV2"} and not probe.get("available"):
            finding = "No expuesto por Fortnite-API.com; no equivale a inexistencia en Fortnite"
        elif name == "shop":
            finding = "Feed actual; no es calendario futuro"
        elif name == "news":
            finding = "Noticias BR actuales; sin coincidencia directa"
        else:
            finding = "Consulta de catálogo"
        lines.append(f"| {name} | `{probe.get('path')}` | {_status(probe)} | {finding} |")
    lines.extend(
        [
            "",
            "## Archivos originales preparados",
            "",
            f"Se validaron **{len(successful)} archivos** ({sum(int(item.get('bytes', 0)) for item in successful):,} bytes). De ellos, **{len(delivery)}** son los archivos seleccionados para enviarse individualmente por Telegram; las imágenes secundarias no seleccionadas quedan dentro del expediente local para auditoría.",
            "",
            "- Las imágenes se descargaron desde las URLs devueltas por el catálogo y se conservaron sin recorte, conversión ni reescalado.",
            "- Las canciones se entregan como carátulas JPG del catálogo; no se descarga audio que la API no expone.",
            "- El teaser MP4, la miniatura y el póster del post se incluyen como evidencia pública cuando la descarga es válida; no se reencodean.",
            "- `manifest-deep.json` contiene bytes, formato, dimensiones y SHA-256 de cada descarga.",
            "- `api_snapshot-deep.json` conserva respuestas de la API y resúmenes relacionados, sin credenciales.",
            "",
            "### Archivos seleccionados para Telegram",
            "",
            "| Archivo | Descripción del pie en español | Dimensiones | Bytes |",
            "|---|---|---:|---:|",
        ]
    )
    for item in delivery:
        dimensions = f"{item.get('width', 'n/d')} × {item.get('height', 'n/d')}" if item.get("width") else "vídeo / n/d"
        lines.append(
            f"| `{Path(str(item.get('path', ''))).name}` | {item.get('caption', 'Recurso Fortnite')} | {dimensions} | {int(item.get('bytes', 0)):,} |"
        )
    if failed:
        lines.extend(["", "### Descargas fallidas", ""])
        for item in failed:
            lines.append(f"- `{item.get('url', 'n/d')}` — {item.get('errorType', 'error')}.")
    lines.extend(
        [
            "",
            "## Fuentes y reproducibilidad",
            "",
            f"1. {_md_link('Publicación de FNcompReport en X', ORIGINAL_POST_URL)} — texto e imagen comunitarios del torneo.",
            f"2. {_md_link('Publicación oficial de Fortnite en X', OFFICIAL_TEASER_URL)} — teaser público.",
            f"3. {_md_link('Endpoint de set Lil Wayne en Fortnite-API.com', 'https://fortnite-api.com/v2/cosmetics/br/search/all?set=Lil%20Wayne&matchMethod=full&language=en')} — registros BR completos.",
            f"4. {_md_link('Endpoint de novedades de Fortnite-API.com', 'https://fortnite-api.com/v2/cosmetics/new?language=en')} — categorías BR, tracks e instrumentos.",
            f"5. {_md_link('Item Shop Cups de Epic', EPIC_ITEM_SHOP_CUPS_URL)} — reglas generales de este tipo de copa.",
            f"6. {_md_link('Agenda competitiva oficial NAC', EPIC_COMPETITIVE_NAC_URL)} y {_md_link('Rules Library', EPIC_RULES_LIBRARY_URL)} — comprobación de agenda/reglamentos públicos.",
            f"7. {_md_link('Beebom', BEEBOM_URL)} — corroboración secundaria del teaser.",
            f"8. {_md_link('Inicio de Fortnite-API.com', FORTNITE_API_HOME)} y {_md_link('documentación de cosméticos', FORTNITE_API_COSMETICS_DOCS)} — referencia de la API comunitaria.",
            "",
            "## Conclusión",
            "",
            f"La investigación profunda encontró {len(related_br)} registro(s) BR, {outfit_count} atuendo(s), {len(related_tracks)} canción(es) ({track_names}) y {len(related_instruments)} instrumento(s). Eso describe el catálogo observado en esta ejecución; no confirma premio, puntuación, hora, región ni reglamento de la copa. Esos datos deben verificarse en la pestaña Competir o en el reglamento de Epic antes de tratarlos como definitivos.",
            "",
        ]
    )
    return "\n".join(line for line in lines if line != " | ")


def _public_media_urls(
    client_timeout: float,
) -> tuple[
    list[dict[str, Any]],
    dict[str, Any] | None,
    dict[str, Any] | None,
    str,
    str,
    str,
]:
    checks, post = _read_public_post(client_timeout)
    teaser_check, teaser_raw = _safe_public_json(f"https://api.fxtwitter.com/status/{OFFICIAL_TEASER_ID}", client_timeout)
    checks.append(teaser_check)
    teaser = _tweet_payload(teaser_raw)
    poster_url = POSTER_FALLBACK_URL
    if post and post.get("photos"):
        first = post["photos"][0]
        if isinstance(first, dict) and isinstance(first.get("url"), str):
            poster_url = first["url"]
    video_url = OFFICIAL_TEASER_VIDEO_FALLBACK
    thumb_url = OFFICIAL_TEASER_THUMB_FALLBACK
    if teaser:
        for video in teaser.get("videos") or []:
            if isinstance(video, dict) and isinstance(video.get("url"), str):
                if video.get("width") == 1920 or video_url == OFFICIAL_TEASER_VIDEO_FALLBACK:
                    video_url = video["url"]
            if isinstance(video, dict) and isinstance(video.get("thumbnail_url"), str):
                thumb_url = video["thumbnail_url"]
                break
    return checks, post, teaser, poster_url, video_url, thumb_url


def build_deep_icon_cup_research_package(
    client: FortniteAPIClient,
    output_dir: Path,
    reference_image: Path | None = None,
    language: str = "en",
    timeout: float = 30,
) -> DeepIconCupArtifacts:
    """Consulta el estado actual, descarga medios relacionados y genera expediente."""
    output_dir.mkdir(parents=True, exist_ok=True)
    retrieved = datetime.now(timezone.utc)
    retrieved_iso = retrieved.isoformat()

    query_specs = (
        ("newCosmetics", "/v2/cosmetics/new", {"language": language}),
        ("setLilWayne", "/v2/cosmetics/br/search/all", {"set": "Lil Wayne", "matchMethod": "full", "language": language}),
        ("nameLilWayne", "/v2/cosmetics/br/search/all", {"name": "Lil Wayne", "matchMethod": "contains", "language": language}),
        ("nameWeezy", "/v2/cosmetics/br/search/all", {"name": "Weezy", "matchMethod": "contains", "language": language}),
        ("nameYoungMoney", "/v2/cosmetics/br/search/all", {"name": "Young Money", "matchMethod": "contains", "language": language}),
        ("nameThaGuitar", "/v2/cosmetics/br/search/all", {"name": "Tha Guitar", "matchMethod": "contains", "language": language}),
        ("nameYMburner", "/v2/cosmetics/br/search/all", {"name": "YM Burner", "matchMethod": "contains", "language": language}),
        ("shop", "/v2/shop", {"language": language}),
        ("news", "/v2/news/br", {"language": language}),
        ("eventsV1", "/v1/events", {"language": language}),
        ("eventsV2", "/v2/events", {"language": language}),
        ("tournamentsV1", "/v1/tournaments", {"language": language}),
        ("tournamentsV2", "/v2/tournaments", {"language": language}),
    )
    values: dict[str, Any | None] = {}
    probes: list[dict[str, Any]] = []
    for name, path, params in query_specs:
        probe, value = _probe(client, name, path, params)
        probes.append(probe)
        values[name] = value

    set_records = _records(values.get("setLilWayne"))
    categories = _category_items(values.get("newCosmetics"))
    related: dict[str, list[dict[str, Any]]] = {}
    for category, records in categories.items():
        matches = [
            _record_summary(record, category)
            for record in records
            if _is_lil_wayne_record(record, category)
        ]
        if matches:
            related[category] = matches
    # The exact set endpoint is authoritative for BR set membership. Keep any
    # record that the search returns, even if its free text has no keyword.
    related["br"] = [_record_summary(record, "br") for record in set_records]

    (
        public_checks,
        post,
        teaser,
        poster_url,
        teaser_video_url,
        teaser_thumb_url,
    ) = _public_media_urls(timeout)
    raw_focused = {
        "newCosmetics": values.get("newCosmetics"),
        "setLilWayne": values.get("setLilWayne"),
        "nameLilWayne": values.get("nameLilWayne"),
        "nameWeezy": values.get("nameWeezy"),
        "nameYoungMoney": values.get("nameYoungMoney"),
        "nameThaGuitar": values.get("nameThaGuitar"),
        "nameYMburner": values.get("nameYMburner"),
        "shop": values.get("shop"),
        "news": values.get("news"),
    }
    snapshot: dict[str, Any] = {
        "investigation": {
            "topic": "Deep Weezy Icon Cup / Lil Wayne",
            "source": "Fortnite-API.com",
            "retrievedAt": retrieved_iso,
            "language": language,
            "baseUrl": client.base_url,
        },
        "queries": probes,
        "newCategoryCounts": {category: len(records) for category, records in categories.items()},
        "related": related,
        "variantRows": [row for record in set_records for row in _variant_rows(record)],
        "rawFocusedResponses": raw_focused,
        "publicSources": {
            "publicMirrorChecks": public_checks,
            "originalPost": ORIGINAL_POST_URL,
            "originalPostNormalized": post,
            "officialTeaser": OFFICIAL_TEASER_URL,
            "officialTeaserNormalized": teaser,
            "posterUrl": poster_url,
            "teaserVideoUrl": teaser_video_url,
            "teaserThumbUrl": teaser_thumb_url,
        },
        "sourceUrls": {
            "originalPost": ORIGINAL_POST_URL,
            "officialTeaser": OFFICIAL_TEASER_URL,
            "apiHome": FORTNITE_API_HOME,
            "apiCosmeticsDocs": FORTNITE_API_COSMETICS_DOCS,
            "itemShopCups": EPIC_ITEM_SHOP_CUPS_URL,
            "competitive": EPIC_COMPETITIVE_NAC_URL,
            "rulesLibrary": EPIC_RULES_LIBRARY_URL,
            "beebom": BEEBOM_URL,
        },
    }

    staging_dir = Path(tempfile.mkdtemp(prefix="fortnite-weezy-deep-", dir=str(output_dir)))
    asset_entries: list[dict[str, Any]] = []
    chosen_by_record: dict[str, dict[str, Any]] = {}
    try:
        # Keep the user-provided reference in the local evidence package.
        if reference_image is not None:
            reference_info = _copy_reference_image(reference_image, staging_dir)
            reference_info.update(
                {
                    "label": "reference-post",
                    "caption": "Referencia de la publicación — imagen original del torneo",
                    "telegramDelivery": False,
                }
            )
            asset_entries.append(reference_info)

        # Public evidence. They remain local in this deep package, but are not
        # necessarily re-sent if the user already received them earlier.
        public_downloads = (
            ("tournament-post", poster_url, "image", ".jpg", "Weezy Icon Cup — póster del torneo publicado por FNcompReport"),
            ("official-teaser", teaser_video_url, "video", ".mp4", "Teaser oficial de Fortnite — vídeo original"),
            ("official-teaser-thumb", teaser_thumb_url, "image", ".jpg", "Teaser oficial de Fortnite — miniatura original"),
        )
        for label, url, kind, extension, caption in public_downloads:
            relative = Path("assets") / "public" / f"{_slug(label)}{extension}"
            if kind == "video":
                result = _download_public_video(url, staging_dir / relative, timeout)
            else:
                result = _download_public_image(url, staging_dir / relative, timeout)
            result.update({"kind": "public_evidence", "label": label, "path": relative.as_posix(), "caption": caption, "telegramDelivery": False})
            asset_entries.append(result)

        # First download every image URL, including secondary images and all
        # variant option images. This lets us choose by measured dimensions.
        related_by_category = {category: records for category, records in related.items()}
        for category, records in related_by_category.items():
            for record in records:
                record_id = str(record.get("id") or record.get("name") or "asset")
                record_name = str(record.get("name") or record.get("title") or record_id)
                for field, url in _media_urls(record, category):
                    relative = Path("assets") / "api-deep" / category / f"{_slug(record_id)}-{_slug(field)}{_extension(url)}"
                    result = _download_public_image(url, staging_dir / relative, timeout)
                    result.update(
                        {
                            "kind": "fortnite_api_related",
                            "category": category,
                            "recordId": record_id,
                            "recordName": record_name,
                            "field": field,
                            "label": f"{record_name} — {field}",
                            "path": relative.as_posix(),
                            "telegramDelivery": False,
                        }
                    )
                    asset_entries.append(result)

        # Select one measured best image per record for the Telegram delivery.
        candidates: dict[str, list[dict[str, Any]]] = {}
        for item in asset_entries:
            if item.get("kind") != "fortnite_api_related" or not item.get("downloaded"):
                continue
            key = f"{item.get('category')}:{item.get('recordId')}"
            candidates.setdefault(key, []).append(item)
        for key, items in candidates.items():
            best = sorted(
                items,
                key=lambda item: (
                    _best_priority(str(item.get("field", ""))),
                    -(int(item.get("width") or 0) * int(item.get("height") or 0)),
                    -int(item.get("bytes") or 0),
                ),
            )[0]
            best["telegramDelivery"] = True
            record_name = str(best.get("recordName") or best.get("recordId") or "Recurso Fortnite")
            category = str(best.get("category") or "")
            record = next(
                (record for record in related.get(category, []) if str(record.get("id")) == str(best.get("recordId"))),
                {},
            )
            best["caption"] = f"{record_name} — {_spanish_type(category, record)} — imagen original del catálogo"
            chosen_by_record[key] = best

        # Also send distinct style renders for the outfits and the reactive
        # back bling. Do not send a second copy when an API variant URL returns
        # the same bytes as another option.
        selected_hashes = {str(item.get("sha256")) for item in chosen_by_record.values()}
        for item in asset_entries:
            if (
                item.get("kind") != "fortnite_api_related"
                or not item.get("downloaded")
                or not str(item.get("field", "")).startswith("variants")
                or str(item.get("sha256")) in selected_hashes
            ):
                continue
            item["telegramDelivery"] = True
            item["caption"] = (
                f"{item.get('recordName') or item.get('recordId') or 'Recurso Fortnite'} — "
                f"variante de {_spanish_type(str(item.get('category') or ''), next((record for record in related.get(str(item.get('category') or ''), []) if str(record.get('id')) == str(item.get('recordId'))), {}))} — imagen original"
            )
            selected_hashes.add(str(item.get("sha256")))

        snapshot["selectedDelivery"] = [
            {
                key: value
                for key, value in item.items()
                if key not in {"url"} or value is not None
            }
            for item in chosen_by_record.values()
        ]

        timestamp_label = retrieved.strftime("%Y%m%dT%H%M%SZ")
        report = _build_report(retrieved_iso, snapshot, asset_entries)
        report_path = output_dir / f"{timestamp_label}-investigacion-profunda-weezy-icon-cup.md"
        snapshot_path = output_dir / f"{timestamp_label}-api-snapshot-deep-weezy.json"
        manifest_path = output_dir / f"{timestamp_label}-manifest-deep-weezy.json"
        archive_path = output_dir / f"{timestamp_label}-recursos-deep-weezy-icon-cup.zip"
        write_text_atomic(report_path, report)
        write_text_atomic(snapshot_path, json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n")
        manifest = {
            "generatedAt": retrieved_iso,
            "source": "Fortnite-API.com + public X syndication + Epic public sources + attached reference image",
            "quality": "original bytes; no conversion, crop or resizing",
            "assets": asset_entries,
            "selectedDelivery": list(chosen_by_record.values()),
            "failedDownloads": [item for item in asset_entries if not item.get("downloaded")],
        }
        write_text_atomic(manifest_path, json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")

        # Add report/snapshot/manifest and all binary files to a local backup.
        with atomic_zipfile(archive_path, compresslevel=6) as archive:
            archive.write(report_path, arcname="INFORME-profundo-weezy-icon-cup.md")
            archive.write(snapshot_path, arcname="api-snapshot-deep-weezy.json")
            archive.write(manifest_path, arcname="manifest-deep-weezy.json")
            for file_path in staging_dir.rglob("*"):
                if file_path.is_file():
                    archive.write(file_path, arcname=file_path.relative_to(staging_dir).as_posix())

        successful = [item for item in asset_entries if item.get("downloaded") and item.get("path")]
        asset_paths = tuple(staging_dir / str(item["path"]) for item in successful)
        # Copy files selected for Telegram into a stable output directory. The
        # staging directory is removed in finally, so delivery must not point
        # to temporary paths.
        stable_dir = output_dir / "Weezy Icon Cup - archivos profundos"
        stable_dir.mkdir(parents=True, exist_ok=True)
        stable_entries: list[dict[str, Any]] = []
        stable_paths: list[Path] = []
        for item in successful:
            source = staging_dir / str(item["path"])
            if not source.is_file():
                continue
            destination = stable_dir / source.name
            write_bytes_atomic(destination, source.read_bytes())
            copied = dict(item)
            copied["path"] = destination.as_posix()
            stable_entries.append(copied)
            if copied.get("telegramDelivery"):
                stable_paths.append(destination)
        manifest["stableFiles"] = stable_entries
        snapshot["selectedDelivery"] = [
            {
                key: value
                for key, value in item.items()
                if key != "url" or value is not None
            }
            for item in stable_entries
            if item.get("telegramDelivery") and item.get("downloaded")
        ]
        write_text_atomic(snapshot_path, json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n")
        write_text_atomic(manifest_path, json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
        with atomic_zipfile(archive_path, compresslevel=6) as archive:
            archive.write(report_path, arcname="INFORME-profundo-weezy-icon-cup.md")
            archive.write(snapshot_path, arcname="api-snapshot-deep-weezy.json")
            archive.write(manifest_path, arcname="manifest-deep-weezy.json")
            for file_path in staging_dir.rglob("*"):
                if file_path.is_file():
                    archive.write(file_path, arcname=file_path.relative_to(staging_dir).as_posix())
            for file_path in stable_dir.rglob("*"):
                if file_path.is_file():
                    archive.write(file_path, arcname=Path("stable") / file_path.relative_to(stable_dir))

        stable_successful = [item for item in stable_entries if item.get("downloaded")]
        delivery_count = sum(1 for item in stable_successful if item.get("telegramDelivery"))
        return DeepIconCupArtifacts(
            report_path=report_path,
            snapshot_path=snapshot_path,
            manifest_path=manifest_path,
            archive_path=archive_path,
            asset_paths=tuple(stable_paths),
            asset_entries=tuple(stable_entries),
            api_probes=tuple(probes),
        )
    finally:
        shutil.rmtree(staging_dir, ignore_errors=True)
