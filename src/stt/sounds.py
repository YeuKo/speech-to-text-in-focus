"""Sonidos de feedback audible (Windows winsound).

Cada evento tiene un patrón de tonos distinguible para reconocerlo sin mirar
la pantalla. Se reproducen en un hilo aparte para no bloquear el pipeline.
"""

from __future__ import annotations

import logging
import threading

log = logging.getLogger(__name__)


def _play(sequence: list[tuple[int, int]]) -> None:
    """Reproduce una secuencia de (frecuencia_hz, duración_ms) sin bloquear."""

    def _run() -> None:
        try:
            import winsound

            for freq, dur in sequence:
                winsound.Beep(freq, dur)
        except Exception:  # winsound no disponible (no Windows) o error de audio
            pass

    threading.Thread(target=_run, daemon=True).start()


def recording_start() -> None:
    """Inicio de grabación: dos tonos ascendentes ('listo, habla')."""
    _play([(660, 100), (990, 130)])


def recording_stop() -> None:
    """Fin de grabación: dos tonos descendentes ('procesando')."""
    _play([(880, 100), (520, 130)])


def error() -> None:
    """Error: tono grave doble."""
    _play([(300, 200), (250, 250)])


__all__ = ["recording_start", "recording_stop", "error"]
