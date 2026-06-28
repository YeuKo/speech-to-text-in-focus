"""Central controller: state machine that orchestrates all components."""

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

_MIN_AUDIO_S = 0.3  # discard recordings shorter than this (accidental key presses)


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
        self._backend_lock = threading.Lock()
        self.startup_warning: str | None = None
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
        """Register a callback fired on every state change (e.g. the tray icon)."""
        self._on_state_change = callback

    def set_auto_stop(self, enabled: bool) -> None:
        """Enable/disable silence auto-stop on the fly (no restart needed).

        With False, recording only stops when the shortcut is pressed again
        (manual mode): it allows arbitrarily long pauses.
        """
        self._cfg.audio.use_vad = enabled
        log.info("Silence auto-stop: %s", "ON" if enabled else "OFF (manual)")

    def is_auto_stop(self) -> bool:
        return self._cfg.audio.use_vad

    def start(self) -> None:
        log.info("Starting controller (backend=%s)...", self._cfg.engine.backend)
        try:
            self._backend.load()
        except Exception as exc:
            # Graceful start: if OpenAI fails (e.g. no API key), fall back to
            # local instead of crashing, and tell the user.
            if self._cfg.engine.backend == "openai":
                log.warning("Could not start OpenAI (%s). Using local instead.", exc)
                self.startup_warning = (
                    "OpenAI is not available (missing/invalid API key). "
                    "Falling back to the local engine. You can set a key and switch "
                    "engine from the tray menu."
                )
                self._cfg.engine.backend = "local"
                self._backend = create_backend(self._cfg)
                self._backend.load()
            else:
                raise
        self._hotkeys.start()

    def current_backend(self) -> str:
        return self._cfg.engine.backend

    def switch_backend(self, name: str) -> tuple[bool, str]:
        """Switch the engine on the fly. Returns (ok, message).

        If the new backend cannot load (e.g. OpenAI with no key), it reverts to
        the previous one and keeps the system running.
        """
        if name == self._cfg.engine.backend:
            return True, f"Already using {name}."
        if self._state != State.IDLE:
            return False, "Busy transcribing — try again in a moment."

        previous = self._cfg.engine.backend
        self._cfg.engine.backend = name
        try:
            new_backend = create_backend(self._cfg)
            new_backend.load()
        except Exception as exc:
            self._cfg.engine.backend = previous  # revert
            log.warning("Could not switch to %s: %s", name, exc)
            return False, str(exc)

        with self._backend_lock:
            old, self._backend = self._backend, new_backend
        try:
            old.close()
        except Exception:
            pass
        log.info("Engine switched to %s.", name)
        return True, f"Now using {name}."

    # --- State transitions --------------------------------------------------

    def _try_transition(self, expected: State, new: State) -> bool:
        """Atomic compare-and-set. Notifies outside the lock if it changes."""
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
                log.exception("Error in state-change callback.")

    # --- Hotkey callbacks (may be called from any thread) -------------------

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
        log.info("Recording... (press %s to stop or wait for silence)", self._cfg.hotkey.toggle)

    def _end_recording(self) -> None:
        sounds.recording_stop()
        audio = self._recorder.stop()
        self._executor.submit(self._transcribe_and_inject, audio)

    def _transcribe_and_inject(self, audio: np.ndarray) -> None:
        try:
            min_samples = int(self._cfg.audio.sample_rate * _MIN_AUDIO_S)
            if len(audio) < min_samples:
                log.info("Audio too short, ignoring.")
                return

            lang = self._cfg.engine.language if self._cfg.engine.language != "auto" else None
            with self._backend_lock:
                backend = self._backend
            result = backend.transcribe(
                audio,
                sample_rate=self._cfg.audio.sample_rate,
                language=lang,
                prompt=self._prompt,
            )
            text = postprocess.apply(result.text, self._cfg.dictionary.replacements)
            if text:
                # Log only the length at INFO; the full text (potentially private)
                # is logged at DEBUG only.
                log.info("Transcribed %d chars in %.1fs.", len(text), result.elapsed_s or 0)
                log.debug("Transcription text: %r", text)
                self._injector.inject(text)
            else:
                log.info("Empty transcription.")
        except Exception:
            log.exception("Error during transcription.")
            sounds.error()
        finally:
            self._force_state(State.IDLE)

    def stop(self) -> None:
        self._hotkeys.stop()
        self._backend.close()
        self._executor.shutdown(wait=False)


__all__ = ["Controller", "State"]
