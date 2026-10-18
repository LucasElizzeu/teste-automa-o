"""Gerenciador de navegador (Playwright) com sessao persistente.

Responsabilidades:
  - abrir/fechar o Chromium;
  - carregar e salvar storage_state.json (cookies + localStorage);
  - detectar sessao expirada e reautenticar;
  - esperar carregamento de pagina e de graficos;
  - capturar elemento ou regiao da pagina.

NAO contem seletores especificos de Grafana/Flowbix: tudo vem do config.yaml.
"""

from __future__ import annotations

import contextlib
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from playwright.sync_api import (
    Browser,
    BrowserContext,
    Error as PlaywrightError,
    Page,
    TimeoutError as PlaywrightTimeout,
    sync_playwright,
)

from core.config import Settings, SystemSpec
from core.paths import SESSIONS_DIR

# Indicadores genericos de tela de login / sessao expirada.
# Sao heuristica de apoio, NAO substituem os seletores do config.yaml.
GENERIC_LOGIN_HINTS = (
    'input[type="password"]',
    'form[action*="login" i]',
    '[class*="login" i] input[name*="user" i]',
    "#login",
)

GENERIC_ERROR_HINTS = (
    "text=/401|403 unauthorized|forbidden/i",
    "text=/session expired|sess[aã]o expirada/i",
)

# Elementos genericos de "carregando": comuns em dashboards web.
LOADING_HINTS = (
    '[class*="loading" i]',
    '[class*="spinner" i]',
    '[aria-label*="loading" i]',
    ".loading-indicator",
)


class SessionExpiredError(RuntimeError):
    """A sessao salva nao e mais valida e o re-login automatico nao foi possivel."""


class LoginFailedError(RuntimeError):
    """As credenciais foram recusadas ou a tela de login nao foi encontrada."""


class DashboardNotLoadedError(RuntimeError):
    """A pagina carregou, mas os graficos/panels nao apareceram."""


class ConfigErrorForLogin(RuntimeError):
    """Faltam seletores de login ou credenciais para este sistema."""

    def __init__(self, system_id: str):
        super().__init__(
            f"Login de {system_id} nao configurado. Preencha em config.yaml os seletores "
            f"systems.{system_id}.login.* (username_selector, password_selector, submit_selector) "
            f"conferidos na pagina real, e defina {system_id.upper()}_USERNAME / "
            f"{system_id.upper()}_PASSWORD no .env."
        )


