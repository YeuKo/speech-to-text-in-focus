"""Controlador central: máquina de estados que orquesta todos los componentes."""

from __future__ import annotations

import enum
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING

import numpy as np

from stt import postprocess
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

    def start(self) -> None:
        log.info("Iniciando controlador (backend=%s)...", self._cfg.engine.backend)
        self._backend.load()
        self._hotkeys.start()

    # --- Callbacks de atajos (pueden llamarse desde cualquier hilo) ---------

    def on_toggle(self) -> None:
        with self._state_lock:
            if self._state == State.IDLE:
                self._state = State.RECORDING
                action = "start"
            elif self._state == State.RECORDING:
                self._state = State.TRANSCRIBING
                action = "stop"
            else:
                return  # TRANSCRIBING: ignorar
        if action == "start":
            self._begin_recording()
        else:
            self._end_recording()

    def on_ptt_press(self) -> None:
        with self._state_lock:
            if self._state != State.IDLE:
                return
            self._state = State.RECORDING
        self._begin_recording()

    def on_ptt_release(self) -> None:
        with self._state_lock:
            if self._state != State.RECORDING:
                return
            self._state = State.TRANSCRIBING
        self._end_recording()

    def _on_auto_stop(self) -> None:
        with self._state_lock:
            if self._state != State.RECORDING:
                return
            self._state = State.TRANSCRIBING
        self._end_recording()

    # --- Pipeline -----------------------------------------------------------

    def _begin_recording(self) -> None:
        _beep(880, 80)
        self._recorder.start()
        log.info("Grabando... (pulsa %s para parar o espera el silencio)", self._cfg.hotkey.toggle)

    def _end_recording(self) -> None:
        _beep(440, 80)
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
        finally:
            with self._state_lock:
                self._state = State.IDLE

    def stop(self) -> None:
        self._hotkeys.stop()
        self._backend.close()
        self._executor.shutdown(wait=False)


def _beep(freq: int, duration_ms: int) -> None:
    try:
        import winsound
        threading.Thread(target=winsound.Beep, args=(freq, duration_ms), daemon=True).start()
    except Exception:
        pass


__all__ = ["Controller", "State"]
