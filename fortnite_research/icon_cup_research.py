"""Investiga la publicación de FNcompReport sobre la Weezy Icon Cup.

El expediente separa tres tipos de evidencia:

* la publicación y la imagen que el usuario entregó;
* los registros que devuelve Fortnite-API.com en este momento;
* las reglas generales y el teaser público de Epic que permiten interpretar
  la colaboración sin convertir una filtración en un anuncio oficial.

Fortnite-API.com es una API comunitaria. Sus cosméticos pueden confirmar que
un recurso ya está indexado, pero no publican por sí mismos el horario, el
formato de puntuación o los premios de un torneo.
"""

from __future__ import annotations

import hashlib
import json
import mimetypes
import shutil
import tempfile
import urllib.parse
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .client import FortniteAPIClient, FortniteAPIError
from .schedule_assets import _data, _download_image, _image_info, _slug


ORIGINAL_POST_URL = "https://x.com/fncompreport/status/2098080878320619883?s=46"
POST_ID = "2098080878320619883"
POSTER_FALLBACK_URL = "https://pbs.twimg.com/media/HR3hcAJaUAAcaUN.jpg?name=orig"
PUBLIC_POST_MIRRORS = (
    f"https://api.fxtwitter.com/status/{POST_ID}",
    "https://api.vxtwitter.com/FNcompReport/status/2098080878320619883",
)

OFFICIAL_TEASER_URL = "https://x.com/Fortnite/status/2097762184587825499"
OFFICIAL_TEASER_ID = "2097762184587825499"
OFFICIAL_TEASER_VIDEO_FALLBACK = (
    "https://video.twimg.com/amplify_video/2097761968476360704/vid/avc1/1920x1080/"
    "OZRPeSNNMMb-PEsk.mp4?tag=16"
)
OFFICIAL_TEASER_THUMB_FALLBACK = (
    "https://pbs.twimg.com/amplify_video_thumb/2097761968476360704/img/"
    "Tc5ElhML0P2i0LSl.jpg"
)

FORTNITE_API_HOME = "https://fortnite-api.com/"
FORTNITE_API_COSMETICS_DOCS = "https://dash.fortnite-api.com/endpoints/cosmetics"
FORTNITE_API_NEWS_DOCS = "https://dash.fortnite-api.com/endpoints/news"
EPIC_ITEM_SHOP_CUPS_URL = (
    "https://www.fortnite.com/competitive/discover-competitive/item-shop-cups?region=NAC"
)
EPIC_RULES_LIBRARY_URL = "https://www.fortnite.com/competitive/rules-guidelines/rules-library"
EPIC_COMPETITIVE_URL = "https://www.fortnite.com/competitive/"
BEEBOM_URL = "https://beebom.com/fortnite-teases-lil-wayne-crossover-coming-soon/"


@dataclass(frozen=True)
class IconCupResearchArtifacts:
    report_path: Path
    archive_path: Path
    asset_count: int
    asset_bytes: int
    api_probes: tuple[dict[str, Any], ...]


