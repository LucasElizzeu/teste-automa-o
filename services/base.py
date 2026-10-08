"""Contrato comum dos servicos de dashboard.

Um servico sabe: onde fica o login, quais seletores usar e como capturar.
Ele NAO sabe nada sobre agendamento ou nomes de arquivo - isso e
responsabilidade do workflow. Assim, adicionar um sistema novo = 1 classe nova.
"""

from __future__ import annotations

import os
import re
import urllib.parse as urlparse
from abc import ABC, abstractmethod
from dataclasses import dataclass

from core.config import Settings, SiteSpec, SystemSpec


@dataclass
class CaptureRequest:
    """Tudo que um servico precisa para produzir uma captura."""

    site: SiteSpec
    spec: SystemSpec
    settings: Settings
    logger: object
    period: str | None = None


@dataclass
class CaptureResult:
    """Resultado de uma captura: bytes da imagem + metadados de origem."""

    image_bytes: bytes
    system_id: str
    url: str
    period: str | None = None


class DashboardService(ABC):
    """Base para qualquer plataforma de dashboard."""

    system_id: str = ""

    def __init__(self, request: CaptureRequest):
        self.request = request
        self.settings = request.settings
        self.site = request.site
        self.spec = request.spec
        self.logger = request.logger

    @property
    def login_url(self) -> str | None:
        """URL de login configurada (yaml ou ambiente)."""
        if self.spec.login_url:
            return self.spec.login_url
        return (os.getenv(f"{self.system_id.upper()}_LOGIN_URL") or "").strip() or None

    @property
    def credentials(self) -> tuple[str, str]:
        """Usuario/senha vindos exclusivamente do .env / ambiente."""
        prefix = self.system_id.upper()
        return (
            (os.getenv(f"{prefix}_USERNAME") or "").strip(),
            (os.getenv(f"{prefix}_PASSWORD") or "").strip(),
        )

    @abstractmethod
    def capture(self) -> CaptureResult:
        """Executa o fluxo completo de captura e devolve a imagem."""
        raise NotImplementedError


def build_url_with_period(url: str, period: str | None) -> str:
    """Acrescenta o periodo na query string, quando o sistema suportar.

    O Grafana aceita `from=now-6h&to=now` na URL, o que evita depender de
    cliques na interface. Sem periodo reconhecido, a URL volta inalterada.
    """
    if not period:
        return url

    match = re.fullmatch(r"(\d+)\s*([smhdw])", str(period).strip().lower())
    if not match:
        return url

    parts = urlparse.urlsplit(url)
    query = dict(urlparse.parse_qsl(parts.query, keep_blank_values=True))
    # Se a URL ja traz o intervalo, respeita o que esta la.
    if "from" in query and "to" in query:
        return url
    query["from"] = f"now-{match.group(1)}{match.group(2)}"
    query["to"] = "now"
    return urlparse.urlunsplit(parts._replace(query=urlparse.urlencode(query)))
