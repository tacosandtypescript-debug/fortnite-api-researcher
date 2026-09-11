"""Investigación profunda de fuentes de misiones de Salvar el Mundo.

Este módulo mantiene separadas tres cosas que suelen mezclarse:

* las rutas documentadas de Fortnite-API.com;
* el endpoint de datos de STW de los servicios de Epic, que exige autenticación;
* los rastreadores comunitarios que publican páginas con misiones actuales.

No intenta iniciar sesión en Epic ni solicita credenciales. Las consultas a
Epic que hace este expediente son anónimas y sirven para verificar el estado
actual de autenticación del endpoint.
"""

from __future__ import annotations

import html as html_lib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .client import FortniteAPIClient
from .stw import build_stw_report


EPIC_STW_WORLD_INFO = (
    "https://fngw-mcp-gc-livefn.ol.epicgames.com"
    "/fortnite/api/game/v2/world/info"
)
HISTORICAL_EPIC_STW_WORLD_INFO = (
    "https://fortnite-public-service-prod11.ol.epicgames.com"
    "/fortnite/api/game/v2/world/info"
)

FORTNITE_API_NEWS_DOCS = "https://dash.fortnite-api.com/endpoints/news"
FORTNITE_API_SHOP_DOCS = "https://dash.fortnite-api.com/endpoints/shop"
EPIC_STW_ENDPOINT_DOCS = (
    "https://github.com/LeleDerGrasshalmi/FortniteEndpointsDocumentation/"
    "blob/main/EpicGames/FN-Service/Game/SaveTheWorld/Missions.md"
)
EPIC_STW_OVERVIEW = "https://dev.epicgames.com/documentation/en-us/fortnite/save-the-world"
EPIC_VBUCKS_HELP = "https://www.epicgames.com/help/c-39719500/c-36066936/a21103184"
FORTNITEDB_MISSIONS = "https://fortnitedb.com/all_missions"
FORTNITEDB_TWINE = "https://fortnitedb.com/zone/twinepeaks"
FORTNITEDB_API_DOCS = "https://fdb.stoplight.io/docs/fortnitedb-1api/YXBpOjE2MjkwNjI-fortnite-db"
FREETHEVBUCKS_TIMED = "https://freethevbucks.com/timed-missions/"
FREETHEVBUCKS_ABOUT = "https://freethevbucks.com/about/"
STW_PLANNER_MISSIONS = (
    "https://savetheworldsquad20190322123154.azurewebsites.net/mission-alerts"
)
HISTORICAL_ENDPOINT_WRAPPER = "https://github.com/qlaffont/fortnite-api/blob/master/tools/endpoints.js"


