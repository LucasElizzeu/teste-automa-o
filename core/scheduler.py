"""Agendador: dispara a captura nos horarios configurados.

Escolhas tecnicas:
  - long-running e simples de operar (roda como servico via systemd);
  - respeita o timezone do config.yaml (America/Manaus) sem depender do TZ
    do host;
  - usa um conjunto de slots por dia (hora:minuto) + intervalo opcional em
    horas, sem duplicar disparos;
  - deriva o horario sempre de um relogio real, entao um drift pequeno nao
    acumula (ao contrario de sleep(3600) repetido).

Se voce preferir cron do sistema em vez de processo residente, use:
    python main.py --all     em um crontab, 5x/dia.
Ambos funcionam; o modo --schedule existe para quem quer tudo no container.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from core.config import Settings
from core.workflow import CaptureRunner
from utils.caption import build_summary

CHECK_INTERVAL_SECONDS = 20


def _timezone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except Exception:
        return ZoneInfo("America/Manaus")


def build_slots(settings: Settings) -> set[tuple[int, int]]:
    """Conjunto {(hora, minuto)} dos disparos diarios."""
    slots: set[tuple[int, int]] = set()

    if settings.schedule.mode in {"cron", "mixed"}:
        for value in settings.schedule.times:
            hour, minute = str(value).split(":")
            slots.add((int(hour), int(minute)))

    if settings.schedule.mode in {"every", "mixed"}:
        for step in settings.schedule.every_hours:
            for hour in range(0, 24, int(step)):
                slots.add((hour, 0))

    return slots


def next_run(slots: set[tuple[int, int]], now: datetime) -> datetime | None:
    """Proximo disparo a partir de `now` (exclusive)."""
    if not slots:
        return None
    for day_offset in range(0, 2):
        day = (now + timedelta(days=day_offset)).date()
        for hour, minute in sorted(slots):
            candidate = datetime.combine(day, datetime.min.time(), tzinfo=now.tzinfo).replace(
                hour=hour, minute=minute, second=0, microsecond=0
            )
            if candidate > now:
                return candidate
    return None


def run_scheduler(settings: Settings, logger) -> None:
    """Loop principal. Interrompido com Ctrl+C (KeyboardInterrupt)."""
    tz = _timezone(settings.schedule.timezone)
    slots = build_slots(settings)

    if not slots:
        logger.error("Nenhum horario configurado em schedule.times/every_hours. Agendador encerrado.")
        return

    pretty = ", ".join(f"{h:02d}:{m:02d}" for h, m in sorted(slots))
    logger.info("Agendador ativo | timezone=%s | horarios=%s", settings.schedule.timezone, pretty)
    logger.info("Proximo disparo: %s", (next_run(slots, datetime.now(tz)) or datetime.now(tz)).strftime("%d/%m/%Y %H:%M"))

    last_fired: datetime | None = None

    while True:
        now = datetime.now(tz)
        key = (now.hour, now.minute)

        if key in slots and now.second < CHECK_INTERVAL_SECONDS * 2:
            if last_fired is None or (now - last_fired) > timedelta(minutes=1):
                last_fired = now
                logger.info("Disparo agendado %02d:%02d iniciado.", now.hour, now.minute)
                _run_cycle(settings, logger, now)

        time.sleep(CHECK_INTERVAL_SECONDS)


def _run_cycle(settings: Settings, logger, moment: datetime) -> None:
    """Uma execucao completa; falhas de um site nao afetam os demais."""
    runner = CaptureRunner(settings, logger)
    try:
        results = runner.run_all(send=settings.telegram.enabled and settings.telegram.send_by_default)
    except Exception as exc:
        logger.exception("Falha inesperada no ciclo de captura: %s", exc)
        return

    ok = sum(1 for r in results if r.ok)
    fail = len(results) - ok
    logger.info("Ciclo concluido | ok=%d | falhas=%d", ok, fail)

    if fail and settings.telegram.enabled:
        from services.telegram import build_client

        client = build_client(settings, logger)
        if client.configured:
            client.send_message(build_summary(results, moment))
