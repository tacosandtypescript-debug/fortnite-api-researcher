"""Investigación de endpoints de Salvar el Mundo (STW)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .client import FortniteAPIClient, FortniteAPIError
from .transport import write_text_atomic


DOCUMENTED_ENDPOINTS = (
    {
        "path": "/v2/news",
        "purpose": "Noticias combinadas de Battle Royale, Salvar el Mundo y Creativo",
        "docs": "https://dash.fortnite-api.com/endpoints/news",
        "raw": True,
    },
    {
        "path": "/v2/news/stw",
        "purpose": "Noticias actuales de Salvar el Mundo",
        "docs": "https://dash.fortnite-api.com/endpoints/news",
        "raw": True,
    },
    {
        "path": "/v2/shop",
        "purpose": "Tienda actual general; no es un feed de misiones STW",
        "docs": "https://dash.fortnite-api.com/endpoints/shop",
        "raw": False,
    },
)


MISSION_ALERT_CANDIDATES = (
    "/v2/missions",
    "/v2/alerts",
    "/v2/stw/missions",
    "/v2/stw/alerts",
)


def _response_summary(payload: Any) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "responseKeys": list(payload)[:20] if isinstance(payload, dict) else [],
    }
    data = payload.get("data") if isinstance(payload, dict) else None
    summary["dataType"] = type(data).__name__
    if isinstance(data, dict):
        summary["dataKeys"] = list(data)[:20]
        if isinstance(data.get("messages"), list):
            summary["messageCount"] = len(data["messages"])
        if isinstance(data.get("entries"), list):
            summary["entryCount"] = len(data["entries"])
    elif isinstance(data, list):
        summary["dataCount"] = len(data)
    return summary


def _call(client: FortniteAPIClient, path: str, language: str) -> tuple[dict[str, Any], Any | None]:
    try:
        result = client.get(path, {"language": language})
    except FortniteAPIError as exc:
        return (
            {
                "path": path,
                "params": {"language": language},
                "httpStatus": exc.status_code,
                "available": False,
                "errorType": "api_error",
            },
            None,
        )
    return (
        {
            "path": path,
            "params": result.params,
            "httpStatus": result.status_code,
            "available": result.status_code == 200,
            **_response_summary(result.payload),
        },
        result.payload,
    )


def build_stw_report(client: FortniteAPIClient, language: str = "es") -> dict[str, Any]:
    """Consulta STW, el feed combinado, la tienda y candidatos de alertas."""
    timestamp = datetime.now(timezone.utc)
    documented: list[dict[str, Any]] = []
    responses: dict[str, Any] = {}

    for spec in DOCUMENTED_ENDPOINTS:
        record, payload = _call(client, spec["path"], language)
        record.update({"documented": True, "purpose": spec["purpose"], "docs": spec["docs"]})
        documented.append(record)
        if payload is not None and spec["raw"]:
            responses[spec["path"]] = payload

    probes: list[dict[str, Any]] = []
    for path in MISSION_ALERT_CANDIDATES:
        record, payload = _call(client, path, language)
        record.update({
            "documented": False,
            "purpose": "Comprobación de una posible ruta de misiones/alertas STW",
        })
        probes.append(record)
        if payload is not None:
            responses[path] = payload

    stw_record = next((item for item in documented if item["path"] == "/v2/news/stw"), None)
    combined_record = next((item for item in documented if item["path"] == "/v2/news"), None)
    shop_record = next((item for item in documented if item["path"] == "/v2/shop"), None)
    missing_alerts = [item["path"] for item in probes if not item["available"]]
    candidate_statuses = "; ".join(
        f"{item['path']}: HTTP {item['httpStatus']}"
        if item.get("httpStatus") is not None
        else f"{item['path']}: sin respuesta"
        for item in probes
    )
    stw_payload = responses.get("/v2/news/stw")
    stw_data = stw_payload.get("data", {}) if isinstance(stw_payload, dict) else {}
    stw_feed_date = stw_data.get("date") if isinstance(stw_data, dict) else None

    return {
        "investigation": {
            "source": "Fortnite-API.com",
            "topic": "Salvar el Mundo (STW): noticias, llamadas y alertas de pavos",
            "retrievedAt": timestamp.isoformat(),
            "language": language,
            "docsHome": "https://dash.fortnite-api.com/",
            "officialStatus": "API comunitaria no oficial; el expediente conserva la respuesta recibida",
        },
        "findings": {
            "stwNewsEndpoint": {
                "path": "/v2/news/stw",
                "available": bool(stw_record and stw_record["available"]),
                "messageCount": stw_record.get("messageCount") if stw_record else None,
                "feedDate": stw_feed_date,
            },
            "combinedNewsEndpoint": {
                "path": "/v2/news",
                "available": bool(combined_record and combined_record["available"]),
                "includesStwKey": "stw" in (responses.get("/v2/news", {}).get("data", {}) if isinstance(responses.get("/v2/news"), dict) else {}),
            },
            "shopEndpoint": {
                "path": "/v2/shop",
                "available": bool(shop_record and shop_record["available"]),
                "interpretation": "Tienda general; la API no la documenta como alertas de misiones STW ni alertas de pavos",
            },
            "missionAndVbuckAlerts": {
                "documentedInReviewedFortniteApiDocs": False,
                "testedCandidatePaths": [item["path"] for item in probes],
                "pathsNotAvailable": missing_alerts,
                "conclusion": (
                    "No hay una ruta pública documentada en Fortnite-API.com para obtener "
                    "alertas diarias de misiones STW con pavos. Estados observados: "
                    f"{candidate_statuses}."
                ),
            },
        },
        "documentedEndpointChecks": documented,
        "candidateEndpointChecks": probes,
        "responses": responses,
        "notes": [
            "La respuesta completa de /v2/news/stw y la respuesta combinada de /v2/news quedan incluidas para auditoría.",
            f"El campo date de /v2/news/stw recibido fue {stw_feed_date or 'null'}; es anterior a la hora de consulta y debe tratarse como contenido posiblemente desactualizado.",
            (
                "Los estados observados demuestran únicamente la disponibilidad de esas "
                "rutas en esta API durante la consulta; no demuestran que no exista otra "
                "API externa con esos datos."
            ),
            "Para alertas de pavos se necesitaría otra fuente específica de misiones STW o un endpoint adicional que sea proporcionado y autorizado.",
        ],
    }


def save_stw_report(document: dict[str, Any], output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc)
    path = output_dir / f"{timestamp.strftime('%Y%m%dT%H%M%SZ')}-salvar-el-mundo-endpoints.json"
    write_text_atomic(path, json.dumps(document, ensure_ascii=False, indent=2) + "\n")
    return path
