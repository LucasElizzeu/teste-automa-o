"""Registro de servicos de dashboard.

Adicionar uma plataforma nova = criar a classe + registrar aqui + declarar
o bloco em config.yaml (systems:). Nenhuma outra parte do codigo muda.
"""

from __future__ import annotations

from core.config import Settings
from services.base import DashboardService
from services.flowbix import FlowbixService
from services.grafana import GrafanaService
from services.asns4 import Asns4Service


SERVICE_REGISTRY: dict[str, type[DashboardService]] = {
    GrafanaService.system_id: GrafanaService,
    FlowbixService.system_id: FlowbixService,
    Asns4Service.system_id: Asns4Service,
}


def get_service_class(settings: Settings, system_id: str) -> type[DashboardService]:
    key = (system_id or "").strip().lower()
    if key not in SERVICE_REGISTRY:
        known = ", ".join(sorted(SERVICE_REGISTRY))
        raise KeyError(
            f"Servico {system_id!r} nao implementado. Registrados: {known}. "
            f"Crie a classe em services/ e adicione em SERVICE_REGISTRY."
        )
    return SERVICE_REGISTRY[key]
