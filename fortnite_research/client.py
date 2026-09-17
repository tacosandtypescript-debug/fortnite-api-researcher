"""Cliente pequeño y sin dependencias para Fortnite-API.com."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any, Iterable, Mapping
from urllib.parse import urlencode

from .transport import HTTPFetchError, fetch, validate_https_url

# Límite de lectura por respuesta. El catálogo completo de Battle Royale
# (/v2/cosmetics/br) supera los 10 MB, así que un tope ajustado impedía
# precisamente el volcado completo que pide el comando `get`.
DEFAULT_MAX_BYTES = 32_000_000

# Rutas que devuelven el catálogo entero y necesitan margen.
BULK_ROUTES = ("/v2/cosmetics/br", "/v2/cosmetics/cars", "/v2/cosmetics/tracks")

# Formatos aceptados por /v2/aes.
AES_KEY_FORMATS = ("hex", "base64")


class FortniteAPIError(RuntimeError):
    """Error de transporte, HTTP o formato de Fortnite-API.com."""

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class APIResult:
    path: str
    params: dict[str, str]
    status_code: int
    payload: Any


class FortniteAPIClient:
    def __init__(
        self,
        base_url: str = "https://fortnite-api.com",
        api_key: str | None = None,
        timeout: float = 30,
        trusted_api_hosts: Iterable[str] | None = None,
        max_bytes: int = DEFAULT_MAX_BYTES,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        if timeout <= 0 or not math.isfinite(timeout):
            raise ValueError("timeout debe ser mayor que cero y finito")
        if max_bytes <= 0:
            raise ValueError("max_bytes debe ser mayor que cero")
        self.timeout = timeout
        self.max_bytes = max_bytes
        self.api_host = validate_https_url(self.base_url)
        trusted = (
            trusted_api_hosts
            if trusted_api_hosts is not None
            else ("fortnite-api.com", "www.fortnite-api.com")
        )
        self.trusted_api_hosts = frozenset(
            str(host).strip().casefold()
            for host in trusted
            if str(host).strip()
        )
        if self.api_key and self.api_host not in self.trusted_api_hosts:
            raise ValueError(
                "La API key solo se puede enviar a un hostname confiable"
            )
        self._allowed_hosts = (
            self.trusted_api_hosts
            if self.api_key
            else frozenset({self.api_host})
        )

    def get(
        self,
        path: str,
        params: Mapping[str, str] | None = None,
        *,
        max_bytes: int | None = None,
    ) -> APIResult:
        if not path.startswith("/") or path.startswith("//"):
            raise ValueError("La ruta debe comenzar con / y ser relativa a la API")
        limit = self.max_bytes if max_bytes is None else max_bytes
        if limit <= 0:
            raise ValueError("max_bytes debe ser mayor que cero")
        query = {str(k): str(v) for k, v in (params or {}).items() if str(v) != ""}
        url = f"{self.base_url}{path}"
        if query:
            url = f"{url}?{urlencode(query, doseq=True)}"
        headers = {
            "Accept": "application/json",
            "User-Agent": "fortnite-api-researcher/0.1.0",
        }
        if self.api_key:
            headers["x-api-key"] = self.api_key
        try:
            response = fetch(
                url,
                headers=headers,
                timeout=self.timeout,
                max_bytes=limit,
                retries=2,
                allowed_hosts=self._allowed_hosts,
            )
        except HTTPFetchError as exc:
            raise FortniteAPIError(
                f"La API no pudo completar la consulta: {exc}",
                status_code=exc.status_code,
            ) from exc
        try:
            payload = json.loads(response.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise FortniteAPIError("La API devolvió una respuesta que no es JSON válido") from exc
        return APIResult(
            path=path,
            params=query,
            status_code=response.status_code,
            payload=payload,
        )

    def shop(self, language: str = "en") -> APIResult:
        return self.get("/v2/shop", {"language": language})

    def aes(self, key_format: str = "hex") -> APIResult:
        """Claves AES del build actual.

        Fortnite-API movió este endpoint: ``/v1/aes`` responde 410 (retirada) y
        la ruta vigente es ``/v2/aes``.
        """
        if key_format not in AES_KEY_FORMATS:
            raise ValueError("key-format debe ser hex o base64")
        return self.get("/v2/aes", {"keyFormat": key_format})

    def cosmetics_br(self, language: str = "en") -> APIResult:
        """Catálogo completo de Battle Royale (respuesta voluminosa)."""
        return self.get("/v2/cosmetics/br", {"language": language})

    def news(self, kind: str = "br", language: str = "en") -> APIResult:
        if kind not in {"br", "stw", "creative"}:
            raise ValueError("kind debe ser br, stw o creative")
        return self.get(f"/v2/news/{kind}", {"language": language})

    def cosmetic_search(
        self,
        name: str,
        language: str = "en",
        match_method: str = "contains",
        all_results: bool = True,
        *,
        max_bytes: int | None = None,
    ) -> APIResult:
        if not name.strip():
            raise ValueError("name no puede estar vacío")
        if match_method not in {"full", "contains", "starts", "ends"}:
            raise ValueError("match-method debe ser full, contains, starts o ends")
        endpoint = "/v2/cosmetics/br/search/all" if all_results else "/v2/cosmetics/br/search"
        return self.get(
            endpoint,
            {"name": name, "matchMethod": match_method, "language": language},
            max_bytes=max_bytes,
        )
