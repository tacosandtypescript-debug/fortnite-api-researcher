"""Investigación de regiones y latencia usando endpoints de diagnóstico de Epic."""

from __future__ import annotations

import json
import re
import socket
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .transport import write_text_atomic


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

# Etiquetas del resumen de ping. Se busca cada valor por su etiqueta (en inglés
# y en español, con el punto comodín para las tildes) en vez de fiarse del orden:
# asignar min/avg/max por posición etiquetaba mal las métricas en silencio.
_LABEL_PATTERNS = {
    "minMs": re.compile(r"(?:Minimum|M.nimo)\s*=\s*(\d+)\s*ms", re.IGNORECASE),
    "maxMs": re.compile(r"(?:Maximum|M.ximo)\s*=\s*(\d+)\s*ms", re.IGNORECASE),
    "avgMs": re.compile(
        r"(?:Average|Media|Promedio)\s*=\s*(\d+)\s*ms",
        re.IGNORECASE,
    ),
}


def _resolve_ipv4(host: str) -> tuple[list[str], str | None]:
    """Devuelve direcciones IPv4 y, por separado, el error de resolución."""
    try:
        addresses = socket.getaddrinfo(host, None, socket.AF_INET, socket.SOCK_STREAM)
    except OSError as exc:
        return [], str(exc)
    return sorted({item[4][0] for item in addresses}), None


def _ping_command(host: str, count: int) -> list[str]:
    """Comando de ping multiplataforma, siempre sin shell."""
    if sys.platform.startswith("win"):
        return ["ping.exe", "-n", str(count), "-w", "1200", host]
    return ["ping", "-c", str(count), "-W", "2", host]


def _ping(host: str, *, count: int = 4) -> dict[str, Any]:
    """Mide latencia y tolera la localización del sistema."""
    try:
        completed = subprocess.run(
            _ping_command(host, count),
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
    received_match = re.search(
        r"(?:Received|Recibidos)\s*=\s*(\d+)",
        output,
        re.IGNORECASE,
    )
    result: dict[str, Any] = {
        "replies": int(received_match.group(1)) if received_match else None,
        "packetLossPercent": int(loss_match.group(1)) if loss_match else None,
    }
    for key, pattern in _LABEL_PATTERNS.items():
        match = pattern.search(output)
        result[key] = int(match.group(1)) if match else None
    if all(result.get(key) is None for key in _LABEL_PATTERNS):
        result["error"] = (
            "El resumen de ping no expuso etiquetas interpretables "
            "(Minimum/Máximo/Media); no se deducen valores por posición"
        )
    return result


def build_region_report(api_checks: dict[str, Any] | None = None) -> dict[str, Any]:
    retrieved_at = datetime.now(timezone.utc).isoformat()
    regions = []
    for name, host in REGION_ENDPOINTS:
        addresses, resolution_error = _resolve_ipv4(host)
        regions.append({
            "region": name,
            "diagnosticHost": host,
            "resolvedIPv4": addresses,
            "resolutionError": resolution_error,
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
    write_text_atomic(path, json.dumps(document, ensure_ascii=False, indent=2) + "\n")
    return path