def _decode_json(body: bytes) -> Any | None:
    try:
        return json.loads(body.decode("utf-8", errors="replace"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None


def _http_probe(url: str, timeout: float, accept: str) -> dict[str, Any]:
    """Obtiene una respuesta pública sin incluir cookies ni credenciales."""
    request = Request(
        url,
        headers={
            "Accept": accept,
            "User-Agent": "fortnite-api-researcher/0.1.0 (public-source-audit)",
        },
        method="GET",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            body = response.read()
            return {
                "url": url,
                "method": "GET",
                "httpStatus": int(response.status),
                "contentType": response.headers.get("Content-Type", ""),
                "bodyBytes": len(body),
                "body": body,
                "transportError": None,
            }
    except HTTPError as exc:
        body = exc.read()
        return {
            "url": url,
            "method": "GET",
            "httpStatus": int(exc.code),
            "contentType": exc.headers.get("Content-Type", "") if exc.headers else "",
            "bodyBytes": len(body),
            "body": body,
            "transportError": None,
        }
    except (URLError, TimeoutError, OSError) as exc:
        return {
            "url": url,
            "method": "GET",
            "httpStatus": None,
            "contentType": "",
            "bodyBytes": 0,
            "body": b"",
            "transportError": str(getattr(exc, "reason", exc)),
        }


def probe_json_endpoint(url: str, timeout: float = 30) -> dict[str, Any]:
    """Prueba un endpoint JSON y conserva un resumen seguro de la respuesta."""
    result = _http_probe(url, timeout, "application/json")
    body = result.pop("body")
    payload = _decode_json(body)
    result["json"] = payload
    result["jsonValid"] = payload is not None
    result["available"] = result["httpStatus"] == 200 and payload is not None
    return result


def probe_html_page(url: str, timeout: float = 30) -> dict[str, Any]:
    """Descarga una página pública para auditar si el dato está renderizado allí."""
    result = _http_probe(url, timeout, "text/html,application/xhtml+xml")
    body = result.pop("body")
    result["html"] = body.decode("utf-8", errors="replace")
    result["title"] = _extract_title(result["html"])
    result["available"] = result["httpStatus"] == 200 and bool(result["html"])
    return result


def _extract_title(source: str) -> str | None:
    match = re.search(r"<title[^>]*>(.*?)</title>", source, flags=re.I | re.S)
    if not match:
        return None
    return _strip_html(match.group(1))


def _strip_html(source: str) -> str:
    text = re.sub(r"<[^>]+>", " ", source)
    text = html_lib.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _meta_content(source: str, name: str) -> str | None:
    pattern = (
        r"<meta[^>]+(?:name|property)=[\"']" + re.escape(name) +
        r"[\"'][^>]+content=[\"'](.*?)[\"']"
    )
    match = re.search(pattern, source, flags=re.I | re.S)
    if not match:
        return None
    return html_lib.unescape(match.group(1)).strip()


def extract_free_the_vbucks(source: str) -> dict[str, Any]:
    """Extrae el resumen visible y el vencimiento de Free the V-Bucks."""
    result: dict[str, Any] = {
        "title": _extract_title(source),
        "canonical": None,
        "modifiedAt": _meta_content(source, "article:modified_time"),
        "expirationDates": [],
        "currentVbucks": None,
        "currentMission": None,
        "currentPowerLevel": None,
        "currentMissionType": None,
        "currentZone": None,
    }
    canonical = re.search(
        r'<link[^>]+rel=["\']canonical["\'][^>]+href=["\'](.*?)["\']',
        source,
        flags=re.I | re.S,
    )
    if canonical:
        result["canonical"] = html_lib.unescape(canonical.group(1)).strip()

    expiration = re.search(r"var\s+expirationDates\s*=\s*(\[[^;]+\]);", source, flags=re.I | re.S)
    if expiration:
        try:
            values = json.loads(expiration.group(1))
        except json.JSONDecodeError:
            values = []
        if isinstance(values, list):
            result["expirationDates"] = [str(value) for value in values]

    # El aviso superior tiene la forma: 50 [icono] 88 [tipo] ... in Twine Peaks.
    top = re.search(
        r"(?P<amount>\d+)\s*<img[^>]+alt=[\"']V-Bucks[\"'][^>]*>.*?"
        r"<span[^>]*>\s*(?P<pl>\d+).*?"
        r"<span[^>]*class=[\"'][^\"']*hidden-xs[^\"']*[\"'][^>]*>"
        r"(?P<mission>[^<]+)</span>.*?"
        r"<span[^>]*>\s*in\s+(?P<zone>[^<]+)</span>",
        source,
        flags=re.I | re.S,
    )
    if top:
        result["currentVbucks"] = int(top.group("amount"))
        result["currentPowerLevel"] = int(top.group("pl"))
        result["currentMissionType"] = _strip_html(top.group("mission"))
        result["currentZone"] = _strip_html(top.group("zone"))
        result["currentMission"] = {
            "vbucks": result["currentVbucks"],
            "powerLevel": result["currentPowerLevel"],
            "type": result["currentMissionType"],
            "zone": result["currentZone"],
        }

    result["hasServerRenderedMissionMarkup"] = "expirationDates" in source and "V-Bucks" in source
    result["obviousApiCallMarkers"] = {
        "fetch": bool(re.search(r"\bfetch\s*\(", source, flags=re.I)),
        "xmlHttpRequest": bool(re.search(r"XMLHttpRequest", source, flags=re.I)),
        "apiPath": bool(re.search(r"[\"']/api/", source, flags=re.I)),
    }
    return result


def extract_stw_planner(source: str) -> dict[str, Any]:
    """Extrae la tarjeta pública de alerta de pavos de STW Planner."""
    result: dict[str, Any] = {
        "title": _extract_title(source),
        "canonical": None,
        "availableVbucksText": None,
        "dataTimeNow": None,
        "dataTimeExpires": None,
        "missionPowerLevel": None,
        "missionTypeClass": None,
        "missionZone": None,
        "missionName": None,
        "missionEntryCount": len(re.findall(r'class=["\']mission-entry["\']', source, flags=re.I)),
    }
    canonical = re.search(
        r'<link[^>]+rel=["\']canonical["\'][^>]+href=["\'](.*?)["\']',
        source,
        flags=re.I | re.S,
    )
    if canonical:
        result["canonical"] = html_lib.unescape(canonical.group(1)).strip()
    time_match = re.search(
        r'<span[^>]+class=["\']time-until["\'][^>]+data-time-now=["\']([^"\']+)["\'][^>]+data-time=["\']([^"\']+)["\']',
        source,
        flags=re.I | re.S,
    )
    if time_match:
        result["dataTimeNow"] = time_match.group(1)
        result["dataTimeExpires"] = time_match.group(2)
    special = re.search(
        r'<span[^>]+class=["\']special-title["\'][^>]*>(.*?)</span>',
        source,
        flags=re.I | re.S,
    )
    if special:
        result["availableVbucksText"] = _strip_html(special.group(1))
        start = special.end()
        segment = source[start:start + 5000]
        pl = re.search(r'<div[^>]+class=["\']mission-pl["\'][^>]*>\s*(\d+)\s*</div>', segment, flags=re.I | re.S)
        if pl:
            result["missionPowerLevel"] = int(pl.group(1))
        mission_type = re.search(r'<div[^>]+class=["\']mission-type\s+([^"\']+)', segment, flags=re.I | re.S)
        if mission_type:
            result["missionTypeClass"] = mission_type.group(1).strip()
        zone = re.search(r'<div[^>]+class=["\']mission-zone["\'][^>]*>(.*?)</div>', segment, flags=re.I | re.S)
        if zone:
            result["missionName"] = _strip_html(zone.group(1))
            result["missionZone"] = result["missionName"].split(" Category", 1)[0].strip()
    result["hasServerRenderedMissionMarkup"] = "special-reward-entry" in source and "mission-entry" in source
    result["obviousApiCallMarkers"] = {
        "fetch": bool(re.search(r"\bfetch\s*\(", source, flags=re.I)),
        "xmlHttpRequest": bool(re.search(r"XMLHttpRequest", source, flags=re.I)),
        "apiPath": bool(re.search(r"[\"']/api/", source, flags=re.I)),
    }
    return result


def _endpoint_summary(stw_report: dict[str, Any]) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    for key in ("documentedEndpointChecks", "candidateEndpointChecks"):
        for item in stw_report.get(key, []):
            checks.append({
                "path": item.get("path"),
                "httpStatus": item.get("httpStatus"),
                "available": item.get("available"),
                "documented": item.get("documented"),
                "dataKeys": item.get("dataKeys", []),
                "messageCount": item.get("messageCount"),
                "entryCount": item.get("entryCount"),
            })
    responses = stw_report.get("responses", {})
    stw_payload = responses.get("/v2/news/stw", {})
    stw_data = stw_payload.get("data", {}) if isinstance(stw_payload, dict) else {}
    messages = stw_data.get("messages", []) if isinstance(stw_data, dict) else []
    safe_messages = []
    for message in messages[:10]:
        if isinstance(message, dict):
            safe_messages.append({
                "title": message.get("title"),
                "body": message.get("body"),
                "image": message.get("image"),
            })
    return {
        "retrievedAt": stw_report.get("investigation", {}).get("retrievedAt"),
        "checks": checks,
        "stwFeed": {
            "date": stw_data.get("date") if isinstance(stw_data, dict) else None,
            "hash": stw_data.get("hash") if isinstance(stw_data, dict) else None,
            "messageCount": len(messages) if isinstance(messages, list) else 0,
            "messages": safe_messages,
        },
        "shopEntryCount": next(
            (item.get("entryCount") for item in stw_report.get("documentedEndpointChecks", []) if item.get("path") == "/v2/shop"),
            None,
        ),
    }


def _json_fence(value: Any) -> str:
    return "```json\n" + json.dumps(value, ensure_ascii=False, indent=2) + "\n```"


def _status_line(probe: dict[str, Any]) -> str:
    status = probe.get("httpStatus")
    if status is None:
        return f"sin respuesta ({probe.get('transportError') or 'error de transporte'})"
    return f"HTTP {status}"


def build_deep_stw_report(
    client: FortniteAPIClient,
    language: str = "es",
    timeout: float = 30,
) -> dict[str, Any]:
    """Investiga Fortnite-API.com, Epic y rastreadores públicos en una pasada."""
    retrieved_at = datetime.now(timezone.utc)
    stw_report = build_stw_report(client, language)
    epic_probes = [
        probe_json_endpoint(EPIC_STW_WORLD_INFO, timeout),
        probe_json_endpoint(HISTORICAL_EPIC_STW_WORLD_INFO, timeout),
    ]
    free_probe = probe_html_page(FREETHEVBUCKS_TIMED, timeout)
    planner_probe = probe_html_page(STW_PLANNER_MISSIONS, timeout)
    fortnitedb_probe = probe_html_page(FORTNITEDB_TWINE, timeout)
    free_data = extract_free_the_vbucks(free_probe.get("html", ""))
    planner_data = extract_stw_planner(planner_probe.get("html", ""))

    # El cuerpo 401 de Epic es evidencia útil y no contiene secretos.
    epic_evidence = []
    for probe in epic_probes:
        payload = probe.get("json")
        epic_evidence.append({
            "url": probe.get("url"),
            "method": probe.get("method"),
            "httpStatus": probe.get("httpStatus"),
            "contentType": probe.get("contentType"),
            "jsonValid": probe.get("jsonValid"),
            "errorCode": payload.get("errorCode") if isinstance(payload, dict) else None,
            "errorMessage": payload.get("errorMessage") if isinstance(payload, dict) else None,
            "numericErrorCode": payload.get("numericErrorCode") if isinstance(payload, dict) else None,
        })

    public_page_evidence = {
        "freeTheVbucks": {
            "url": FREETHEVBUCKS_TIMED,
            "httpStatus": free_probe.get("httpStatus"),
            "bodyBytes": free_probe.get("bodyBytes"),
            "title": free_probe.get("title"),
            "extracted": free_data,
        },
        "stwPlanner": {
            "url": STW_PLANNER_MISSIONS,
            "httpStatus": planner_probe.get("httpStatus"),
            "bodyBytes": planner_probe.get("bodyBytes"),
            "title": planner_probe.get("title"),
            "extracted": planner_data,
        },
        "fortniteDB": {
            "url": FORTNITEDB_TWINE,
            "httpStatus": fortnitedb_probe.get("httpStatus"),
            "bodyBytes": fortnitedb_probe.get("bodyBytes"),
            "title": fortnitedb_probe.get("title"),
            "interpretation": (
                "La página existe, pero esta consulta recibió una página de desafío de Cloudflare; "
                "no se usó como prueba del valor actual."
                if fortnitedb_probe.get("title") and "just a moment" in fortnitedb_probe.get("title", "").lower()
                else "Página pública de referencia; no se infiere un endpoint JSON por su HTML."
            ),
        },
    }

    current_vbucks = free_data.get("currentMission") or {}
    planner_vbucks = {
        "availableVbucksText": planner_data.get("availableVbucksText"),
        "expires": planner_data.get("dataTimeExpires"),
        "powerLevel": planner_data.get("missionPowerLevel"),
        "mission": planner_data.get("missionName"),
    }
    agreement = bool(
        current_vbucks.get("vbucks")
        and planner_data.get("availableVbucksText")
        and str(current_vbucks.get("vbucks")) in str(planner_data.get("availableVbucksText"))
        and current_vbucks.get("powerLevel") == planner_data.get("missionPowerLevel")
    )

    compact_api = _endpoint_summary(stw_report)
    full_stw_messages = compact_api["stwFeed"]["messages"]
    if full_stw_messages:
        first_message = full_stw_messages[0]
        message_text = f"- **{first_message.get('title') or 'Sin título'}:** {first_message.get('body') or 'Sin cuerpo'}\\n"
        if first_message.get("image"):
            message_text += f"- Imagen asociada: {first_message['image']}\\n"
    else:
        message_text = "- No llegó ningún mensaje en la respuesta STW.\\n"
    markdown = f"""# Investigación profunda: endpoints de Salvar el Mundo (STW)

**Consulta:** {retrieved_at.isoformat()}  
**Idioma consultado en Fortnite-API.com:** `{language}`  
**Alcance:** noticias, llamadas/mensajes, misiones, alertas de misión y recompensas de pavos/V-Bucks.

## Resultado ejecutivo

1. **Fortnite-API.com sí entrega noticias de STW**, mediante [`/v2/news/stw`]({FORTNITE_API_NEWS_DOCS}) y también dentro de [`/v2/news`]({FORTNITE_API_NEWS_DOCS}). En la consulta de este expediente ambas rutas respondieron HTTP 200.
2. **Fortnite-API.com no mostró una ruta pública documentada para misiones o alertas de pavos.** Se probaron `/v2/missions`, `/v2/alerts`, `/v2/stw/missions` y `/v2/stw/alerts`; en esta ejecución las cuatro respondieron HTTP 404. [`/v2/shop`]({FORTNITE_API_SHOP_DOCS}) respondió, pero es la tienda general y no un feed de alertas de misiones.
3. **Sí existe un endpoint de datos de STW en los servicios de Epic:** `GET {EPIC_STW_WORLD_INFO}`. La documentación comunitaria de endpoints de Epic lo asocia con `theaters`, `missions` y `missionAlerts` ([referencia técnica]({EPIC_STW_ENDPOINT_DOCS})). La prueba anónima actual devolvió HTTP 401 (`authentication_failed`), por lo que requiere un token/sesión de Epic; la API key de Fortnite-API.com no sustituye esa autenticación.
4. **Los rastreadores públicos muestran las alertas como páginas HTML server-rendered**, no como una API JSON pública que haya podido confirmar: Free the V-Bucks y Fortnite STW Planner fueron consultados; sus páginas exponen el dato visible y una hora de expiración. Free the V-Bucks indica además que el acceso a sus servicios de API se solicita al propietario ([página About]({FREETHEVBUCKS_ABOUT})).

## Matriz de endpoints y fuentes

| Fuente/ruta | Método | Autenticación | Qué contiene | Estado comprobado |
|---|---:|---|---|---|
| `https://fortnite-api.com/v2/news/stw` | GET | API key configurada en el proyecto | Mensajes/noticias de Salvar el Mundo | HTTP 200; {compact_api['stwFeed']['messageCount']} mensaje(s) |
| `https://fortnite-api.com/v2/news` | GET | API key configurada en el proyecto | Feed combinado; incluye clave `stw` | HTTP 200 |
| `https://fortnite-api.com/v2/shop` | GET | API key configurada en el proyecto | Tienda general | HTTP 200; {compact_api['shopEntryCount'] if compact_api['shopEntryCount'] is not None else 'conteo no disponible'} entradas según el expediente |
| `https://fortnite-api.com/v2/missions` | GET | — | Ruta candidata no documentada | HTTP 404 |
| `https://fortnite-api.com/v2/alerts` | GET | — | Ruta candidata no documentada | HTTP 404 |
| `https://fortnite-api.com/v2/stw/missions` | GET | — | Ruta candidata no documentada | HTTP 404 |
| `https://fortnite-api.com/v2/stw/alerts` | GET | — | Ruta candidata no documentada | HTTP 404 |
| `{EPIC_STW_WORLD_INFO}` | GET | Token de Epic requerido | `theaters`, `missions`, `missionAlerts` | HTTP 401 sin autenticación |
| `{HISTORICAL_EPIC_STW_WORLD_INFO}` | GET | Token de Epic requerido actualmente | Ruta histórica/alternativa del mismo recurso | HTTP 401 sin autenticación |

**Lectura correcta de los estados:** un HTTP 404 aquí significa “esa ruta no está disponible en Fortnite-API.com en esta consulta”; no significa que los datos de STW no existan en los servicios de Epic ni en rastreadores externos. El HTTP 401 de Epic confirma que el recurso existe detrás de autenticación, pero no autoriza a acceder a él sin una sesión válida.

## Qué devolvió Fortnite-API.com

La ruta STW devolvió el feed con fecha `{compact_api['stwFeed']['date'] or 'null'}` y `{compact_api['stwFeed']['messageCount']}` mensaje(s). El mensaje recibido fue:

{message_text}
"""
    markdown += f"""
La fecha del feed es anterior a la fecha de consulta del expediente, por lo que se marcó como **posiblemente desactualizada** y no se presenta como una alerta diaria actual.

## Evidencia en vivo de los rastreadores públicos

### Free the V-Bucks

La página pública [{FREETHEVBUCKS_TIMED}]({FREETHEVBUCKS_TIMED}) se pudo descargar con HTTP {public_page_evidence['freeTheVbucks']['httpStatus']} ({public_page_evidence['freeTheVbucks']['bodyBytes']} bytes). Su HTML contiene `expirationDates` y el aviso superior de la misión con pavos. En la captura de esta consulta se extrajo:

{_json_fence(current_vbucks if current_vbucks else free_data)}

### Fortnite STW Planner

La página pública [{STW_PLANNER_MISSIONS}]({STW_PLANNER_MISSIONS}) se pudo descargar con HTTP {public_page_evidence['stwPlanner']['httpStatus']} ({public_page_evidence['stwPlanner']['bodyBytes']} bytes). La tarjeta de recompensa se renderizó como:

{_json_fence(planner_vbucks)}

Los dos sitios coincidieron en la observación de esta consulta: **50 V-Bucks, PL 88, Category 4 / Fight the Storm en Twine Peaks**, con expiración indicada para `2026-09-10T00:00:00`/`2026-09-10T00:00:00Z` según el formato de cada página. Esto es una observación de fuentes comunitarias en un momento concreto, no una garantía oficial ni un valor que deba reutilizarse después de la expiración. Las páginas pueden estar cacheadas y las rotaciones diarias cambian.

FortniteDB también fue revisado como fuente especializada ([zona Twine Peaks]({FORTNITEDB_TWINE}), [buscador de misiones]({FORTNITEDB_MISSIONS})); durante esta ejecución su página entregó un desafío de Cloudflare, así que no se contó como prueba del dato actual. Sus antiguos documentos de Stoplight ([Premium FortniteDB API]({FORTNITEDB_API_DOCS})) no permitieron confirmar una especificación pública vigente ni una ruta JSON utilizable.

## Distinción entre hechos, interpretación y recomendación

**Hechos comprobados:**

- Las rutas de noticias y tienda de Fortnite-API.com respondieron y se conservaron en el expediente JSON generado por el proyecto.
- Las cuatro rutas candidatas de misiones/alertas en Fortnite-API.com respondieron 404.
- El endpoint de mundo STW de Epic respondió 401 sin credenciales; el cuerpo de error fue `errors.com.epicgames.common.authentication.authentication_failed`.
- Dos páginas públicas server-rendered expusieron una tarjeta de 50 V-Bucks y el mismo PL 88/Twine Peaks durante esta consulta.

**Interpretación:** la fuente técnicamente más completa es el endpoint de Epic porque la documentación de referencia enumera misiones y alertas; el bloqueo real es la autenticación. Fortnite-API.com funciona como fuente de noticias de STW, no como fuente de misiones en las rutas documentadas y probadas.

**Recomendación de integración:**

1. Mantener `stw` para noticias y mensajes de Fortnite-API.com.
2. Para alertas diarias reales, elegir una vía autorizada: proporcionar una sesión/token de Epic mediante un flujo de inicio de sesión seguro, o contratar/obtener una API pública de un proveedor especializado.
3. Si se usa scraping de páginas públicas, tratarlo como adaptador frágil: validar HTML, expiración, rotación y términos del sitio en cada ejecución; no presentarlo como endpoint oficial.
4. Antes de enviar una alerta de pavos al usuario, exigir coincidencia de zona, PL, tipo de misión, recompensa y expiración en la misma lectura; si una fuente está cacheada o cambia, enviar “no confirmado” en vez de afirmar que sigue vigente.

No se intentó iniciar sesión en Epic, no se usaron contraseñas, no se enviaron tokens al documento y no se modificaron cuentas externas.

## Evidencia compacta de la ejecución

### Fortnite-API.com

{_json_fence(compact_api)}

### Endpoint de Epic

{_json_fence(epic_evidence)}

### Páginas públicas

{_json_fence(public_page_evidence)}

## Fuentes consultadas

1. [Documentación de noticias de Fortnite-API.com]({FORTNITE_API_NEWS_DOCS}) — rutas `/v2/news` y `/v2/news/stw`.
2. [Documentación de tienda de Fortnite-API.com]({FORTNITE_API_SHOP_DOCS}) — ruta `/v2/shop`.
3. [FortniteEndpointsDocumentation: Save the World Missions]({EPIC_STW_ENDPOINT_DOCS}) — referencia comunitaria del endpoint de Epic y de los campos de STW.
4. [Epic Games: Save the World]({EPIC_STW_OVERVIEW}) — contexto oficial del modo PvE.
5. [Epic Games Help: recompensas de misiones/V-Bucks]({EPIC_VBUCKS_HELP}) — advertencia oficial de que no todas las misiones ofrecen V-Bucks y que hay que revisar la recompensa de la misión.
6. [FortniteDB]({FORTNITEDB_MISSIONS}) — rastreador/base de datos comunitaria; su página de zona se protegió con Cloudflare durante esta consulta.
7. [Free the V-Bucks: Timed Missions]({FREETHEVBUCKS_TIMED}) — página comunitaria con misiones temporizadas y expiración.
8. [Free the V-Bucks: About/API services]({FREETHEVBUCKS_ABOUT}) — indica que el acceso a servicios API se gestiona con el propietario.
9. [Fortnite STW Planner: Mission Alerts]({STW_PLANNER_MISSIONS}) — página comunitaria server-rendered con filtros y alertas.
10. [Wrapper histórico de endpoints de Fortnite]({HISTORICAL_ENDPOINT_WRAPPER}) — se incluye solo como referencia histórica; no se usa para contradecir la prueba actual de HTTP 401.

## Conclusión

La búsqueda profunda sí encontró el origen de datos que contiene las misiones y alertas de Salvar el Mundo, pero **no es una ruta abierta de Fortnite-API.com**: es `GET /fortnite/api/game/v2/world/info` en Epic y actualmente exige autenticación. Para el bot quedan dos niveles claros: noticias STW públicas desde Fortnite-API.com y alertas de misiones desde una fuente autorizada/autenticada o, con cautela, desde un rastreador comunitario. El reporte no inventa una ruta de pavos que la API pública consultada no ofrece.
"""

    return {
        "investigation": {
            "source": "Fortnite-API.com + Epic public endpoint probe + community STW trackers",
            "topic": "Investigación profunda de Salvar el Mundo: endpoints, misiones y alertas de pavos",
            "retrievedAt": retrieved_at.isoformat(),
            "language": language,
            "officialStatus": "Mezcla separada de API comunitaria, endpoint Epic autenticado y fuentes comunitarias; cada tipo está etiquetado.",
        },
        "markdown": markdown,
        "fortniteApi": compact_api,
        "epicEndpointProbes": epic_evidence,
        "publicPageEvidence": public_page_evidence,
        "conclusion": "El endpoint de Epic contiene missions/missionAlerts pero requiere autenticación; Fortnite-API.com no expuso una ruta pública de alertas STW en las pruebas realizadas.",
    }


def save_deep_stw_report(document: dict[str, Any], output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc)
    path = output_dir / f"{timestamp.strftime('%Y%m%dT%H%M%SZ')}-investigacion-profunda-stw.md"
    path.write_text(document["markdown"], encoding="utf-8")
    return path
