"""Genera un guion verificable para un video sobre la Weezy Icon Cup."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .client import FortniteAPIClient
from .deep_icon_cup_research import (
    _category_items,
    _is_lil_wayne_record,
    _probe,
    _record_summary,
    _records,
    _spanish_type,
    _type_value,
)
from .evidence import staleness, staleness_notice
from .icon_cup_research import (
    BEEBOM_URL,
    EPIC_COMPETITIVE_URL,
    EPIC_ITEM_SHOP_CUPS_URL,
    EPIC_RULES_LIBRARY_URL,
    FORTNITE_API_COSMETICS_DOCS,
    FORTNITE_API_HOME,
    OFFICIAL_TEASER_URL,
    ORIGINAL_POST_URL,
    _read_public_post,
)
from .transport import write_text_atomic


# These are the event pages found during the live deep check. Fortnite-API.com
# catalogs cosmetics, but it does not expose the tournament schedule or payout
# table; those fields come from Epic's public Competitive page and the public
# event data rendered by Fortnite Tracker.
EPIC_WEEZY_EVENT_BR_URL = (
    "https://www.fortnite.com/competitive/events/S42_WeezyIconCup?"
    "region=NAC&round=S42_WeezyIconCup_NAC"
)
EPIC_WEEZY_EVENT_ZB_URL = (
    "https://www.fortnite.com/competitive/events/S42_WeezyIconCup?"
    "region=NAC&round=S42_WeezyIconCup_ZB_NAC"
)
EPIC_WEEZY_SCHEDULE_URL = "https://www.fortnite.com/competitive/events/S42_WeezyIconCup/schedule?region=NAC"
TRACKER_WEEZY_BR_URL = "https://fortnitetracker.com/events/epicgames_S42_WeezyIconCup_NAC"
TRACKER_WEEZY_ZB_URL = "https://fortnitetracker.com/events/epicgames_S42_WeezyIconCup_ZB_NAC"

WEEZY_EVENT_FACTS = {
    "officialEpic": {
        "eventName": "Copa de ídolos de Weezy",
        "region": "NAC",
        "date": "2026-09-12",
        "displayedStart": "17:00",
        "displayedEnd": "20:00",
        "displayedTimeNote": "hora mostrada por el calendario oficial para NAC",
        "modes": ["Solo Battle Royale", "Solo Zero Build"],
        "regionsListed": ["ASIA", "ME", "NAW", "EU", "BR", "NAE", "NAC", "OCE"],
        "platformsListed": ["Xbox", "PlayStation", "Teléfonos", "PC", "Nintendo Switch"],
        "minimumAge": 13,
        "mfaRequired": True,
        "page": EPIC_WEEZY_EVENT_BR_URL,
        "zeroBuildPage": EPIC_WEEZY_EVENT_ZB_URL,
        "schedulePage": EPIC_WEEZY_SCHEDULE_URL,
    },
    "publicEventFeed": {
        "battleRoyaleEventId": "epicgames_S42_WeezyIconCup_NAC",
        "zeroBuildEventId": "epicgames_S42_WeezyIconCup_ZB_NAC",
        "eventType": "ShopCup",
        "matchCap": 11,
        "scoring": {
            "Victory Royale": 7,
            "Segundo lugar": 4,
            "Tercer lugar": 2,
            "Top 4 a Top 50": 1,
            "Cada eliminación": 2,
        },
        "tiebreaker": [
            "Victorias campales acumuladas",
            "Promedio de eliminaciones",
            "Promedio de desempate por colocación",
            "Tiempo promedio con vida",
        ],
        "prizes": [
            {
                "condition": "Top 700",
                "items": ["Weezy (atuendo)", "Weezy Board (accesorio mochilero)"],
                "sourceValues": [
                    "AthenaCharacter:character_noisecluegust",
                    "AthenaBackpack:backpack_noisecluegust",
                ],
            },
            {
                "condition": "Conseguir 8 puntos",
                "items": ["YM (emoticono)"],
                "sourceValues": ["AthenaDance:emoticon_noiseclue"],
            },
        ],
        "battleRoyalePage": TRACKER_WEEZY_BR_URL,
        "zeroBuildPage": TRACKER_WEEZY_ZB_URL,
        "sourceNote": "datos públicos del evento renderizados por Fortnite Tracker; no son un endpoint de Fortnite-API.com",
    },
}

# Fecha en la que se contrastaron a mano los hechos competitivos de arriba.
# El informe avisa cuando este snapshot envejece: unos premios o una hora
# caducados locutados como confirmados son el error más caro del módulo.
WEEZY_FACTS_VERIFIED_AT = "2026-09-15"
WEEZY_FACTS_MAX_AGE_DAYS = 10


@dataclass(frozen=True)
class VideoBriefArtifacts:
    report_path: Path
    snapshot_path: Path
    api_probes: tuple[dict[str, Any], ...]


def _contains(value: Any, terms: tuple[str, ...]) -> bool:
    encoded = json.dumps(value, ensure_ascii=False).casefold()
    return any(term.casefold() in encoded for term in terms)


def build_video_brief(
    client: FortniteAPIClient,
    output_dir: Path,
    language: str = "en",
    timeout: float = 30,
) -> VideoBriefArtifacts:
    """Consulta datos actuales y produce un guion listo para locución."""
    output_dir.mkdir(parents=True, exist_ok=True)
    retrieved = datetime.now(timezone.utc)
    retrieved_iso = retrieved.isoformat()
    query_specs = (
        ("newCosmetics", "/v2/cosmetics/new", {"language": language}),
        ("setLilWayne", "/v2/cosmetics/br/search/all", {"set": "Lil Wayne", "matchMethod": "full", "language": language}),
        ("tracks", "/v2/cosmetics/tracks", {"language": language}),
        ("instruments", "/v2/cosmetics/instruments", {"language": language}),
        ("shop", "/v2/shop", {"language": language}),
        ("news", "/v2/news/br", {"language": language}),
        ("eventsV1", "/v1/events", {"language": language}),
        ("eventsV2", "/v2/events", {"language": language}),
        ("tournamentsV1", "/v1/tournaments", {"language": language}),
        ("tournamentsV2", "/v2/tournaments", {"language": language}),
    )
    values: dict[str, Any | None] = {}
    probes: list[dict[str, Any]] = []
    for name, path, params in query_specs:
        probe, value = _probe(client, name, path, params)
        probes.append(probe)
        values[name] = value

    set_records = _records(values.get("setLilWayne"))
    new_categories = _category_items(values.get("newCosmetics"))
    tracks = [
        _record_summary(record, "tracks")
        for record in _records(values.get("tracks"))
        if _contains(record, ("lil wayne",))
    ]
    instruments = [
        _record_summary(record, "instruments")
        for record in _records(values.get("instruments"))
        if _is_lil_wayne_record(record, "instruments")
    ]
    set_summaries = [_record_summary(record, "br") for record in set_records]
    outfits = [record for record in set_records if _type_value(record.get("type")) == "Outfit"]
    type_counts = Counter(_spanish_type("br", record) for record in set_records)
    outfit_names = ", ".join(
        str(record.get("name") or "sin nombre") for record in outfits
    ) or "ninguno"
    track_titles = ", ".join(
        str(item.get("title") or "sin título") for item in tracks
    ) or "ninguna"
    instrument_names = ", ".join(
        str(item.get("name") or item.get("title") or "sin nombre")
        for item in instruments
    ) or "ninguno"
    catalog_summary = ", ".join(
        f"{label}: {count}" for label, count in sorted(type_counts.items())
    ) or "sin registros"
    status_by_name = {
        str(probe.get("name")): (
            f"HTTP {probe.get('httpStatus')}"
            if probe.get("httpStatus") is not None
            else "sin respuesta"
        )
        for probe in probes
    }
    tournament_probe_statuses = "; ".join(
        f"{name}: {status_by_name.get(name, 'sin datos')}"
        for name in ("eventsV1", "eventsV2", "tournamentsV1", "tournamentsV2")
    )
    official_event = WEEZY_EVENT_FACTS["officialEpic"]
    public_event = WEEZY_EVENT_FACTS["publicEventFeed"]
    score_text = ", ".join(
        f"{label} +{points}"
        for label, points in public_event.get("scoring", {}).items()
    )
    prize_text = "; ".join(
        f"{item.get('condition')}: {', '.join(item.get('items', []))}"
        for item in public_event.get("prizes", [])
    ) or "no configurado"
    event_modes = " y ".join(official_event.get("modes", [])) or "modo no indicado"
    event_date = str(official_event.get("date") or "fecha no indicada")
    event_time = (
        f"{official_event.get('displayedStart', 'n/d')}–"
        f"{official_event.get('displayedEnd', 'n/d')}"
    )
    tiebreaker_text = ", ".join(public_event.get("tiebreaker", [])) or "no indicado"
    prize_by_condition = {
        str(item.get("condition")): ", ".join(item.get("items", []))
        for item in public_event.get("prizes", [])
        if item.get("condition")
    }
    placement_prize = prize_by_condition.get("Top 700", "no configurado")
    points_prize = next(
        (
            f"{condition}: {items}"
            for condition, items in prize_by_condition.items()
            if condition != "Top 700"
        ),
        "no configurado",
    )
    visual_names = ", ".join(
        str(record.get("name") or "sin nombre") for record in set_records[:5]
    ) or "no hay registros"
    outfit_voice = (
        f"Los atuendos catalogados son {outfit_names}."
        if outfits
        else "No hay atuendos catalogados en este snapshot."
    )
    snapshot_event_evidence = {
        **WEEZY_EVENT_FACTS,
        "verification": {
            "mode": "configured_snapshot",
            "revalidatedInThisRun": False,
            "verifiedAt": WEEZY_FACTS_VERIFIED_AT,
            "maxAgeDays": WEEZY_FACTS_MAX_AGE_DAYS,
            "note": "Los datos competitivos están configurados en el repositorio y no se vuelven a consultar automáticamente.",
        },
    }
    facts_age_days, facts_stale = staleness(
        WEEZY_FACTS_VERIFIED_AT,
        now=retrieved,
        max_age_days=WEEZY_FACTS_MAX_AGE_DAYS,
    )
    snapshot_event_evidence["verification"]["ageDays"] = facts_age_days
    snapshot_event_evidence["verification"]["stale"] = facts_stale
    facts_notice = staleness_notice(
        "datos competitivos del evento",
        WEEZY_FACTS_VERIFIED_AT,
        now=retrieved,
        max_age_days=WEEZY_FACTS_MAX_AGE_DAYS,
        sources="Pestaña Competir del juego y biblioteca de reglas de Epic.",
    )
    public_checks, post = _read_public_post(timeout)
    post_text = str((post or {}).get("text") or "no disponible").replace("\n", " / ")
    post_date = str((post or {}).get("createdAt") or "no disponible")
    public_check_summary = "; ".join(
        (
            f"HTTP {check.get('httpStatus')}"
            if check.get("httpStatus") is not None
            else str(check.get("errorType") or "sin respuesta")
        )
        for check in public_checks
    ) or "sin comprobaciones"

    snapshot = {
        "investigation": {
            "topic": "Video brief Weezy Icon Cup / Lil Wayne",
            "source": "Fortnite-API.com",
            "retrievedAt": retrieved_iso,
            "language": language,
            "baseUrl": client.base_url,
        },
        "queries": probes,
        "newCategoryCounts": {key: len(value) for key, value in new_categories.items()},
        "setLilWayne": set_summaries,
        "tracksLilWayne": tracks,
        "instrumentsLilWayne": instruments,
        "publicSources": {
            "originalPost": ORIGINAL_POST_URL,
            "originalPostText": post_text,
            "originalPostCreatedAt": post_date,
            "publicMirrorChecks": public_checks,
            "officialTeaser": OFFICIAL_TEASER_URL,
        },
        "eventEvidence": snapshot_event_evidence,
    }

    lines = [
        "# Guion para video: Weezy Icon Cup / Lil Wayne",
        "",
        f"**Investigación actualizada:** {retrieved_iso}",
        "**Objetivo:** video informativo de 60–90 segundos, sin presentar rumores como confirmaciones.",
        "",
        facts_notice,
        "",
        "## Veredicto para el video",
        "",
        f"La colaboración de Lil Wayne tiene {len(set_records)} registros BR en el snapshot ({catalog_summary}), {len(tracks)} canciones de Festival y {len(instruments)} instrumento(s) relacionado(s). Los atuendos encontrados son: {outfit_names}. La ficha competitiva configurada para esta investigación indica {official_event.get('region')} el {official_event.get('date')}, con {', '.join(official_event.get('modes', [])) or 'modo no indicado'}.",
        "",
        "La API de Fortnite-API.com confirma los cosméticos. Los datos competitivos proceden de un snapshot configurado en el repositorio; esta ejecución no revalida automáticamente la página de Epic ni el feed público de Fortnite Tracker.",
        "",
        "## Ficha competitiva encontrada",
        "",
        "| Dato | Resultado actual | Fuente |",
        "|---|---|---|",
        f"| Región consultada | {official_event.get('region', 'no indicada')} | Snapshot configurado |",
        f"| Fecha y hora | {official_event.get('date', 'no indicada')}, {official_event.get('displayedStart', 'n/d')}–{official_event.get('displayedEnd', 'n/d')} | Snapshot configurado |",
        f"| Modos | {', '.join(official_event.get('modes', [])) or 'no indicados'} | Snapshot configurado |",
        f"| Plataformas | {', '.join(official_event.get('platformsListed', [])) or 'no indicadas'} | Snapshot configurado |",
        f"| Premio por colocación | Top 700: {placement_prize} | Snapshot configurado |",
        f"| Premio por puntos | {points_prize} | Snapshot configurado |",
        f"| Partidas máximas | {public_event.get('matchCap', 'no indicado')} | Snapshot configurado |",
        f"| Requisitos explícitos | {official_event.get('minimumAge', 'n/d')} años; MFA: {'sí' if official_event.get('mfaRequired') else 'no indicada'} | Snapshot configurado |",
        "",
        f"El snapshot configurado muestra {official_event.get('displayedStart', 'n/d')}–{official_event.get('displayedEnd', 'n/d')} para {official_event.get('region', 'la región indicada')}. Confirma la hora en la pestaña Competir de tu cuenta si juegas desde otra región o si el cliente convierte la zona horaria.",
        "",
        "## Qué aporta cada fuente",
        "",
        f"- Fortnite-API.com: confirma el catálogo del set `Lil Wayne`, {len(tracks)} pista(s) de Festival y {instrument_names}; estados de las rutas de eventos/torneos: {tournament_probe_statuses}.",
        "- Epic Games y Fortnite Tracker: los datos competitivos se mantienen como snapshot configurado y deben revalidarse antes de publicar el video; no se consultan automáticamente en esta ejecución.",
        f"- Puntuación y premios configurados: {score_text or 'no disponibles'}; {prize_text}.",
        "",
        "## Guion de locución",
        "",
        "### Hook — 0:00–0:07",
        "",
        "“Lil Wayne está llegando a Fortnite y la Weezy Icon Cup ya tiene una pista muy fuerte: la API acaba de revelar prácticamente todo un paquete de cosméticos.”",
        "",
        "### Qué se anunció — 0:07–0:17",
        "",
        f"“El reporte de [FNcompReport]({ORIGINAL_POST_URL}) adelantó una copa para {event_date}. En el snapshot configurado, la ficha de [Copa de ídolos de Weezy]({EPIC_WEEZY_EVENT_BR_URL}) aparece para {official_event.get('region', 'la región indicada')} en {event_modes}, de {event_time}. Verifica estos datos antes de publicar.”",
        "",
        "### Lo que ya aparece en la API — 0:17–0:39",
        "",
        f"“La búsqueda exacta del set `Lil Wayne` devuelve {len(set_records)} objetos de Battle Royale. El desglose de esta ejecución es: {catalog_summary}.”",
        "",
        f"“{outfit_voice} La API devuelve los metadatos y las variantes registradas en este snapshot; muestra únicamente los nombres y atributos que aparezcan en los datos.”",
        "",
        "### Festival — 0:39–0:50",
        "",
        f"“El paquete también trae {len(tracks)} canción(es) de Festival: {track_titles}. Además aparecen estos instrumentos relacionados: {instrument_names}. Son recursos catalogados; la API no significa por sí sola que ya estén a la venta.”",
        "",
        "### Torneo, puntuación y premios — 0:50–1:12",
        "",
        f"“La ficha competitiva configurada indica hasta {public_event.get('matchCap', 'un número no indicado')} partidas. La puntuación configurada es: {score_text or 'no disponible'}. El desempate indicado es: {tiebreaker_text}.”",
        "",
        f"“El feed público configurado señala {placement_prize} para el Top 700 y {points_prize} por puntos. Trátalo como un dato pendiente de revalidación y no lo presentes como dinero ni como las dos skins completas.”",
        "",
        "### Cierre responsable — 1:12–1:24",
        "",
        "“Antes de publicar, revalida la ficha de Epic, el reglamento específico, la región y el feed de premios. En este reporte, los cosméticos proceden de la API y los datos competitivos son un snapshot configurado que puede cambiar.”",
        "",
        "## Datos a mostrar en pantalla",
        "",
        "| Elemento | Estado | Texto recomendado en el video |",
        "|---|---|---|",
        f"| Teaser oficial | URL configurada; comprobaciones públicas: {public_check_summary} | “Teaser oficial de Fortnite” |",
        f"| Atuendos catalogados | {len(outfits)} en esta ejecución | “{outfit_names}” |",
        f"| Catálogo BR | {len(set_records)} registros; {catalog_summary} | “Set Lil Wayne” |",
        f"| {len(tracks)} canciones | Registros devueltos por `/v2/cosmetics/tracks` | “{track_titles}” |",
        f"| Weezy Icon Cup | Snapshot configurado; no se revalida automáticamente | “Copa indicada para {official_event.get('region', 'la región indicada')}” |",
        f"| Horario configurado | {event_time} | “{event_modes}” |",
        f"| Puntuación configurada | {score_text or 'no disponible'} | Revalidar antes de publicar |",
        f"| Premio Top 700 | {placement_prize} | Revalidar antes de publicar |",
        f"| Premio por puntos | {points_prize} | Revalidar antes de publicar |",
        "| Reglamento específico | Estado pendiente de comprobación | No presentarlo como confirmado |",
        "",
        "## Orden visual recomendado",
        "",
        "1. Mostrar el póster de la Weezy Icon Cup si la descarga de la fuente pública fue válida.",
        f"2. Cortar a los atuendos catalogados: {outfit_names}.",
        f"3. Mostrar los primeros recursos del catálogo: {visual_names}.",
        f"4. Mostrar las carátulas de Festival disponibles: {track_titles}.",
        f"5. Cerrar con una tarjeta que indique “{official_event.get('region', 'región no indicada')} · {event_date} · {event_time}” y marque los premios como snapshot pendiente de revalidación.",
        "",
        "## Frases que conviene evitar",
        "",
        "- “La skin será gratis para todos” — no conviertas un premio configurado o pendiente de revalidación en una recompensa universal.",
        f"- “El ganador recibe las dos skins” — el catálogo contiene {len(outfits)} atuendo(s), pero eso no determina el premio del torneo.",
        f"- “La copa empieza a la misma hora en todo el mundo” — el snapshot solo indica {event_time} para {official_event.get('region', 'la región configurada')}.",
        "- “El reglamento ya está publicado” — la existencia o el contenido del reglamento debe comprobarse en una fuente oficial vigente.",
        "",
        "## Fuentes consultadas",
        "",
        f"- [Post de FNcompReport]({ORIGINAL_POST_URL}) — anuncio comunitario de la copa.",
        f"- [Teaser oficial de Fortnite]({OFFICIAL_TEASER_URL}) — colaboración pública.",
        f"- [Ficha oficial de la Copa de ídolos de Weezy]({EPIC_WEEZY_EVENT_BR_URL}) — modo, fecha, requisitos, plataformas y regiones.",
        f"- [Horario oficial NAC de la Copa de ídolos de Weezy]({EPIC_WEEZY_SCHEDULE_URL}) — URL de referencia; el snapshot local indica {event_date}, {event_time}.",
        f"- [Ficha de Fortnite Tracker: Battle Royale]({TRACKER_WEEZY_BR_URL}) y [Zero Build]({TRACKER_WEEZY_ZB_URL}) — tabla pública de puntuación, límite de partidas y premios del feed del evento.",
        f"- [Set Lil Wayne en Fortnite-API.com](https://fortnite-api.com/v2/cosmetics/br/search/all?set=Lil%20Wayne&matchMethod=full&language=en) — {len(set_records)} objetos BR en esta ejecución.",
        "- [Canciones de Fortnite-API.com](https://fortnite-api.com/v2/cosmetics/tracks?language=en) — carátulas y metadatos de Festival.",
        f"- [Instrumentos de Fortnite-API.com](https://fortnite-api.com/v2/cosmetics/instruments?language=en) — {instrument_names}.",
        f"- [Item Shop Cups de Epic]({EPIC_ITEM_SHOP_CUPS_URL}) — marco general y reglas variables por copa.",
        f"- [Agenda competitiva oficial]({EPIC_COMPETITIVE_URL}) y [Rules Library]({EPIC_RULES_LIBRARY_URL}) — revisión de publicación y reglamento específico.",
        f"- [Beebom]({BEEBOM_URL}) — cobertura secundaria del teaser; no se usa para confirmar premios.",
        f"- [Fortnite-API.com]({FORTNITE_API_HOME}) y [documentación de cosméticos]({FORTNITE_API_COSMETICS_DOCS}).",
        "",
        "## Nota editorial",
        "",
        "Las imágenes y el vídeo se deben usar limpios, sin texto añadido encima. El nombre y la explicación de cada recurso pueden ir en la narración, en subtítulos del video o en el pie del mensaje de Telegram. Este documento usa la información disponible al momento del snapshot; el feed del evento y el horario pueden actualizarse antes de iniciar.",
        "",
    ]
    report = "\n".join(lines)
    timestamp = retrieved.strftime("%Y%m%dT%H%M%SZ")
    report_path = output_dir / f"{timestamp}-guion-video-weezy-icon-cup.md"
    snapshot_path = output_dir / f"{timestamp}-snapshot-guion-weezy-icon-cup.json"
    write_text_atomic(report_path, report)
    write_text_atomic(snapshot_path, json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n")
    return VideoBriefArtifacts(report_path, snapshot_path, tuple(probes))
