"""Persistencia de expedientes de investigación."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
import re

from .client import APIResult


def _slug(value: str) -> str:
    clean = re.sub(r"[^a-zA-Z0-9.-]+", "-", value).strip("-").lower()
    return clean or "consulta"


def save_result(result: APIResult, output_dir: Path, label: str) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc)
    filename = f"{timestamp.strftime('%Y%m%dT%H%M%SZ')}-{_slug(label)}.json"
    document = {
        "investigation": {
            "source": "Fortnite-API.com",
            "retrievedAt": timestamp.isoformat(),
            "path": result.path,
            "params": result.params,
            "httpStatus": result.status_code,
        },
        "response": result.payload,
    }
    path = output_dir / filename
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path

