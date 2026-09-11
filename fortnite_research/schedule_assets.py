"""Investiga calendarios de colaboraciones y empaqueta sus recursos originales.

La API de Fortnite expone cosméticos y sus imágenes CDN, pero no publica un
calendario futuro oficial de la tienda. Este módulo conserva esa diferencia:
separa coincidencias reales de la API, evidencia oficial y fechas de terceros.
"""

from __future__ import annotations

import hashlib
import json
import mimetypes
import re
import tempfile
import unicodedata
import urllib.parse
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .client import FortniteAPIClient, FortniteAPIError


@dataclass(frozen=True)
class Target:
    key: str
    label: str
    date: str
    name_query: str
    set_queries: tuple[str, ...]
    shop_keywords: tuple[str, ...]
    date_assessment: str
    notes: str
    sources: tuple[tuple[str, str], ...]


TARGETS: tuple[Target, ...] = (
    Target(
        key="champion-pj",
        label="Champion PJ",
        date="2026-09-09",
        name_query="Champion PJ",
        set_queries=(),
        shop_keywords=("champion pj", "character_waywardrebelfncs"),
        date_assessment=(
            "No confirmada para el 9 de septiembre. La API sí identifica el "
            "cosmético, pero el feed actual no muestra una fecha futura; la "
            "predicción comunitaria consultada apuntaba al 13 de septiembre."
        ),
        notes=(
            "La fuente oficial confirma el FNCS Cup y el premio Champion PJ; "
            "eso no demuestra una salida en la tienda el 9 de septiembre de 2026."
        ),
        sources=(
            (
                "Página oficial del Champion PJ FNCS Cup",
                "https://www.fortnite.com/competitive/events/s37_pj/schedule?lang=en-US",
            ),
            (
                "Anuncio oficial del Champion PJ FNCS Cup",
                "https://www.fortnite.com/news/get-fortnite-twitch-drops-and-compete-in-the-champion-pj-fncs-cup",
            ),
            (
                "Predicción comunitaria FNForecast (no oficial)",
                "https://www.fnforecast.app/?set=FNCS",
            ),
        ),
    ),
    Target(
        key="mega-man",
        label="Mega Man",
        date="2026-09-10",
        name_query="Mega Man",
        set_queries=("Mega Man",),
        shop_keywords=("mega man", "mega buster", "character_dunebrief"),
        date_assessment=(
            "Fuertemente respaldada por una fuente comunitaria de calendario, "
            "pero no confirmada por una página oficial con esa fecha exacta."
        ),
        notes=(
            "La API contiene el set completo de 13 registros y los añadió en "
            "la actualización del 7 de septiembre. Epic confirma que Mega Man "
            "llega a la tienda durante la temporada Override."
        ),
        sources=(
            (
                "Artículo oficial Fortnite Override",
                "https://www.fortnite.com/news/fortnite-override-break-the-rules-change-the-game",
            ),
            (
                "Calendario comunitario con fecha del 10 de septiembre (no oficial)",
                "https://t.me/s/brasilfortnite",
            ),
            (
                "Cobertura de colaboraciones y filtraciones (no oficial)",
                "https://www.vice.com/en/article/fortnite-override-trailer-chapter-7-season-4-collabs/",
            ),
        ),
    ),
    Target(
        key="cadillac-ct5-v-blackwing",
        label="Cadillac CT5-V Blackwing",
        date="2026-09-10",
        name_query="Cadillac CT5-V Blackwing",
        set_queries=("Blackwing", "CT5"),
        shop_keywords=("cadillac ct5", "ct5-v", "blackwing"),
        date_assessment=(
            "Fecha comunitaria/no oficial: la referencia consultada la sitúa "
            "el 10 de septiembre, pero no hay confirmación de Epic ni registro "
            "del vehículo en Fortnite-API."
        ),
        notes=(
            "El catálogo de coches consultado sí devuelve un Cadillac DeVille "
            "de 1966, pero no CT5, CT5-V ni Blackwing. Por eso no se descarga "
            "una imagen de Fortnite inventada o tomada de otro vehículo."
        ),
        sources=(
            (
                "Calendario comunitario con fecha del 10 de septiembre (no oficial)",
                "https://t.me/s/brasilfortnite",
            ),
            (
                "Referencia del datamining de la colaboración (no oficial)",
                "https://t.me/s/FortniteNews",
            ),
            (
                "Página oficial del Cadillac CT5-V Blackwing (vehículo real)",
                "https://www.cadillac.com/performance/ct5-v-blackwing",
            ),
        ),
    ),
    Target(
        key="overwatch",
        label="Overwatch",
        date="2026-09-11",
        name_query="Overwatch",
        set_queries=("Overwatch",),
        shop_keywords=("overwatch", "mercy", "tracer", "genji", "d.va"),
        date_assessment=(
            "No confirmada para el 11 de septiembre. El set está confirmado "
            "en la API, pero la fuente oficial fecha su lanzamiento original "
            "el 14 de mayo de 2026."
        ),
        notes=(
            "Se encontró el set completo de 27 registros: cuatro outfits, "
            "accesorios, emotes, sprays, envoltura y pantallas de carga."
        ),
        sources=(
            (
                "Artículo oficial Fortnite x Overwatch",
                "https://www.fortnite.com/news/answer-the-call-overwatch-heroes-join-the-showdown-in-act-iii",
            ),
            (
                "Tráiler oficial de gameplay en YouTube",
                "https://www.youtube.com/watch?v=YJI7gpRzxjc",
            ),
            (
                "Artículo oficial de Overwatch sobre la colaboración",
                "https://overwatch.blizzard.com/en-us/news/24103213/",
            ),
        ),
    ),
    Target(
        key="wolverine",
        label="Wolverine",
        date="2026-09-14",
        name_query="Wolverine",
        set_queries=("Wolverine", "Deadpool & Wolverine"),
        shop_keywords=("wolverine", "hightowerwasabi", "olive stomp"),
        date_assessment=(
            "No confirmada para el 14 de septiembre. La API conserva los "
            "cosméticos, pero no ofrece una fecha futura de tienda para ellos."
        ),
        notes=(
            "Se incluyen los 22 registros del set Wolverine y los registros "
            "relacionados encontrados en Deadpool & Wolverine, claramente "
            "marcados en el manifiesto."
        ),
        sources=(
            (
                "Artículo oficial del lanzamiento original de Wolverine",
                "https://www.fortnite.com/news/wolverine-is-coming-to-fortnite",
            ),
            (
                "Anuncio oficial del Champion PJ Cup que documenta premios FNCS",
                "https://www.fortnite.com/news/get-fortnite-twitch-drops-and-compete-in-the-champion-pj-fncs-cup",
            ),
        ),
    ),
    Target(
        key="hiroshi-jackson",
        label="Hiroshi Jackson",
        date="2026-09-15",
        name_query="Hiroshi Jackson",
        set_queries=("Hiroshi Jackson", "Screamer"),
        shop_keywords=("hiroshi jackson", "hiroshi", "screamer"),
        date_assessment=(
            "No confirmada. La mención encontrada procede de cobertura de "
            "filtraciones de la temporada y no trae fecha oficial de tienda."
        ),
        notes=(
            "No apareció un cosmético Hiroshi Jackson ni un set Screamer en "
            "Fortnite-API al consultar nombre, set, novedades y tienda actual; "
            "por eso no se adjunta un supuesto banner o skin de Fortnite."
        ),
        sources=(
            (
                "Cobertura de la colaboración Screamer/Hiroshi (no oficial)",
                "https://www.vice.com/en/article/fortnite-override-trailer-chapter-7-season-4-collabs/",
            ),
            (
                "Referencia comunitaria de key art filtrado (no oficial)",
                "https://t.me/s/brasilfortnite",
            ),
        ),
    ),
)


