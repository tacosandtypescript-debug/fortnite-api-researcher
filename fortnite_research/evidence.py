"""Utilidades compartidas para no perder evidencia ni romperse con datos raros.

Dos problemas se repetían en los módulos de investigación:

* un dato inesperado de la API (``duration: "3:45"``, ``width: null``, ``bytes``
  ausente) abortaba la ejecución **después** de haber descargado cientos de
  megabytes, porque el casteo se hacía en la fase de redacción del informe;
* cualquier fallo de una ruta se publicaba como «no expuesta por la API», de
  modo que un 401, un 403 o un 429 (límite de peticiones) se leían como prueba
  de que la ruta no existe.

Este módulo concentra las dos correcciones para que el criterio sea idéntico en
todos los informes.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

# Estados HTTP que sí permiten afirmar que una ruta no está publicada.
NOT_FOUND_STATUS = frozenset({404, 410})
# Estados que significan «no puedo concluir»: credenciales, límite o servidor.
CREDENTIAL_STATUS = frozenset({401, 403, 407})
RATE_LIMIT_STATUS = frozenset({429})


def int_or_none(value: Any) -> int | None:
    """Convierte a entero lo convertible y devuelve ``None`` si no lo es."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if math.isfinite(value) else None
    text = str(value).strip().replace("\u00a0", "").replace(",", "")
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return int(float(text))
    except (TypeError, ValueError, OverflowError):
        return None


def int_or_zero(value: Any) -> int:
    """Igual que :func:`int_or_none` pero con cero como valor neutro."""
    parsed = int_or_none(value)
    return parsed if parsed is not None else 0


def sum_bytes(items: Iterable[Mapping[str, Any]]) -> int:
    """Suma ``bytes`` de una colección de entradas de manifiesto."""
    return sum(int_or_zero(item.get("bytes")) for item in items)


def probe_status_kind(status: Any) -> str:
    """Clasifica un estado HTTP en una categoría interpretable."""
    code = int_or_none(status)
    if code is None:
        return "no_response"
    if 200 <= code < 300:
        return "ok"
    if code in NOT_FOUND_STATUS:
        return "not_found"
    if code in CREDENTIAL_STATUS:
        return "credentials"
    if code in RATE_LIMIT_STATUS:
        return "rate_limited"
    if code >= 500:
        return "server_error"
    return "other"


def probe_interpretation(
    probe: Mapping[str, Any],
    *,
    not_found: str,
    unknown: str = "No concluyente",
) -> str:
    """Explica un sondeo fallido sin confundir «no existe» con «no lo sé».

    Solo un 404/410 se interpreta como ausencia de ruta. Un 401/403, un 429 o un
    5xx son resultados no concluyentes y así deben aparecer en el informe: un
    límite de peticiones publicado como «ruta no publicada» es una conclusión
    falsa.
    """
    status = probe.get("httpStatus")
    kind = probe_status_kind(status)
    if kind == "not_found":
        return not_found
    if kind == "credentials":
        return (
            f"Requiere credenciales o permisos (HTTP {status}); "
            "no es prueba de que la ruta no exista"
        )
    if kind == "rate_limited":
        return (
            f"Límite de peticiones alcanzado (HTTP {status}); "
            "repite la consulta antes de concluir"
        )
    if kind == "server_error":
        return (
            f"Error temporal del servidor (HTTP {status}); "
            "no es prueba de que la ruta no exista"
        )
    if kind == "no_response":
        return "Sin respuesta HTTP; no concluyente"
    return f"{unknown} (HTTP {status})"


def describe_status(status: Any) -> str:
    """Etiqueta corta del estado de un sondeo, útil en tablas Markdown."""
    code = int_or_none(status)
    return "sin respuesta" if code is None else str(code)


def parse_utc(value: Any) -> datetime | None:
    """Interpreta una fecha ISO (o un instante Unix) como UTC."""
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def staleness(
    verified_at: Any,
    *,
    now: datetime,
    max_age_days: int,
) -> tuple[int | None, bool]:
    """Días desde la verificación de un dato y si debe considerarse caducado.

    Una fecha ausente o ilegible se trata como caducada: es preferible pedir una
    revalidación de más que publicar un dato sin fecha de origen.
    """
    verified = parse_utc(verified_at)
    if verified is None:
        return None, True
    days = (now.astimezone(timezone.utc) - verified).days
    return days, days > max_age_days


def staleness_notice(
    label: str,
    verified_at: Any,
    *,
    now: datetime,
    max_age_days: int,
    sources: str = "",
) -> str:
    """Frase de vigencia para anteponer a cualquier informe con datos fijados.

    Los hechos competitivos viven en el repositorio y no se revalidan solos: el
    informe debe decirlo en la primera pantalla y no en una nota al pie.
    """
    days, stale = staleness(verified_at, now=now, max_age_days=max_age_days)
    age = "sin fecha de verificación" if days is None else f"{days} día(s)"
    if stale:
        return (
            f"> ⚠️ **REVALIDAR ANTES DE PUBLICAR.** {label}: verificados el "
            f"{verified_at} ({age}) y no se han vuelto a consultar en esta ejecución. "
            f"Contrasta fecha, hora, formato y premios en la fuente oficial. {sources}".strip()
        )
    return (
        f"> Vigencia de {label}: verificados el {verified_at} ({age}). "
        "Vuelve a contrastarlos si publicas más adelante."
    )
