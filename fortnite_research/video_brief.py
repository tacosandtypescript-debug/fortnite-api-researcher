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


@dataclass(frozen=True)
class VideoBriefArtifacts:
    report_path: Path
    snapshot_path: Path
    api_probes: tuple[dict[str, Any], ...]


def _contains(value: Any, terms: tuple[str, ...]) -> bool:
    encoded = json.dumps(value, ensure_ascii=False).casefold()
    return any(term.casefold() in encoded for term in terms)


def _duration_text(seconds: Any) -> str:
    total = int(seconds or 0)
    minutes, remaining = divmod(total, 60)
    return f"{minutes}:{remaining:02d}"


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
    public_checks, post = _read_public_post(timeout)
    post_text = str((post or {}).get("text") or "no disponible").replace("\n", " / ")
    post_date = str((post or {}).get("createdAt") or "no disponible")

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
        "eventEvidence": WEEZY_EVENT_FACTS,
    }

    lines = [
        "# Guion para video: Weezy Icon Cup / Lil Wayne",
        "",
        f"**Investigación actualizada:** {retrieved_iso}",
        "**Objetivo:** video informativo de 60–90 segundos, sin presentar rumores como confirmaciones.",
        "",
        "## Veredicto para el video",
        "",
        "La colaboración de Lil Wayne ya tiene una huella muy clara en el catálogo: dos skins, accesorios, dos emotes, un emoticono, tres canciones de Festival y una guitarra. La diferencia importante de esta revisión es que la Weezy Icon Cup ya aparece en la ficha oficial de Competitivo de Fortnite para NAC, el sábado 12 de septiembre, con Battle Royale y Zero Build en solitario.",
        "",
        "El anuncio comunitario de FNcompReport quedó corroborado por Epic. La API de Fortnite-API.com confirma los cosméticos, mientras que el horario, la puntuación y los premios salen de la página oficial de Competitivo y de los datos públicos del evento que muestra Fortnite Tracker.",
        "",
        "## Ficha competitiva encontrada",
        "",
        "| Dato | Resultado actual | Fuente |",
        "|---|---|---|",
        "| Región consultada | NAC | Calendario oficial |",
        "| Fecha y hora | Sábado 12 de septiembre, 5:00 p. m.–8:00 p. m. | Calendario oficial NAC |",
        "| Modos | Solo Battle Royale y Solo Zero Build | Rondas oficiales del evento |",
        "| Plataformas | Xbox, PlayStation, teléfonos, PC y Nintendo Switch | Ficha oficial |",
        "| Premio por colocación | Top 700: `Weezy` + `Weezy Board` | Feed público del evento |",
        "| Premio por puntos | 8 puntos: `YM` | Feed público del evento |",
        "| Partidas máximas | 11 | Feed público del evento |",
        "| Requisitos explícitos | 13 años o edad mínima local y AMF/MFA habilitada | Ficha oficial |",
        "",
        "El calendario oficial muestra las mismas 5:00 p. m.–8:00 p. m. para las dos rondas en NAC. Confirma la hora en la pestaña Competir de tu cuenta si juegas desde otra región o si el cliente convierte la zona horaria.",
        "",
        "## Qué aporta cada fuente",
        "",
        "- Fortnite-API.com: confirma el catálogo del set `Lil Wayne`, las pistas de Festival y `Tha Guitar`; las rutas probadas de eventos/torneos devolvieron 404.",
        "- Epic Games: confirma que la Copa de ídolos de Weezy existe, sus modos, la fecha de NAC, las plataformas, las regiones visibles y los requisitos básicos.",
        "- Fortnite Tracker: expone los datos públicos del evento que permiten leer puntuación, límite de 11 partidas y premios; sus páginas son una fuente secundaria del feed de evento, no la biblioteca oficial de reglas.",
        "",
        "## Guion de locución",
        "",
        "### Hook — 0:00–0:07",
        "",
        "“Lil Wayne está llegando a Fortnite y la Weezy Icon Cup ya tiene una pista muy fuerte: la API acaba de revelar prácticamente todo un paquete de cosméticos.”",
        "",
        "### Qué se anunció — 0:07–0:17",
        "",
        f"“El reporte de [FNcompReport]({ORIGINAL_POST_URL}) adelantó una copa para el sábado 12 de septiembre. Ya no es solo un rumor: la ficha oficial de [Copa de ídolos de Weezy]({EPIC_WEEZY_EVENT_BR_URL}) la muestra para NAC en Solo Battle Royale y Solo Zero Build, de 5:00 a 8:00 de la tarde.”",
        "",
        "### Lo que ya aparece en la API — 0:17–0:39",
        "",
        f"“La búsqueda exacta del set `Lil Wayne` devuelve {len(set_records)} objetos de Battle Royale: {type_counts.get('Atuendo / skin', 0)} skins, {type_counts.get('Accesorio mochilero', 0)} accesorios mochileros, {type_counts.get('Pico', 0)} picos, {type_counts.get('Emote', 0)} emotes, un emoticono, un ala delta, una pantalla de carga y una envoltura.”",
        "",
        "“Las dos skins se llaman `Weezy` y `Lil Wayne`. La skin Weezy tiene variantes de sombrero, gafas, camiseta sin mangas y reactividad; la segunda tiene variantes de gafas y reactividad.”",
        "",
        "### Festival — 0:39–0:50",
        "",
        f"“El paquete también trae {len(tracks)} canciones de Festival: {', '.join(str(item.get('title')) for item in tracks)}. Además aparece `Tha Guitar` como instrumento de Festival. Son recursos catalogados; la API no significa por sí sola que ya estén a la venta.”",
        "",
        "### Torneo, puntuación y premios — 0:50–1:12",
        "",
        "“La ficha del evento indica hasta 11 partidas. La puntuación es de 7 puntos por Victoria Royale, 4 por segundo lugar, 2 por tercero, 1 punto del cuarto al puesto 50 y 2 por cada eliminación. El desempate se resuelve por victorias, promedio de eliminaciones, promedio del desempate de colocación y tiempo promedio con vida.”",
        "",
        "“El feed público del evento señala que el Top 700 recibe acceso a `Weezy` y `Weezy Board`, mientras que alcanzar 8 puntos entrega el emoticono `YM`. La página oficial describe la recompensa como acceso al lote Weezy; no la presentes como dinero ni como las dos skins completas.”",
        "",
        "### Cierre responsable — 1:12–1:24",
        "",
        "“Lo único que sigue pendiente es ver el reglamento específico publicado por Epic y comprobar cómo se reflejarán las recompensas en cada región. Para el video ya puedes afirmar que la copa está listada oficialmente, pero conviene decir que los premios concretos provienen del feed público del evento y pueden actualizarse antes de comenzar.”",
        "",
        "## Datos confirmados para mostrar en pantalla",
        "",
        "| Elemento | Estado | Texto recomendado en el video |",
        "|---|---|---|",
        "| Teaser oficial | Confirmado por la cuenta Fortnite | “Teaser oficial de Fortnite” |",
        "| Dos skins | Confirmadas como registros del catálogo | “Weezy” y “Lil Wayne” |",
        "| 13 objetos BR | Confirmados por búsqueda exacta del set | “Set Lil Wayne: 13 objetos BR” |",
        f"| {len(tracks)} canciones | Confirmadas por `/v2/cosmetics/tracks` | “Lollipop, A Milli (2023 Remix), 6 Foot 7 Foot” |",
        "| Weezy Icon Cup | Listada en la ficha oficial de Competitivo | “Copa oficial: NAC, 12 de septiembre” |",
        "| Horario NAC | 5:00 p. m.–8:00 p. m. | “Battle Royale y Zero Build” |",
        "| Puntuación | Feed público del evento | “Victoria +7 / elim +2” |",
        "| Premio Top 700 | Feed público del evento | “Weezy + Weezy Board” |",
        "| Premio de 8 puntos | Feed público del evento | “YM” |",
        "| Reglamento específico | No aparece identificado en la biblioteca al momento de revisar | Presentar la tabla como datos actuales del evento |",
        "",
        "## Orden visual recomendado",
        "",
        "1. Mostrar el póster de la Weezy Icon Cup recibido del post comunitario.",
        "2. Cortar a las dos imágenes de skin: primero `Weezy`, después `Lil Wayne`.",
        "3. Mostrar rápidamente `Weezy Board`, `Weezy Boardbreaker`, `Young Money Stage`, `YM Burner` y `Tha Guitar`.",
        "4. Mostrar las carátulas de `Lollipop`, `A Milli (2023 Remix)` y `6 Foot 7 Foot` como bloque de Festival.",
        "5. Cerrar con una tarjeta textual fuera de las imágenes: “NAC · 12 sep · 5–8 p. m. · Top 700: Weezy + Weezy Board”.",
        "",
        "## Frases que conviene evitar",
        "",
        "- “La skin será gratis para todos” — el premio está limitado al Top 700 según el feed consultado.",
        "- “El ganador recibe las dos skins” — el premio identificado es `Weezy` más `Weezy Board`; `Lil Wayne` es otro registro del catálogo.",
        "- “La copa empieza a las [hora] en todo el mundo” — 5:00–8:00 p. m. es el horario mostrado para NAC; otras regiones pueden tener otra hora local.",
        "- “El reglamento ya está publicado” — la ficha oficial existe, pero no encontré una página específica de reglas Weezy en la biblioteca al momento de esta revisión.",
        "",
        "## Fuentes consultadas",
        "",
        f"- [Post de FNcompReport]({ORIGINAL_POST_URL}) — anuncio comunitario de la copa.",
        f"- [Teaser oficial de Fortnite]({OFFICIAL_TEASER_URL}) — colaboración pública.",
        f"- [Ficha oficial de la Copa de ídolos de Weezy]({EPIC_WEEZY_EVENT_BR_URL}) — modo, fecha, requisitos, plataformas y regiones.",
        f"- [Horario oficial NAC de la Copa de ídolos de Weezy]({EPIC_WEEZY_SCHEDULE_URL}) — sesión del 12 de septiembre, 5:00 p. m.–8:00 p. m. para las dos rondas.",
        f"- [Ficha de Fortnite Tracker: Battle Royale]({TRACKER_WEEZY_BR_URL}) y [Zero Build]({TRACKER_WEEZY_ZB_URL}) — tabla pública de puntuación, límite de partidas y premios del feed del evento.",
        f"- [Set Lil Wayne en Fortnite-API.com](https://fortnite-api.com/v2/cosmetics/br/search/all?set=Lil%20Wayne&matchMethod=full&language=en) — 13 objetos BR.",
        f"- [Canciones de Fortnite-API.com](https://fortnite-api.com/v2/cosmetics/tracks?language=en) — carátulas y metadatos de Festival.",
        f"- [Instrumentos de Fortnite-API.com](https://fortnite-api.com/v2/cosmetics/instruments?language=en) — guitarra `Tha Guitar`.",
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
    report_path.write_text(report, encoding="utf-8")
    snapshot_path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return VideoBriefArtifacts(report_path, snapshot_path, tuple(probes))
