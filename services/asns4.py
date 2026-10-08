"""Servico AFCNetFlow (ASNs / Operadoras).

Mesma estrutura dos demais servicos: o contrato comum esta em base.py, o que
muda sao os seletores e a ausencia de from/to na URL (o periodo e aplicado na
interface, via filtro).
"""

from __future__ import annotations

import time

from browser.playwright_manager import PlaywrightManager, SessionExpiredError
from services.base import CaptureRequest, CaptureResult, DashboardService, build_url_with_period


class Asns4Service(DashboardService):
    system_id = "asns4"

    def capture(self) -> CaptureResult:
        started = time.monotonic()
        # Esta aplicacao NAO aceita from/to na query string; o periodo e
        # escolhido na interface ("Ultima 1 hora"). build_url_with_period
        # devolve a URL original quando nao reconhece o formato.
        target_url = self.site.url

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
        self.logger.info("AFCNetFlow: captura concluida em %.1fs.", elapsed)

        return CaptureResult(
            image_bytes=image_bytes,
            system_id=self.system_id,
            url=target_url,
            period=self.request.period,
            captured_at="",
        )
