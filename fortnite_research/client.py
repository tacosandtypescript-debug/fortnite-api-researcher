"""Cliente pequeño y sin dependencias para Fortnite-API.com."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


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
    def __init__(self, base_url: str = "https://fortnite-api.com", api_key: str | None = None, timeout: float = 30):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    def get(self, path: str, params: Mapping[str, str] | None = None) -> APIResult:
        if not path.startswith("/") or path.startswith("//"):
            raise ValueError("La ruta debe comenzar con / y ser relativa a la API")
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
        request = Request(url, headers=headers, method="GET")
        try:
            with urlopen(request, timeout=self.timeout) as response:
                status_code = int(response.status)
                body = response.read()
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:1000]
            raise FortniteAPIError(f"La API respondió HTTP {exc.code}: {detail}", status_code=exc.code) from exc
        except URLError as exc:
            raise FortniteAPIError(f"No se pudo conectar con Fortnite-API.com: {exc.reason}") from exc
        except TimeoutError as exc:
            raise FortniteAPIError("La consulta a Fortnite-API.com agotó el tiempo de espera") from exc
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise FortniteAPIError("La API devolvió una respuesta que no es JSON válido") from exc
        return APIResult(path=path, params=query, status_code=status_code, payload=payload)

    def shop(self, language: str = "en") -> APIResult:
        return self.get("/v2/shop", {"language": language})

    def news(self, kind: str = "br", language: str = "en") -> APIResult:
        if kind not in {"br", "stw", "creative"}:
            raise ValueError("kind debe ser br, stw o creative")
        return self.get(f"/v2/news/{kind}", {"language": language})

    def cosmetic_search(self, name: str, language: str = "en", match_method: str = "contains", all_results: bool = True) -> APIResult:
        if not name.strip():
            raise ValueError("name no puede estar vacío")
        if match_method not in {"full", "contains", "starts", "ends"}:
            raise ValueError("match-method debe ser full, contains, starts o ends")
        endpoint = "/v2/cosmetics/br/search/all" if all_results else "/v2/cosmetics/br/search"
        return self.get(endpoint, {"name": name, "matchMethod": match_method, "language": language})
