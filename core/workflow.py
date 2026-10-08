"""Orquestracao: captura -> tratamento da imagem -> gravacao em disco.

Este modulo e o unico lugar que conhece a sequencia completa. Os servicos
sabem capturar; o workflow costura tudo com retry e isolamento de falhas
(um site quebrado nao derruba os outros).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from core.config import Settings, SiteSpec
from core.paths import SCREENSHOTS_DIR
from services.base import CaptureRequest
from services.registry import get_service_class
from utils.images import crop_image


@dataclass
class SiteResult:
    site_name: str
    ok: bool
    image_path: Path | None = None
    error: str | None = None
    duration: float = 0.0
    attempts: int = 1


@dataclass

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

    def _destination(self, site: SiteSpec, moment: datetime) -> Path:
        """Caminho de saida, com uma subpasta por dia."""
        name = self.settings.output.filename_pattern.format(
            date=moment.strftime("%Y-%m-%d"),
            time=moment.strftime("%H-%M"),
            site=site.slug,
            system=site.system.upper(),
        )
        day_dir = Path(SCREENSHOTS_DIR) / moment.strftime("%Y-%m-%d")
        day_dir.mkdir(parents=True, exist_ok=True)
        return day_dir / name

    # --------------------------------------------------------------- execucao

    def run_all(self) -> list[SiteResult]:
        sites = self.settings.enabled_sites
        if not sites:
            self.logger.warning("Nenhum site habilitado no config.yaml.")
            return []

        self.logger.info("Iniciando captura de %d site(s).", len(sites))
        results = [self._run_single(site) for site in sites]

        ok = sum(1 for r in results if r.ok)
        self.logger.info(
            "Ciclo concluido | ok=%d | falhas=%d", ok, len(results) - ok
        )
        return results

    def run_site(self, name: str) -> SiteResult:
        return self._run_single(self.settings.find_site(name))

    def _run_single(self, site: SiteSpec) -> SiteResult:
        attempts = max(1, self.settings.auth.retry_attempts)
        started = time.monotonic()
        last_error: str | None = None

        for attempt in range(1, attempts + 1):
            self.logger.info(
                "Iniciando captura | site=%s | tentativa=%d/%d",
                site.name,
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

            self.logger.info("Screenshot salvo | site=%s | arquivo=%s", site.name, image_path)
            return SiteResult(
                site_name=site.name,
                ok=True,
                image_path=image_path,
                duration=time.monotonic() - started,
                attempts=attempt,
            )

        reason = last_error or "erro desconhecido"
        self.logger.error("Site %s falhou apos %d tentativa(s): %s", site.name, attempts, reason)
        return SiteResult(
            site_name=site.name,
            ok=False,
            error=reason,
            duration=time.monotonic() - started,
            attempts=attempts,
        )

    def _capture_once(self, site: SiteSpec) -> Path:
        """Uma tentativa completa: captura, recorta e grava."""
        spec = self.settings.get_system(site.system)
        service = get_service_class(self.settings, site.system)(
            CaptureRequest(
                site=site,
                spec=spec,
                settings=self.settings,
                logger=self.logger,
                period=site.period,
            )
        )
        capture = service.capture()

        region = site.crop_region or self.settings.output.crop_region
        image_bytes = crop_image(capture.image_bytes, region) if region else capture.image_bytes
        if region:
            self.logger.info("Imagem recortada para a regiao configurada.")

        moment = self.now()
        destination = self._destination(site, moment)
        destination.write_bytes(image_bytes)
        return destination

    @staticmethod
    def _describe(exc: Exception) -> str:
        """Mensagem curta e segura (sem stack, sem credenciais)."""
        text = str(exc).strip() or exc.__class__.__name__
        return text.splitlines()[0][:400]
