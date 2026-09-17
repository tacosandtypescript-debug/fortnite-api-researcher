"""Descarga y entrega banners de perfil de Fortnite como documentos PNG."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .client import FortniteAPIClient
from .evidence import sum_bytes
from .schedule_assets import _data, _download_image, _slug
from .telegram import TelegramDocumentSender


WOLVERINE_BANNER_IDS: tuple[str, ...] = (
    "BRS14_HighTowerDate",
    "BRS14_HighTowerGrape",
    "BRS14_HighTowerHoneyDew",
    "BRS14_HighTowerMango",
    "BRS14_HighTowerWasabi",
)


@dataclass(frozen=True)
class BannerDelivery:
    files: tuple[Path, ...]
    ids: tuple[str, ...]
    bytes_total: int
    missing: tuple[str, ...] = ()


def _banner_index(value: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(value, list):
        return {}
    return {
        str(item.get("id")): item
        for item in value
        if isinstance(item, dict) and item.get("id")
    }


def prepare_wolverine_banners(
    client: FortniteAPIClient,
    output_dir: Path,
    language: str = "en",
    timeout: float = 30,
) -> BannerDelivery:
    """Descarga los banners disponibles y tolera que alguno falte.

    Epic retira identificadores de banners con el tiempo. Antes, un solo id
    ausente abortaba la entrega completa; ahora se informa de los que faltan y
    solo se falla si no se pudo obtener ninguno. Los errores de datos se lanzan
    como ``ValueError`` (no como error de Telegram, que aún no ha intervenido).
    """
    response = client.get("/v1/banners", {"language": language})
    banners = _banner_index(_data(response.payload))
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_dir.mkdir(parents=True, exist_ok=True)
    files: list[Path] = []
    download_entries: list[dict[str, Any]] = []
    missing: list[str] = []
    for banner_id in WOLVERINE_BANNER_IDS:
        banner = banners.get(banner_id)
        if not banner:
            missing.append(banner_id)
            continue
        images = banner.get("images") or {}
        icon_url = images.get("icon") if isinstance(images, dict) else None
        if not icon_url:
            missing.append(banner_id)
            continue
        destination = output_dir / f"{timestamp}-banner-{_slug(banner_id)}.png"
        result = _download_image(str(icon_url), destination, timeout)
        if not result.get("downloaded"):
            missing.append(banner_id)
            continue
        files.append(destination)
        download_entries.append(result)
    if not files:
        raise ValueError(
            "No se pudo descargar ningún banner de la lista configurada; "
            "Epic pudo retirar estos identificadores de la API"
        )
    return BannerDelivery(
        tuple(files),
        WOLVERINE_BANNER_IDS,
        sum_bytes(download_entries),
        tuple(missing),
    )


def send_banner_documents(
    delivery: BannerDelivery,
    sender: TelegramDocumentSender,
) -> None:
    # ``strict=True``: si las dos listas se desalinearan, el envío debe fallar en
    # vez de emparejar un archivo con el pie de otro banner.
    for path, banner_id in zip(delivery.files, delivery.ids, strict=True):
        sender.send_document(
            path,
            caption=f"Banner Fortnite Marvel/Wolverine: {banner_id}",
        )
