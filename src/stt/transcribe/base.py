"""Interfaz común de los backends de transcripción y su factory.

El resto de la app depende solo de ``TranscriberBackend``, de modo que conmutar
entre el modelo local y la API de OpenAI no afecta al controlador ni a la UI.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

import numpy as np

if TYPE_CHECKING:
    from stt.config import Config


@dataclass
class TranscriptionResult:
    """Resultado de transcribir un fragmento de audio."""

    text: str
    language: str | None = None
    duration_s: float | None = None  # duración del audio
    elapsed_s: float | None = None  # tiempo que tardó la transcripción


@runtime_checkable
class TranscriberBackend(Protocol):
    """Contrato que deben cumplir los backends.

    ``audio`` es PCM mono float32 normalizado a [-1, 1] al ``sample_rate`` dado.
    ``prompt`` permite sesgar el reconocimiento (p. ej. con el diccionario).
    """

    def load(self) -> None:
        """Prepara el backend (carga el modelo local / valida credenciales)."""
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
        """Libera recursos (modelo en memoria, conexiones)."""
        ...


def create_backend(config: "Config") -> TranscriberBackend:
    """Crea el backend según ``config.engine.backend``.

    Importa el módulo concreto de forma perezosa para no exigir dependencias
    pesadas (faster-whisper, openai) hasta que realmente se usan.
    """
    backend = config.engine.backend
    if backend == "local":
        from stt.transcribe.local import LocalWhisperBackend

        return LocalWhisperBackend(config)
    if backend == "openai":
        from stt.transcribe.openai_api import OpenAIBackend

        return OpenAIBackend(config)
    raise ValueError(f"Backend de transcripción desconocido: {backend!r}")


__all__ = ["TranscriberBackend", "TranscriptionResult", "create_backend"]
