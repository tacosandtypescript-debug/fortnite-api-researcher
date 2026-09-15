"""Transporte HTTP seguro y persistencia atómica para el investigador.

El proyecto usa únicamente la biblioteca estándar. Este módulo concentra las
reglas que deben ser iguales para la API, los CDN y las fuentes públicas:

* solo se aceptan URLs HTTPS;
* las respuestas tienen un límite de tamaño;
* las lecturas GET pueden reintentarse ante errores transitorios;
* las redirecciones no pueden salir de una lista de hosts permitidos;
* los archivos se escriben en un temporal y se sustituyen al final.
"""

from __future__ import annotations

import os
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterable, Iterator, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from zipfile import ZIP_DEFLATED, ZipFile


RETRYABLE_STATUS_CODES = frozenset({408, 425, 429, 500, 502, 503, 504})


class HTTPFetchError(RuntimeError):
    """Error HTTP o de transporte con el mínimo contexto útil para reportes."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        body: bytes = b"",
        headers: Any = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.body = body
        self.headers = headers


class ResponseTooLargeError(HTTPFetchError):
    """La respuesta excede el límite configurado y no debe reintentarse."""


@dataclass(frozen=True)
class HTTPResponse:
    status_code: int
    headers: Any
    body: bytes


def validate_https_url(
    url: str,
    *,
    allowed_hosts: Iterable[str] | None = None,
) -> str:
    """Valida una URL HTTPS y devuelve su hostname normalizado."""
    if not isinstance(url, str) or not url.strip():
        raise ValueError("La URL no puede estar vacía")
    try:
        parsed = urlsplit(url)
        hostname = parsed.hostname
    except ValueError as exc:
        raise ValueError("La URL no es válida") from exc
    if parsed.scheme.casefold() != "https" or not hostname:
        raise ValueError("Solo se permiten URLs HTTPS con hostname")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("La URL no puede contener credenciales embebidas")
    normalized_host = hostname.casefold()
    if allowed_hosts is not None:
        normalized_allowed = {
            str(host).strip().casefold()
            for host in allowed_hosts
            if str(host).strip()
        }
        if normalized_host not in normalized_allowed:
            raise ValueError(f"El hostname no está permitido: {hostname}")
    return normalized_host


class _SafeRedirectHandler(HTTPRedirectHandler):
    """Restringe redirecciones a HTTPS y evita filtrar la API key."""

    def __init__(self, allowed_hosts: Iterable[str] | None):
        super().__init__()
        self.allowed_hosts = (
            {
                str(host).strip().casefold()
                for host in allowed_hosts
                if str(host).strip()
            }
            if allowed_hosts is not None
            else None
        )

    def redirect_request(
        self,
        req: Request,
        fp: Any,
        code: int,
        msg: str,
        newurl: str,
    ) -> Request | None:
        try:
            origin_host = validate_https_url(req.full_url)
            target_host = validate_https_url(
                newurl,
                allowed_hosts=self.allowed_hosts,
            )
        except ValueError as exc:
            raise URLError(str(exc)) from exc
        redirected = super().redirect_request(req, fp, code, msg, newurl)
        if redirected is not None and target_host != origin_host:
            for mapping in (
                getattr(redirected, "headers", {}),
                getattr(redirected, "unredirected_hdrs", {}),
            ):
                for key in list(mapping):
                    if key.casefold() == "x-api-key":
                        del mapping[key]
        return redirected


def _open(
    request: Request,
    *,
    timeout: float,
    allowed_hosts: Iterable[str] | None,
) -> Any:
    opener = build_opener(_SafeRedirectHandler(allowed_hosts))
    return opener.open(request, timeout=timeout)


def _retry_after(headers: Any) -> float | None:
    if headers is None:
        return None
    value = headers.get("Retry-After") if hasattr(headers, "get") else None
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return None
    return min(max(seconds, 0.0), 8.0)


def _read_body(response: Any, max_bytes: int) -> bytes:
    headers = getattr(response, "headers", None)
    content_length = headers.get("Content-Length") if headers is not None else None
    try:
        declared_length = int(content_length)
    except (TypeError, ValueError):
        declared_length = None
    if declared_length is not None and declared_length > max_bytes:
        raise ResponseTooLargeError(
            f"La respuesta supera el límite de {max_bytes} bytes"
        )
    body = response.read(max_bytes + 1)
    if len(body) > max_bytes:
        raise ResponseTooLargeError(
            f"La respuesta supera el límite de {max_bytes} bytes"
        )
    return body


def _error_body(error: HTTPError, max_bytes: int) -> bytes:
    try:
        return error.read(max_bytes + 1)[:max_bytes]
    except (OSError, ValueError):
        return b""


def fetch(
    url: str,
    *,
    headers: Mapping[str, str] | None = None,
    data: bytes | None = None,
    method: str | None = None,
    timeout: float = 30,
    max_bytes: int = 10_000_000,
    retries: int = 0,
    allowed_hosts: Iterable[str] | None = None,
) -> HTTPResponse:
    """Hace una petición HTTPS y devuelve una respuesta limitada.

    Los reintentos deben reservarse para operaciones idempotentes. Por eso el
    valor predeterminado es cero; los consumidores GET pueden solicitar dos
    reintentos y los envíos con efectos laterales no los usan.
    """
    if timeout <= 0:
        raise ValueError("timeout debe ser mayor que cero")
    if max_bytes <= 0:
        raise ValueError("max_bytes debe ser mayor que cero")
    if retries < 0:
        raise ValueError("retries no puede ser negativo")
    normalized_allowed_hosts = (
        frozenset(
            str(host).strip().casefold()
            for host in allowed_hosts
            if str(host).strip()
        )
        if allowed_hosts is not None
        else None
    )
    validate_https_url(url, allowed_hosts=normalized_allowed_hosts)

    for attempt in range(retries + 1):
        request = Request(
            url,
            data=data,
            headers=dict(headers or {}),
            method=method or ("POST" if data is not None else "GET"),
        )
        try:
            with _open(
                request,
                timeout=timeout,
                allowed_hosts=normalized_allowed_hosts,
            ) as response:
                return HTTPResponse(
                    status_code=int(response.status),
                    headers=response.headers,
                    body=_read_body(response, max_bytes),
                )
        except ResponseTooLargeError:
            raise
        except HTTPError as exc:
            body = _error_body(exc, min(max_bytes, 4096))
            error = HTTPFetchError(
                f"HTTP {exc.code}: {body.decode('utf-8', errors='replace')[:1000]}",
                status_code=int(exc.code),
                body=body,
                headers=exc.headers,
            )
            retryable = exc.code in RETRYABLE_STATUS_CODES
        except (URLError, TimeoutError, OSError) as exc:
            error = HTTPFetchError(
                f"Error de transporte: {str(getattr(exc, 'reason', exc))[:300]}"
            )
            retryable = True
        if attempt >= retries or not retryable:
            raise error
        delay = _retry_after(getattr(error, "headers", None))
        if delay is None:
            delay = min(0.4 * (2**attempt), 4.0)
        time.sleep(delay)
    raise AssertionError("El bucle de reintentos terminó sin resultado")


def write_bytes_atomic(path: os.PathLike[str] | str, content: bytes) -> None:
    """Escribe bytes sin dejar un archivo final parcialmente escrito."""
    destination = os.fspath(path)
    parent = os.path.dirname(destination) or "."
    os.makedirs(parent, exist_ok=True)
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=parent,
            prefix=f".{os.path.basename(destination)}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_name = temporary.name
            temporary.write(content)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_name, destination)
        temporary_name = None
    finally:
        if temporary_name:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass


def write_text_atomic(
    path: os.PathLike[str] | str,
    content: str,
    *,
    encoding: str = "utf-8",
) -> None:
    write_bytes_atomic(path, content.encode(encoding))


@contextmanager
def atomic_zipfile(
    path: os.PathLike[str] | str,
    *,
    compression: int = ZIP_DEFLATED,
    compresslevel: int = 6,
) -> Iterator[ZipFile]:
    """Construye un ZIP temporal y lo publica solo cuando se cierra bien."""
    destination = os.fspath(path)
    parent = os.path.dirname(destination) or "."
    os.makedirs(parent, exist_ok=True)
    temporary_name: str | None = None
    archive: ZipFile | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=parent,
            prefix=f".{os.path.basename(destination)}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_name = temporary.name
        archive = ZipFile(
            temporary_name,
            mode="w",
            compression=compression,
            compresslevel=compresslevel,
        )
        yield archive
        archive.close()
        with open(temporary_name, "r+b") as complete:
            os.fsync(complete.fileno())
        os.replace(temporary_name, destination)
        temporary_name = None
    except BaseException:
        if archive is not None:
            archive.close()
        raise
    finally:
        if temporary_name:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass
