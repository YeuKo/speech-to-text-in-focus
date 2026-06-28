"""Common transcription backend interface and its factory.

The rest of the app depends only on ``TranscriberBackend``, so switching between
the local model and the OpenAI API does not affect the controller or the UI.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

import numpy as np

if TYPE_CHECKING:
    from stt.config import Config


@dataclass
class TranscriptionResult:
    """Result of transcribing an audio chunk."""

    text: str
    language: str | None = None
    duration_s: float | None = None  # audio duration
    elapsed_s: float | None = None  # time the transcription took


@runtime_checkable
class TranscriberBackend(Protocol):
    """Contract that backends must satisfy.

    ``audio`` is mono float32 PCM normalised to [-1, 1] at the given
    ``sample_rate``. ``prompt`` biases recognition (e.g. with the dictionary).
    """

    def load(self) -> None:
        """Prepare the backend (load the local model / validate credentials)."""
        ...

    def transcribe(
        self,
        audio: np.ndarray,
        *,
        sample_rate: int,
        language: str | None = None,
        prompt: str | None = None,
    ) -> TranscriptionResult: ...

    def close(self) -> None:
        """Release resources (in-memory model, connections)."""
        ...


def create_backend(config: "Config") -> TranscriberBackend:
    """Create the backend based on ``config.engine.backend``.

    The concrete module is imported lazily so heavy dependencies
    (faster-whisper, openai) are not required until they are actually used.
    """
    backend = config.engine.backend
    if backend == "local":
        from stt.transcribe.local import LocalWhisperBackend

        return LocalWhisperBackend(config)
    if backend == "openai":
        from stt.transcribe.openai_api import OpenAIBackend

        return OpenAIBackend(config)
    raise ValueError(f"Unknown transcription backend: {backend!r}")


__all__ = ["TranscriberBackend", "TranscriptionResult", "create_backend"]
