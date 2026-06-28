"""Audible feedback sounds (Windows winsound).

Each event has a distinguishable tone pattern so it can be recognised without
looking at the screen. Sounds play on a separate thread so they don't block the
pipeline.
"""

from __future__ import annotations

import logging
import threading

log = logging.getLogger(__name__)


def _play(sequence: list[tuple[int, int]]) -> None:
    """Play a sequence of (frequency_hz, duration_ms) tones without blocking."""

    def _run() -> None:
        try:
            import winsound

            for freq, dur in sequence:
                winsound.Beep(freq, dur)
        except Exception:  # winsound unavailable (non-Windows) or audio error
            pass

    threading.Thread(target=_run, daemon=True).start()


def recording_start() -> None:
    """Recording started: two rising tones ('ready, speak')."""
    _play([(660, 100), (990, 130)])


def recording_stop() -> None:
    """Recording stopped: two falling tones ('processing')."""
    _play([(880, 100), (520, 130)])


def error() -> None:
    """Error: low double tone."""
    _play([(300, 200), (250, 250)])


__all__ = ["recording_start", "recording_stop", "error"]
