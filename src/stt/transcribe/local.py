"""Backend local con faster-whisper (CTranslate2).

Esbozo de Fase 0: la firma y el ciclo de vida están definidos; la transcripción
real se completa en el MVP (Fase 1). La carga de ``faster_whisper`` es perezosa
para no exigir la dependencia al importar el módulo.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

import numpy as np

from stt import hardware
from stt.transcribe.base import TranscriptionResult

if TYPE_CHECKING:
    from stt.config import Config

log = logging.getLogger(__name__)


class LocalWhisperBackend:
    """Transcribe con un modelo Whisper local vía faster-whisper."""

    def __init__(self, config: "Config") -> None:
        self._cfg = config
        self._model = None  # se inicializa en load()
        self._hw: hardware.Hardware | None = None

    def load(self) -> None:
        from faster_whisper import WhisperModel  # import perezoso

        self._hw = hardware.detect(self._cfg.local.device, self._cfg.local.compute_type)
        model_name = hardware.resolve_model(self._cfg.local.model, self._hw)
        log.info("Cargando modelo local %s...", model_name)
        self._model = WhisperModel(
            model_name,
            device=self._hw.device,
            compute_type=self._hw.compute_type,
        )

    def transcribe(
        self,
        audio: np.ndarray,
        *,
        sample_rate: int,
        language: str | None = None,
        prompt: str | None = None,
    ) -> TranscriptionResult:
        if self._model is None:
            raise RuntimeError("Backend local no inicializado: llama a load() primero.")

        started = time.monotonic()
        # faster-whisper espera audio mono float32 a 16 kHz.
        segments, info = self._model.transcribe(
            audio,
            language=None if language in (None, "auto") else language,
            initial_prompt=prompt,
            vad_filter=self._cfg.audio.use_vad,
        )
        text = "".join(segment.text for segment in segments).strip()
        elapsed = time.monotonic() - started
        return TranscriptionResult(
            text=text,
            language=getattr(info, "language", None),
            duration_s=getattr(info, "duration", None),
            elapsed_s=elapsed,
        )

    def close(self) -> None:
        self._model = None


__all__ = ["LocalWhisperBackend"]