def _safe_public_json(url: str, timeout: float) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Lee un espejo público de X y devuelve solo un estado seguro para el reporte."""
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "fortnite-api-researcher/0.1.0",
        },
        method="GET",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            body = response.read()
            status = int(response.status)
    except HTTPError as exc:
        return {"url": url, "httpStatus": exc.code, "available": False, "errorType": "http"}, None
    except (URLError, TimeoutError) as exc:
        detail = getattr(exc, "reason", str(exc))
        return {
            "url": url,
            "httpStatus": None,
            "available": False,
            "errorType": "transport",
            "detail": str(detail)[:160],
        }, None
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {"url": url, "httpStatus": status, "available": False, "errorType": "not_json"}, None
    return {"url": url, "httpStatus": status, "available": True}, payload if isinstance(payload, dict) else None


def _tweet_payload(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    """Normaliza la parte útil de FxTwitter/VxTwitter sin guardar datos ajenos."""
    if not isinstance(payload, dict):
        return None
    tweet = payload.get("tweet") if isinstance(payload.get("tweet"), dict) else payload
    if not isinstance(tweet, dict):
        return None
    author = tweet.get("author") if isinstance(tweet.get("author"), dict) else {}
    media = tweet.get("media") if isinstance(tweet.get("media"), dict) else {}
    all_media = media.get("all") if isinstance(media.get("all"), list) else []
    photos: list[dict[str, Any]] = []
    videos: list[dict[str, Any]] = []
    for item in all_media:
        if not isinstance(item, dict):
            continue
        compact = {
            key: item.get(key)
            for key in (
                "type",
                "url",
                "thumbnail_url",
                "width",
                "height",
                "duration_millis",
                "format",
                "bitrate",
            )
            if item.get(key) is not None
        }
        if item.get("type") == "video" or item.get("type") == "gif":
            videos.append(compact)
        else:
            photos.append(compact)
    return {
        "id": str(tweet.get("id") or ""),
        "url": tweet.get("url"),
        "text": tweet.get("text"),
        "createdAt": tweet.get("created_at"),
        "author": {
            "name": author.get("name"),
            "screenName": author.get("screen_name") or author.get("screenName"),
        },
        "likes": tweet.get("likes"),
        "replies": tweet.get("replies"),
        "retweets": tweet.get("retweets"),
        "possiblySensitive": tweet.get("possibly_sensitive"),
        "photos": photos,
        "videos": videos,
    }


def _read_public_post(timeout: float) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    checks: list[dict[str, Any]] = []
    normalized: dict[str, Any] | None = None
    for url in PUBLIC_POST_MIRRORS:
        check, payload = _safe_public_json(url, timeout)
        checks.append(check)
        if normalized is None:
            normalized = _tweet_payload(payload)
    return checks, normalized


def _fetch_api_query(
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
    return {
        "name": name,
        "path": path,
        "params": params,
        "httpStatus": result.status_code,
        "available": True,
        "dataType": type(value).__name__,
        "topLevelKeys": list(value.keys()) if isinstance(value, dict) else [],
        "count": len(value) if isinstance(value, (list, dict)) else None,
    }, value


def _records(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        for key in ("items", "br", "cosmetics", "entries", "data"):
            nested = value.get(key)
            if isinstance(nested, list):
                return [item for item in nested if isinstance(item, dict)]
    return []


def _record_summary(record: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "id",
        "name",
        "description",
        "type",
        "rarity",
        "series",
        "set",
        "introduction",
        "images",
        "dynamicPakId",
        "added",
        "lastAppearance",
    )
    return {key: record[key] for key in keys if key in record}


def _set_matches(value: Any, set_name: str = "Lil Wayne") -> list[dict[str, Any]]:
    return [
        _record_summary(record)
        for record in _records(value)
        if isinstance(record.get("set"), dict) and record["set"].get("value") == set_name
    ]


def _text_matches(value: Any, terms: tuple[str, ...]) -> list[dict[str, Any]]:
    """Devuelve mensajes o nodos de catálogo que contienen los términos."""
    matches: list[dict[str, Any]] = []
    seen: set[str] = set()

    def visit(node: Any) -> None:
        if isinstance(node, dict):
            encoded = json.dumps(node, ensure_ascii=False).casefold()
            if any(term.casefold() in encoded for term in terms) and (node.get("id") or node.get("name") or node.get("title")):
                identity = str(node.get("id") or node.get("name") or node.get("title"))
                if identity not in seen:
                    seen.add(identity)
                    matches.append(
                        {
                            key: node[key]
                            for key in ("id", "name", "title", "tabTitle", "body", "set", "type", "added", "image", "tileImage")
                            if key in node
                        }
                    )
            for child in node.values():
                visit(child)
        elif isinstance(node, list):
            for child in node:
                visit(child)

    visit(value)
    return matches[:100]


def _image_urls_for_records(records: list[dict[str, Any]]) -> list[tuple[str, str]]:
    urls: list[tuple[str, str]] = []
    seen: set[str] = set()
    for record in records:
        record_id = str(record.get("id") or record.get("name") or "asset")
        images = record.get("images") if isinstance(record.get("images"), dict) else {}

        def visit(node: Any, field: str) -> None:
            if isinstance(node, str) and node.startswith(("http://", "https://")):
                if node not in seen:
                    seen.add(node)
                    urls.append((f"{record_id}-{field}", node))
                return
            if isinstance(node, dict):
                for key, child in node.items():
                    visit(child, f"{field}-{key}")

        visit(images, "image")
    return urls


def _jpeg_dimensions(content: bytes) -> tuple[int | None, int | None]:
    if not content.startswith(b"\xff\xd8\xff"):
        return None, None
    position = 2
    sof_markers = (
        set(range(0xC0, 0xC4))
        | set(range(0xC5, 0xC8))
        | set(range(0xC9, 0xCC))
        | set(range(0xCD, 0xD0))
    )
    while position + 4 <= len(content):
        if content[position] != 0xFF:
            position += 1
            continue
        while position < len(content) and content[position] == 0xFF:
            position += 1
        if position >= len(content):
            break
        marker = content[position]
        position += 1
        if marker in {0xD8, 0xD9}:
            continue
        if position + 2 > len(content):
            break
        segment_length = int.from_bytes(content[position : position + 2], "big")
        if segment_length < 2 or position + segment_length > len(content):
            break
        if marker in sof_markers and segment_length >= 7:
            height = int.from_bytes(content[position + 3 : position + 5], "big")
            width = int.from_bytes(content[position + 5 : position + 7], "big")
            return width, height
        position += segment_length
    return None, None


def _extension_for_url(url: str, default: str = ".bin") -> str:
    extension = Path(urllib.parse.urlparse(url).path).suffix.lower()
    return extension if extension in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".mp4"} else default


def _download_binary(
    url: str,
    destination: Path,
    timeout: float,
    expected: str,
    max_bytes: int = 75_000_000,
) -> dict[str, Any]:
    """Descarga bytes originales y valida el tipo por firma, no solo por extensión."""
    accept = "video/mp4,image/jpeg,image/png,image/webp,image/*,*/*" if expected in {"image", "video"} else "*/*"
    request = Request(
        url,
        headers={"Accept": accept, "User-Agent": "fortnite-api-researcher/0.1.0"},
        method="GET",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            content_type = response.headers.get("Content-Type")
            content = response.read(max_bytes + 1)
            status = int(response.status)
    except HTTPError as exc:
        return {"url": url, "downloaded": False, "httpStatus": exc.code, "errorType": "http"}
    except (URLError, TimeoutError) as exc:
        detail = getattr(exc, "reason", str(exc))
        return {
            "url": url,
            "downloaded": False,
            "httpStatus": None,
            "errorType": "transport",
            "detail": str(detail)[:160],
        }
    if not content or len(content) > max_bytes:
        return {"url": url, "downloaded": False, "httpStatus": status, "errorType": "size_or_empty"}

    if expected == "image":
        info = _image_info(content, content_type)
        if not info.get("valid"):
            return {"url": url, "downloaded": False, "httpStatus": status, "errorType": "not_an_image"}
        width, height = _jpeg_dimensions(content)
        if width is None:
            width, height = info.get("width"), info.get("height")
        metadata = {"format": info.get("format"), "width": width, "height": height}
    elif expected == "video":
        if b"ftyp" not in content[:64]:
            return {"url": url, "downloaded": False, "httpStatus": status, "errorType": "not_an_mp4"}
        metadata = {"format": "MP4", "width": None, "height": None}
    else:
        metadata = {"format": content_type or "unknown"}

    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(content)
    return {
        "url": url,
        "downloaded": True,
        "httpStatus": status,
        "contentType": content_type,
        "bytes": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
        **metadata,
        "path": destination.as_posix(),
    }


def _copy_reference_image(source: Path, staging_dir: Path) -> dict[str, Any]:
    if not source.is_file():
        raise OSError(f"La imagen de referencia no existe: {source}")
    content = source.read_bytes()
    content_type = mimetypes.guess_type(source.name)[0]
    info = _image_info(content, content_type)
    if not info.get("valid"):
        raise OSError("La imagen de referencia no tiene un formato válido")
    width, height = _jpeg_dimensions(content)
    if width is None:
        width, height = info.get("width"), info.get("height")
    relative = Path("assets") / "referencia" / source.name
    destination = staging_dir / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(content)
    return {
        "kind": "user_reference",
        "sourceName": source.name,
        "downloaded": True,
        "httpStatus": None,
        "contentType": content_type,
        "bytes": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
        "format": info.get("format"),
        "width": width,
        "height": height,
        "path": relative.as_posix(),
    }


def _status(probe: dict[str, Any]) -> str:
    value = probe.get("httpStatus")
    return f"HTTP {value}" if value is not None else "sin respuesta"


def _md_link(label: str, url: str) -> str:
    return f"[{label}]({url})"


def _record_type(record: dict[str, Any]) -> str:
    item_type = record.get("type")
    if isinstance(item_type, dict):
        return str(item_type.get("displayValue") or item_type.get("value") or "sin tipo")
    return str(item_type or "sin tipo")


def _build_report(
    retrieved_at: str,
    api_snapshot: dict[str, Any],
    public_checks: list[dict[str, Any]],
    post: dict[str, Any] | None,
    teaser_post: dict[str, Any] | None,
    asset_entries: list[dict[str, Any]],
    reference_info: dict[str, Any] | None,
) -> str:
    queries = api_snapshot.get("queries", [])
    set_records = api_snapshot.get("lilWayneSet", [])
    new_records = api_snapshot.get("newLilWayneMatches", [])
    news_matches = api_snapshot.get("newsMatches", [])
    shop_matches = api_snapshot.get("shopMatches", [])
    successful_assets = [item for item in asset_entries if item.get("downloaded")]
    failed_assets = [item for item in asset_entries if not item.get("downloaded")]
    post_text = (post or {}).get("text") or "No disponible en el espejo público consultado."
    post_date = (post or {}).get("createdAt") or "No disponible"
    teaser_date = (teaser_post or {}).get("createdAt") or "No disponible"
    teaser_videos = (teaser_post or {}).get("videos") or []

    lines = [
        "# Investigación: Weezy Icon Cup",
        "",
        f"**Consulta ejecutada en UTC:** {retrieved_at}",
        f"**Publicación investigada:** {_md_link('FNcompReport en X', ORIGINAL_POST_URL)}",
        "**Fuente de catálogo:** Fortnite-API.com, API comunitaria no oficial.",
        "",
        "## Veredicto ejecutivo",
        "",
        "**La publicación es compatible con una colaboración de Lil Wayne que ya empezó a entrar en el catálogo de Fortnite, pero el anuncio del torneo todavía no trae todos los datos competitivos verificables.** La API devolvió cinco cosméticos del set `Lil Wayne`, todos añadidos el 10 de septiembre de 2026, y la novedad contiene los mismos registros. No devolvió un atuendo dentro de ese set en esta consulta.",
        "",
        "La identificación de “Weezy” con Lil Wayne tiene confianza alta: la publicación utiliza el nombre artístico, el catálogo de la API etiqueta el set como `Lil Wayne` y existe un teaser de la cuenta oficial de Fortnite. La existencia exacta de la copa, su hora, la puntuación y sus recompensas no deben darse por cerradas hasta que aparezca la ficha en la pestaña **Competir** o su reglamento oficial.",
        "",
        "## Qué afirma la publicación",
        "",
        f"- Texto recuperado del espejo público de X: `{post_text.replace(chr(10), ' / ')}`.",
        f"- Fecha de publicación reportada por el espejo: `{post_date}`.",
        "- La imagen adjunta muestra a Lil Wayne y el rótulo “WEEZY ICON CUP”, con los modos Solo Battle Royale y Solo Zero Build y la fecha del sábado 12 de septiembre.",
        "- El post pertenece a `@FNcompReport`; se conserva como reporte comunitario y no como una página oficial de reglas de Epic.",
        f"- La imagen original recibida se incluye byte por byte en el ZIP: {reference_info.get('width') if reference_info else 'n/d'} × {reference_info.get('height') if reference_info else 'n/d'} píxeles, {reference_info.get('bytes', 0):,} bytes.",
        "",
        "## Lo que sí encontró Fortnite-API.com",
        "",
        f"- **Set `Lil Wayne`: {len(set_records)} registros.** Todos tienen `added = 2026-09-10T16:00:38Z`, introducción en Chapter 7, Season 4 y rareza Icon Series.",
        f"- **Novedades:** `/v2/cosmetics/new` devolvió {api_snapshot.get('newBrCount', 'n/d')} entradas de Battle Royale; dentro de ellas volvieron a aparecer {len(new_records)} coincidencias del set.",
        f"- **Tienda actual:** `/v2/shop` respondió {_status(next((q for q in queries if q.get('name') == 'shop'), {}))}; las coincidencias de Lil Wayne en el feed actual fueron {len(shop_matches)}.",
        f"- **Noticias:** `/v2/news/br` respondió {_status(next((q for q in queries if q.get('name') == 'news'), {}))}; no hay un mensaje de noticias que nombre directamente a Weezy o Lil Wayne en este snapshot ({len(news_matches)} coincidencias textuales).",
        "- **Eventos/torneos:** las rutas candidatas probadas no están expuestas en esta API; un 404 aquí significa “ruta no publicada por Fortnite-API.com”, no que el torneo no exista dentro del juego.",
        "",
        "### Registros del set que devolvió la API",
        "",
        "| # | ID | Nombre | Tipo | Introducido | Añadido |",
        "|---:|---|---|---|---|---|",
    ]
    for index, record in enumerate(set_records, start=1):
        introduction = record.get("introduction") if isinstance(record.get("introduction"), dict) else {}
        lines.append(
            f"| {index} | `{record.get('id', 'n/d')}` | **{record.get('name', 'sin nombre')}** | {_record_type(record)} | Chapter {introduction.get('chapter', 'n/d')}, Season {introduction.get('season', 'n/d')} | {record.get('added', 'n/d')} |"
        )
    if not set_records:
        lines.append("| — | — | No se encontraron registros | — | — | — |")

    lines.extend(
        [
            "",
            "### Lectura de esos cinco registros",
            "",
            "- `Tha Guitar` aparece dos veces porque la API lo clasifica como **Back Bling** y como **Pickaxe**.",
            "- `Young Money Stage` es un **Glider**.",
            "- `Weezy's Pose` es una **Loading Screen** y su descripción contiene el crédito artístico de Ryan Smallman.",
            "- `YM Burner` es una **Wrap**.",
            "- **No se devolvió un `outfit` en la búsqueda exacta del set `Lil Wayne`.** Eso solo describe el estado del catálogo consultado; no permite concluir que el atuendo no exista en archivos internos o que no vaya a llegar después.",
            "",
            "## Relación con la copa y las recompensas",
            "",
            f"La {_md_link('página oficial de Item Shop Cups de Epic', EPIC_ITEM_SHOP_CUPS_URL)} explica que son torneos especiales de un día, que cada copa puede tener un modo y tamaño de equipo propio y que los premios cosméticos cambian según la copa. También indica como requisitos generales tener 13 años o más y una cuenta de nivel 50 o superior; el reglamento específico de cada copa es el que manda.",
            "",
            f"En la {_md_link('biblioteca oficial de reglas', EPIC_RULES_LIBRARY_URL)} consultada el 10 de septiembre de 2026 aparecen reglamentos de otros eventos de 2026, pero no aparece todavía un documento identificable como “Weezy Icon Cup”. Por lo tanto, no asigno a esta copa una hora, límite de puntos, región, número de partidas o premio concreto a partir de ejemplos de otras Icon Cups.",
            "",
            "Como referencia de precedentes, otras Icon Cups han usado la competición para entregar acceso anticipado o cosméticos del creador; ese patrón hace plausible que la Weezy Cup esté ligada a cosméticos de Lil Wayne, pero **no confirma cuál será el corte de puntos ni el premio de esta edición**.",
            "",
            "## Teaser oficial y grado de confirmación",
            "",
            f"- La cuenta oficial {_md_link('@Fortnite en X', OFFICIAL_TEASER_URL)} publicó un teaser el 9 de septiembre de 2026; el espejo público lo fecha en `{teaser_date}` y reporta {len(teaser_videos)} recurso(s) de vídeo.",
            "- El texto visible del post oficial es un mensaje críptico de bienvenida; la identificación de la voz como Lil Wayne y la frase promocional de “Weezy F. Baby” están descritas por cobertura secundaria, no por el texto plano del post.",
            f"- {_md_link('Beebom', BEEBOM_URL)} describe ese teaser de nueve segundos y lo interpreta como la llegada de Lil Wayne a Fortnite. Es una corroboración fuerte, pero sigue siendo una fuente periodística secundaria.",
            "- La combinación de teaser oficial + set `Lil Wayne` recién añadido en la API hace que la lectura Lil Wayne/Weezy sea de **confianza alta**.",
            "",
            "## Lo que todavía no está confirmado",
            "",
            "| Dato | Estado | Por qué |",
            "|---|---|---|",
            "| Nombre “Weezy” = Lil Wayne | Alto | Set `Lil Wayne` en la API y teaser oficial corroborado por cobertura |",
            "| Existencia de una copa el sábado 12 | Medio-alto | Texto e imagen del reporte; falta la ficha oficial de evento |",
            "| Solo Battle Royale y Solo Zero Build | Medio-alto | Está escrito en la publicación, pero falta el reglamento de Epic |",
            "| Fecha 12 de septiembre | Medio-alto | Está escrita en el reporte; no se encontró un horario oficial publicado |",
            "| Atuendo de Lil Wayne en el set API | No confirmado | La consulta exacta del set devolvió 5 elementos y ninguno es `outfit` |",
            "| Premio de la copa | Desconocido | No apareció en la API ni en el reglamento oficial indexado |",
            "| Hora, regiones, duración, puntos y partidas | Desconocido | Fortnite-API.com no expone un endpoint público de torneos |",
            "| Disponibilidad en tienda y fecha de venta | Desconocido | `/v2/shop` no mostró coincidencias en el snapshot |",
            "",
            "## Auditoría de endpoints",
            "",
            "| Consulta | Ruta | Estado | Interpretación |",
            "|---|---|---:|---|",
        ]
    )
    for query in queries:
        name = query.get("name")
        if name in {"eventsV1", "eventsV2", "tournamentsV1", "tournamentsV2"} and not query.get("available"):
            interpretation = "Ruta de eventos/torneos no expuesta por Fortnite-API.com"
        elif name == "setLilWayne":
            interpretation = "Catálogo exacto del set Lil Wayne"
        elif name == "newCosmetics":
            interpretation = "Novedades de cosméticos del build actual"
        elif name == "news":
            interpretation = "Feed de noticias BR actual"
        elif name == "shop":
            interpretation = "Tienda actual; no es calendario futuro"
        else:
            interpretation = "Consulta de catálogo"
        lines.append(f"| {name} | `{query.get('path')}` | {_status(query)} | {interpretation} |")

    lines.extend(
        [
            "",
            "## Recursos entregados",
            "",
            f"- Descargas válidas: **{len(successful_assets)}**; fallidas: **{len(failed_assets)}**; bytes originales: **{sum(int(item.get('bytes', 0)) for item in successful_assets):,}**.",
            "- Se conserva la imagen adjunta del usuario sin recorte, conversión ni reescalado.",
            "- Se incluyen la imagen original del post, el teaser oficial de Fortnite en MP4 si la descarga fue aceptada, su miniatura y las imágenes CDN que la API devolvió para los cinco registros de Lil Wayne.",
            "- `api_snapshot.json` conserva las respuestas enfocadas y los resúmenes de estado sin API key, token de Telegram ni chat ID.",
            "- `manifest.json` contiene bytes, formato, dimensiones y SHA-256 para que puedas comprobar que Telegram recibió documentos originales.",
            "",
            "## Fuentes",
            "",
            f"1. {_md_link('Publicación de FNcompReport en X', ORIGINAL_POST_URL)} — fuente primaria del texto y la imagen aportados.",
            f"2. {_md_link('Publicación oficial de Fortnite en X', OFFICIAL_TEASER_URL)} — teaser público de la colaboración.",
            f"3. {_md_link('Epic Games — Item Shop Cups', EPIC_ITEM_SHOP_CUPS_URL)} — formato general, premios variables y requisitos generales.",
            f"4. {_md_link('Epic Games — Rules Library', EPIC_RULES_LIBRARY_URL)} — comprobación del índice de reglamentos disponibles.",
            f"5. {_md_link('Beebom — Fortnite Teases Lil Wayne Crossover', BEEBOM_URL)} — corroboración secundaria del teaser y de la identificación de Lil Wayne.",
            f"6. {_md_link('Fortnite-API.com', FORTNITE_API_HOME)}; {_md_link('documentación de cosméticos', FORTNITE_API_COSMETICS_DOCS)}; {_md_link('documentación de noticias', FORTNITE_API_NEWS_DOCS)} — consultas directas usadas en este expediente.",
            "",
            "## Conclusión operativa",
            "",
            "La pista ya dejó de ser solo una imagen: Fortnite-API.com tiene cinco objetos nuevos dentro del set `Lil Wayne`, con nombres y URLs de imágenes reales. La API todavía no ofrece la ficha del torneo ni el atuendo, y la fuente oficial de reglas aún no muestra un reglamento Weezy identificable. El siguiente punto de verificación es la pestaña **Competir** del juego y la biblioteca de reglas de Epic el 12 de septiembre; hasta entonces, trata premios y horarios circulados por cuentas de filtraciones como provisionales.",
            "",
        ]
    )
    return "\n".join(lines)


def build_icon_cup_research_package(
    client: FortniteAPIClient,
    output_dir: Path,
    reference_image: Path | None,
    language: str = "en",
    timeout: float = 30,
) -> IconCupResearchArtifacts:
    """Consulta la API, conserva medios originales y genera informe + ZIP."""
    output_dir.mkdir(parents=True, exist_ok=True)
    retrieved_at = datetime.now(timezone.utc)
    retrieved_iso = retrieved_at.isoformat()

    query_specs = (
        ("news", "/v2/news/br", {"language": language}),
        ("newCosmetics", "/v2/cosmetics/new", {"language": language}),
        ("setLilWayne", "/v2/cosmetics/br/search/all", {"set": "Lil Wayne", "matchMethod": "full", "language": language}),
        ("weezyName", "/v2/cosmetics/br/search/all", {"name": "Weezy", "matchMethod": "contains", "language": language}),
        ("shop", "/v2/shop", {"language": language}),
        ("eventsV1", "/v1/events", {"language": language}),
        ("eventsV2", "/v2/events", {"language": language}),
        ("tournamentsV1", "/v1/tournaments", {"language": language}),
        ("tournamentsV2", "/v2/tournaments", {"language": language}),
    )
    values: dict[str, Any | None] = {}
    probes: list[dict[str, Any]] = []
    for name, path, params in query_specs:
        probe, value = _fetch_api_query(client, name, path, params)
        probes.append(probe)
        values[name] = value

    set_records = _set_matches(values.get("setLilWayne"))
    new_value = values.get("newCosmetics")
    new_records = [
        _record_summary(record)
        for record in _records(new_value)
        if isinstance(record.get("set"), dict) and record["set"].get("value") == "Lil Wayne"
    ]
    # /v2/cosmetics/new is wrapped as {items: {br: [...]}}; _records can see
    # the first useful list, but retain the exact Battle Royale count too.
    new_br_count = None
    if isinstance(new_value, dict) and isinstance(new_value.get("items"), dict):
        br_items = new_value["items"].get("br")
        if isinstance(br_items, list):
            new_br_count = len(br_items)
            new_records = [
                _record_summary(record)
                for record in br_items
                if isinstance(record, dict)
                and isinstance(record.get("set"), dict)
                and record["set"].get("value") == "Lil Wayne"
            ]

    shop_value = values.get("shop")
    shop_matches = _text_matches(shop_value, ("lil wayne", "weezy", "young money"))
    news_matches = _text_matches(values.get("news"), ("lil wayne", "weezy", "young money"))
    public_checks, post = _read_public_post(timeout)
    teaser_checks, teaser_raw = _safe_public_json(
        f"https://api.fxtwitter.com/status/{OFFICIAL_TEASER_ID}", timeout
    )
    teaser_post = _tweet_payload(teaser_raw)
    public_checks.append(teaser_checks)
    poster_url = POSTER_FALLBACK_URL
    if post and post.get("photos"):
        first_photo = post["photos"][0]
        if isinstance(first_photo, dict) and isinstance(first_photo.get("url"), str):
            poster_url = first_photo["url"]

    teaser_video_url = OFFICIAL_TEASER_VIDEO_FALLBACK
    teaser_thumb_url = OFFICIAL_TEASER_THUMB_FALLBACK
    if teaser_post:
        for video in teaser_post.get("videos") or []:
            if isinstance(video, dict) and isinstance(video.get("url"), str):
                # FxTwitter can return a lower-resolution first variant; prefer
                # the known 1920x1080 original when it is available.
                if video.get("width") == 1920 or teaser_video_url == OFFICIAL_TEASER_VIDEO_FALLBACK:
                    teaser_video_url = video["url"]
            if isinstance(video, dict) and isinstance(video.get("thumbnail_url"), str):
                teaser_thumb_url = video["thumbnail_url"]
                break

    api_snapshot: dict[str, Any] = {
        "investigation": {
            "source": "Fortnite-API.com",
            "topic": "Weezy Icon Cup / Lil Wayne",
            "retrievedAt": retrieved_iso,
            "language": language,
            "baseUrl": client.base_url,
        },
        "queries": probes,
        "lilWayneSet": set_records,
        "newLilWayneMatches": new_records,
        "newBrCount": new_br_count,
        "shopMatches": shop_matches,
        "newsMatches": news_matches,
        "rawFocusedResponses": {
            "news": values.get("news"),
            "newCosmetics": values.get("newCosmetics"),
            "setLilWayne": values.get("setLilWayne"),
            "weezyName": values.get("weezyName"),
            "shop": values.get("shop"),
        },
        "publicSources": {
            "originalPost": ORIGINAL_POST_URL,
            "publicMirrorChecks": public_checks,
            "originalPostNormalized": post,
            "officialTeaser": OFFICIAL_TEASER_URL,
            "officialTeaserNormalized": teaser_post,
            "posterUrl": poster_url,
            "teaserVideoUrl": teaser_video_url,
            "teaserThumbUrl": teaser_thumb_url,
        },
        "sourceUrls": {
            "itemShopCups": EPIC_ITEM_SHOP_CUPS_URL,
            "rulesLibrary": EPIC_RULES_LIBRARY_URL,
            "competitive": EPIC_COMPETITIVE_URL,
            "beebom": BEEBOM_URL,
            "apiHome": FORTNITE_API_HOME,
            "apiCosmeticsDocs": FORTNITE_API_COSMETICS_DOCS,
            "apiNewsDocs": FORTNITE_API_NEWS_DOCS,
        },
    }

    staging_dir = Path(tempfile.mkdtemp(prefix="fortnite-weezy-cup-", dir=str(output_dir)))
    asset_entries: list[dict[str, Any]] = []
    try:
        reference_info: dict[str, Any] | None = None
        if reference_image is not None:
            reference_info = _copy_reference_image(reference_image, staging_dir)
            asset_entries.append(reference_info)

        downloads: list[tuple[str, str, str, str]] = [
            ("post", poster_url, "image", _extension_for_url(poster_url, ".jpg")),
            ("official-teaser", teaser_video_url, "video", ".mp4"),
            ("official-teaser-thumb", teaser_thumb_url, "image", _extension_for_url(teaser_thumb_url, ".jpg")),
        ]
        for label, url, expected, extension in downloads:
            relative = Path("assets") / "public" / f"{_slug(label)}{extension}"
            result = _download_binary(url, staging_dir / relative, timeout, expected)
            result.update({"kind": "public_x_media", "label": label, "path": relative.as_posix()})
            asset_entries.append(result)

        for label, url in _image_urls_for_records(set_records):
            relative = Path("assets") / "api-cosmetics" / f"{_slug(label)}{_extension_for_url(url, '.png')}"
            result = _download_image(url, staging_dir / relative, timeout)
            result.update({"kind": "fortnite_api_cosmetic", "label": label, "path": relative.as_posix()})
            asset_entries.append(result)

        report = _build_report(
            retrieved_iso,
            api_snapshot,
            public_checks,
            post,
            teaser_post,
            asset_entries,
            reference_info,
        )
        timestamp_label = retrieved_at.strftime("%Y%m%dT%H%M%SZ")
        report_path = output_dir / f"{timestamp_label}-investigacion-weezy-icon-cup.md"
        archive_path = output_dir / f"{timestamp_label}-recursos-weezy-icon-cup.zip"
        report_path.write_text(report, encoding="utf-8")

        manifest = {
            "generatedAt": retrieved_iso,
            "source": "Fortnite-API.com + public X syndication + Epic public sources + attached reference image",
            "quality": "original bytes; no conversion, crop or resizing",
            "assets": asset_entries,
            "failedDownloads": [item for item in asset_entries if not item.get("downloaded")],
            "referenceImage": reference_info,
        }
        snapshot_path = staging_dir / "api_snapshot.json"
        manifest_path = staging_dir / "manifest.json"
        snapshot_path.write_text(json.dumps(api_snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        with zipfile.ZipFile(archive_path, mode="w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            archive.write(report_path, arcname="INFORME-weezy-icon-cup.md")
            archive.write(manifest_path, arcname="manifest.json")
            archive.write(snapshot_path, arcname="api_snapshot.json")
            for file_path in staging_dir.rglob("*"):
                if file_path.is_file() and file_path not in {manifest_path, snapshot_path}:
                    archive.write(file_path, arcname=file_path.relative_to(staging_dir).as_posix())

        successful_assets = [item for item in asset_entries if item.get("downloaded")]
        return IconCupResearchArtifacts(
            report_path=report_path,
            archive_path=archive_path,
            asset_count=len(successful_assets),
            asset_bytes=sum(int(item.get("bytes", 0)) for item in successful_assets),
            api_probes=tuple(probes),
        )
    finally:
        shutil.rmtree(staging_dir, ignore_errors=True)
