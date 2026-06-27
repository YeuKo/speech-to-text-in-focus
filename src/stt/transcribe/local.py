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

_CUDA_ERR_HINTS = ("cublas", "cudnn", "cuda", ".dll")


def _is_cuda_dll_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(h in msg for h in _CUDA_ERR_HINTS)


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
        log.info("Cargando modelo %s en %s...", model_name, self._hw.device)
        try:
            self._model = WhisperModel(
                model_name,
                device=self._hw.device,
                compute_type=self._hw.compute_type,
            )
        except Exception as exc:
            if self._hw.device == "cuda" and _is_cuda_dll_error(exc):
                self._warn_cuda_version(exc)
                self._load_cpu()
            else:
                raise

    def _load_cpu(self) -> None:
        from faster_whisper import WhisperModel

        self._hw = hardware.Hardware(device="cpu", compute_type="int8", has_cuda=False)
        model_name = hardware.resolve_model("small", self._hw)
        log.info("Cargando %s en CPU...", model_name)
        self._model = WhisperModel(model_name, device="cpu", compute_type="int8")
        log.info("Modelo cargado en CPU. Funciona, pero más lento que en GPU.")

    def _warn_cuda_version(self, exc: Exception) -> None:
        log.warning(
            "No se pudo usar la GPU: %s\n"
            "  faster-whisper necesita CUDA 12.x (cublas64_12.dll).\n"
            "  Tienes instalado CUDA 13.x, que usa cublas64_13.dll (incompatible).\n"
            "  Opciones para usar la GPU:\n"
            "    1. Instala CUDA 12.x desde https://developer.nvidia.com/cuda-12-0-0-download-archive\n"
            "       (puede coexistir con CUDA 13.x)\n"
            "    2. Pon device = \"cpu\" en config.toml para ignorar la GPU.\n"
            "  Por ahora usando CPU automáticamente.",
            exc,
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
            raise RuntimeError("Backend no inicializado: llama a load() primero.")

        started = time.monotonic()
        kwargs = dict(
            language=None if language in (None, "auto") else language,
            initial_prompt=prompt,
            vad_filter=self._cfg.audio.use_vad,
        )
        try:
            segments, info = self._model.transcribe(audio, **kwargs)
            # La iteración del generador es donde se ejecuta la GPU/CPU.
            text = "".join(s.text for s in segments).strip()
        except RuntimeError as exc:
            if self._hw and self._hw.device == "cuda" and _is_cuda_dll_error(exc):
                self._warn_cuda_version(exc)
                self._load_cpu()
                segments, info = self._model.transcribe(audio, **kwargs)
                text = "".join(s.text for s in segments).strip()
            else:
                raise

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
