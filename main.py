"""Ponto de entrada do sistema de monitoramento operacional.

Uso:
    python main.py --all
    python main.py --site "CONSUMO TEFE"
    python main.py --site "CONSUMO TEFE" --send
    python main.py --site "CONSUMO TEFE" --no-send
    python main.py --telegram-test
    python main.py --schedule
    python main.py --cleanup
    python main.py --list
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime

from core.config import load_settings
from core.logging_setup import setup_logging
from core.paths import ensure_directories
from core.retention import cleanup_old_screenshots
from core.scheduler import run_scheduler
from core.workflow import CaptureRunner

EXIT_OK = 0
EXIT_PARTIAL = 1
EXIT_FATAL = 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="main.py",
        description="Monitoramento operacional: captura de dashboards e envio via Telegram.",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--all", action="store_true", help="Captura todos os sites habilitados no config.yaml.")
    group.add_argument("--site", metavar="NOME", help="Captura apenas o site informado (nome exato do config.yaml).")
    group.add_argument("--telegram-test", action="store_true", help="Envia uma mensagem de teste ao Telegram.")
    group.add_argument("--schedule", action="store_true", help="Inicia o agendador (execucao continua).")
    group.add_argument("--cleanup", action="store_true", help="Remove screenshots mais antigos que a retencao.")
    group.add_argument("--list", action="store_true", help="Lista os sites configurados e sai.")

    parser.add_argument(
        "--send",
        dest="send",
        action="store_true",
        default=None,
        help="Forca o envio ao Telegram.",
    )
    parser.add_argument(
        "--no-send",
        dest="send",
        action="store_false",
        help="Captura sem enviar (util para testar seletores).",
    )
    parser.add_argument(
        "--headed",
        action="store_true",
        help="Sobrescreve HEADLESS e abre o navegador visivel.",
    )
    parser.add_argument("--config", default=None, help="Caminho alternativo para o config.yaml.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    settings = load_settings(config_path=args.config)
    ensure_directories(settings)
    logger = setup_logging(settings)

    if args.list:
        for site in settings.sites:
            status = "habilitado" if site.enabled else "desabilitado"
            logger.info("%s | %s | %s | periodo=%s | %s", site.name, site.system, site.url, site.period, status)
        return EXIT_OK

    if args.headed:
        settings.browser.headless = False

    if args.telegram_test:
        from services.telegram import TelegramClient

        client = TelegramClient(settings.telegram, logger)
        if not client.configured:
            logger.error("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID nao configurados no .env.")
            return EXIT_FATAL
        ok = client.send_message("✅ Bot de monitoramento conectado com sucesso.")
        if ok:
            logger.info("Mensagem de teste enviada ao Telegram.")
            return EXIT_OK
        logger.error("Falha ao enviar a mensagem de teste.")
        return EXIT_FATAL

    if args.cleanup:
        removed = cleanup_old_screenshots(settings)
        logger.info("Limpeza concluida: %d arquivo(s) removido(s).", removed)
        return EXIT_OK

    if args.schedule:
        run_scheduler(settings, logger)
        return EXIT_OK

    send = settings.telegram.send_by_default if args.send is None else args.send
    runner = CaptureRunner(settings, logger)

    if args.all:
        results = runner.run_all(send=send)
    else:
        results = [runner.run_site(args.site, send=send)]

    if not results:
        logger.warning("Nenhum resultado produzido.")
        return EXIT_FATAL

    failures = [r for r in results if not r.ok]
    for result in results:
        if result.ok:
            logger.info("[OK] %s -> %s", result.site_name, result.image_path)
        else:
            logger.error("[FALHA] %s -> %s", result.site_name, result.error)

    return EXIT_PARTIAL if failures else EXIT_OK


if __name__ == "__main__":
    started = time.monotonic()
    try:
        code = main()
    except KeyboardInterrupt:
        print("\nInterrompido pelo usuario.", file=sys.stderr)
        code = EXIT_FATAL
    elapsed = time.monotonic() - started
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Finalizado em {elapsed:.1f}s (exit={code})")
    sys.exit(code)
