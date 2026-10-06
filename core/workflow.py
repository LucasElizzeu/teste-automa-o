"""Orquestracao: captura -> tratamento da imagem -> envio -> log.

Este modulo e o unico lugar que conhece a sequencia completa. Os servicos
sabem capturar, o cliente Telegram sabe enviar, e o workflow costura tudo
com retry e isolamento de falhas (um site quebrado nao derruba os outros).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo

from core.config import Settings, SiteSpec, credentials_for, login_url_for
from core.paths import SCREENSHOTS_DIR
from services.base import CaptureRequest, build_url_with_period
from services.registry import get_service_class
from services.telegram import TelegramClient, build_client
from utils.caption import build_caption, build_error_message
from utils.images import annotate_image, crop_image


@dataclass
class SiteResult:
    site_name: str
    ok: bool
    image_path: Path | None = None
    error: str | None = None
    duration: float = 0.0
    attempts: int = 1


@dataclass
class RunSummary:
    started_at: datetime
    results: list[SiteResult] = field(default_factory=list)

    @property
    def ok_count(self) -> int:
        return sum(1 for r in self.results if r.ok)

    @property
    def fail_count(self) -> int:
        return sum(1 for r in self.results if not r.ok)


class CaptureRunner:
    """Executa a captura de um ou de todos os sites."""

    def __init__(self, settings: Settings, logger):
        self.settings = settings
        self.logger = logger
        self.tz = self._resolve_timezone(settings.schedule.timezone)

    # ------------------------------------------------------------- utilidades

    @staticmethod
    def _resolve_timezone(name: str) -> ZoneInfo:
        try:
            return ZoneInfo(name)
        except Exception:
            return ZoneInfo("America/Manaus")

    def now(self) -> datetime:
        return datetime.now(self.tz)

    def _filename(self, site: SiteSpec, moment: datetime) -> Path:
        pattern = self.settings.output.filename_pattern
        name = pattern.format(
            date=moment.strftime("%Y-%m-%d"),
            time=moment.strftime("%H-%M"),
            site=site.slug,
            system=site.system.upper(),
        )
        day_dir = Path(SCREENSHOTS_DIR) / moment.strftime("%Y-%m-%d")
        day_dir.mkdir(parents=True, exist_ok=True)
        return day_dir / name

    # --------------------------------------------------------------- execucao

    def run_all(self, send: bool = True) -> list[SiteResult]:
        sites = self.settings.enabled_sites
        if not sites:
            self.logger.warning("Nenhum site habilitado no config.yaml.")
            return []
        self.logger.info("Iniciando captura de %d site(s).", len(sites))

        telegram = build_client(self.settings, self.logger) if send else None
        if send and telegram and not telegram.configured:
            self.logger.warning(
                "TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID ausentes: as capturas serao feitas sem envio."
            )

        results: list[SiteResult] = []
        for site in sites:
            results.append(self._run_single(site, telegram))
        return results

    def run_site(self, name: str, send: bool = True) -> SiteResult:
        site = self.settings.find_site(name)
        telegram = build_client(self.settings, self.logger) if send else None
        return self._run_single(site, telegram)

    def _run_single(self, site: SiteSpec, telegram: TelegramClient | None) -> SiteResult:
        attempts = max(1, self.settings.auth.retry_attempts)
        last_error: str | None = None
        started = time.monotonic()

        for attempt in range(1, attempts + 1):
            self.logger.info(
                "Iniciando captura | site=%s | sistema=%s | tentativa=%d/%d",
                site.name,
                site.system,
                attempt,
                attempts,
            )
            try:
                image_path = self._capture_once(site)
            except Exception as exc:
                last_error = self._describe(exc)
                self.logger.error(
                    "Dashboard nao carregou | site=%s | tentativa=%d | erro=%s",
                    site.name,
                    attempt,
                    last_error,
                )
                if attempt < attempts:
                    wait = self.settings.auth.backoff_for(attempt)
                    self.logger.info("Aguardando %ds antes da proxima tentativa.", wait)
                    time.sleep(wait)
                    continue
                break

            duration = time.monotonic() - started
            self.logger.info("Screenshot criado | site=%s | arquivo=%s", site.name, image_path.name)

            if telegram is not None:
                if self._send(site, image_path, telegram):
                    self.logger.info("Imagem enviada ao Telegram | site=%s", site.name)
                else:
                    self.logger.error("Falha ao enviar ao Telegram | site=%s", site.name)

            return SiteResult(
                site_name=site.name,
                ok=True,
                image_path=image_path,
                duration=duration,
                attempts=attempt,
            )

        reason = last_error or "erro desconhecido"
        self.logger.error("Site %s falhou apos %d tentativa(s): %s", site.name, attempts, reason)
        if telegram is not None:
            telegram.send_error(site.name, site.system, reason, chat_id=site.chat_id)

        return SiteResult(
            site_name=site.name,
            ok=False,
            error=reason,
            duration=time.monotonic() - started,
            attempts=attempts,
        )

    def _capture_once(self, site: SiteSpec) -> Path:
        """Uma tentativa completa: captura, recorta, identifica e salva."""
        spec = self.settings.get_system(site.system)
        service_class = get_service_class(self.settings, site.system)

        moment = self.now()
        request = CaptureRequest(
            site=site,
            spec=spec,
            settings=self.settings,
            logger=self.logger,
            storage_path=Path(SCREENSHOTS_DIR),
            period=site.period,
        )
        service = service_class(request)
        capture = service.capture()

        raw = capture.image_bytes
        region = site.crop_region or self.settings.output.crop_region
        processed = crop_image(raw, region) if region else raw
        if region:
            self.logger.info("Imagem recortada para a regiao configurada.")

        if self.settings.output.add_label_banner:
            processed = annotate_image(
                processed,
                site=site.name,
                system=site.system,
                moment=moment,
                description=site.description,
                period=site.period,
            )
            self.logger.info("Identificacao adicionada a imagem.")

        destination = self._filename(site, moment)
        destination.write_bytes(processed)
        return destination

    def _send(self, site: SiteSpec, image_path: Path, telegram: TelegramClient) -> bool:
        caption = build_caption(
            site_name=site.name,
            system_id=site.system,
            moment=self.now(),
            url=build_url_with_period(site.url, site.period),
            description=site.description,
        )
        return telegram.send_photo(image_path, caption=caption, chat_id=site.chat_id)

    @staticmethod
    def _describe(exc: Exception) -> str:
        """Mensagem curta e segura (sem stack, sem credenciais)."""
        text = str(exc).strip() or exc.__class__.__name__
        return text.splitlines()[0][:400]


def build_error_notice(site: SiteSpec, error: str) -> str:
    """Mensagem de erro pronta para o Telegram."""
    return build_error_message(site.name, site.system, error)


def resolve_context(settings: Settings, system_id: str) -> tuple[str, str, str | None]:
    """Devolve (usuario, senha, login_url) de um sistema - usado em diagnostico."""
    username, password = credentials_for(settings, system_id)
    return username, password, login_url_for(settings, system_id)


class _Unused:
    """Placeholder para evitar import nao usado em linters."""

    _: Callable | None = None
