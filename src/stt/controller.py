"""Controlador central: máquina de estados que orquesta todos los componentes."""

from __future__ import annotations

import enum
import logging
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING

import numpy as np

from stt import postprocess, sounds
from stt.audio.recorder import Recorder
from stt.hotkey import HotkeyManager
from stt.inject import TextInjector
from stt.transcribe import create_backend

if TYPE_CHECKING:
    from stt.config import Config

log = logging.getLogger(__name__)

_MIN_AUDIO_S = 0.3  # descartar grabaciones más cortas (pulsaciones accidentales)


class State(enum.Enum):
    IDLE = "idle"
    RECORDING = "recording"
    TRANSCRIBING = "transcribing"


class Controller:
    def __init__(self, config: "Config") -> None:
        self._cfg = config
        self._state = State.IDLE
        self._state_lock = threading.Lock()
        self._on_state_change: Callable[[str], None] | None = None
        self._backend = create_backend(config)
        self._prompt = postprocess.build_prompt(config.dictionary.terms)
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="stt-tx")

        self._recorder = Recorder(config.audio, on_auto_stop=self._on_auto_stop)
        self._injector = TextInjector(config.injection)
        self._hotkeys = HotkeyManager(
            config.hotkey,
            on_toggle=self.on_toggle,
            on_ptt_press=self.on_ptt_press,
            on_ptt_release=self.on_ptt_release,
        )

    @property
    def state(self) -> State:
        return self._state

    def set_on_state_change(self, callback: Callable[[str], None]) -> None:
        """Registra un callback notificado en cada cambio de estado (p. ej. bandeja)."""
        self._on_state_change = callback

    def set_auto_stop(self, enabled: bool) -> None:
        """Activa/desactiva el auto-stop por silencio en caliente (sin reiniciar).

        Con False, la grabación solo para cuando se vuelve a pulsar el atajo
        (modo manual): permite pausas tan largas como se quiera.
        """
        self._cfg.audio.use_vad = enabled
        log.info("Auto-stop por silencio: %s", "ON" if enabled else "OFF (manual)")

    def is_auto_stop(self) -> bool:
        return self._cfg.audio.use_vad

    def start(self) -> None:
        log.info("Iniciando controlador (backend=%s)...", self._cfg.engine.backend)
        self._backend.load()
        self._hotkeys.start()

    # --- Transiciones de estado --------------------------------------------

    def _try_transition(self, expected: State, new: State) -> bool:
        """Compare-and-set atómico. Notifica fuera del lock si cambia."""
        with self._state_lock:
            if self._state != expected:
                return False
            self._state = new
        self._notify(new)
        return True

    def _force_state(self, new: State) -> None:
        with self._state_lock:
            self._state = new
        self._notify(new)

    def _notify(self, state: State) -> None:
        if self._on_state_change:
            try:
                self._on_state_change(state.value)
            except Exception:
                log.exception("Error en callback de estado.")

    # --- Callbacks de atajos (pueden llamarse desde cualquier hilo) ---------

    def on_toggle(self) -> None:
        if self._try_transition(State.IDLE, State.RECORDING):
            self._begin_recording()
        elif self._try_transition(State.RECORDING, State.TRANSCRIBING):
            self._end_recording()

    def on_ptt_press(self) -> None:
        if self._try_transition(State.IDLE, State.RECORDING):
            self._begin_recording()

    def on_ptt_release(self) -> None:
        if self._try_transition(State.RECORDING, State.TRANSCRIBING):
            self._end_recording()

    def _on_auto_stop(self) -> None:
        if self._try_transition(State.RECORDING, State.TRANSCRIBING):
            self._end_recording()

    # --- Pipeline -----------------------------------------------------------

    def _begin_recording(self) -> None:
        sounds.recording_start()
        self._recorder.start()
        log.info("Grabando... (pulsa %s para parar o espera el silencio)", self._cfg.hotkey.toggle)

    def _end_recording(self) -> None:
        sounds.recording_stop()
        audio = self._recorder.stop()
        self._executor.submit(self._transcribe_and_inject, audio)

    def _transcribe_and_inject(self, audio: np.ndarray) -> None:
        try:
            min_samples = int(self._cfg.audio.sample_rate * _MIN_AUDIO_S)
            if len(audio) < min_samples:
                log.info("Audio demasiado corto, ignorando.")
                return

            lang = self._cfg.engine.language if self._cfg.engine.language != "auto" else None
            result = self._backend.transcribe(
                audio,
                sample_rate=self._cfg.audio.sample_rate,
                language=lang,
                prompt=self._prompt,
            )
            text = postprocess.apply(result.text, self._cfg.dictionary.replacements)
            if text:
                log.info("Transcrito en %.1fs: %r", result.elapsed_s or 0, text)
                self._injector.inject(text)
            else:
                log.info("Transcripción vacía.")
        except Exception:
            log.exception("Error durante la transcripción.")
            sounds.error()
        finally:
            self._force_state(State.IDLE)

    def stop(self) -> None:
        self._hotkeys.stop()
        self._backend.close()
        self._executor.shutdown(wait=False)


__all__ = ["Controller", "State"]
