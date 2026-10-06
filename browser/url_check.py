"""Validacao defensiva de URLs.

Evita que um valor colado errado (link de Markdown, espacos, aspas)
chegue ao Playwright como uma URL invalida e produza um erro obscuro.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

# Detecta "[texto](https://...)" - link de Markdown colado por engano.
MARKDOWN_LINK = re.compile(r"^\s*\[(?P<text>[^\]]*)\]\((?P<url>[^)]+)\)\s*$")


class InvalidUrlError(ValueError):
    """URL ausente, malformada ou em formato inesperado."""


def normalize_url(value: str | None, label: str = "URL") -> str:
    """Devolve uma URL limpa ou levanta InvalidUrlError com o motivo exato."""
    if value is None:
        raise InvalidUrlError(f"{label}: valor ausente (None).")

    raw = str(value).strip()
    if not raw:
        raise InvalidUrlError(f"{label}: valor vazio.")

    # 1) Desembrulha link de Markdown, que e o erro mais comum ao colar.
    match = MARKDOWN_LINK.match(raw)
    if match:
        inner = match.group("url").strip()
        raise InvalidUrlError(
            f"{label} foi colada como link de Markdown: {raw!r}. "
            f"Use apenas a URL pura: {inner!r}"
        )

    # 2) Remove aspas externas que tenham sobrado do YAML.
    if (raw.startswith('"') and raw.endswith('"')) or (raw.startswith("'") and raw.endswith("'")):
        raw = raw[1:-1].strip()

    # 3) Rejeita espacos internos.
    if " " in raw or "\t" in raw:
        raise InvalidUrlError(f"{label} contem espaco em branco: {raw!r}")

    parts = urlsplit(raw)
    if parts.scheme not in {"http", "https"}:
        raise InvalidUrlError(
            f"{label} nao comeca com http:// ou https:// (recebido: {raw!r})."
        )
    if not parts.netloc:
        raise InvalidUrlError(f"{label} sem host (recebido: {raw!r}).")

    return raw


def is_usable(value: str | None) -> bool:
    """True quando a URL passa na validacao. Util para checagens opcionais."""
    try:
        normalize_url(value)
        return True
    except InvalidUrlError:
        return False
