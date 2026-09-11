"""Investigación de regiones y latencia usando endpoints de diagnóstico de Epic."""

from __future__ import annotations

import json
import re
import socket
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REGION_ENDPOINTS = (
    ("NA-East", "ping-nae.ds.on.epicgames.com"),
    ("NA-Central", "ping-nac.ds.on.epicgames.com"),
    ("NA-West", "ping-naw.ds.on.epicgames.com"),
)

SOURCES = (
    "https://www.epicgames.com/help/en-US/c5719335176219/c5719372265755/a5720393283867",
    "https://www.epicgames.com/help/c-34254770/c-33726977/a13493305?lang=uk",
    "https://dev.epicgames.com/documentation/fortnite/matchmaking-region",
    "https://fortnite-api.com/",
)


def _resolve_ipv4(host: str) -> list[str]:
    try:
        addresses = socket.getaddrinfo(host, None, socket.AF_INET, socket.SOCK_STREAM)
    except OSError as exc:
        return [f"resolution-error: {exc}"]
    return sorted({item[4][0] for item in addresses})


def _ping(host: str) -> dict[str, Any]:
    """Hace cuatro pings sin shell y tolera la localización de Windows."""
    try:
        completed = subprocess.run(
            ["ping.exe", "-n", "4", "-w", "1200", host],
            capture_output=True,
            text=True,
            encoding="oem",
            errors="replace",
            timeout=15,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        return {
            "replies": None,
            "packetLossPercent": None,
            "minMs": None,
            "avgMs": None,
            "maxMs": None,
            "error": str(exc),
        }
    output = f"{completed.stdout}\n{completed.stderr}"
    loss_match = re.search(r"\((\d+)%", output)
    received_match = re.search(r"(?:Received|Recibidos)\s*=\s*(\d+)", output)
    times = [int(value) for value in re.findall(r"=\s*(\d+)\s*ms", output)]
    summary_times = times[-3:] if len(times) >= 3 else []
    result: dict[str, Any] = {
        "replies": int(received_match.group(1)) if received_match else None,
        "packetLossPercent": int(loss_match.group(1)) if loss_match else None,
        "minMs": summary_times[0] if len(summary_times) == 3 else None,
        "avgMs": summary_times[2] if len(summary_times) == 3 else None,
        "maxMs": summary_times[1] if len(summary_times) == 3 else None,
    }
    if completed.returncode != 0 and result["packetLossPercent"] is None:
        result["error"] = "ping.exe no devolvió un resumen interpretable"
    return result


def build_region_report(api_checks: dict[str, Any] | None = None) -> dict[str, Any]:
    retrieved_at = datetime.now(timezone.utc).isoformat()
    regions = []
    for name, host in REGION_ENDPOINTS:
        regions.append({
            "region": name,
            "diagnosticHost": host,
            "resolvedIPv4": _resolve_ipv4(host),
            "localPing": _ping(host),
        })
    return {
        "investigation": {
            "topic": "Servidores de Fortnite en New York",
            "retrievedAt": retrieved_at,
            "conclusion": (
                "Epic no publica una región oficial llamada New York ni asigna una ciudad física "
                "a NA-East en la documentación consultada. New York debe tratarse como una posible "
                "referencia informal dentro de la región NA-East, no como un servidor confirmado."
            ),
            "sources": list(SOURCES),
        },
        "officiallyPublishedRegions": [
            "North America: East",
            "North America: Central",
            "North America: West",
            "Brazil",
            "Europe",
            "Oceania",
            "Asia",
            "Middle East",
        ],
        "testedRegions": regions,
        "apiScope": {
            "fortniteApiCom": "La API pública consultada ofrece cosméticos, tienda, noticias y otros datos; no expone una ruta documentada que devuelva una lista de servidores físicos por ciudad.",
            "physicalLocationCaveat": "Una IP DNS resuelta o una medición de ping demuestra conectividad hacia el endpoint de diagnóstico, no la ubicación física exacta del servidor de una partida.",
            "liveEndpointChecks": api_checks or {},
        },
    }


def save_region_report(document: dict[str, Any], output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc)
    path = output_dir / f"{timestamp.strftime('%Y%m%dT%H%M%SZ')}-servidores-fortnite-na.json"
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path
