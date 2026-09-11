"""Descarga y entrega banners de perfil de Fortnite como documentos PNG."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .client import FortniteAPIClient, FortniteAPIError
from .schedule_assets import _data, _download_image, _slug
from .telegram import TelegramDocumentSender, TelegramError


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
    try:
        response = client.get("/v1/banners", {"language": language})
    except FortniteAPIError:
        raise
    banners = _banner_index(_data(response.payload))
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_dir.mkdir(parents=True, exist_ok=True)
    files: list[Path] = []
    total_bytes = 0
    for banner_id in WOLVERINE_BANNER_IDS:
        banner = banners.get(banner_id)
        if not banner:
            raise TelegramError(f"No apareció el banner solicitado en Fortnite-API: {banner_id}")
        images = banner.get("images") or {}
        icon_url = images.get("icon") if isinstance(images, dict) else None
        if not icon_url:
            raise TelegramError(f"El banner no tiene icono CDN: {banner_id}")
        destination = output_dir / f"{timestamp}-banner-{_slug(banner_id)}.png"
        result = _download_image(str(icon_url), destination, timeout)
        if not result.get("downloaded"):
            raise TelegramError(f"No se pudo validar el PNG del banner: {banner_id}")
        files.append(destination)
        total_bytes += int(result.get("bytes", 0))
    return BannerDelivery(tuple(files), WOLVERINE_BANNER_IDS, total_bytes)


def send_banner_documents(
    delivery: BannerDelivery,
    sender: TelegramDocumentSender,
) -> None:
    for path, banner_id in zip(delivery.files, delivery.ids):
        sender.send_document(
            path,
            caption=f"Banner Fortnite Marvel/Wolverine: {banner_id}",
        )
