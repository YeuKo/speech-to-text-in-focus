"""Microphone capture with sounddevice + auto-stop on silence.

Silence-based stopping uses an **adaptive threshold** by default: it estimates
the background noise in real time (the lowest level observed) and treats as
"silence" anything below that noise multiplied by a factor. This adapts to any
microphone and environment on its own, with no calibration needed.

If ``audio.auto_threshold`` is False, the fixed ``audio.silence_threshold`` value
is used instead (useful for very specific environments).
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from typing import TYPE_CHECKING

import numpy as np

from stt.audio.devices import resolve_input_device
from stt.audio.silence import SPEECH_LEVEL

if TYPE_CHECKING:
    from stt.config import AudioConfig

log = logging.getLogger(__name__)

_WARMUP_S = 0.4          # don't cut during the first 0.4 s (avoids false positives)
_NOISE_FACTOR = 3.5      # treat as speech above background_noise * this factor
_MIN_FLOOR = 0.0010      # minimum noise floor (avoids a 0 threshold in dead silence)
_FLOOR_RISE = 0.005      # how fast the noise estimate rises (slow)


class Recorder:
    def __init__(
        self,
        config: "AudioConfig",
        *,
        on_auto_stop: Callable[[], None] | None = None,
        on_chunk: Callable[[np.ndarray], None] | None = None,
    ) -> None:
        self._cfg = config
        self._on_auto_stop = on_auto_stop
        self._on_chunk = on_chunk
        self._stream = None
        self._frames: list[np.ndarray] = []
        self._buffered = 0            # samples held in _frames, tracked as we go
        self._lock = threading.Lock()
        self._recording = False
        self._last_speech_at = 0.0
        self._started_at = 0.0
        self._noise_floor: float | None = None
        self._speech_detected = False

    @property
    def is_recording(self) -> bool:
        return self._recording

    def start(self) -> None:
        import sounddevice as sd

        with self._lock:
            self._frames = []
            self._buffered = 0
            self._recording = True
            now = time.monotonic()
            self._started_at = now
            self._last_speech_at = now
            self._noise_floor = None
            self._speech_detected = False

        device = resolve_input_device(self._cfg.input_device)
        try:
            self._stream = self._open_stream(sd, device)
        except Exception as exc:
            if device is None:
                raise
            # The chosen microphone may be gone (headset unplugged) or busy. Keep
            # dictation working on the default rather than failing outright.
            log.warning(
                "Could not open microphone %r (%s); falling back to the Windows default.",
                self._cfg.input_device, exc,
            )
            self._stream = self._open_stream(sd, None)

        self._stream.start()
        log.debug("Recording started (%d Hz, device=%s, gain=%.1fx).",
                  self._cfg.sample_rate,
                  "default" if device is None else device, self._cfg.gain)

    def _open_stream(self, sd, device: int | None):
        return sd.InputStream(
            samplerate=self._cfg.sample_rate,
            channels=self._cfg.channels,
            dtype="float32",
            blocksize=1024,
            device=device,
            callback=self._callback,
        )

    def _threshold(self, rms: float) -> float:
        """Return the silence threshold. Adaptive unless a manual override is set."""
        if not self._cfg.auto_threshold:
            return self._cfg.silence_threshold

        # Estimate the background noise: drop instantly to the lowest observed
        # value, rise very slowly. The result tracks the quietest (ambient) level.
        if self._noise_floor is None:
            self._noise_floor = rms
        elif rms < self._noise_floor:
            self._noise_floor = rms
        else:
            self._noise_floor += (rms - self._noise_floor) * _FLOOR_RISE

        # Capped at the level of ordinary speech. Without the ceiling, someone who
        # starts talking the instant they press the shortcut anchors the noise
        # estimate to their own voice, and from then on nothing counts as speech:
        # the auto-stop never fires and every pause check reads as silence.
        return min(max(self._noise_floor * _NOISE_FACTOR, _MIN_FLOOR), SPEECH_LEVEL)

    def _callback(self, indata: np.ndarray, frames: int, sd_time, status) -> None:
        if status:
            log.debug("sounddevice: %s", status)

        # Gain is applied here, before anything else looks at the audio, so the
        # silence detection below becomes more sensitive by the same amount.
        if self._cfg.gain != 1.0:
            indata = np.clip(indata * self._cfg.gain, -1.0, 1.0)

        with self._lock:
            if not self._recording:
                return
            self._frames.append(indata.copy())
            self._buffered += len(indata)

        now = time.monotonic()
        rms = float(np.sqrt(np.mean(indata ** 2)))
        threshold = self._threshold(rms)  # also updates the noise estimate during warmup

        # Hand over a finished chunk so it can be transcribed while the user is
        # still talking. Done before the auto-stop check because it applies
        # whether or not stopping on silence is enabled.
        self._maybe_emit_chunk(rms, threshold)

        if not self._cfg.auto_stop:
            return

        if now - self._started_at < _WARMUP_S:
            self._last_speech_at = now
            return

        if rms >= threshold:
            self._last_speech_at = now
            self._speech_detected = True
        # Silence auto-stop only kicks in AFTER speech has been heard: this gives
        # unlimited time to start talking after pressing the shortcut.
        elif self._speech_detected and (
            now - self._last_speech_at > self._cfg.silence_timeout_ms / 1000
        ):
            with self._lock:
                if not self._recording:
                    return
                self._recording = False
            log.debug("Silence detected (rms=%.4f < threshold=%.4f) -> auto-stop.", rms, threshold)
            if self._on_auto_stop:
                threading.Thread(target=self._on_auto_stop, daemon=True).start()

    def _maybe_emit_chunk(self, rms: float, threshold: float) -> None:
        """Release the buffered audio as a chunk once it is long enough.

        The cut waits for a pause so a word is never split in two, which would
        cost more accuracy than the wait saves. If the speaker never pauses, the
        chunk is released anyway at ``chunk_max_seconds``.

        Runs inside the audio callback, so it only moves references around: the
        transcription itself happens on the consumer's thread.
        """
        if self._on_chunk is None or self._cfg.chunk_seconds <= 0:
            return

        sample_rate = self._cfg.sample_rate
        with self._lock:
            seconds = self._buffered / sample_rate
            if seconds < self._cfg.chunk_seconds:
                return
            if rms >= threshold and seconds < self._cfg.chunk_max_seconds:
                return              # still mid-sentence: wait for a pause
            frames, self._frames = self._frames, []
            self._buffered = 0

        if not frames:
            return
        chunk = np.concatenate(frames, axis=0)
        if chunk.ndim > 1:
            chunk = chunk.mean(axis=1)
        log.debug("Chunk of %.1fs ready while recording.", len(chunk) / sample_rate)
        try:
            self._on_chunk(chunk.astype(np.float32))
        except Exception:
            log.exception("Error handing over an audio chunk.")

    def stop(self) -> np.ndarray:
        with self._lock:
            self._recording = False

        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception as exc:
                log.warning("Error closing the stream: %s", exc)
            self._stream = None

        with self._lock:
            frames, self._frames = self._frames, []
            self._buffered = 0

        if not frames:
            return np.zeros(0, dtype=np.float32)

        audio = np.concatenate(frames, axis=0)
        if audio.ndim > 1:
            audio = audio.mean(axis=1)
        return audio.astype(np.float32)


__all__ = ["Recorder"]
