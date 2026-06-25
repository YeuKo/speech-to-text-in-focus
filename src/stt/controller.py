"""Controlador central: máquina de estados que orquesta los componentes.

Ensambla configuración, atajos, grabador, backend de transcripción, post-procesado
e inyección de texto. El cableado y el pipeline de transcripción están definidos;
los componentes que dependen de Windows (grabador, atajos, inyección) se completan
en el MVP (Fase 1), pero el flujo y el post-procesado ya son reales.
"""

from __future__ import annotations

import enum
import logging
from typing import TYPE_CHECKING

import numpy as np

from stt import postprocess
from stt.transcribe import create_backend

if TYPE_CHECKING:
    from stt.config import Config

log = logging.getLogger(__name__)


class State(enum.Enum):
    IDLE = "idle"
    RECORDING = "recording"
    TRANSCRIBING = "transcribing"


class Controller:
    def __init__(self, config: "Config") -> None:
        self._cfg = config
        self._state = State.IDLE
        self._backend = create_backend(config)
        # Prompt de sesgo construido una vez a partir del diccionario.
        self._prompt = postprocess.build_prompt(config.dictionary.terms)
        # Componentes Windows: se inyectan/crean al arrancar (Fase 1).
        self._recorder = None
        self._injector = None

    @property
    def state(self) -> State:
        return self._state

    def start(self) -> None:
        """Prepara el backend (carga el modelo / valida credenciales)."""
        log.info("Iniciando controlador (backend=%s)...", self._cfg.engine.backend)
        self._backend.load()

    # --- Eventos de los atajos -------------------------------------------

    def on_toggle(self) -> None:
        if self._state == State.IDLE:
            self._begin_recording()
        elif self._state == State.RECORDING:
            self._end_recording_and_transcribe()

    def on_ptt_press(self) -> None:
        if self._state == State.IDLE:
            self._begin_recording()

    def on_ptt_release(self) -> None:
        if self._state == State.RECORDING:
            self._end_recording_and_transcribe()

    # --- Pipeline ---------------------------------------------------------

    def _begin_recording(self) -> None:
        self._state = State.RECORDING
        log.info("Grabando...")
        # Fase 1: self._recorder.start()

    def _end_recording_and_transcribe(self) -> None:
        self._state = State.TRANSCRIBING
        # Fase 1: audio = self._recorder.stop()
        audio = np.zeros(0, dtype=np.float32)  # placeholder hasta Fase 1
        try:
            text = self._transcribe(audio)
            if text:
                self._inject(text)
        finally:
            self._state = State.IDLE

    def _transcribe(self, audio: np.ndarray) -> str:
        result = self._backend.transcribe(
            audio,
            sample_rate=self._cfg.audio.sample_rate,
            language=self._cfg.engine.language,
            prompt=self._prompt,
        )
        text = postprocess.apply(result.text, self._cfg.dictionary.replacements)
        log.info("Transcrito (%s): %r", result.language, text)
        return text

    def _inject(self, text: str) -> None:
        if self._injector is None:
            log.warning("Inyector no disponible (Fase 1). Texto: %r", text)
            return
        self._injector.inject(text)

    def stop(self) -> None:
        self._backend.close()


__all__ = ["Controller", "State"]
