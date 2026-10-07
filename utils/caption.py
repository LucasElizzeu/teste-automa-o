"""Formatacao de legendas e mensagens do Telegram."""

from __future__ import annotations

from datetime import datetime

SYSTEM_LABEL = {
    "grafana": "Grafana",
    "flowbix": "Flowbix",
}


def _phase(period: str | None) -> str:
    if not period:
        return "ultimas horas"
    value = str(period).strip().lower()
    suffix = value[-1:] if value else ""
    number = value[:-1] if suffix.isalpha() else value
    if not number.isdigit():
        return f"ultimas {value}"
    word = {"h": "horas", "d": "dias", "m": "minutos", "s": "segundos", "w": "semanas"}.get(suffix)
    return f"ultimas {number} {word}" if word else f"ultimas {value}"


def build_caption(
    site_name: str,
    system_id: str,
    moment: datetime,
    url: str = "",
    description: str = "",
) -> str:
    """Legenda da imagem - identifica circuito, horario e origem."""
    label = SYSTEM_LABEL.get(system_id.lower(), system_id.capitalize())
    arrow = site_name.replace(" - ", " → ").replace(" -> ", " → ")
    lines = " "
    if description:
        lines.append(f"📝 {description}")
    return _escape_safe("\n".join(lines))


def build_error_message(site_name: str, system_id: str, error: str) -> str:
    """Mensagem de falha enviada ao grupo."""
    label = SYSTEM_LABEL.get(system_id.lower(), system_id.capitalize())
    return (
        "⚠️ <b>Falha no monitoramento</b>\n\n"
        f"<b>Site:</b> {site_name}\n"
        f"<b>Sistema:</b> {label}\n"
        f"<b>Erro:</b> {_escape_safe(error, block=False)}"
    )


def build_summary(results, moment: datetime) -> str:
    """Resumo da execucao agendada (opcional, util para saber o que rodou)."""
    ok = [r for r in results if r.ok]
    fail = [r for r in results if not r.ok]
    lines = [
        f"🗂 <b>Execucao {moment.strftime('%d/%m/%Y %H:%M')}</b>",
        "",
        f"✅ Enviados: {len(ok)}",
    ]
    if fail:
        lines.append(f"❌ Falhas: {len(fail)}")
        for item in fail:
            lines.append(f"   • {item.site_name}: {_escape_safe(item.error or 'erro', block=False)}")
    return "\n".join(lines)


def _escape_safe(text: str, block: bool = True) -> str:
    """Escapa o minimo necessario para o HTML do Telegram sem quebrar acentos."""
    value = str(text or "")
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
