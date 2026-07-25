"""Audible feedback for the dictation events (Windows).

Three modes, chosen with ``[feedback].sound`` or from the tray menu:

- ``"system"`` (default) — plays Windows' own speech-recognition cues from
  ``%WINDIR%\\Media``. They are short, discreet and follow the volume mixer.
- ``"beeps"`` — synthesized square-wave tones via ``winsound.Beep``. Loud and
  impossible to miss (they bypass the mixer), useful with headphones off.
- ``"off"`` — silent; the tray icon is the only indicator.

Every call is fire-and-forget: playback happens on a daemon thread so the
recording pipeline is never delayed, and any audio error is swallowed.
"""

from __future__ import annotations

import logging
import os
import threading
from functools import cache
from pathlib import Path

log = logging.getLogger(__name__)

# Candidate WAVs per event, best first. Windows ships the "Speech *" cues with
# its speech-recognition feature; the rest are fallbacks for trimmed installs.
_MEDIA: dict[str, tuple[str, ...]] = {
    "start": ("Speech On.wav", "Windows Navigation Start.wav", "ding.wav"),
    "stop": ("Speech Off.wav", "Speech Sleep.wav", "Windows Background.wav", "chord.wav"),
    "error": ("Speech Misrecognition.wav", "Windows Exclamation.wav", "chord.wav"),
}

# Fallback tone patterns (frequency_hz, duration_ms), also used by mode "beeps".
_TONES: dict[str, list[tuple[int, int]]] = {
    "start": [(660, 100), (990, 130)],   # rising: "ready, speak"
    "stop": [(880, 100), (520, 130)],    # falling: "processing"
    "error": [(300, 200), (250, 250)],   # low double tone
}


@cache
def _media_file(event: str) -> str | None:
    """Absolute path of the first existing WAV for ``event``, or None."""
    media_dir = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Media"
    for name in _MEDIA.get(event, ()):
        candidate = media_dir / name
        try:
            if candidate.is_file():
                return str(candidate)
        except OSError:  # unreadable path (e.g. locked-down install)
            continue
    log.debug("No system sound found for %r in %s.", event, media_dir)
    return None


def _play_tones(sequence: list[tuple[int, int]]) -> None:
    import winsound

    for freq, dur in sequence:
        winsound.Beep(freq, dur)


def _play(event: str, mode: str) -> None:
    """Play the cue for ``event`` according to ``mode``, off the caller's thread."""
    if mode == "off":
        return

    def _run() -> None:
        try:
            import winsound

            path = _media_file(event) if mode == "system" else None
            if path is not None:
                # SND_NODEFAULT: stay silent instead of falling back to the
                # system ding if the file cannot be played.
                winsound.PlaySound(
                    path,
                    winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT,
                )
                return
            _play_tones(_TONES[event])
        except Exception:  # winsound unavailable (non-Windows) or audio error
            pass

    threading.Thread(target=_run, daemon=True).start()


def recording_start(mode: str = "system") -> None:
    """Recording started ('ready, speak')."""
    _play("start", mode)


def recording_stop(mode: str = "system") -> None:
    """Recording stopped, transcription begins ('processing')."""
    _play("stop", mode)


def error(mode: str = "system") -> None:
    """Something went wrong during transcription."""
    _play("error", mode)


__all__ = ["recording_start", "recording_stop", "error"]
