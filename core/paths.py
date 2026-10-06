"""Caminhos do projeto e criacao de diretorios."""

from __future__ import annotations

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

CONFIG_PATH = BASE_DIR / "config.yaml"
ENV_PATH = BASE_DIR / ".env"

SCREENSHOTS_DIR = BASE_DIR / "screenshots"
LOGS_DIR = BASE_DIR / "logs"
SESSIONS_DIR = BASE_DIR / "sessions"
TMP_DIR = BASE_DIR / ".tmp"


def ensure_directories(settings=None) -> None:
    """Cria a arvore de pastas necessaria. Aceita settings para nao quebrar chamadas."""
    for directory in (SCREENSHOTS_DIR, LOGS_DIR, SESSIONS_DIR, TMP_DIR):
        directory.mkdir(parents=True, exist_ok=True)
        keep = directory / ".gitkeep"
        if not keep.exists() and directory.name in {"screenshots", "logs", "sessions"}:
            keep.touch()
