"""Politica de retencao dos screenshots.

Remove apenas arquivos .png dentro de screenshots/ (incluindo subpastas por
dia). Nunca toca em logs/ nem em sessions/.
"""

from __future__ import annotations

import shutil
import time
from pathlib import Path

from core.paths import SCREENSHOTS_DIR


def cleanup_old_screenshots(settings=None, logger=None) -> int:
    """Apaga screenshots mais antigos que SCREENSHOT_RETENTION_DAYS.

    Devolve a quantidade de arquivos removidos.
    """
    days = 7
    if settings is not None:
        days = int(getattr(settings.output, "screenshot_retention_days", 7) or 7)
    if days <= 0:
        # 0 ou negativo = retencao desativada
        return 0

    root = Path(SCREENSHOTS_DIR)
    if not root.exists():
        return 0

    cutoff = time.time() - days * 86400
    removed = 0

    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() not in {".png", ".jpg", ".jpeg"}:
            continue
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink()
                removed += 1
        except OSError:
            continue

    # Remove subpastas diarias que ficaram vazias.
    for directory in sorted((p for p in root.rglob("*") if p.is_dir()), reverse=True):
        try:
            if not any(directory.iterdir()):
                directory.rmdir()
        except OSError:
            continue

    return removed
