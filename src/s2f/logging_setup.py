"""Logging configuration: console + rotating file handler."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

_FMT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"


def setup(level: str = "INFO", log_dir: str | Path = "logs") -> None:
    """Configure the root logger with console and ``log_dir/s2f.log`` output.

    The file rotates at 1 MB keeping 3 backups. Idempotent: clears previous
    handlers so lines are not duplicated if called more than once.
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
            path / "s2f.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8"
        )
        file_handler.setFormatter(fmt)
        root.addHandler(file_handler)
    except OSError as exc:  # never crash the app just because the log can't be written
        root.warning("Could not create log file in %s: %s", log_dir, exc)


__all__ = ["setup"]