@dataclass(frozen=True)
class ScheduleArtifacts:
    report_path: Path
    archive_path: Path
    asset_count: int
    asset_bytes: int
    target_counts: dict[str, int]


def _data(payload: Any) -> Any:
    if isinstance(payload, dict) and "data" in payload:
        return payload["data"]
    return payload


def _slug(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
    clean = re.sub(r"[^a-zA-Z0-9.-]+", "-", ascii_value).strip("-").lower()
    return clean or "asset"


def _compact_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).casefold()


def _query(
    client: FortniteAPIClient,
    path: str,
    params: dict[str, str],
) -> tuple[dict[str, Any], Any | None]:
    try:
        result = client.get(path, params)
    except FortniteAPIError as exc:
        return (
            {
                "path": path,
                "params": params,
                "httpStatus": exc.status_code,
                "available": False,
                "errorType": "api_error",
            },
            None,
        )
    value = _data(result.payload)
    count = len(value) if isinstance(value, (list, dict)) else None
    return (
        {
            "path": path,
            "params": params,
            "httpStatus": result.status_code,
            "available": True,
            "dataType": type(value).__name__,
            "count": count,
        },
        value,
    )


def _as_records(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        for key in ("items", "cosmetics", "entries", "data"):
            nested = value.get(key)
            if isinstance(nested, list):
                return [item for item in nested if isinstance(item, dict)]
    return []


def _record_summary(record: dict[str, Any]) -> dict[str, Any]:
    selected = (
        "id",
        "name",
        "description",
        "type",
        "rarity",
        "series",
        "set",
        "added",
        "lastAppearance",
        "introduction",
        "video",
        "images",
    )
    return {key: record[key] for key in selected if key in record}


def _walk_urls(value: Any, prefix: str = "images") -> Iterable[tuple[str, str]]:
    if isinstance(value, str) and value.startswith(("http://", "https://")):
        yield prefix, value
        return
    if isinstance(value, dict):
        for key, child in value.items():
            yield from _walk_urls(child, f"{prefix}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _walk_urls(child, f"{prefix}[{index}]")


def _record_image_urls(record: dict[str, Any]) -> list[tuple[str, str]]:
    images = record.get("images")
    unique: list[tuple[str, str]] = []
    seen: set[str] = set()
    for field, url in _walk_urls(images):
        if url not in seen:
            seen.add(url)
            unique.append((field, url))
    return unique


def _collect_matching_dicts(value: Any, keywords: tuple[str, ...], limit: int = 50) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    normalized = tuple(keyword.casefold() for keyword in keywords)

    def visit(node: Any) -> None:
        if len(matches) >= limit:
            return
        if isinstance(node, dict):
            encoded = _compact_text(node)
            if any(keyword in encoded for keyword in normalized) and ("id" in node or "name" in node):
                identity = str(node.get("id") or node.get("name") or encoded[:100])
                if identity not in seen_ids:
                    seen_ids.add(identity)
                    matches.append(_record_summary(node))
            for child in node.values():
                visit(child)
        elif isinstance(node, list):
            for child in node:
                visit(child)

    visit(value)
    return matches


def _shop_matches(value: Any, keywords: tuple[str, ...]) -> list[dict[str, Any]]:
    entries = value.get("entries", []) if isinstance(value, dict) else []
    matches: list[dict[str, Any]] = []
    for entry in entries if isinstance(entries, list) else []:
        if not isinstance(entry, dict):
            continue
        encoded = _compact_text(entry)
        if not any(keyword.casefold() in encoded for keyword in keywords):
            continue
        names: list[str] = []
        for item in entry.get("brItems", []):
            if isinstance(item, dict) and item.get("name"):
                names.append(str(item["name"]))
        matches.append(
            {
                "offerId": entry.get("offerId"),
                "devName": entry.get("devName"),
                "names": names,
                "inDate": entry.get("inDate"),
                "outDate": entry.get("outDate"),
            }
        )
    return matches


def _new_matches(value: Any, keywords: tuple[str, ...]) -> list[dict[str, Any]]:
    return _collect_matching_dicts(value, keywords, limit=30)


def _banner_matches(value: Any, keywords: tuple[str, ...]) -> list[dict[str, Any]]:
    return _collect_matching_dicts(value, keywords, limit=30)


def _public_status(url: str, timeout: float) -> dict[str, Any]:
    request = Request(
        url,
        headers={"Accept": "application/json", "User-Agent": "fortnite-api-researcher/0.1.0"},
        method="GET",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            response.read(64)
            return {"url": url, "httpStatus": int(response.status), "available": True}
    except HTTPError as exc:
        return {"url": url, "httpStatus": exc.code, "available": False}
    except (URLError, TimeoutError):
        return {"url": url, "httpStatus": None, "available": False, "errorType": "transport"}


def _image_info(content: bytes, content_type: str | None) -> dict[str, Any]:
    kind = (content_type or "").split(";", 1)[0].lower()
    if content.startswith(b"\x89PNG\r\n\x1a\n") and len(content) >= 24:
        width = int.from_bytes(content[16:20], "big")
        height = int.from_bytes(content[20:24], "big")
        return {"valid": True, "format": "PNG", "width": width, "height": height}
    if content.startswith(b"\xff\xd8\xff"):
        return {"valid": True, "format": "JPEG", "width": None, "height": None}
    if content.startswith(b"GIF8"):
        return {"valid": True, "format": "GIF", "width": int.from_bytes(content[6:8], "little"), "height": int.from_bytes(content[8:10], "little")}
    if content.startswith(b"RIFF") and content[8:12] == b"WEBP":
        return {"valid": True, "format": "WEBP", "width": None, "height": None}
    return {"valid": False, "format": kind or "unknown", "width": None, "height": None}


def _download_image(url: str, destination: Path, timeout: float) -> dict[str, Any]:
    request = Request(
        url,
        headers={"Accept": "image/avif,image/webp,image/png,image/jpeg,*/*", "User-Agent": "fortnite-api-researcher/0.1.0"},
        method="GET",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            content_type = response.headers.get("Content-Type")
            content = response.read()
    except HTTPError as exc:
        return {"url": url, "downloaded": False, "httpStatus": exc.code, "errorType": "http"}
    except (URLError, TimeoutError) as exc:
        detail = getattr(exc, "reason", str(exc))
        return {"url": url, "downloaded": False, "httpStatus": None, "errorType": "transport", "detail": str(detail)[:120]}
    if not content or len(content) > 25_000_000:
        return {"url": url, "downloaded": False, "httpStatus": 200, "errorType": "size_or_empty"}
    info = _image_info(content, content_type)
    if not info["valid"]:
        return {"url": url, "downloaded": False, "httpStatus": 200, "errorType": "not_an_image"}
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(content)
    return {
        "url": url,
        "downloaded": True,
        "httpStatus": 200,
        "contentType": content_type,
        "bytes": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
        "format": info["format"],
        "width": info["width"],
        "height": info["height"],
        "path": destination.as_posix(),
    }


def _md_link(label: str, url: str) -> str:
    return f"[{label}]({url})"


def _record_names(records: list[dict[str, Any]], limit: int = 16) -> str:
    names = [str(item.get("name") or item.get("id") or "sin nombre") for item in records]
    if len(names) > limit:
        return ", ".join(names[:limit]) + f" … (+{len(names) - limit})"
    return ", ".join(names) if names else "ninguno"


def _build_report(
    retrieved_at: str,
    target_results: list[dict[str, Any]],
    api_probes: list[dict[str, Any]],
    archive_checks: list[dict[str, Any]],
    asset_entries: list[dict[str, Any]],
    shop_date: str | None,
) -> str:
    total_records = sum(len(item["records"]) for item in target_results)
    total_assets = sum(1 for item in asset_entries if item.get("downloaded"))
    total_bytes = sum(int(item.get("bytes", 0)) for item in asset_entries if item.get("downloaded"))
    lines = [
        "# Investigación de calendario, skins, imágenes, banners y vídeos de Fortnite",
        "",
        f"- Consulta ejecutada (UTC): {retrieved_at}",
        "- Año interpretado: 2026 porque la consulta se ejecutó el 9 de septiembre de 2026.",
        "- Fuente de datos principal: Fortnite-API.com, API comunitaria no oficial.",
        "- Documentación de endpoints: https://dash.fortnite-api.com/endpoints/cosmetics.",
        "- Regla de evidencia: una coincidencia en la API confirma que el recurso existe en el catálogo; no confirma por sí sola una fecha futura de tienda.",
        "",
        "## Resultado ejecutivo",
        "",
        f"- Registros de cosméticos relacionados encontrados: **{total_records}**.",
        f"- Imágenes originales CDN descargadas y validadas: **{total_assets}**.",
        f"- Tamaño total de imágenes dentro del ZIP: **{total_bytes:,} bytes**.",
        f"- Fecha del feed de tienda consultado: {shop_date or 'no disponible'}.",
        "- Ningún registro cosmético consultado expuso un vídeo directo en su campo video.",
        "- /v1/banners respondió correctamente, pero las coincidencias por estos nombres fueron banners de perfil: no se encontró un banner promocional de tienda asociado a la lista.",
        "",
        "## Resultado por fecha",
        "",
    ]
    for item in target_results:
        target: Target = item["target"]
        records: list[dict[str, Any]] = item["records"]
        relevant_assets = [
            asset for asset in asset_entries
            if asset.get("target") == target.key and asset.get("downloaded")
        ]
        video_values = sorted(
            {
                str(record.get("video"))
                for record in records
                if record.get("video")
            }
        )
        banner_count = len(item.get("banner_matches", []))
        banner_names = [
            str(banner.get("id") or banner.get("name") or "sin id")
            for banner in item.get("banner_matches", [])
        ]
        shop_count = len(item.get("shop_matches", []))
        lines.extend(
            [
                f"### {target.date} — {target.label}",
                "",
                f"- **Estado de la fecha:** {target.date_assessment}",
                f"- **Coincidencia en cosméticos:** {len(records)} registro(s).",
                f"- **Nombres/IDs encontrados:** {_record_names(records)}.",
                f"- **Imágenes originales:** {len(relevant_assets)} archivo(s) validados en el ZIP.",
                f"- **Vídeo en el registro API:** {'sí, ' + ', '.join(video_values) if video_values else 'no; el campo video llegó vacío o nulo.'}",
                f"- **Banners de perfil coincidentes:** {banner_count}{' — ' + ', '.join(banner_names) if banner_names else ''}.",
                f"- **Coincidencias en la tienda consultada:** {shop_count}.",
                f"- **Coincidencias en novedades actuales:** {len(item.get('new_matches', []))}.",
                f"- **Coincidencias en catálogo de coches:** {len(item.get('car_matches', []))}.",
                f"- **Lectura:** {target.notes}",
                "",
                "**Fuentes consultadas:**",
                "",
            ]
        )
        for label, url in target.sources:
            lines.append(f"- {_md_link(label, url)}")
        lines.append("")
    lines.extend(
        [
            "## Qué significa cada tipo de material",
            "",
            "- **Skin/cosmético:** son los registros reales devueltos por /v2/cosmetics/br/search/all; sus icon, featured y otros recursos se conservaron en bytes originales cuando existían.",
            "- **Coche:** se revisó /v2/cosmetics/cars; el Cadillac CT5-V Blackwing no apareció. El único Cadillac relacionado fue el DeVille de 1966, que no se mezcló con el resultado solicitado.",
            "- **Banner:** /v1/banners representa banners de perfil del jugador. No es un endpoint de calendario de banners publicitarios de la tienda.",
            "- **Vídeo:** los cosméticos no devolvieron un archivo de vídeo directo. El expediente enlaza los tráileres oficiales disponibles; el ZIP no contiene una descarga recomprimida de YouTube.",
            "",
            "## Estado del historial público de tienda",
            "",
            "| Fecha | Archivo histórico público | Estado |",
            "|---|---|---:|",
        ]
    )
    for check in archive_checks:
        date = check["url"].rsplit("/", 1)[-1].removesuffix(".json")
        status = check.get("httpStatus") if check.get("httpStatus") is not None else "sin respuesta"
        label = "disponible" if check.get("available") else "no publicado/no disponible"
        lines.append(f"| {date} | {_md_link('JSON histórico', check['url'])} | {status} — {label} |")
    lines.extend(
        [
            "",
            "La ausencia de un JSON futuro no demuestra que una fecha sea falsa: normalmente significa que ese snapshot todavía no se ha publicado. La API principal también expone principalmente el estado actual.",
            "",
            "## Endpoints consultados",
            "",
            "| Endpoint | Resultado |",
            "|---|---|",
        ]
    )
    for probe in api_probes:
        params = "&".join(f"{key}={value}" for key, value in probe.get("params", {}).items())
        query = f"{probe['path']}?{params}" if params else probe["path"]
        status = probe.get("httpStatus") if probe.get("httpStatus") is not None else "sin respuesta"
        result_label = "OK" if probe.get("available") else "no encontrado/error"
        lines.append(f"| {query} | {status} — {result_label} |")
    lines.extend(
        [
            "",
            "## Archivos entregados",
            "",
            "- INFORME-calendario-fortnite.md: este expediente con fechas, evidencia y enlaces.",
            "- RECURSOS-calendario-fortnite.zip: imágenes CDN originales, sin convertir a foto ni reducir dimensiones, más manifest.json y api_snapshot.json.",
            "- En el manifiesto, cada imagen incluye URL de origen, tamaño, formato, dimensiones cuando están disponibles y SHA-256.",
            "",
        ]
    )
    return "\n".join(lines)


def build_schedule_package(
    client: FortniteAPIClient,
    output_dir: Path,
    language: str = "en",
    timeout: float = 30,
) -> ScheduleArtifacts:
    """Consulta la API, descarga recursos originales y crea informe + ZIP."""
    output_dir.mkdir(parents=True, exist_ok=True)
    retrieved_at = datetime.now(timezone.utc)
    retrieved_iso = retrieved_at.isoformat()
    cache: dict[tuple[str, tuple[tuple[str, str], ...]], tuple[dict[str, Any], Any | None]] = {}
    api_probes: list[dict[str, Any]] = []

    def cached_query(path: str, params: dict[str, str]) -> Any | None:
        key = (path, tuple(sorted(params.items())))
        if key not in cache:
            probe, value = _query(client, path, params)
            cache[key] = (probe, value)
            api_probes.append(probe)
        return cache[key][1]

    cars_data = cached_query("/v2/cosmetics/cars", {"language": language})
    shop_data = cached_query("/v2/shop", {"language": language})
    new_data = cached_query("/v2/cosmetics/new", {"language": language})
    banners_data = cached_query("/v1/banners", {"language": language})

    target_results: list[dict[str, Any]] = []
    for target in TARGETS:
        records_by_id: dict[str, dict[str, Any]] = {}
        direct_params = {
            "name": target.name_query,
            "matchMethod": "contains",
            "language": language,
        }
        direct_data = cached_query("/v2/cosmetics/br/search/all", direct_params)
        for record in _as_records(direct_data):
            identity = str(record.get("id") or record.get("name") or "")
            if identity:
                records_by_id[identity] = record
        for set_query in target.set_queries:
            set_params = {
                "set": set_query,
                "matchMethod": "contains",
                "language": language,
            }
            set_data = cached_query("/v2/cosmetics/br/search/all", set_params)
            for record in _as_records(set_data):
                identity = str(record.get("id") or record.get("name") or "")
                if identity:
                    records_by_id[identity] = record
        target_results.append(
            {
                "target": target,
                "records": list(records_by_id.values()),
                "new_matches": _new_matches(new_data, target.shop_keywords),
                "banner_matches": _banner_matches(banners_data, target.shop_keywords),
                "shop_matches": _shop_matches(shop_data, target.shop_keywords),
                "car_matches": _collect_matching_dicts(
                    cars_data,
                    ("cadillac", "ct5", "blackwing")
                    if target.key == "cadillac-ct5-v-blackwing"
                    else (),
                    limit=20,
                ),
            }
        )

    archive_checks = [
        _public_status(
            f"https://raw.githubusercontent.com/Fortnite-Datamining/Fortnite-Datamining/history/shop/{target.date}.json",
            timeout,
        )
        for target in TARGETS
    ]
    unique_archive_checks: list[dict[str, Any]] = []
    seen_archive_urls: set[str] = set()
    for check in archive_checks:
        if check["url"] not in seen_archive_urls:
            seen_archive_urls.add(check["url"])
            unique_archive_checks.append(check)

    staging_dir = Path(tempfile.mkdtemp(prefix="fortnite-schedule-", dir=str(output_dir)))
    asset_entries: list[dict[str, Any]] = []
    used_urls: dict[str, str] = {}
    try:
        for item in target_results:
            target: Target = item["target"]
            for record in item["records"]:
                record_id = str(record.get("id") or record.get("name") or "sin-id")
                for field, url in _record_image_urls(record):
                    if url in used_urls:
                        asset_entries.append(
                            {
                                "target": target.key,
                                "recordId": record_id,
                                "field": field,
                                "url": url,
                                "downloaded": True,
                                "path": used_urls[url],
                                "duplicateOfUrl": True,
                            }
                        )
                        continue
                    extension = Path(urllib.parse.urlparse(url).path).suffix.lower()
                    if extension not in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
                        extension = ".png"
                    relative = Path("assets") / _slug(target.label) / _slug(record_id) / f"{_slug(field)}{extension}"
                    destination = staging_dir / relative
                    result = _download_image(url, destination, timeout)
                    result.update(
                        {
                            "target": target.key,
                            "recordId": record_id,
                            "recordName": record.get("name"),
                            "field": field,
                            "path": relative.as_posix(),
                        }
                    )
                    asset_entries.append(result)
                    if result.get("downloaded"):
                        used_urls[url] = relative.as_posix()

        for item in target_results:
            target: Target = item["target"]
            for banner in item["banner_matches"]:
                banner_id = str(banner.get("id") or banner.get("name") or "sin-id")
                for field, url in _record_image_urls(banner):
                    if url in used_urls:
                        asset_entries.append(
                            {
                                "target": target.key,
                                "recordId": banner_id,
                                "recordName": banner.get("name"),
                                "field": f"banner.{field}",
                                "url": url,
                                "downloaded": True,
                                "path": used_urls[url],
                                "duplicateOfUrl": True,
                            }
                        )
                        continue
                    extension = Path(urllib.parse.urlparse(url).path).suffix.lower()
                    if extension not in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
                        extension = ".png"
                    relative = (
                        Path("assets")
                        / _slug(target.label)
                        / "banners"
                        / _slug(banner_id)
                        / f"{_slug(field)}{extension}"
                    )
                    destination = staging_dir / relative
                    result = _download_image(url, destination, timeout)
                    result.update(
                        {
                            "target": target.key,
                            "recordId": banner_id,
                            "recordName": banner.get("name"),
                            "field": f"banner.{field}",
                            "path": relative.as_posix(),
                        }
                    )
                    asset_entries.append(result)
                    if result.get("downloaded"):
                        used_urls[url] = relative.as_posix()

        shop_date = shop_data.get("date") if isinstance(shop_data, dict) else None
        report = _build_report(
            retrieved_iso,
            target_results,
            api_probes,
            unique_archive_checks,
            asset_entries,
            shop_date,
        )
        timestamp_label = retrieved_at.strftime("%Y%m%dT%H%M%SZ")
        report_path = output_dir / f"{timestamp_label}-informe-calendario-fortnite.md"
        archive_path = output_dir / f"{timestamp_label}-recursos-calendario-fortnite.zip"
        report_path.write_text(report, encoding="utf-8")

        target_counts = {
            item["target"].key: len(item["records"])
            for item in target_results
        }
        api_snapshot = {
            "investigation": {
                "source": "Fortnite-API.com",
                "retrievedAt": retrieved_iso,
                "language": language,
                "dateAssumption": 2026,
            },
            "apiProbes": api_probes,
            "targets": [
                {
                    "key": item["target"].key,
                    "label": item["target"].label,
                    "date": item["target"].date,
                    "records": [_record_summary(record) for record in item["records"]],
                    "newMatches": item["new_matches"],
                    "bannerMatches": item["banner_matches"],
                    "shopMatches": item["shop_matches"],
                    "carMatches": item["car_matches"],
                }
                for item in target_results
            ],
            "publicShopHistoryChecks": unique_archive_checks,
        }
        manifest = {
            "generatedAt": retrieved_iso,
            "source": "Fortnite-API.com",
            "quality": "original CDN bytes; no photo conversion or resizing",
            "assets": asset_entries,
            "targets": target_counts,
            "failedDownloads": [
                asset for asset in asset_entries if not asset.get("downloaded")
            ],
        }
        snapshot_path = staging_dir / "api_snapshot.json"
        manifest_path = staging_dir / "manifest.json"
        snapshot_path.write_text(
            json.dumps(api_snapshot, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        with zipfile.ZipFile(
            archive_path,
            mode="w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=6,
        ) as archive:
            archive.write(report_path, arcname="INFORME-calendario-fortnite.md")
            archive.write(manifest_path, arcname="manifest.json")
            archive.write(snapshot_path, arcname="api_snapshot.json")
            for file_path in staging_dir.rglob("*"):
                if file_path.is_file() and file_path not in {manifest_path, snapshot_path}:
                    archive.write(file_path, arcname=file_path.relative_to(staging_dir).as_posix())
        successful_assets = [asset for asset in asset_entries if asset.get("downloaded")]
        return ScheduleArtifacts(
            report_path=report_path,
            archive_path=archive_path,
            asset_count=len(successful_assets),
            asset_bytes=sum(int(asset.get("bytes", 0)) for asset in successful_assets),
            target_counts=target_counts,
        )
    finally:
        for file_path in sorted(staging_dir.rglob("*"), reverse=True):
            if file_path.is_file() or file_path.is_symlink():
                file_path.unlink(missing_ok=True)
            elif file_path.is_dir():
                file_path.rmdir()
        staging_dir.rmdir()
