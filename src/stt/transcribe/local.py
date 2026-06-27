"""Backend local con faster-whisper (CTranslate2)."""

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
        self._model = None
        self._hw: hardware.Hardware | None = None

    def load(self) -> None:
        from faster_whisper import WhisperModel

        self._hw = hardware.detect(self._cfg.local.device, self._cfg.local.compute_type)
        model_name = hardware.resolve_model(self._cfg.local.model, self._hw)
        log.info("Cargando modelo local %s en %s...", model_name, self._hw.device)
        try:
            self._model = WhisperModel(
                model_name,
                device=self._hw.device,
                compute_type=self._hw.compute_type,
            )
        except Exception as exc:
            if self._hw.device == "cuda":
                log.warning(
                    "No se pudo cargar en GPU (%s). "
                    "Probablemente falta el CUDA Toolkit 12.x (cublas64_12.dll). "
                    "Reintentando en CPU con modelo 'small'...",
                    exc,
                )
                self._hw = hardware.Hardware(device="cpu", compute_type="int8", has_cuda=False)
                cpu_model = hardware.resolve_model("small", self._hw)
                self._model = WhisperModel(cpu_model, device="cpu", compute_type="int8")
                log.info("Modelo cargado en CPU (%s). Para GPU: instala CUDA Toolkit 12.x.", cpu_model)
            else:
                raise

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
