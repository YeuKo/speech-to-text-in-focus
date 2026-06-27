"""Backend remoto con la API de transcripción de OpenAI.

La API key se lee de una variable de entorno (o del almacén seguro de Windows
vía keyring), nunca del fichero de config. Antes de enviar, se recortan los
silencios para reducir la duración facturada.
"""

from __future__ import annotations

import io
import logging
import os
import time
import wave
from typing import TYPE_CHECKING

import numpy as np

from stt.audio.silence import trim_silence
from stt.transcribe.base import TranscriptionResult

if TYPE_CHECKING:
    from stt.config import Config

log = logging.getLogger(__name__)


def _resolve_api_key(env_name: str) -> str:
    """Obtiene la API key de la variable de entorno o de keyring."""
    key = os.environ.get(env_name)
    if key:
        return key
    try:
        import keyring  # type: ignore

        stored = keyring.get_password("stt-dictation", "openai_api_key")
        if stored:
            return stored
    except Exception as exc:
        log.debug("keyring no disponible: %s", exc)
    raise RuntimeError(
        f"No se encontró la API key de OpenAI. Define la variable de entorno {env_name} "
        "o guárdala en keyring (servicio 'stt-dictation', usuario 'openai_api_key')."
    )


def _to_wav_bytes(audio: np.ndarray, sample_rate: int) -> bytes:
    """Convierte audio float32 [-1,1] mono a un WAV PCM16 en memoria."""
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
    """Transcribe enviando el audio a la API de OpenAI."""

    def __init__(self, config: "Config") -> None:
        self._cfg = config
        self._client = None
        self._usage = None

    def load(self) -> None:
        from openai import OpenAI  # import perezoso

        api_key = _resolve_api_key(self._cfg.openai.api_key_env)
        self._client = OpenAI(api_key=api_key)
        if self._cfg.usage.track:
            from stt.usage import UsageTracker

            self._usage = UsageTracker(self._cfg.usage.file, self._cfg.usage.price_per_min)
            log.info("Seguimiento de coste activo. Total acumulado: $%.4f", self._usage.total)
        log.info("Backend OpenAI listo (modelo %s).", self._cfg.openai.model)

    def transcribe(
        self,
        audio: np.ndarray,
        *,
        sample_rate: int,
        language: str | None = None,
        prompt: str | None = None,
    ) -> TranscriptionResult:
        if self._client is None:
            raise RuntimeError("Backend OpenAI no inicializado: llama a load() primero.")

        started = time.monotonic()

        if self._cfg.openai.trim_silence and audio.size:
            original_s = audio.size / sample_rate
            audio = trim_silence(audio, sample_rate)
            trimmed_s = audio.size / sample_rate
            if trimmed_s < original_s:
                log.info(
                    "Silencios recortados: %.1fs -> %.1fs (se factura la duración enviada).",
                    original_s,
                    trimmed_s,
                )

        sent_seconds = audio.size / sample_rate
        wav_bytes = _to_wav_bytes(audio, sample_rate)
        # El SDK acepta un archivo con nombre; usamos una tupla (nombre, bytes).
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
