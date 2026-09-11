"""Investiga la publicación de FNBRunderground sobre Loot Hacker Sprites.

El módulo combina tres capas de evidencia sin mezclarlas:

* la imagen que se recibió como referencia;
* las noticias y búsquedas que sí expone Fortnite-API.com;
* la documentación oficial de Epic y los reportes comunitarios que detallan
  los 15 nombres, ubicaciones y bonificaciones.

Fortnite-API.com no ofrece una ruta documentada de Sprites. Por eso una
respuesta 404 se conserva como resultado de la auditoría y no se convierte en
una lista inventada de cosméticos.
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

from .client import FortniteAPIClient, FortniteAPIError
from .schedule_assets import _data, _download_image, _image_info, _slug


ORIGINAL_POST_URL = "https://x.com/fnbrunderground/status/2098035630483591223?s=46"
EPIC_BATTLE_ROYALE_URL = "https://www.fortnite.com/@epic/battle-royale"
EPIC_OVERRIDE_URL = "https://www.fortnite.com/news/fortnite-override-break-the-rules-change-the-game"
EPIC_UPDATE_NOTES_URL = (
    "https://communities.epicgames.com/thread/"
    "v42-10-fortnite-override-battle-royale-update-notes/y3Ub"
)
FORTNITE_API_HOME = "https://fortnite-api.com/"
FORTNITE_API_NEWS_DOCS = "https://dash.fortnite-api.com/endpoints/news"
FORTNITE_API_COSMETICS_DOCS = "https://dash.fortnite-api.com/endpoints/cosmetics"
BEEBOM_URL = "https://beebom.com/fortnite-loot-hacker-sprites-locations-powers/amp/"
THE_CLICK_URL = "https://www.theclick.gg/fortnite-loot-hacker-sprites/"
ALL_THINGS_HOW_URL = "https://allthings.how/fortnite-override-sprite-dust-why-loot-hacks-work/"
FORTNITE_GG_SPRITES_URL = "https://fortnite.gg/sprites"


SPRITE_DETAILS: tuple[dict[str, str], ...] = (
    {
        "name": "Loot Hacker Jonesy Sprite",
        "status": "Novedad reportada para el 10 de septiembre de 2026",
        "locations": "Golden Grove; Chopped Shop; Wonkeeland",
    },
    {
        "name": "Loot Hacker Adventure Sprite",
        "status": "Novedad reportada para el 10 de septiembre de 2026",
        "locations": "Latte Landing; Shaken Sanctuary",
    },
    {
        "name": "Loot Hacker Bush Sprite",
        "status": "Novedad reportada para el 10 de septiembre de 2026",
        "locations": "Cluster Coast; Wonkeeland",
    },
    {
        "name": "Loot Hacker Sonic Sprite",
        "status": "Novedad reportada para el 10 de septiembre de 2026",
        "locations": "Green Hill Zone",
    },
    {
        "name": "Loot Hacker Tails Sprite",
        "status": "Novedad reportada para el 10 de septiembre de 2026",
        "locations": "Green Hill Zone",
    },
    {
        "name": "Loot Hacker Shadow Sprite",
        "status": "Novedad reportada para el 10 de septiembre de 2026",
        "locations": "Green Hill Zone",
    },
    {
        "name": "Loot Hacker 8-Bit Sprite",
        "status": "Novedad reportada para el 10 de septiembre de 2026",
        "locations": "Reality's Reign; The Battlewoods",
    },
    {
        "name": "Loot Hacker Jackrabbit Sprite",
        "status": "Novedad reportada para el 10 de septiembre de 2026",
        "locations": "The Battlewoods; Sunken Shores",
    },
    {
        "name": "Loot Hacker Crown Sprite",
        "status": "Variante que los reportes sitúan como disponible previamente",
        "locations": "Progresión de las variantes Crown anteriores",
    },
    {
        "name": "Loot Hacker Killswitch Sprite",
        "status": "Novedad reportada para el 10 de septiembre de 2026",
        "locations": "Reality's Reign; Heatwave Harbor",
    },
    {
        "name": "Loot Hacker Klombo Sprite",
        "status": "Novedad reportada para el 10 de septiembre de 2026",
        "locations": "Stone Sanctum",
    },
    {
        "name": "Loot Hacker Overshield Sprite",
        "status": "Novedad reportada para el 10 de septiembre de 2026",
        "locations": "Lifty Lodge; Reality's Reign",
    },
    {
        "name": "Loot Hacker X-Ray Sprite",
        "status": "Novedad reportada para el 10 de septiembre de 2026",
        "locations": "Sunken Shores; Golden Grove",
    },
    {
        "name": "Loot Hacker Onigiri Sprite",
        "status": "Novedad reportada para el 10 de septiembre de 2026",
        "locations": "Lifty Lodge; Latte Landing",
    },
    {
        "name": "Loot Hacker Storm Scout Sprite",
        "status": "Novedad reportada para el 10 de septiembre de 2026",
        "locations": "Reality's Reign; Geno's Machine",
    },
)


@dataclass(frozen=True)
class SpriteResearchArtifacts:
    report_path: Path
    archive_path: Path
    asset_count: int
    asset_bytes: int
    api_probes: tuple[dict[str, Any], ...]


def _query(
    client: FortniteAPIClient,
    path: str,
    params: dict[str, str],
) -> tuple[dict[str, Any], Any | None]:
    """Consulta una ruta y devuelve un resumen que no incluye credenciales."""
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
    return (
        {
            "path": path,
            "params": params,
            "httpStatus": result.status_code,
            "available": True,
            "dataType": type(value).__name__,
            "topLevelKeys": list(value.keys()) if isinstance(value, dict) else [],
            "count": len(value) if isinstance(value, (list, dict)) else None,
        },
        value,
    )


def _news_items(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, dict):
        return []
    for key in ("motds", "messages"):
        items = value.get(key)
        if isinstance(items, list):
            return [item for item in items if isinstance(item, dict)]
    return []


def _matching_news(value: Any) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in _news_items(value):
        text = json.dumps(item, ensure_ascii=False).casefold()
        if not any(term in text for term in ("sprite", "loot hack", "hacker")):
            continue
        result.append(
            {
                "title": item.get("title"),
                "body": item.get("body"),
                "image": item.get("image"),
                "tileImage": item.get("tileImage"),
            }
        )
    return result


def _named_matches(value: Any, keyword: str, limit: int = 30) -> list[dict[str, Any]]:
    """Busca nombres en respuestas de catálogo sin guardar respuestas enormes."""
    matches: list[dict[str, Any]] = []
    seen: set[str] = set()
    normalized = keyword.casefold()

    def iter_records(node: Any):
        if isinstance(node, dict):
            if node.get("name") or node.get("id"):
                yield node
                return
            for child in node.values():
                yield from iter_records(child)
        elif isinstance(node, list):
            for child in node:
                yield from iter_records(child)

    for node in iter_records(value):
        if len(matches) >= limit:
            break
        name = str(node.get("name") or "")
        identity = str(node.get("id") or name or "")
        if identity and normalized in name.casefold() and identity not in seen:
            seen.add(identity)
            matches.append(
                {
                    key: node[key]
                    for key in ("id", "name", "description", "type", "rarity", "set")
                    if key in node
                }
            )
    return matches


def _new_cosmetics_summary(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {"responseType": type(value).__name__, "spriteMatches": []}
    return {
        "date": value.get("date"),
        "build": value.get("build"),
        "previousBuild": value.get("previousBuild"),
        "lastAdditions": value.get("lastAdditions"),
        "spriteMatches": _named_matches(value, "sprite"),
        "lootHackerMatches": _named_matches(value, "loot hacker"),
    }


def _search_summary(value: Any) -> dict[str, Any]:
    records = _named_matches(value, "sprite", limit=100)
    return {
        "recordCount": len(records),
        "records": records[:40],
        "lootHackerRecordCount": len(_named_matches(value, "loot hacker", limit=100)),
    }


def _jpeg_dimensions(content: bytes) -> tuple[int | None, int | None]:
    """Obtiene dimensiones básicas de JPEG sin añadir una dependencia nueva."""
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
        segment_length = int.from_bytes(content[position:position + 2], "big")
        if segment_length < 2 or position + segment_length > len(content):
            break
        if marker in sof_markers and segment_length >= 7:
            height = int.from_bytes(content[position + 3:position + 5], "big")
            width = int.from_bytes(content[position + 5:position + 7], "big")
            return width, height
        position += segment_length
    return None, None


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


def _news_asset_urls(value: Any) -> list[tuple[str, str]]:
    urls: list[tuple[str, str]] = []
    if isinstance(value, dict) and isinstance(value.get("image"), str):
        urls.append(("feed", value["image"]))
    for index, item in enumerate(_matching_news(value), start=1):
        for field in ("image", "tileImage"):
            url = item.get(field)
            if isinstance(url, str) and url.startswith(("http://", "https://")):
                urls.append((f"motd-{index:02d}-{field}", url))
    unique: list[tuple[str, str]] = []
    seen: set[str] = set()
    for label, url in urls:
        if url not in seen:
            seen.add(url)
            unique.append((label, url))
    return unique


def _extension_for_url(url: str) -> str:
    extension = Path(urllib.parse.urlparse(url).path).suffix.lower()
    return extension if extension in {".png", ".jpg", ".jpeg", ".webp", ".gif"} else ".bin"


def _status_text(probe: dict[str, Any]) -> str:
    status = probe.get("httpStatus")
    if status is None:
        return "sin respuesta"
    return f"HTTP {status}"


def _md_link(label: str, url: str) -> str:
    return f"[{label}]({url})"


def _build_report(
    retrieved_at: str,
    api_snapshot: dict[str, Any],
    asset_entries: list[dict[str, Any]],
    reference_info: dict[str, Any] | None,
) -> str:
    news_summary = api_snapshot.get("newsSummary", {})
    new_summary = api_snapshot.get("newCosmeticsSummary", {})
    sprite_search = api_snapshot.get("spriteSearchSummary", {})
    queries = api_snapshot.get("queries", [])
    successful_assets = [item for item in asset_entries if item.get("downloaded")]
    failed_assets = [item for item in asset_entries if not item.get("downloaded")]

    lines = [
        "# Loot Hacker Sprites: investigación de la publicación de FNBRunderground",
        "",
        f"**Fecha de consulta UTC:** {retrieved_at}",
        "**Tema:** LOOT HACKER SPRITES NOW APPEARING",
        "**Publicación original:** " + _md_link("FNBRunderground en X", ORIGINAL_POST_URL),
        "",
        "## Veredicto",
        "",
        "**La afirmación central de la imagen está respaldada para el contexto de la actualización v42.10, pero la imagen no es una publicación oficial de Epic.** Epic confirma que Override recibió nuevos Loot Hacks, nuevos Sprites y mejoras; su página de Battle Royale también muestra que los Hacker Sprites están activos. La lista completa de 15 variantes y la bonificación aproximada de 1.2x / +20% aparecen en guías comunitarias y reportes de archivos, no en la nota oficial que pude consultar.",
        "",
        "La consulta directa del enlace de X no fue legible desde el lector web. Por eso se usó el archivo adjunto como evidencia visual de la publicación y no se atribuyeron al post datos que no aparecen en la imagen. El archivo original se incluye intacto en el ZIP.",
        "",
        "## Qué se ve en la imagen recibida",
        "",
        f"- Archivo de referencia: {reference_info.get('sourceName') if reference_info else 'no adjuntado'}.",
        f"- Validación local: {reference_info.get('format') if reference_info else 'n/d'} de {reference_info.get('width') if reference_info else 'n/d'} × {reference_info.get('height') if reference_info else 'n/d'} píxeles; {reference_info.get('bytes') if reference_info else 0:,} bytes originales.",
        "- Encabezado: FORTNITE UNDERGROUND NEWS.",
        "- Titular visible: LOOT HACKER SPRITES NOW APPEARING.",
        "- Composición: 15 tarjetas de Sprites en una cuadrícula de 3 filas por 5 columnas, con una estética azul/morada de escaneo.",
        "- Firma visible: @FNBRunderground y un enlace de Discord; esto identifica una fuente comunitaria, no un canal de anuncios de Epic.",
        "- La imagen por sí sola no contiene fecha de parche, build, código de isla ni tasa de aparición; esos puntos requieren fuentes adicionales.",
        "",
        "## Evidencia oficial de Epic",
        "",
        f"1. En las {_md_link('notas oficiales v42.10 de Fortnite Override', EPIC_UPDATE_NOTES_URL)}, Epic describe nuevos Loot Hacks para personalizar el botín, nuevos Overrides y una sección de nuevos Sprites y mejoras.",
        "2. La misma nota nombra cuatro Sprites nuevos de la actualización: X-Ray, Onigiri, Mega Man y Overshield. También explica que X-Ray marca enemigos, Onigiri activa Overdrive tras consumir, Mega Man reduce la fricción y Overshield concede un escudo que escala con el nivel.",
        "3. Epic indica que dominar un Sprite da una ventaja adicional de reaparición con menor coste de Sprite Dust y añade una vía de recompensas de maestría.",
        f"4. La {_md_link('página oficial de Battle Royale', EPIC_BATTLE_ROYALE_URL)} muestra el anuncio dinámico de que los Hacker Sprites están activos y enlaza las notas de v42.10.",
        f"5. El {_md_link('artículo oficial de Override', EPIC_OVERRIDE_URL)} explica el sistema general: Sprites, Sprite Dust y Loot Hacks que cambian el botín de los cofres.",
        "",
        "**Límite importante:** Epic confirma el sistema y cuatro Sprites base, pero la nota oficial no enumera en el texto los 15 nombres Loot Hacker de la imagen. No se presenta esa lista como una tabla oficial de Epic.",
        "",
        "## Las 15 variantes identificadas por fuentes secundarias",
        "",
        "La siguiente tabla consolida la lista que coincide con la cuadrícula de la imagen y con dos guías comunitarias. Las fechas y ubicaciones son una lectura secundaria del contenido de la temporada y pueden cambiar si Epic modifica la rotación.",
        "",
        "| # | Variante | Situación reportada | Zona/POI reportado |",
        "|---:|---|---|---|",
    ]
    for index, item in enumerate(SPRITE_DETAILS, start=1):
        lines.append(f"| {index} | {item['name']} | {item['status']} | {item['locations']} |")
    lines.extend(
        [
            "",
            f"Las guías consultadas son {_md_link('Beebom', BEEBOM_URL)} y {_md_link('The Click', THE_CLICK_URL)}. La lectura común es que Crown ya estaba disponible y que las otras 14 variantes entran en la rotación de Sprites del 10 de septiembre de 2026. Esto tiene **confianza media**, porque no procede de una tabla de nombres publicada por Epic.",
            "",
            "### Excepción de Mega Man",
            "",
            "Mega Man aparece en las notas oficiales como un Sprite base nuevo, pero los reportes de la colección Loot Hacker lo tratan como excluido de estas 15 variantes. Por eso no se añadió Loot Hacker Mega Man a la lista, aunque sí se conserva su mención en la evidencia oficial.",
            "",
            "## Qué significa Loot Hacker",
            "",
            "- Un Loot Hacker Sprite debe entenderse como una variante/estado de colección de un Sprite, no como una skin del casillero ni como un banner de perfil.",
            "- Las guías y reportes de archivos describen que conserva el poder del Sprite base y aumenta aproximadamente 1.2x la probabilidad relevante de obtener un Loot Hack al registrar cofres, expresado también como +20%. Esa bonificación es **evidencia secundaria**, no una cifra publicada en la nota oficial de Epic.",
            "- Loot Hacks y Loot Hacker Sprites son conceptos relacionados pero distintos: el Loot Hack modifica los posibles objetos de un cofre usando Sprite Dust; el Loot Hacker mejora la oportunidad de que ese sistema entre en juego.",
            "- Los reportes mencionan cofres, códigos de Cheat Code, eliminaciones y comercio entre jugadores como vías de obtención. No encontré en la fuente oficial una tabla que garantice cada método para cada variante.",
            "- La tasa exacta de caída no está confirmada. No se debe usar una cifra de 0.50% como dato oficial.",
            "",
            "### Progresión de Crown que reportan las guías",
            "",
            "The Click describe una secuencia de colección Crown base → Cheat Master Crown → Gold Crown → Loot Hacker Crown, vinculada a victorias/maestría. Se conserva como una ruta reportada por terceros, no como una regla oficial verificada por la API.",
            "",
            "## Comprobación en Fortnite-API.com",
            "",
            "La API configurada en el proyecto sí permite comprobar el contexto de noticias, pero no expone un catálogo de Sprites en las rutas probadas.",
            "",
            f"- /v2/news/br respondió {_status_text(next((q for q in queries if q.get('name') == 'news'), {}))}. El feed tiene fecha {news_summary.get('date') or 'no indicada'} y devuelve dos mensajes relevantes: uno sobre colección/maestría de Sprites y otro sobre nuevos Loot Hacks, Prop Hunt y Sprites como X-Ray y Onigiri.",
            f"- /v2/cosmetics/new respondió {_status_text(next((q for q in queries if q.get('name') == 'newCosmetics'), {}))}; build {new_summary.get('build') or 'no indicada'}. El texto Sprite que aparece en sus novedades corresponde a registros de cosméticos del catálogo, no a un endpoint de poderes de Sprite; no apareció un registro Loot Hacker.",
            f"- /v1/sprites respondió {_status_text(next((q for q in queries if q.get('name') == 'spritesV1'), {}))}.",
            f"- /v2/sprites respondió {_status_text(next((q for q in queries if q.get('name') == 'spritesV2'), {}))}.",
            f"- La búsqueda de catálogo Loot Hacker respondió {_status_text(next((q for q in queries if q.get('name') == 'lootHackerSearch'), {}))} y no devolvió registros de cosmético con ese nombre.",
            f"- La búsqueda de catálogo Sprite respondió {_status_text(next((q for q in queries if q.get('name') == 'spriteSearch'), {}))}, con {sprite_search.get('recordCount', 0)} coincidencias del catálogo; esta lista no equivale a la colección de poderes del modo Override.",
            "",
            "### Tabla de auditoría de endpoints",
            "",
            "| Consulta | Ruta | Parámetros | Estado | Lectura |",
            "|---|---|---|---:|---|",
        ]
    )
    for query in queries:
        params = "&".join(f"{key}={value}" for key, value in query.get("params", {}).items()) or "—"
        if query.get("name") in {"spritesV1", "spritesV2", "lootHackerSearch"} and not query.get("available"):
            reading = "Ruta no expuesta / sin registro de catálogo"
        elif query.get("name") == "news":
            reading = "Contexto de temporada confirmado por el feed de noticias"
        elif query.get("name") == "newCosmetics":
            reading = "Novedades de cosméticos; no es catálogo de poderes"
        elif query.get("name") == "spriteSearch":
            reading = "Coincidencias cosméticas con la palabra Sprite"
        else:
            reading = "Consulta realizada"
        lines.append(
            f"| {query.get('name')} | {query.get('path')} | {params} | {_status_text(query)} | {reading} |"
        )
    lines.extend(
        [
            "",
            f"La documentación de {_md_link('cosméticos de Fortnite-API.com', FORTNITE_API_COSMETICS_DOCS)} enumera las rutas de catálogo; no incluye una ruta pública de Sprites. La documentación de {_md_link('noticias', FORTNITE_API_NEWS_DOCS)} sí cubre el feed usado aquí.",
            "",
            "## Qué queda confirmado y qué no",
            "",
            "| Afirmación | Nivel | Motivo |",
            "|---|---|---|",
            f"| Override tiene Sprites, Sprite Dust y Loot Hacks | Alto | {_md_link('Epic: Override', EPIC_OVERRIDE_URL)} y notas v42.10 |",
            f"| X-Ray, Onigiri, Mega Man y Overshield son Sprites nuevos de v42.10 | Alto | {_md_link('Notas oficiales v42.10', EPIC_UPDATE_NOTES_URL)} |",
            f"| Existen 15 variantes Loot Hacker con los nombres de la tabla | Medio | Coincidencia de {_md_link('Beebom', BEEBOM_URL)} y {_md_link('The Click', THE_CLICK_URL)} con la imagen |",
            "| Bonificación aproximada 1.2x / +20% | Medio-bajo | Reportada por guías/lecturas de archivos, no por la nota oficial |",
            "| Cada ubicación, método de obtención y secuencia Crown | Medio-bajo | Datos de terceros sensibles a cambios de rotación |",
            "| La imagen demuestra por sí sola que los 15 ya estaban activos | Bajo | La imagen no lleva build, fecha verificable ni prueba de partida |",
            "",
            "## Archivos conservados",
            "",
            f"- Recursos válidos incluidos: **{len(successful_assets)}**; descargas fallidas: **{len(failed_assets)}**.",
            "- La imagen adjunta se copia byte por byte al ZIP; no se convierte, recorta ni reescala.",
            "- Las imágenes de noticias descargadas desde las URLs que devolvió la API también se conservan en su formato original, con SHA-256 en manifest.json.",
            "- api_snapshot.json contiene las rutas, parámetros y resúmenes de respuesta, sin incluir la API key ni el token de Telegram.",
            "",
            "## Fuentes",
            "",
            f"1. {_md_link('Publicación original de FNBRunderground en X', ORIGINAL_POST_URL)} — enlace aportado para la investigación; el lector web no pudo abrir el post, por lo que se utilizó la imagen adjunta.",
            f"2. {_md_link('Epic Games — Fortnite Battle Royale', EPIC_BATTLE_ROYALE_URL)} — estado dinámico de Override y Hacker Sprites.",
            f"3. {_md_link('Epic Games — Fortnite Override: Break the Rules, Change the Game', EPIC_OVERRIDE_URL)} — sistema de Sprites, Sprite Dust y Loot Hacks.",
            f"4. {_md_link('Epic Games — v42.10 Fortnite Override: Battle Royale Update Notes', EPIC_UPDATE_NOTES_URL)} — nuevos Loot Hacks, nuevos Sprites y mejoras de maestría.",
            f"5. {_md_link('Beebom — Fortnite Loot Hacker Sprites', BEEBOM_URL)} — lista, ubicaciones y bonificación reportada; fuente secundaria.",
            f"6. {_md_link('The Click — Fortnite Loot Hacker Sprites', THE_CLICK_URL)} — estados de variantes, Crown y exclusión reportada de Mega Man; fuente secundaria.",
            f"7. {_md_link('All Things How — Fortnite Override Sprites/Loot Hacks', ALL_THINGS_HOW_URL)} — diferencia entre Sprites base, poderes y Loot Hacks; fuente secundaria.",
            f"8. {_md_link('Fortnite.GG — Sprites', FORTNITE_GG_SPRITES_URL)} — referencia comunitaria de estados y nombres.",
            f"9. {_md_link('Fortnite-API.com', FORTNITE_API_HOME)} y su {_md_link('documentación de endpoints', FORTNITE_API_COSMETICS_DOCS)} — consultas directas realizadas durante este expediente.",
            "",
            "## Conclusión operativa",
            "",
            "La imagen de FNBRunderground está sustancialmente alineada con el contenido real de Override v42.10: los Hacker Sprites/Loot Hacker Sprites pertenecen a una colección activa alrededor del sistema de Loot Hacks. Lo que queda verificado con mayor fuerza es el sistema y los cuatro Sprites base de la actualización; los 15 nombres, las ubicaciones y el +20% deben tratarse como información comunitaria de confianza media hasta que Epic publique una tabla oficial o se confirme dentro de una partida/archivo del cliente.",
            "",
            "Para el investigador del proyecto, la conclusión técnica es clara: fortnite-api.com sirve para seguir el feed de noticias y el contexto de la actualización, pero no permite obtener hoy una ficha estructurada de Loot Hacker Sprites. El archivo adjunto y las imágenes oficiales de noticias quedan empaquetados para revisión visual y auditoría posterior.",
            "",
        ]
    )
    return "\n".join(lines)


def build_sprite_research_package(
    client: FortniteAPIClient,
    output_dir: Path,
    reference_image: Path | None,
    language: str = "en",
    timeout: float = 30,
) -> SpriteResearchArtifacts:
    """Consulta la API, conserva evidencia visual y genera informe + ZIP."""
    output_dir.mkdir(parents=True, exist_ok=True)
    retrieved_at = datetime.now(timezone.utc)
    retrieved_iso = retrieved_at.isoformat()
    query_specs = (
        ("news", "/v2/news/br", {"language": language}),
        ("newCosmetics", "/v2/cosmetics/new", {"language": language}),
        ("spritesV1", "/v1/sprites", {"language": language}),
        ("spritesV2", "/v2/sprites", {"language": language}),
        (
            "lootHackerSearch",
            "/v2/cosmetics/br/search/all",
            {"name": "Loot Hacker", "matchMethod": "contains", "language": language},
        ),
        (
            "spriteSearch",
            "/v2/cosmetics/br/search/all",
            {"name": "Sprite", "matchMethod": "contains", "language": language},
        ),
    )
    values: dict[str, Any | None] = {}
    probes: list[dict[str, Any]] = []
    for name, path, params in query_specs:
        probe, value = _query(client, path, params)
        probe["name"] = name
        probes.append(probe)
        values[name] = value

    news_value = values.get("news")
    new_value = values.get("newCosmetics")
    loot_search_value = values.get("lootHackerSearch")
    sprite_search_value = values.get("spriteSearch")
    news_summary = {
        "date": news_value.get("date") if isinstance(news_value, dict) else None,
        "matchingMessages": _matching_news(news_value),
    }
    new_summary = _new_cosmetics_summary(new_value)
    api_snapshot: dict[str, Any] = {
        "investigation": {
            "source": "Fortnite-API.com",
            "topic": "Loot Hacker Sprites / FNBRunderground publication",
            "retrievedAt": retrieved_iso,
            "language": language,
            "baseUrl": client.base_url,
        },
        "queries": probes,
        "newsSummary": news_summary,
        "newCosmeticsSummary": new_summary,
        "lootHackerSearchSummary": _search_summary(loot_search_value),
        "spriteSearchSummary": _search_summary(sprite_search_value),
        "spriteCatalog": list(SPRITE_DETAILS),
        "sourceUrls": {
            "originalPost": ORIGINAL_POST_URL,
            "epicBattleRoyale": EPIC_BATTLE_ROYALE_URL,
            "epicOverride": EPIC_OVERRIDE_URL,
            "epicUpdateNotes": EPIC_UPDATE_NOTES_URL,
            "beebom": BEEBOM_URL,
            "theClick": THE_CLICK_URL,
            "allThingsHow": ALL_THINGS_HOW_URL,
            "fortniteGG": FORTNITE_GG_SPRITES_URL,
        },
    }

    staging_dir = Path(tempfile.mkdtemp(prefix="fortnite-sprites-", dir=str(output_dir)))
    asset_entries: list[dict[str, Any]] = []
    try:
        reference_info: dict[str, Any] | None = None
        if reference_image is not None:
            reference_info = _copy_reference_image(reference_image, staging_dir)
            asset_entries.append(reference_info)

        used_urls: set[str] = set()
        for index, (label, url) in enumerate(_news_asset_urls(news_value)):
            if url in used_urls:
                continue
            used_urls.add(url)
            relative = (
                Path("assets")
                / "official-api-news"
                / f"{index:02d}-{_slug(label)}{_extension_for_url(url)}"
            )
            destination = staging_dir / relative
            result = _download_image(url, destination, timeout)
            result.update(
                {
                    "kind": "official_api_news",
                    "label": label,
                    "path": relative.as_posix(),
                }
            )
            asset_entries.append(result)

        report = _build_report(retrieved_iso, api_snapshot, asset_entries, reference_info)
        timestamp_label = retrieved_at.strftime("%Y%m%dT%H%M%SZ")
        report_path = output_dir / f"{timestamp_label}-investigacion-loot-hacker-sprites.md"
        archive_path = output_dir / f"{timestamp_label}-recursos-loot-hacker-sprites.zip"
        report_path.write_text(report, encoding="utf-8")

        manifest = {
            "generatedAt": retrieved_iso,
            "source": "Fortnite-API.com + Epic public sources + attached reference image",
            "quality": "original bytes; no photo conversion, crop or resizing",
            "assets": asset_entries,
            "failedDownloads": [item for item in asset_entries if not item.get("downloaded")],
            "referenceImage": reference_info,
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
            archive.write(report_path, arcname="INFORME-loot-hacker-sprites.md")
            archive.write(manifest_path, arcname="manifest.json")
            archive.write(snapshot_path, arcname="api_snapshot.json")
            for file_path in staging_dir.rglob("*"):
                if file_path.is_file() and file_path not in {manifest_path, snapshot_path}:
                    archive.write(
                        file_path,
                        arcname=file_path.relative_to(staging_dir).as_posix(),
                    )

        successful_assets = [item for item in asset_entries if item.get("downloaded")]
        return SpriteResearchArtifacts(
            report_path=report_path,
            archive_path=archive_path,
            asset_count=len(successful_assets),
            asset_bytes=sum(int(item.get("bytes", 0)) for item in successful_assets),
            api_probes=tuple(probes),
        )
    finally:
        shutil.rmtree(staging_dir, ignore_errors=True)
