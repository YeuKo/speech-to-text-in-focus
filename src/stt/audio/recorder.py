"""Captura de micrófono con sounddevice + auto-stop por silencio."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from stt.config import AudioConfig

log = logging.getLogger(__name__)

_WARMUP_S = 0.4  # no cortar durante los primeros 0.4 s (evita falsos positivos)


class Recorder:
    def __init__(
        self,
        config: "AudioConfig",
        *,
        on_auto_stop: Callable[[], None] | None = None,
    ) -> None:
        self._cfg = config
        self._on_auto_stop = on_auto_stop
        self._stream = None
        self._frames: list[np.ndarray] = []
        self._lock = threading.Lock()
        self._recording = False
        self._last_speech_at = 0.0
        self._started_at = 0.0

    @property
    def is_recording(self) -> bool:
        return self._recording

    def start(self) -> None:
        import sounddevice as sd

        with self._lock:
            self._frames = []
            self._recording = True
            now = time.monotonic()
            self._started_at = now
            self._last_speech_at = now

        self._stream = sd.InputStream(
            samplerate=self._cfg.sample_rate,
            channels=self._cfg.channels,
            dtype="float32",
            blocksize=1024,
            callback=self._callback,
        )
        self._stream.start()
        log.debug("Grabación iniciada (%d Hz).", self._cfg.sample_rate)

    def _callback(self, indata: np.ndarray, frames: int, sd_time, status) -> None:
        if status:
            log.debug("sounddevice: %s", status)

        with self._lock:
            if not self._recording:
                return
            self._frames.append(indata.copy())

        if not self._cfg.use_vad:
            return

        now = time.monotonic()
        if now - self._started_at < _WARMUP_S:
            return

        rms = float(np.sqrt(np.mean(indata ** 2)))
        if rms >= self._cfg.silence_threshold:
            self._last_speech_at = now
        elif now - self._last_speech_at > self._cfg.silence_timeout_ms / 1000:
            with self._lock:
                if not self._recording:
                    return
                self._recording = False
            log.debug("Silencio detectado -> auto-stop.")
            if self._on_auto_stop:
                threading.Thread(target=self._on_auto_stop, daemon=True).start()

    def stop(self) -> np.ndarray:
        with self._lock:
            self._recording = False

        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception as exc:
                log.warning("Error al cerrar el stream: %s", exc)
            self._stream = None

        with self._lock:
            frames = list(self._frames)

        if not frames:
            return np.zeros(0, dtype=np.float32)

        audio = np.concatenate(frames, axis=0)
        if audio.ndim > 1:
            audio = audio.mean(axis=1)
        return audio.astype(np.float32)


__all__ = ["Recorder"]
