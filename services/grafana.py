"""Servico Grafana.

Estrutura pronta; os seletores de login e de painel vem do config.yaml e
devem ser preenchidos DEPOIS de conferir a pagina real (proposital: nao
inventamos seletores).

Fluxo de captura:
  1. reaproveita storage_state.json se ainda valido;
  2. se cair na tela de login, autentica e atualiza a sessao;
  3. abre o dashboard (com o periodo na URL quando possivel);
  4. espera os paineis renderizarem;
  5. captura o painel/regiao/pagina.
"""

from __future__ import annotations

from dataclasses import replace
import time

from browser.playwright_manager import (
    DashboardNotLoadedError,
    PlaywrightManager,
    SessionExpiredError,
)
from services.base import CaptureRequest, CaptureResult, DashboardService, build_url_with_period


class GrafanaService(DashboardService):
    system_id = "grafana"

    def capture(self) -> CaptureResult:
        started = time.monotonic()
        target_url = build_url_with_period(self.site.url, self.request.period)

        with PlaywrightManager(self.settings, self.logger, self.system_id) as browser:
            browser.ensure_authenticated(
                spec=self.spec,
                login_url=self.login_url,
                username=self.credentials[0],
                password=self.credentials[1],
                target_url=self.site.url,
            )

            try:
                browser.open_dashboard(self.spec, target_url, self.request.period)
            except SessionExpiredError:
                # Sessao morreu entre a validacao e o dashboard: relogin + retry unico.
                self.logger.info("Sessao caiu durante a navegacao; refazendo login.")
                browser.invalidate_session()
                username, password = self.credentials
                if not self.login_url or not username or not password:
                    raise
                browser.login(self.spec, self.login_url, username, password)
                browser.open_dashboard(self.spec, target_url, self.request.period)

            browser.dismiss_overlays()
            region = self.site.crop_region or self.settings.output.crop_region
            image_bytes = browser.screenshot(self.spec, region=region)

        elapsed = time.monotonic() - started
        self.logger.info("Grafana: captura concluida em %.1fs.", elapsed)

        return CaptureResult(
            image_bytes=image_bytes,
            system_id=self.system_id,
            url=target_url,
            period=self.request.period,
        )

