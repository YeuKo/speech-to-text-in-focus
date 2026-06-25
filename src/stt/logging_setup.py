"""Configuración de logging: consola + fichero rotativo."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

_FMT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"


def setup(level: str = "INFO", log_dir: str | Path = "logs") -> None:
    """Configura el logging raíz con salida a consola y a ``log_dir/stt.log``.

    El fichero rota a 1 MB con 3 copias de respaldo. Idempotente: limpia
    handlers previos para no duplicar líneas si se llama más de una vez.
    """
    root = logging.getLogger()
    root.setLevel(level.upper())
    for h in list(root.handlers):
        root.removeHandler(h)

    fmt = logging.Formatter(_FMT)

    console = logging.StreamHandler()
    console.setFormatter(fmt)
    root.addHandler(console)

    try:
        path = Path(log_dir)
        path.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            path / "stt.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8"
        )
        file_handler.setFormatter(fmt)
        root.addHandler(file_handler)
    except OSError as exc:  # no debe tumbar la app por no poder escribir el log
        root.warning("No se pudo crear el log en %s: %s", log_dir, exc)


__all__ = ["setup"]
