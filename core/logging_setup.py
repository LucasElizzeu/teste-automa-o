"""Logs em arquivo + console, com redacao automatica de segredos."""

from __future__ import annotations

import logging
import os
import re
from logging.handlers import RotatingFileHandler
from pathlib import Path

from core.paths import LOGS_DIR

LOG_FORMAT = "%(asctime)s | %(levelname)s | %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# Padroes que jamais podem aparecer no log.
_SECRET_PATTERNS = [
    re.compile(r"bot\d{6,}:[A-Za-z0-9_\-]{20,}"),                       # token do Telegram
    re.compile(r"(?i)(token|password|senha|secret|authorization)\s*[=:]\s*\S+"),
    re.compile(r"(?i)(Authorization:\s*Bearer\s+)\S+"),
    re.compile(r"https://api\.telegram\.org/bot[^/\s]+"),
]

_REDACTED = "[REDACTED]"


class SecretFilter(logging.Filter):
    """Remove qualquer segredo que tenha escapado para a mensagem de log."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # pragma: no cover - log malformado
            return True
        clean = message
        for pattern in _SECRET_PATTERNS:
            clean = pattern.sub(_REDACTED, clean)
        if clean != message:
            record.msg = clean
            record.args = ()
        return True


def setup_logging(settings=None, level: str | None = None) -> logging.Logger:
    """Configura o logger raiz uma unica vez e devolve o logger do app."""
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    log_level = (level or os.getenv("LOG_LEVEL") or "INFO").upper()

    logger = logging.getLogger("monitoramento")
    logger.setLevel(log_level)
    logger.propagate = False

    if logger.handlers:
        for handler in logger.handlers:
            handler.setLevel(log_level)
        return logger

    formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)
    secret_filter = SecretFilter()

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    console.addFilter(secret_filter)
    logger.addHandler(console)

    file_handler = RotatingFileHandler(
        Path(LOGS_DIR) / "monitoramento.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    file_handler.addFilter(secret_filter)
    logger.addHandler(file_handler)

    return logger


def get_logger() -> logging.Logger:
    return logging.getLogger("monitoramento")


def date_only_handler(prefix: str = "execucao") -> Path:
    """Caminho de um log diario separado (opcional, para auditoria)."""
    from datetime import datetime

    return Path(LOGS_DIR) / f"{prefix}-{datetime.now().strftime('%Y-%m-%d')}.log"
