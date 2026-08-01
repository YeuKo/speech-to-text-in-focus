"""Local backend using faster-whisper (CTranslate2)."""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

import numpy as np

from s2f import hardware
from s2f.transcribe.base import TranscriptionResult

if TYPE_CHECKING:
    from s2f.config import Config

log = logging.getLogger(__name__)

_CUDA_ERR_HINTS = ("cublas", "cudnn", "cuda", ".dll")


def _is_cuda_dll_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(h in msg for h in _CUDA_ERR_HINTS)


class LocalWhisperBackend:
    """Transcribe with a local Whisper model via faster-whisper."""

    def __init__(self, config: "Config") -> None:
        self._cfg = config
        self._model = None
        self._hw: hardware.Hardware | None = None

    def load(self) -> None:
        from faster_whisper import WhisperModel

        self._hw = hardware.detect(self._cfg.local.device, self._cfg.local.compute_type)
        model_name = hardware.resolve_model(self._cfg.local.model, self._hw)
        log.info("Loading model %s on %s...", model_name, self._hw.device)
        try:
            self._model = WhisperModel(
                model_name,
                device=self._hw.device,
                compute_type=self._hw.compute_type,
            )
        except Exception as exc:
            if self._hw.device == "cuda" and _is_cuda_dll_error(exc):
                self._warn_cuda(exc)
                self._load_cpu()
            else:
                raise

    def _load_cpu(self) -> None:
        from faster_whisper import WhisperModel

        self._hw = hardware.Hardware(device="cpu", compute_type="int8", has_cuda=False)
        model_name = hardware.resolve_model("small", self._hw)
        log.info("Loading %s on CPU...", model_name)
        self._model = WhisperModel(model_name, device="cpu", compute_type="int8")
        log.info("Model loaded on CPU. Works, but slower than on GPU.")

    def _warn_cuda(self, exc: Exception) -> None:
        log.warning(
            "Could not use the GPU: %s\n"
            "  faster-whisper requires the CUDA 12.x runtime (cublas64_12.dll, cudnn).\n"
            "  Your installed CUDA libraries may be a different major version.\n"
            "  To use the GPU, install the CUDA 12.x Toolkit from\n"
            "  https://developer.nvidia.com/cuda-toolkit-archive (it can coexist with\n"
            "  newer versions), or set device = \"cpu\" in config.toml to skip the GPU.\n"
            "  Falling back to CPU for now.",
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
            raise RuntimeError("Backend not initialised: call load() first.")

        started = time.monotonic()
        kwargs = dict(
            language=None if language in (None, "auto") else language,
            # Transcribe, never translate. It is the default, but stating it means
            # a future default cannot silently turn dictation into translation.
            task="transcribe",
            initial_prompt=prompt,
            vad_filter=self._cfg.audio.vad_filter,
            # Whisper decodes 30-second windows and, by default, feeds what it just
            # produced back in as context for the next one. That helps a coherent
            # narration, but it is also the classic cause of the model getting stuck
            # repeating the same sentence to the end of a recording: one bad guess
            # feeds itself. Dictation is short and self-contained, so each window is
            # better decoded on its own.
            condition_on_previous_text=False,
        )
        try:
            segments, info = self._model.transcribe(audio, **kwargs)
            # Iterating the generator is where the GPU/CPU work actually happens.
            text = "".join(s.text for s in segments).strip()
        except RuntimeError as exc:
            if self._hw and self._hw.device == "cuda" and _is_cuda_dll_error(exc):
                self._warn_cuda(exc)
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
