"""Captura de micrófono con sounddevice.

Esbozo de Fase 0: define la interfaz de grabación (iniciar/parar y entregar el
audio como float32 mono). El bucle de captura con VAD y auto-stop por silencio
se implementa en el MVP (Fase 1). La carga de ``sounddevice`` es perezosa.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from stt.config import AudioConfig

log = logging.getLogger(__name__)


class Recorder:
    """Graba audio del micrófono a ``sample_rate`` en mono float32."""

    def __init__(self, config: "AudioConfig") -> None:
        self._cfg = config
        self._stream = None
        self._frames: list[np.ndarray] = []
        self._recording = False

    @property
    def is_recording(self) -> bool:
        return self._recording

    def start(self) -> None:
        """Comienza a capturar audio (no bloqueante)."""
        raise NotImplementedError("Pendiente Fase 1: abrir InputStream de sounddevice.")

    def stop(self) -> np.ndarray:
        """Detiene la captura y devuelve el audio acumulado (float32 mono [-1,1])."""
        raise NotImplementedError("Pendiente Fase 1: cerrar stream y concatenar frames.")


__all__ = ["Recorder"]
