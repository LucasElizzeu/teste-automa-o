"""Captura do AFCNetFlow com login por formulario."""

from browser.playwright_manager import (
    DashboardNotLoadedError,
    PlaywrightManager,
)
from core.config import ConfigError
from services.base import CaptureResult, DashboardService


class TrafficService(DashboardService):
    system_id = "traffic"

    def capture(self):
        username, password = self.credentials
        if not username or not password:
            raise ConfigError(
                "Defina TRAFFIC_USERNAME e TRAFFIC_PASSWORD no .env."
            )

        with PlaywrightManager(
            self.settings, self.logger, self.system_id
        ) as browser:
            page = browser.page
            page.set_viewport_size({
                "width": 3200,
                "height": 1800,
            })
            response = page.goto(
                self.site.url, wait_until="domcontentloaded"
            )

            if response is not None and response.status >= 400:
                raise DashboardNotLoadedError(
                    f"Pagina retornou HTTP {response.status}."
                )

            browser.wait_for_network_idle()

            email = page.get_by_placeholder(
                "Digite seu e-mail", exact=True
            )
            senha = page.get_by_placeholder(
                "Digite sua senha", exact=True
            )

            # Se a sessao anterior ainda estiver valida, pula o login.
            if senha.is_visible():
                email.fill(username)
                senha.fill(password)
                page.get_by_role(
                    "button",
                    name="Entrar no Sistema",
                    exact=True,
                ).click()

                # Nao captura enquanto o formulario continuar visivel.
                senha.wait_for(
                    state="hidden",
                    timeout=self.settings.browser.navigation_timeout_ms,
                )
                browser.wait_for_network_idle()
                browser.save_session()

            # Abre a tela desejada depois de autenticar.
            browser.open_dashboard(self.spec, self.site.url)
            browser.dismiss_overlays()

            # Recorta a barra lateral na resolucao 3200 x 1800.
            image = page.screenshot(
                clip={
                    "x": 256,
                    "y": 0,
                    "width": 2944,
                    "height": 1640,
                },
                animations="disabled",
            )

        return CaptureResult(
            image_bytes=image,
            system_id=self.system_id,
            url=self.site.url,
        )
