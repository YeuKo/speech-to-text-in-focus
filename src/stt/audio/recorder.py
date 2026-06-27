"""Captura de micrófono con sounddevice + auto-stop por silencio.

El corte por silencio usa por defecto un **umbral adaptativo**: estima el ruido
de fondo en tiempo real (el nivel más bajo observado) y considera "silencio"
todo lo que esté por debajo de ese ruido multiplicado por un factor. Así se
adapta solo a cualquier micrófono y entorno, sin necesidad de calibrar.

Si ``audio.auto_threshold`` es False, se usa el valor fijo
``audio.silence_threshold`` (útil para entornos muy concretos).
"""

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

_WARMUP_S = 0.4          # no cortar durante los primeros 0.4 s (evita falsos positivos)
_NOISE_FACTOR = 3.5      # se considera voz a partir de ruido_de_fondo * este factor
_MIN_FLOOR = 0.0010      # suelo mínimo de ruido (evita umbral 0 en silencio absoluto)
_FLOOR_RISE = 0.005      # qué rápido sube la estimación de ruido (lento)


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
        self._noise_floor: float | None = None

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
            self._noise_floor = None

        self._stream = sd.InputStream(
            samplerate=self._cfg.sample_rate,
            channels=self._cfg.channels,
            dtype="float32",
            blocksize=1024,
            callback=self._callback,
        )
        self._stream.start()
        log.debug("Grabación iniciada (%d Hz).", self._cfg.sample_rate)

    def _threshold(self, rms: float) -> float:
        """Devuelve el umbral de silencio. Adaptativo salvo override manual."""
        if not self._cfg.auto_threshold:
            return self._cfg.silence_threshold

        # Estima el ruido de fondo: baja al instante hasta el mínimo observado,
        # sube muy despacio. El resultado sigue el nivel más silencioso (ambiente).
        if self._noise_floor is None:
            self._noise_floor = rms
        elif rms < self._noise_floor:
            self._noise_floor = rms
        else:
            self._noise_floor += (rms - self._noise_floor) * _FLOOR_RISE

        return max(self._noise_floor * _NOISE_FACTOR, _MIN_FLOOR)

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
        rms = float(np.sqrt(np.mean(indata ** 2)))
        threshold = self._threshold(rms)  # actualiza el ruido también en warmup

        if now - self._started_at < _WARMUP_S:
            self._last_speech_at = now
            return

        if rms >= threshold:
            self._last_speech_at = now
        elif now - self._last_speech_at > self._cfg.silence_timeout_ms / 1000:
            with self._lock:
                if not self._recording:
                    return
                self._recording = False
            log.debug("Silencio detectado (rms=%.4f < umbral=%.4f) -> auto-stop.", rms, threshold)
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
