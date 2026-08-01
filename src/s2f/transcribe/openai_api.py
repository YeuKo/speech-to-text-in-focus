"""Remote backend using the OpenAI transcription API.

The API key is read from an environment variable (or the Windows credential
store via keyring), never from the config file. Before sending, silences are
trimmed to reduce the billed audio duration.
"""

from __future__ import annotations

import io
import logging
import os
import time
import wave
from typing import TYPE_CHECKING

import numpy as np

from s2f.audio.silence import trim_silence
from s2f.transcribe.base import TranscriptionResult

if TYPE_CHECKING:
    from s2f.config import Config

log = logging.getLogger(__name__)


def _resolve_api_key(env_name: str) -> str:
    """Get the API key from the environment variable or keyring."""
    from s2f import keystore

    key = os.environ.get(env_name) or keystore.get_api_key()
    if key:
        return key
    raise RuntimeError(
        f"OpenAI API key not found. Set the {env_name} environment variable, "
        "run 's2f --set-api-key', or use the tray menu 'Set OpenAI API key…'."
    )


def _to_wav_bytes(audio: np.ndarray, sample_rate: int) -> bytes:
    """Convert mono float32 [-1,1] audio to in-memory PCM16 WAV bytes."""
    pcm16 = np.clip(audio, -1.0, 1.0)
    pcm16 = (pcm16 * 32767.0).astype("<i2")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm16.tobytes())
    return buf.getvalue()


class OpenAIBackend:
    """Transcribe by sending the audio to the OpenAI API."""

    def __init__(self, config: "Config") -> None:
        self._cfg = config
        self._client = None
        self._usage = None

    def load(self) -> None:
        from openai import OpenAI  # lazy import

        api_key = _resolve_api_key(self._cfg.openai.api_key_env)
        self._client = OpenAI(api_key=api_key)
        if self._cfg.usage.track:
            from s2f.usage import UsageTracker

            self._usage = UsageTracker(self._cfg.usage.file, self._cfg.usage.price_per_min)
            log.info("Cost tracking enabled. Running total: $%.4f", self._usage.total)
        log.info("OpenAI backend ready (model %s).", self._cfg.openai.model)

    def transcribe(
        self,
        audio: np.ndarray,
        *,
        sample_rate: int,
        language: str | None = None,
        prompt: str | None = None,
    ) -> TranscriptionResult:
        if self._client is None:
            raise RuntimeError("OpenAI backend not initialised: call load() first.")

        started = time.monotonic()

        if self._cfg.openai.trim_silence and audio.size:
            original_s = audio.size / sample_rate
            audio = trim_silence(audio, sample_rate)
            trimmed_s = audio.size / sample_rate
            if trimmed_s < original_s:
                log.info(
                    "Silence trimmed: %.1fs -> %.1fs (the sent duration is what's billed).",
                    original_s,
                    trimmed_s,
                )

        sent_seconds = audio.size / sample_rate
        wav_bytes = _to_wav_bytes(audio, sample_rate)
        # The SDK accepts a named file; we use a (name, bytes, mime) tuple.
        file_tuple = ("audio.wav", wav_bytes, "audio/wav")
        resp = self._client.audio.transcriptions.create(
            model=self._cfg.openai.model,
            file=file_tuple,
            language=None if language in (None, "auto") else language,
            prompt=prompt,
        )
        elapsed = time.monotonic() - started

        if self._usage is not None:
            self._usage.record(self._cfg.openai.model, sent_seconds)

        return TranscriptionResult(text=resp.text.strip(), language=language, elapsed_s=elapsed)

    def close(self) -> None:
        self._client = None


__all__ = ["OpenAIBackend"]
