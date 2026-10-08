"""Carregamento e validacao de configuracao (config.yaml + .env).

Prioridade de credenciais: variaveis de ambiente > .env > config.yaml.
O config.yaml NUNCA deve conter senhas ou tokens.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

from core.paths import CONFIG_PATH, ENV_PATH

TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


class ConfigError(Exception):
    """Erro de configuracao - falha rapido e com mensagem clara."""


@dataclass
class TelegramSettings:
    enabled: bool = True
    send_by_default: bool = True
    silent_notifications: bool = False
    max_caption_length: int = 1024
    token: str = ""
    chat_id: str = ""

    @property
    def configured(self) -> bool:
        return bool(self.token and self.chat_id)


@dataclass
class BrowserSettings:
    headless: bool = True
    viewport_width: int = 1920
    viewport_height: int = 1080
    device_scale_factor: int = 2
    navigation_timeout_ms: int = 60000
    element_timeout_ms: int = 30000
    extra_settle_seconds: float = 4.0
    locale: str = "pt-BR"
    user_agent: str | None = None


@dataclass
class AuthSettings:
    reuse_session: bool = True
    session_max_age_hours: float = 12.0
    retry_attempts: int = 3
    retry_backoff_seconds: list[int] = field(default_factory=lambda: [10, 20])

    def backoff_for(self, attempt: int) -> int:
        """Espera para a tentativa `attempt` (1-indexed) apos uma falha."""
        if not self.retry_backoff_seconds:
            return 0
        index = min(attempt - 1, len(self.retry_backoff_seconds) - 1)
        return int(self.retry_backoff_seconds[index])


@dataclass
class OutputSettings:
    screenshot_retention_days: int = 7
    filename_pattern: str = "{date}_{time}_{site}_{system}.png"
    crop_region: dict[str, int] | None = None
    add_label_banner: bool = True


@dataclass
class ScheduleSettings:
    mode: str = "mixed"
    times: list[str] = field(default_factory=list)
    every_hours: list[int] = field(default_factory=list)
    timezone: str = "America/Manaus"

    def validate(self) -> None:
        for value in self.times:
            if not TIME_RE.match(str(value)):
                raise ConfigError(f"Horario invalido em schedule.times: {value!r} (use HH:MM)")
        for value in self.every_hours:
            if not isinstance(value, int) or not 1 <= value <= 24:
                raise ConfigError(f"schedule.every_hours deve conter inteiros entre 1 e 24, recebido {value!r}")
        if self.mode not in {"cron", "every", "mixed"}:
            raise ConfigError("schedule.mode deve ser 'cron', 'every' ou 'mixed'")


@dataclass
class SelectorSpec:
    """Bloco de seletores opcional. None = ainda nao verificado na pagina real."""

    username: str | None = None
    password: str | None = None
    submit: str | None = None
    success: str | None = None
    logged_in_url_contains: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "SelectorSpec":
        data = data or {}
        return cls(
            username=data.get("username_selector"),
            password=data.get("password_selector"),
            submit=data.get("submit_selector"),
            success=data.get("success_selector"),
            logged_in_url_contains=data.get("logged_in_url_contains"),
        )

    @property
    def complete(self) -> bool:
        return bool(self.username and self.password and self.submit)


@dataclass
class PanelSpec:
    container: str | None = None
    ready: str | None = None
    error: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "PanelSpec":
        data = data or {}
        return cls(
            container=data.get("container_selector"),
            ready=data.get("ready_selector"),
            error=data.get("error_selector"),
        )


@dataclass
class FiltersSpec:
    time_picker: str | None = None
    presets: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "FiltersSpec":
        data = data or {}
        return cls(
            time_picker=data.get("time_picker_selector"),
            presets={str(k): str(v) for k, v in (data.get("presets") or {}).items()},
        )


@dataclass
class SystemSpec:
    system_id: str
    login_url: str | None = None
    login: SelectorSpec = field(default_factory=SelectorSpec)
    panel: PanelSpec = field(default_factory=PanelSpec)
    filters: FiltersSpec = field(default_factory=FiltersSpec)
    login_wait_seconds: float = 0.0      # pausa extra apos autenticar
    extra_settle_seconds: float | None = None   # sobrescreve o global

    @classmethod
    def from_dict(cls, system_id: str, data: dict[str, Any] | None) -> "SystemSpec":
        data = data or {}
        return cls(
            system_id=system_id,
            login_url=data.get("login_url"),
            login=SelectorSpec.from_dict(data.get("login")),
            panel=PanelSpec.from_dict(data.get("panel")),
            filters=FiltersSpec.from_dict(data.get("filters")),
            login_wait_seconds=float(data.get("login_wait_seconds") or 0),
            extra_settle_seconds=(
                float(data["extra_settle_seconds"])
                if data.get("extra_settle_seconds") is not None
                else None
            ),
        )


@dataclass
class SiteSpec:
    name: str
    system: str
    url: str
    period: str = "6h"
    enabled: bool = True
    description: str = ""
    crop_region: dict[str, int] | None = None
    chat_id: str | None = None

    @property
    def slug(self) -> str:
        """Identificador seguro para nome de arquivo: MANAUS_TEFE."""
        value = self.name.upper()
        for char in " -–—/\\|:.":
            value = value.replace(char, "_")
        value = re.sub(r"_+", "_", value).strip("_")
        return re.sub(r"[^A-Z0-9_]", "", value) or "SITE"


@dataclass
class Settings:
    schedule: ScheduleSettings
    browser: BrowserSettings
    telegram: TelegramSettings
    auth: AuthSettings
    output: OutputSettings
    systems: dict[str, SystemSpec]
    sites: list[SiteSpec]
    config_path: Path

    def get_system(self, system_id: str) -> SystemSpec:
        key = (system_id or "").strip().lower()
        if key not in self.systems:
            raise ConfigError(
                f"Sistema {system_id!r} nao declarado em config.yaml (systems:). "
                f"Disponiveis: {', '.join(sorted(self.systems)) or 'nenhum'}"
            )
        return self.systems[key]

    def find_site(self, name: str) -> SiteSpec:
        target = _normalize(name)
        for site in self.sites:
            if _normalize(site.name) == target:
                return site
        available = ", ".join(s.name for s in self.sites) or "nenhum"
        raise ConfigError(f"Site {name!r} nao encontrado no config.yaml. Disponiveis: {available}")

    @property
    def enabled_sites(self) -> list[SiteSpec]:
        return [s for s in self.sites if s.enabled]


def _normalize(value: str) -> str:
    """Compara nomes ignorando acentos, caixa e separadores."""
    import unicodedata

    text = unicodedata.normalize("NFKD", str(value))
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.upper()
    for char in ("-", "–", "—", "/", "|", ":"):
        text = text.replace(char, " ")
    return re.sub(r"\s+", " ", text).strip()


def _as_bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on", "sim"}


def _credential(key: str, system_id: str) -> str:
    """Busca USERNAME/PASSWORD de um sistema no ambiente/.env."""
    env_key = f"{system_id.upper()}_{key.upper()}"
    return (os.getenv(env_key) or "").strip()


def load_settings(config_path: str | Path | None = None) -> Settings:
    """Le config.yaml + .env e devolve um objeto Settings validado."""
    # .env nao sobrescreve variaveis ja exportadas no ambiente real
    if ENV_PATH.exists():
        load_dotenv(ENV_PATH, override=False)

    path = Path(config_path).expanduser() if config_path else CONFIG_PATH
    if not path.exists():
        raise ConfigError(f"Arquivo de configuracao nao encontrado: {path}")

    with path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}

    if not isinstance(raw, dict):
        raise ConfigError("config.yaml deve conter um mapa de chaves no nivel raiz.")

    # --------------------------------------------- schedule
    sched_raw = raw.get("schedule") or {}
    schedule = ScheduleSettings(
        mode=str(sched_raw.get("mode", "mixed")),
        times=[str(t) for t in (sched_raw.get("times") or [])],
        every_hours=[int(h) for h in (sched_raw.get("every_hours") or [])],
        timezone=str(sched_raw.get("timezone") or os.getenv("TZ") or "America/Manaus"),
    )
    schedule.validate()

    # --------------------------------------------- browser
    browser_raw = raw.get("browser") or {}
    browser = BrowserSettings(
        headless=_as_bool(browser_raw.get("headless"), True),
        viewport_width=int(browser_raw.get("viewport_width", 1920)),
        viewport_height=int(browser_raw.get("viewport_height", 1080)),
        device_scale_factor=int(browser_raw.get("device_scale_factor", 2)),
        navigation_timeout_ms=int(browser_raw.get("navigation_timeout_ms", 60000)),
        element_timeout_ms=int(browser_raw.get("element_timeout_ms", 30000)),
        extra_settle_seconds=float(browser_raw.get("extra_settle_seconds", 4)),
        locale=str(browser_raw.get("locale", "pt-BR")),
        user_agent=browser_raw.get("user_agent"),
    )
    # .env tem prioridade sobre o yaml para facilitar testes locais
    if os.getenv("HEADLESS") is not None:
        browser.headless = _as_bool(os.getenv("HEADLESS"), browser.headless)

    # --------------------------------------------- telegram
    tg_raw = raw.get("telegram") or {}
    telegram = TelegramSettings(
        enabled=_as_bool(tg_raw.get("enabled"), True),
        send_by_default=_as_bool(tg_raw.get("send_by_default"), True),
        silent_notifications=_as_bool(tg_raw.get("silent_notifications"), False),
        max_caption_length=int(tg_raw.get("max_caption_length", 1024)),
        token=(os.getenv("TELEGRAM_BOT_TOKEN") or "").strip(),
        chat_id=(os.getenv("TELEGRAM_CHAT_ID") or "").strip(),
    )

    # --------------------------------------------- auth
    auth_raw = raw.get("auth") or {}
    backoff = auth_raw.get("retry_backoff_seconds") or [10, 20]
    auth = AuthSettings(
        reuse_session=_as_bool(auth_raw.get("reuse_session"), True),
        session_max_age_hours=float(auth_raw.get("session_max_age_hours", 12)),
        retry_attempts=max(1, int(auth_raw.get("retry_attempts", 3))),
        retry_backoff_seconds=[int(b) for b in backoff],
    )

    # --------------------------------------------- output
    out_raw = raw.get("output") or {}
    crop = out_raw.get("crop_region")
    output = OutputSettings(
        screenshot_retention_days=int(
            os.getenv("SCREENSHOT_RETENTION_DAYS") or out_raw.get("screenshot_retention_days", 7)
        ),
        filename_pattern=str(out_raw.get("filename_pattern", "{date}_{time}_{site}_{system}.png")),
        crop_region=_parse_region(crop, "output.crop_region"),
        add_label_banner=_as_bool(out_raw.get("add_label_banner"), True),
    )

    # --------------------------------------------- systems
    systems: dict[str, SystemSpec] = {}
    for key, value in (raw.get("systems") or {}).items():
        systems[str(key).lower()] = SystemSpec.from_dict(str(key).lower(), value)

    # --------------------------------------------- sites
    sites_raw = raw.get("sites") or []
    if not isinstance(sites_raw, list):
        raise ConfigError("config.yaml: 'sites' deve ser uma lista.")

    sites: list[SiteSpec] = []
    seen: set[str] = set()
    for index, item in enumerate(sites_raw):
        if not isinstance(item, dict):
            raise ConfigError(f"sites[{index}] deve ser um mapa com nome/sistema/url.")
        name = str(item.get("nome") or "").strip()
        system = str(item.get("sistema") or "").strip().lower()
        url = str(item.get("url") or "").strip()
        if not name:
            raise ConfigError(f"sites[{index}] sem 'nome'.")
        if _normalize(name) in seen:
            raise ConfigError(f"Site duplicado no config.yaml: {name!r}.")
        seen.add(_normalize(name))
        if not system:
            raise ConfigError(f"Site {name!r} sem 'sistema'.")
        if system not in systems:
            raise ConfigError(
                f"Site {name!r} aponta para sistema {system!r}, que nao existe em systems:."
            )

        tg_site = item.get("telegram") or {}
        sites.append(
            SiteSpec(
                name=name,
                system=system,
                url=url,
                period=str(item.get("periodo") or item.get("period") or "6h"),
                enabled=_as_bool(item.get("enabled"), True),
                description=str(item.get("descricao") or item.get("description") or ""),
                crop_region=_parse_region(item.get("crop_region"), f"sites[{index}].crop_region"),
                chat_id=(str(tg_site.get("chat_id")).strip() if tg_site.get("chat_id") else None),
            )
        )

    if not sites:
        raise ConfigError("config.yaml nao possui nenhum site cadastrado em 'sites'.")

    return Settings(
        schedule=schedule,
        browser=browser,
        telegram=telegram,
        auth=auth,
        output=output,
        systems=systems,
        sites=sites,
        config_path=path,
    )


def _parse_region(value: Any, label: str) -> dict[str, int] | None:
    if value in (None, "", "null"):
        return None
    if not isinstance(value, dict):
        raise ConfigError(f"{label} deve ser um mapa {{x, y, width, height}}.")
    try:
        region = {k: int(value[k]) for k in ("x", "y", "width", "height")}
    except KeyError as exc:
        raise ConfigError(f"{label} incompleto: falta a chave {exc.args[0]!r}.") from exc
    if region["width"] <= 0 or region["height"] <= 0:
        raise ConfigError(f"{label} precisa de width/height positivos.")
    return region


def credentials_for(settings: Settings, system_id: str) -> tuple[str, str]:
    """Credenciais do sistema, vindas do ambiente/.env (nunca do yaml)."""
    return _credential("username", system_id), _credential("password", system_id)


def login_url_for(settings: Settings, system_id: str) -> str | None:
    spec = settings.get_system(system_id)
    if spec.login_url:
        return spec.login_url
    return (os.getenv(f"{system_id.upper()}_LOGIN_URL") or "").strip() or None