class PlaywrightManager:
    """Context manager que entrega uma pagina autenticada pronta para captura."""

    def __init__(self, settings: Settings, logger, system_id: str = "",
        http_credentials: dict[str, str] | None = None,):
        self.settings = settings
        self.logger = logger
        self.system_id = system_id
        self.http_credentials = http_credentials
        self._playwright = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None

    # ------------------------------------------------------------------ setup

    def __enter__(self) -> "PlaywrightManager":
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        # Salva a sessao mesmo em caso de erro: pode ter autenticado no meio.
        with contextlib.suppress(Exception):
            self.save_session()
        self.stop()

    @property
    def session_path(self) -> Path:
        name = f"{self.system_id or 'default'}_storage_state.json"
        return Path(SESSIONS_DIR) / name

    def start(self) -> None:
        self._playwright = sync_playwright().start()
        launch_args = [
            "--disable-dev-shm-usage",
            "--no-sandbox",
            "--disable-gpu",
            "--hide-scrollbars",
            "--ignore-certificate-errors",
        ]
        self._browser = self._playwright.chromium.launch(
            headless=self.settings.browser.headless,
            args=launch_args,
        )

        context_args: dict[str, Any] = {
            "viewport": {
                "width": self.settings.browser.viewport_width,
                "height": self.settings.browser.viewport_height,
            },
            "device_scale_factor": self.settings.browser.device_scale_factor,
            "locale": self.settings.browser.locale,
            "ignore_https_errors": True,
        }
        if self.settings.browser.user_agent:
            context_args["user_agent"] = self.settings.browser.user_agent

        state = self._load_session_state()
        if state:
            context_args["storage_state"] = state
            self.logger.info("Sessao carregada de %s", self.session_path.name)

        if self.http_credentials:
            context_args["http_credentials"] = self.http_credentials
        self._context = self._browser.new_context(**context_args)
        self._context.set_default_timeout(self.settings.browser.element_timeout_ms)
        self._context.set_default_navigation_timeout(self.settings.browser.navigation_timeout_ms)

        self._page = self._context.new_page()
        self._page.set_default_timeout(self.settings.browser.element_timeout_ms)
        self._page.set_default_navigation_timeout(self.settings.browser.navigation_timeout_ms)

        self.logger.info(
            "Navegador iniciado (%s, %dx%d @%.1fx)",
            "headless" if self.settings.browser.headless else "visivel",
            self.settings.browser.viewport_width,
            self.settings.browser.viewport_height,
            self.settings.browser.device_scale_factor,
        )

    def stop(self) -> None:
        for closer in (self._context, self._browser):
            if closer is not None:
                with contextlib.suppress(Exception):
                    closer.close()
        if self._playwright is not None:
            with contextlib.suppress(Exception):
                self._playwright.stop()
        self._page = None
        self._context = None
        self._browser = None
        self._playwright = None

    @property
    def page(self) -> Page:
        if self._page is None:
            raise RuntimeError("Navegador nao iniciado. Use o gerenciador como context manager.")
        return self._page

    # ----------------------------------------------------------------- sessao

    def _load_session_state(self) -> str | Path | None:
        if not self.settings.auth.reuse_session:
            return None
        path = self.session_path
        if not path.exists():
            return None
        max_age = timedelta(hours=self.settings.auth.session_max_age_hours)
        modified = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        if datetime.now(timezone.utc) - modified > max_age:
            self.logger.info("Sessao de %s expirada por idade; sera refeito o login.", path.name)
            return None
        return path

    def save_session(self) -> None:
        """Grava o storage_state de forma atomica (nunca deixa arquivo corrompido)."""
        if self._context is None or not self.settings.auth.reuse_session:
            return
        path = self.session_path
        tmp = path.with_suffix(path.suffix + ".tmp")
        try:
            self._context.storage_state(path=str(tmp))
            tmp.replace(path)
            self.logger.info("Sessao atualizada em %s", path.name)
        except Exception as exc:  # pragma: no cover - IO do host
            self.logger.warning("Nao foi possivel salvar a sessao: %s", exc)
            with contextlib.suppress(Exception):
                tmp.unlink(missing_ok=True)

    def invalidate_session(self) -> None:
        """Apaga a sessao salva - usado quando o servidor rejeita os cookies."""
        path = self.session_path
        if path.exists():
            with contextlib.suppress(Exception):
                path.unlink()
            self.logger.info("Sessao local descartada (%s).", path.name)

    # ------------------------------------------------------------ autenticacao

    def is_logged_in(self, spec: SystemSpec) -> bool:
        """Heuristica: estamos em uma pagina que NAO parece tela de login."""
        page = self.page
        login = spec.login
        if login.logged_in_url_contains:
            return login.logged_in_url_contains in page.url
        if login.success:
            try:
                return page.locator(login.success).first.is_visible(timeout=2000)
            except PlaywrightError:
                pass
        return not self.detect_login_screen()

    def detect_login_screen(self) -> bool:
        """Procura sinais genericos de tela de login na pagina atual."""
        page = self.page
        for selector in GENERIC_LOGIN_HINTS:
            try:
                if page.locator(selector).first.is_visible(timeout=1200):
                    return True
            except PlaywrightError:
                continue
        return False

    def login(self, spec: SystemSpec, login_url: str, username: str, password: str) -> None:
        """Executa o login. Exige seletores reais configurados no config.yaml."""
        login = spec.login
        if not login.complete:
            raise ConfigErrorForLogin(spec.system_id)

        page = self.page
        self.logger.info("Autenticando em %s (%s)...", spec.system_id, login_url)
        page.goto(login_url, wait_until="domcontentloaded")

        page.locator(login.username).first.fill(username)
        page.locator(login.password).first.fill(password)

        # Algumas SPA so habilitam o botao apos validar os campos. Espera ele
        # ficar clicavel em vez de clicar no vazio.
        submit = page.locator(login.submit).first
        try:
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline:
                if submit.is_enabled():
                    break
                page.wait_for_timeout(250)
        except PlaywrightError:
            pass
        submit.click()

        # Espera sair da tela de login.
        deadline = time.monotonic() + self.settings.browser.navigation_timeout_ms / 1000
        while time.monotonic() < deadline:
            page.wait_for_timeout(500)
            if login.success:
                try:
                    if page.locator(login.success).first.is_visible(timeout=1000):
                        self.logger.info("%s autenticado.", spec.system_id)
                        self.save_session()
                        return
                except PlaywrightError:
                    continue
            elif login.logged_in_url_contains and login.logged_in_url_contains in page.url:
                self.logger.info("%s autenticado.", spec.system_id)
                self.save_session()
                return
            elif not login.success and not login.logged_in_url_contains and not self.detect_login_screen():
                self.logger.info("%s autenticado.", spec.system_id)
                self.save_session()
                return

        raise LoginFailedError(
            f"Login em {spec.system_id} nao confirmou sucesso em "
            f"{self.settings.browser.navigation_timeout_ms} ms."
        )

    def ensure_authenticated(
        self,
        spec: SystemSpec,
        login_url: str | None,
        username: str,
        password: str,
        target_url: str,
    ) -> None:
        """Garante uma sessao valida antes de navegar para o dashboard."""
        page = self.page

        # 1) Tenta reaproveitar a sessao salva indo direto ao dashboard.
        if self.settings.auth.reuse_session and self.session_path.exists():
            page.goto(target_url, wait_until="domcontentloaded")
            page.wait_for_timeout(1500)
            if not self.detect_login_screen():
                self.logger.info("Sessao reutilizada com sucesso para %s.", spec.system_id)
                return
            self.logger.info("Sessao expirada detectada; sera feito novo login.")
            self.invalidate_session()

        # 2) Sem sessao valida: login completo.
        if not login_url:
            raise ConfigErrorForLogin(spec.system_id)
        if not username or not password:
            raise ConfigErrorForLogin(spec.system_id)
        self.login(spec, login_url, username, password)

    # -------------------------------------------------------------- navegacao

    def open_dashboard(self, spec: SystemSpec, url: str, period: str | None = None) -> None:
        """Abre o dashboard, aplica periodo e espera os graficos."""
        page = self.page
        self.logger.info("Abrindo dashboard: %s", url)
        page.goto(url, wait_until="domcontentloaded")

        # Se caiu numa tela de login, a sessao morreu no meio do caminho.
        if self.detect_login_screen():
            raise SessionExpiredError("Tela de login detectada ao abrir o dashboard.")

        self.wait_for_network_idle()
        self.apply_period(spec, period)
        self.wait_for_charts(spec)

    def wait_for_network_idle(self, timeout_ms: int | None = None) -> None:
        """Espera a rede ficar ociosa - dashboards carregam dados via XHR/fetch."""
        page = self.page
        try:
            page.wait_for_load_state("networkidle", timeout=timeout_ms or self.settings.browser.element_timeout_ms)
        except PlaywrightTimeout:
            self.logger.warning("Rede nao ficou ociosa a tempo; seguindo com a captura.")

    def apply_period(self, spec: SystemSpec, period: str | None) -> None:
        """Aplica o periodo do grafico quando ha um preset configurado.

        Sem preset configurado, NAO tentamos adivinhar a UI do sistema: o
        periodo pode vir na propria URL (ex.: Grafana aceita from=now-6h),
        entao registramos e seguimos.
        """
        if not period:
            return
        filters = spec.filters
        preset_label = filters.presets.get(period)
        if not filters.time_picker or not preset_label:
            self.logger.info(
                "Periodo '%s' sera resolvido pela URL/estado do dashboard "
                "(nenhum preset configurado para %s).",
                period,
                spec.system_id,
            )
            return
        page = self.page
        try:
            page.locator(filters.time_picker).first.click(timeout=5000)
            page.get_by_text(preset_label, exact=False).first.click(timeout=5000)
            page.wait_for_timeout(1000)
            self.logger.info("Periodo '%s' aplicado (%s).", period, preset_label)
        except PlaywrightError as exc:
            self.logger.warning("Nao foi possivel aplicar o periodo '%s': %s", period, exc)

    def wait_for_charts(self, spec: SystemSpec) -> None:
        """Espera os paineis carregarem e valida que os graficos apareceram."""
        page = self.page
        panel = spec.panel
        timeout_ms = self.settings.browser.element_timeout_ms

        if panel.container:
            try:
                page.locator(panel.container).first.wait_for(state="visible", timeout=timeout_ms)
                self.logger.info("Container de paineis visivel.")
            except PlaywrightTimeout as exc:
                raise DashboardNotLoadedError(
                    f"Container de paineis nao apareceu: {panel.container}"
                ) from exc

        if panel.ready:
            try:
                page.locator(panel.ready).first.wait_for(state="visible", timeout=timeout_ms)
            except PlaywrightTimeout as exc:
                raise DashboardNotLoadedError(f"Indicador de pronto nao apareceu: {panel.ready}") from exc

        self.wait_for_no_spinner(timeout_ms=15000)

        if panel.error:
            try:
                if page.locator(panel.error).first.is_visible(timeout=1000):
                    raise DashboardNotLoadedError("Dashboard exibiu indicador de erro.")
            except PlaywrightTimeout:
                pass

        self.assert_charts_present(spec)

        # Pausa extra antes de capturar. O valor do sistema, quando definido,
        # tem prioridade sobre o global.
        extra = (
            spec.extra_settle_seconds
            if spec.extra_settle_seconds is not None
            else self.settings.browser.extra_settle_seconds
        )
        extra = float(extra or 0)
        if extra:
            self.logger.info("Aguardando %.1fs extras antes de capturar.", extra)
            page.wait_for_timeout(int(extra * 1000))

    def wait_for_no_spinner(self, timeout_ms: int = 15000) -> None:
        """Espera os spinners/loading genericos desaparecerem."""
        page = self.page
        deadline = time.monotonic() + timeout_ms / 1000
        while time.monotonic() < deadline:
            visible = False
            for selector in LOADING_HINTS:
                try:
                    if page.locator(selector).first.is_visible(timeout=500):
                        visible = True
                        break
                except PlaywrightError:
                    continue
            if not visible:
                return
            page.wait_for_timeout(500)
        self.logger.warning("Ainda havia indicador de carregamento apos %d ms.", timeout_ms)

    def assert_charts_present(self, spec: SystemSpec) -> None:
        """Confere que existe algo renderizado (canvas/svg/imagem de grafico).

        Sem `panel.container` configurado, usa deteccao generica de canvas/svg
        e apenas avisa quando nao encontra - nao bloqueia a captura.
        """
        page = self.page
        scope = spec.panel.container or "body"
        candidates = [
            f"{scope} canvas",
            f"{scope} svg",
            f"{scope} img[src*='render' i]",
            f"{scope} [class*='panel' i]",
        ]
        total = 0
        for selector in candidates:
            try:
                total = max(total, page.locator(selector).count())
            except PlaywrightError:
                continue
        if total == 0:
            if spec.panel.container:
                raise DashboardNotLoadedError(
                    f"Nenhum grafico encontrado dentro de {spec.panel.container}."
                )
            self.logger.warning(
                "Nenhum canvas/svg encontrado em %s. Configure systems.%s.panel.container_selector "
                "apos conferir a pagina real.",
                spec.system_id,
                spec.system_id,
            )

    # -------------------------------------------------------------- captura

    def screenshot(
        self,
        spec: SystemSpec,
        region: dict[str, int] | None = None,
        full_page: bool = False,
    ) -> bytes:
        """Captura o painel configurado, ou a regiao informada, ou a pagina."""
        page = self.page
        if spec.panel.container:
            try:
                locator = page.locator(spec.panel.container).first
                locator.wait_for(state="visible", timeout=self.settings.browser.element_timeout_ms)
                self.logger.info("Capturando elemento %s", spec.panel.container)
                return locator.screenshot(animations="disabled")
            except PlaywrightError as exc:
                self.logger.warning(
                    "Falha ao capturar o painel %s (%s); usando a pagina inteira.",
                    spec.panel.container,
                    exc,
                )

        if region:
            x, y = int(region["x"]), int(region["y"])
            width, height = int(region["width"]), int(region["height"])
            self.logger.info("Capturando regiao %dx%d em (%d,%d)", width, height, x, y)
            return page.screenshot(
                clip={"x": x, "y": y, "width": width, "height": height},
                animations="disabled",
            )

        self.logger.info("Capturando pagina inteira (nenhum painel/regiao configurado).")
        return page.screenshot(full_page=full_page, animations="disabled")

    # ------------------------------------------------------------ utilitarios

    def dismiss_overlays(self, selectors: Iterable[str] = ()) -> None:
        """Fecha avisos/cookies que possam cobrir o grafico."""
        page = self.page
        defaults = (
            "button:has-text('Aceitar')",
            "button:has-text('Accept')",
            "button:has-text('Fechar')",
            "[aria-label='Close']",
        )
        for selector in tuple(selectors) + defaults:
            try:
                element = page.locator(selector).first
                if element.is_visible(timeout=500):
                    element.click(timeout=2000)
                    page.wait_for_timeout(300)
            except PlaywrightError:
                continue
