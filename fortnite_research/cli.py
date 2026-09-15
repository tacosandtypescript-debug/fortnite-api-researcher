"""CLI del investigador de Fortnite."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .client import FortniteAPIClient, FortniteAPIError
from .banner_delivery import prepare_wolverine_banners, send_banner_documents
from .config import Settings
from .deep_stw import build_deep_stw_report, save_deep_stw_report
from .deep_icon_cup_research import build_deep_icon_cup_research_package
from .icon_cup_research import build_icon_cup_research_package
from .penny_bot import run_penny_bot
from .video_brief import build_video_brief
from .regions import build_region_report, save_region_report
from .report import save_result
from .schedule_assets import build_schedule_package
from .sprite_research import build_sprite_research_package
from .stw import build_stw_report, save_stw_report
from .telegram import TelegramDocumentSender, TelegramError


def _params(values: list[str]) -> dict[str, str]:
    params: dict[str, str] = {}
    for value in values:
        if "=" not in value:
            raise ValueError(f"--param debe tener formato clave=valor: {value}")
        key, item = value.split("=", 1)
        if not key:
            raise ValueError("La clave de --param no puede estar vacía")
        params[key] = item
    return params


def _telegram_sender(settings: Settings) -> TelegramDocumentSender:
    """Prepara el envío sin descubrir chats salvo autorización explícita."""
    sender = TelegramDocumentSender(settings.telegram_bot_token, settings.telegram_chat_id)
    if not sender.chat_id and settings.telegram_allow_chat_discovery:
        sender.chat_id = sender.find_recent_start_chat_id()
    if not sender.chat_id and settings.telegram_allow_chat_discovery:
        sender.chat_id = sender.find_recent_private_chat_id()
    return sender


def _client(settings: Settings) -> FortniteAPIClient:
    return FortniteAPIClient(
        settings.api_base_url,
        settings.api_key,
        settings.api_timeout,
        trusted_api_hosts=settings.api_trusted_hosts,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Investiga Fortnite-API.com y guarda/entrega el resultado")
    sub = parser.add_subparsers(dest="command", required=True)

    shop = sub.add_parser("shop", help="Consulta la tienda actual")
    shop.add_argument("--language", default="en")
    shop.add_argument("--send", action="store_true", help="Envía el JSON como documento por Telegram")

    news = sub.add_parser("news", help="Consulta noticias")
    news.add_argument("--kind", choices=["br", "stw", "creative"], default="br")
    news.add_argument("--language", default="en")
    news.add_argument("--send", action="store_true")

    stw = sub.add_parser("stw", help="Investiga endpoints de Salvar el Mundo y alertas de pavos")
    stw.add_argument("--language", default="es")
    stw.add_argument("--send", action="store_true", help="Envía el expediente como documento por Telegram")

    stw_deep = sub.add_parser("stw-deep", help="Busca a fondo fuentes de misiones y alertas de pavos STW")
    stw_deep.add_argument("--language", default="es")
    stw_deep.add_argument("--send", action="store_true", help="Envía la investigación Markdown como documento por Telegram")

    bot = sub.add_parser(
        "bot",
        help="Monitoriza Penny y avisa por Telegram de pavos, llamas, cosméticos y noticias",
    )
    bot.add_argument(
        "--interval",
        type=float,
        default=None,
        help="Segundos entre consultas; por defecto PENNY_POLL_INTERVAL_SECONDS",
    )
    bot.add_argument(
        "--once",
        action="store_true",
        help="Consulta y notifica una sola vez, sin quedarse ejecutándose",
    )
    bot.add_argument(
        "--dry-run",
        action="store_true",
        help="Muestra la alerta sin enviarla a Telegram",
    )

    cosmetic = sub.add_parser("cosmetic-search", help="Busca cosméticos de Battle Royale")
    cosmetic.add_argument("--name", required=True)
    cosmetic.add_argument("--match-method", choices=["full", "contains", "starts", "ends"], default="contains")
    cosmetic.add_argument("--language", default="en")
    cosmetic.add_argument("--first-only", action="store_true")
    cosmetic.add_argument("--send", action="store_true")

    generic = sub.add_parser("get", help="Consulta una ruta documentada directamente")
    generic.add_argument("path", help="Ejemplo: /v1/playlists")
    generic.add_argument("--param", action="append", default=[], help="Parámetro clave=valor; puede repetirse")
    generic.add_argument("--send", action="store_true")

    servers = sub.add_parser("servers", help="Busca rutas de servidores/regiones y mide endpoints oficiales")
    servers.add_argument("--send", action="store_true", help="Envía el JSON como documento por Telegram")

    schedule = sub.add_parser(
        "schedule-assets",
        help="Investiga fechas de colaboraciones y empaqueta imágenes CDN originales",
    )
    schedule.add_argument("--language", default="en")
    schedule.add_argument("--send", action="store_true", help="Envía informe y ZIP como documentos por Telegram")

    banners = sub.add_parser(
        "banners",
        help="Prepara cinco banners de perfil Marvel/Wolverine y puede enviarlos",
    )
    banners.add_argument("--language", default="en")
    banners.add_argument("--send", action="store_true", help="Envía los cinco PNG por Telegram")

    sprites = sub.add_parser(
        "sprites-research",
        help="Investiga Loot Hacker Sprites y empaqueta la imagen de referencia",
    )
    sprites.add_argument("--image", type=Path, required=True, help="Imagen recibida de la publicación")
    sprites.add_argument("--language", default="en")
    sprites.add_argument("--send", action="store_true", help="Envía informe y ZIP como documentos por Telegram")

    icon_cup = sub.add_parser(
        "icon-cup-research",
        help="Investiga una Icon Cup, consulta cosméticos y empaqueta medios originales",
    )
    icon_cup.add_argument("--image", type=Path, required=True, help="Imagen recibida de la publicación")
    icon_cup.add_argument("--language", default="en")
    icon_cup.add_argument("--send", action="store_true", help="Envía informe y ZIP como documentos por Telegram")

    deep_icon_cup = sub.add_parser(
        "deep-icon-cup-research",
        help="Investiga a fondo una Icon Cup: tandas nuevas, skins, variantes y Festival",
    )
    deep_icon_cup.add_argument("--image", type=Path, required=True, help="Imagen recibida de la publicación")
    deep_icon_cup.add_argument("--language", default="en")
    deep_icon_cup.add_argument(
        "--send",
        action="store_true",
        help="Envía el informe y los recursos seleccionados individualmente por Telegram",
    )

    video_brief = sub.add_parser(
        "video-brief",
        help="Revisa el estado del torneo y genera un guion verificable para video",
    )
    video_brief.add_argument("--language", default="en")
    video_brief.add_argument("--send", action="store_true", help="Envía el guion y el snapshot como documentos por Telegram")

    send_file = sub.add_parser("send-file", help="Envía un archivo existente como documento por Telegram")
    send_file.add_argument("path", type=Path)
    send_file.add_argument("--caption", default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        settings = Settings.load()
        if args.command == "bot":
            return run_penny_bot(
                settings,
                interval=args.interval,
                once=args.once,
                dry_run=args.dry_run,
            )
        if args.command == "send-file":
            sender = _telegram_sender(settings)
            sender.send_document(args.path, caption=args.caption)
            print(f"ENVIADO POR TELEGRAM: {args.path}")
            return 0
        if args.command == "servers":
            client = _client(settings)
            api_checks: dict[str, dict] = {}
            for path in ("/v1/status", "/v1/servers", "/v1/regions"):
                try:
                    response = client.get(path)
                    api_checks[path] = {"httpStatus": response.status_code, "available": True, "responseKeys": list(response.payload) if isinstance(response.payload, dict) else []}
                except FortniteAPIError as exc:
                    api_checks[path] = {"httpStatus": exc.status_code, "available": False, "errorType": "api_error"}
            document = build_region_report(api_checks)
            output_path = save_region_report(document, settings.output_dir)
            label = "servidores-fortnite-na"
            should_send = args.send or settings.auto_send_telegram
            if should_send:
                sender = _telegram_sender(settings)
                sender.send_document(output_path, caption=f"Investigación Fortnite: {label}")
                print(f"ENVIADO POR TELEGRAM: {output_path}")
            else:
                print(f"GUARDADO: {output_path}")
            return 0
        if args.command == "stw":
            client = _client(settings)
            document = build_stw_report(client, args.language)
            output_path = save_stw_report(document, settings.output_dir)
            label = "salvar-el-mundo-endpoints"
            should_send = args.send or settings.auto_send_telegram
            if should_send:
                sender = _telegram_sender(settings)
                sender.send_document(output_path, caption=f"Investigación Fortnite: {label}")
                print(f"ENVIADO POR TELEGRAM: {output_path}")
            else:
                print(f"GUARDADO: {output_path}")
            return 0
        if args.command == "stw-deep":
            client = _client(settings)
            document = build_deep_stw_report(client, args.language, settings.api_timeout)
            output_path = save_deep_stw_report(document, settings.output_dir)
            should_send = args.send or settings.auto_send_telegram
            if should_send:
                sender = _telegram_sender(settings)
                sender.send_document(output_path, caption="Investigación profunda Fortnite: Salvar el Mundo")
                print(f"ENVIADO POR TELEGRAM: {output_path}")
            else:
                print(f"GUARDADO: {output_path}")
            return 0
        if args.command == "schedule-assets":
            client = _client(settings)
            artifacts = build_schedule_package(
                client,
                settings.output_dir,
                language=args.language,
                timeout=settings.api_timeout,
            )
            should_send = args.send or settings.auto_send_telegram
            if should_send:
                sender = _telegram_sender(settings)
                sender.send_document(
                    artifacts.report_path,
                    caption="Investigación Fortnite: calendario, skins, banners y vídeos",
                )
                sender.send_document(
                    artifacts.archive_path,
                    caption=(
                        "Recursos Fortnite: imágenes CDN originales y manifiesto "
                        f"({artifacts.asset_count} archivos)"
                    ),
                )
                print(f"ENVIADO POR TELEGRAM: {artifacts.report_path}")
                print(f"ENVIADO POR TELEGRAM: {artifacts.archive_path}")
            else:
                print(f"GUARDADO: {artifacts.report_path}")
                print(f"GUARDADO: {artifacts.archive_path}")
            print(f"IMAGENES VALIDADAS: {artifacts.asset_count}; BYTES: {artifacts.asset_bytes}")
            print(f"REGISTROS POR OBJETIVO: {artifacts.target_counts}")
            return 0
        if args.command == "banners":
            client = _client(settings)
            delivery = prepare_wolverine_banners(
                client,
                settings.output_dir,
                language=args.language,
                timeout=settings.api_timeout,
            )
            should_send = args.send or settings.auto_send_telegram
            if should_send:
                sender = _telegram_sender(settings)
                send_banner_documents(delivery, sender)
                for path in delivery.files:
                    print(f"ENVIADO POR TELEGRAM: {path}")
            else:
                for path in delivery.files:
                    print(f"GUARDADO: {path}")
            print(f"BANNERS: {len(delivery.files)}; BYTES: {delivery.bytes_total}")
            return 0
        if args.command == "sprites-research":
            client = _client(settings)
            artifacts = build_sprite_research_package(
                client,
                settings.output_dir,
                reference_image=args.image,
                language=args.language,
                timeout=settings.api_timeout,
            )
            should_send = args.send or settings.auto_send_telegram
            if should_send:
                sender = _telegram_sender(settings)
                sender.send_document(
                    artifacts.report_path,
                    caption="Investigación Fortnite: Loot Hacker Sprites / FNBRunderground",
                )
                sender.send_document(
                    artifacts.archive_path,
                    caption=(
                        "Recursos Loot Hacker Sprites: imagen de referencia, noticias API y manifiesto "
                        f"({artifacts.asset_count} archivos)"
                    ),
                )
                print(f"ENVIADO POR TELEGRAM: {artifacts.report_path}")
                print(f"ENVIADO POR TELEGRAM: {artifacts.archive_path}")
            else:
                print(f"GUARDADO: {artifacts.report_path}")
                print(f"GUARDADO: {artifacts.archive_path}")
            print(f"RECURSOS VALIDADOS: {artifacts.asset_count}; BYTES: {artifacts.asset_bytes}")
            for probe in artifacts.api_probes:
                print(f"API {probe.get('name')}: HTTP {probe.get('httpStatus')}")
            return 0
        if args.command == "icon-cup-research":
            client = _client(settings)
            artifacts = build_icon_cup_research_package(
                client,
                settings.output_dir,
                reference_image=args.image,
                language=args.language,
                timeout=settings.api_timeout,
            )
            should_send = args.send or settings.auto_send_telegram
            if should_send:
                sender = _telegram_sender(settings)
                sender.send_document(
                    artifacts.report_path,
                    caption="Investigación Fortnite: Weezy Icon Cup / Lil Wayne",
                )
                sender.send_document(
                    artifacts.archive_path,
                    caption=(
                        "Recursos Weezy Icon Cup: imagen, teaser, cosméticos API y manifiesto "
                        f"({artifacts.asset_count} archivos)"
                    ),
                )
                print(f"ENVIADO POR TELEGRAM: {artifacts.report_path}")
                print(f"ENVIADO POR TELEGRAM: {artifacts.archive_path}")
            else:
                print(f"GUARDADO: {artifacts.report_path}")
                print(f"GUARDADO: {artifacts.archive_path}")
            print(f"RECURSOS VALIDADOS: {artifacts.asset_count}; BYTES: {artifacts.asset_bytes}")
            for probe in artifacts.api_probes:
                print(f"API {probe.get('name')}: HTTP {probe.get('httpStatus')}")
            return 0
        if args.command == "deep-icon-cup-research":
            client = _client(settings)
            artifacts = build_deep_icon_cup_research_package(
                client,
                settings.output_dir,
                reference_image=args.image,
                language=args.language,
                timeout=settings.api_timeout,
            )
            should_send = args.send or settings.auto_send_telegram
            if should_send:
                sender = _telegram_sender(settings)
                sender.send_document(
                    artifacts.report_path,
                    caption="Investigación profunda Fortnite: Weezy Icon Cup / Lil Wayne",
                )
                sender.send_document(
                    artifacts.snapshot_path,
                    caption="Snapshot API Fortnite: cosméticos, skins, variantes y Festival",
                )
                for item in artifacts.asset_entries:
                    if not item.get("telegramDelivery") or not item.get("downloaded"):
                        continue
                    path = Path(str(item["path"]))
                    sender.send_document(path, caption=str(item.get("caption") or "Recurso Fortnite"))
                    print(f"ENVIADO POR TELEGRAM: {path}")
                print(f"ENVIADO POR TELEGRAM: {artifacts.report_path}")
                print(f"ENVIADO POR TELEGRAM: {artifacts.snapshot_path}")
            else:
                print(f"GUARDADO: {artifacts.report_path}")
                print(f"GUARDADO: {artifacts.snapshot_path}")
            selected = [item for item in artifacts.asset_entries if item.get("telegramDelivery") and item.get("downloaded")]
            successful = [item for item in artifacts.asset_entries if item.get("downloaded")]
            print(f"RECURSOS VALIDADOS: {len(successful)}; SELECCIONADOS PARA TELEGRAM: {len(selected)}")
            print(f"BYTES ORIGINALES: {sum(int(item.get('bytes', 0)) for item in successful):,}")
            for probe in artifacts.api_probes:
                print(f"API {probe.get('name')}: HTTP {probe.get('httpStatus')}")
            return 0
        if args.command == "video-brief":
            client = _client(settings)
            artifacts = build_video_brief(
                client,
                settings.output_dir,
                language=args.language,
                timeout=settings.api_timeout,
            )
            should_send = args.send or settings.auto_send_telegram
            if should_send:
                sender = _telegram_sender(settings)
                sender.send_document(
                    artifacts.report_path,
                    caption="Guion para video Fortnite: Weezy Icon Cup / Lil Wayne",
                )
                sender.send_document(
                    artifacts.snapshot_path,
                    caption="Datos API del guion: torneo, skins y Festival",
                )
                print(f"ENVIADO POR TELEGRAM: {artifacts.report_path}")
                print(f"ENVIADO POR TELEGRAM: {artifacts.snapshot_path}")
            else:
                print(f"GUARDADO: {artifacts.report_path}")
                print(f"GUARDADO: {artifacts.snapshot_path}")
            for probe in artifacts.api_probes:
                print(f"API {probe.get('name')}: HTTP {probe.get('httpStatus')}")
            return 0
        client = _client(settings)
        if args.command == "shop":
            result = client.shop(args.language)
            label = f"tienda-{args.language}"
        elif args.command == "news":
            result = client.news(args.kind, args.language)
            label = f"noticias-{args.kind}-{args.language}"
        elif args.command == "cosmetic-search":
            result = client.cosmetic_search(args.name, args.language, args.match_method, not args.first_only)
            label = f"cosmeticos-{args.name}"
        else:
            result = client.get(args.path, _params(args.param))
            label = args.path.strip("/").replace("/", "-")
        output_path = save_result(result, settings.output_dir, label)
        should_send = args.send or settings.auto_send_telegram
        if should_send:
            sender = _telegram_sender(settings)
            sender.send_document(output_path, caption=f"Investigación Fortnite: {label}")
            print(f"ENVIADO POR TELEGRAM: {output_path}")
        else:
            print(f"GUARDADO: {output_path}")
        return 0
    except (FortniteAPIError, TelegramError, ValueError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
