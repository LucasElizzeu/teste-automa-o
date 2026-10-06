"""Servico Flowbix.

Mesma estrutura do Grafana. A unica diferenca real e o bloco de seletores
e o fato de o Flowbix normalmente NAO aceitar periodo por query string -
nesse caso o periodo e aplicado por preset no config.yaml
(systems.flowbix.filters.presets).

Enquanto os seletores nao forem preenchidos, o servico falha com uma
mensagem explicita em vez de tentar adivinhar a interface.
"""

from __future__ import annotations

import time

from browser.playwright_manager import PlaywrightManager, SessionExpiredError
from services.base import CaptureRequest, CaptureResult, DashboardService, build_url_with_period


class FlowbixService(DashboardService):
    system_id = "flowbix"

    def capture(self) -> CaptureResult:
        started = time.monotonic()
        # Flowbix normalmente nao usa from/to na URL; o helper devolve a URL
        # original se o filtro de querystring nao se aplicar.
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
        self.logger.info("Flowbix: captura concluida em %.1fs.", elapsed)

        return CaptureResult(
            image_bytes=image_bytes,
            system_id=self.system_id,
            url=target_url,
            period=self.request.period,
            captured_at="",
        )
