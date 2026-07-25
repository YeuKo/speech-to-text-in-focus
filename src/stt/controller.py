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
from stt.audio.silence import has_speech, normalise_level
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
        self._on_notify: Callable[[str, str, str], None] | None = None
        self._backend = create_backend(config)
        self._backend_lock = threading.Lock()
        self.startup_warning: str | None = None
        self._prompt = postprocess.build_prompt(config.dictionary.terms)
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="stt-tx")
        # User-facing events go through their own single worker: drawing the
        # status pill must never delay recording or stall the hotkey thread. One
        # worker also keeps the events in order.
        self._notifier = ThreadPoolExecutor(max_workers=1, thread_name_prefix="stt-notify")

        # Text of the chunks already transcribed while the user was still
        # talking. Only ever touched from the transcription worker.
        self._partials: list[str] = []
        self._recorder = Recorder(
            config.audio,
            on_auto_stop=self._on_auto_stop,
            on_chunk=self._on_chunk_ready,
        )
        self._injector = TextInjector(config.injection)
        self._hotkeys = self._make_hotkeys()

    def _make_hotkeys(self) -> HotkeyManager:
        return HotkeyManager(
            self._cfg.hotkey,
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

    def set_on_notify(self, callback: Callable[[str, str, str], None]) -> None:
        """Register the sink for user-facing events (kind, title, message).

        The controller only reports what happened; the UI layer decides how to
        show it, or whether to show it at all.
        """
        self._on_notify = callback

    def _notify_user(self, kind: str, title: str, message: str) -> None:
        """Report a user-facing event. Never blocks the pipeline."""
        if self._on_notify is None:
            return
        callback = self._on_notify

        def _run() -> None:
            try:
                callback(kind, title, message)
            except Exception:
                log.exception("Error reporting a user event.")

        try:
            self._notifier.submit(_run)
        except RuntimeError:  # already shutting down
            pass

    # --- Feedback settings (tray menu) --------------------------------------

    def set_sound_mode(self, mode: str) -> None:
        """Change the audible feedback: "system", "beeps" or "off"."""
        self._cfg.feedback.sound = mode
        log.info("Feedback sound: %s", mode)

    def sound_mode(self) -> str:
        return self._cfg.feedback.sound

    def set_overlay(self, enabled: bool) -> None:
        self._cfg.feedback.overlay = enabled
        log.info("Floating status pill: %s", "ON" if enabled else "OFF")

    def overlay_enabled(self) -> bool:
        return self._cfg.feedback.overlay

    # --- Custom words -------------------------------------------------------

    def current_terms(self) -> list[str]:
        return list(self._cfg.dictionary.terms)

    def set_terms(self, terms: list[str]) -> None:
        """Replace the custom-words list and rebuild the prompt, no restart needed."""
        self._cfg.dictionary.terms = terms
        self._prompt = postprocess.build_prompt(terms)
        log.info("Custom words updated (%d terms).", len(terms))

    # --- Language -----------------------------------------------------------

    def current_language(self) -> str:
        return self._cfg.engine.language

    def set_language(self, code: str) -> None:
        """Set the dictation language ("auto" to let the model decide).

        Read afresh on every transcription, so it applies to the next dictation
        without reloading the model. Worth having within reach: with the language
        forced to the wrong one, Whisper does not fail — it quietly translates.
        """
        self._cfg.engine.language = code
        log.info("Language: %s", code)

    # --- Microphone ---------------------------------------------------------

    def current_microphone(self) -> str:
        return self._cfg.audio.input_device

    def set_microphone(self, name: str) -> None:
        """Choose the input device ("auto" for the Windows default).

        The recorder opens its stream on each start(), so the change takes effect
        on the next dictation with no restart.
        """
        self._cfg.audio.input_device = name
        log.info("Microphone: %s", name)

    def set_auto_stop(self, enabled: bool) -> None:
        """Enable/disable silence auto-stop on the fly (no restart needed).

        With False, recording only stops when the shortcut is pressed again
        (manual mode): it allows arbitrarily long pauses.
        """
        self._cfg.audio.auto_stop = enabled
        log.info("Silence auto-stop: %s", "ON" if enabled else "OFF (manual)")

    def is_auto_stop(self) -> bool:
        return self._cfg.audio.auto_stop

    # --- Shortcuts ----------------------------------------------------------

    def shortcut_mode(self) -> str:
        return self._cfg.hotkey.mode

    def set_shortcut_mode(self, mode: str) -> tuple[bool, str]:
        """Switch between the two shortcuts and the single gesture."""
        if mode == self._cfg.hotkey.mode:
            return True, f"Already using {mode}."
        previous = self._cfg.hotkey.mode
        self.suspend_hotkeys()
        self._cfg.hotkey.mode = mode
        try:
            self.resume_hotkeys()
        except Exception as exc:
            self._cfg.hotkey.mode = previous
            self.resume_hotkeys()
            return False, f"Could not switch to {mode}: {exc}"
        log.info("Shortcut mode: %s", mode)
        return True, f"Shortcut mode: {mode}."

    # --- Hotkey reconfiguration (for the tray's capture dialog) -------------

    def suspend_hotkeys(self) -> None:
        """Temporarily stop listening (so capture doesn't trigger the app)."""
        self._hotkeys.stop()

    def resume_hotkeys(self) -> None:
        """Re-register the hotkeys from the current config."""
        self._hotkeys = self._make_hotkeys()
        self._hotkeys.start()

    def apply_hotkey(self, which: str, combo: str) -> tuple[bool, str]:
        """Set a new combination for "toggle" or "push_to_talk".

        Assumes hotkeys are currently suspended; re-registers on the way out.
        Reverts and reports if the combination is invalid or already in use.
        """
        if which not in ("toggle", "push_to_talk", "gesture"):
            self.resume_hotkeys()
            return False, f"Unknown hotkey: {which}"

        # An empty gesture is how you turn it off; the other two cannot be empty.
        others = {
            name: getattr(self._cfg.hotkey, name)
            for name in ("toggle", "push_to_talk", "gesture")
            if name != which
        }
        if combo and combo in others.values():
            self.resume_hotkeys()
            return False, "That combination is already used by another mode."

        previous = getattr(self._cfg.hotkey, which)
        setattr(self._cfg.hotkey, which, combo)
        try:
            self.resume_hotkeys()
        except Exception as exc:
            setattr(self._cfg.hotkey, which, previous)
            self.resume_hotkeys()
            return False, f"Could not register '{combo}': {exc}"
        return True, f"{which.replace('_', ' ')} shortcut set to: {combo}"

    def start(self) -> None:
        log.info("Starting controller (backend=%s)...", self._cfg.engine.backend)
        # Loading the model takes seconds, and on a first run it downloads well
        # over a gigabyte. A packaged build has no console, so without this the
        # app would simply appear to do nothing for minutes.
        self._notify_user("loading", "Loading the speech model",
                          "The first run downloads it — this only happens once.")
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
        self._notify_user("ready", "Ready",
                          f"Press {self._cfg.hotkey.toggle} to dictate.")

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

    def _on_chunk_ready(self, audio: np.ndarray) -> None:
        """Queue a chunk the recorder released mid-speech.

        Called from the audio callback, so it must return immediately: submitting
        to the worker is all that happens here.
        """
        try:
            self._executor.submit(self._transcribe_chunk, audio)
        except RuntimeError:      # shutting down
            pass

    def _on_auto_stop(self) -> None:
        if self._try_transition(State.RECORDING, State.TRANSCRIBING):
            self._end_recording()

    # --- Pipeline -----------------------------------------------------------

    def _begin_recording(self) -> None:
        sounds.recording_start(self._cfg.feedback.sound)
        try:
            self._recorder.start()
        except Exception:
            # Without this the state machine would stay in RECORDING with no
            # stream behind it: the icon says recording, nothing is captured, and
            # the next press "stops" a recording that never began.
            log.exception("Could not open the microphone.")
            self._force_state(State.IDLE)
            sounds.error(self._cfg.feedback.sound)
            self._notify_user(
                "error", "Microphone unavailable",
                "Could not open the microphone — see logs/stt.log.",
            )
            return
        log.info("Recording... (press %s to stop or wait for silence)", self._cfg.hotkey.toggle)
        self._notify_user("recording", "Recording", "Speak now — I'm listening.")

    def _end_recording(self) -> None:
        sounds.recording_stop(self._cfg.feedback.sound)
        audio = self._recorder.stop()
        self._notify_user("transcribing", "Transcribing", "Processing your audio…")
        self._executor.submit(self._transcribe_and_inject, audio)

    def _transcribe(self, audio: np.ndarray) -> str:
        """Audio in, cleaned-up text out. Empty when there was nothing to say.

        Shared by the chunks handed over mid-recording and by the final tail, so
        both get the same treatment.
        """
        seconds = len(audio) / self._cfg.audio.sample_rate

        # Never hand silence to Whisper: with nothing to decode it invents text,
        # typically echoing the vocabulary prompt back. A recording can end up
        # empty whenever a stray noise (a keystroke, a fan) triggers the silence
        # auto-stop before any word was actually said.
        if not has_speech(audio, self._cfg.audio.sample_rate):
            log.info("No speech in %.1fs of audio, skipping transcription.", seconds)
            return ""

        # Level it out only now, after the speech check: normalising first would
        # amplify a silent recording's noise into apparent speech.
        if self._cfg.audio.auto_gain:
            audio = normalise_level(audio)

        lang = self._cfg.engine.language if self._cfg.engine.language != "auto" else None
        with self._backend_lock:
            backend = self._backend
        result = backend.transcribe(
            audio,
            sample_rate=self._cfg.audio.sample_rate,
            language=lang,
            prompt=self._prompt,
        )
        text = postprocess.collapse_repeats(result.text)
        text = postprocess.apply(text, self._cfg.dictionary.replacements)
        if self._cfg.dictionary.fuzzy:
            text = postprocess.apply_fuzzy(text, self._cfg.dictionary.terms)

        if postprocess.is_prompt_echo(text, self._cfg.dictionary.terms):
            # Faint noise got through the speech check and the model answered with
            # the vocabulary list instead of a transcription.
            log.info("Discarded a hallucinated echo of the vocabulary prompt.")
            log.debug("Discarded text: %r", text)
            return ""

        log.info("Transcribed %.1fs of audio into %d chars in %.1fs.",
                 seconds, len(text), result.elapsed_s or 0)
        log.debug("Transcription text: %r", text)
        return text

    def _transcribe_chunk(self, audio: np.ndarray) -> None:
        """Transcribe a slice handed over while the user is still talking.

        Runs on the same single worker as the final tail, so the pieces can only
        be appended in the order they were spoken. A chunk that fails is logged
        and skipped rather than losing the whole dictation.
        """
        try:
            text = self._transcribe(audio)
            if text:
                self._partials.append(text)
        except Exception:
            log.exception("Error transcribing a chunk; continuing with the rest.")

    def _transcribe_and_inject(self, audio: np.ndarray) -> None:
        try:
            parts = list(self._partials)
            self._partials.clear()

            # A short tail is normal when chunking: the shortcut was released just
            # after a cut. Only complain if there is nothing at all.
            min_samples = int(self._cfg.audio.sample_rate * _MIN_AUDIO_S)
            tail = self._transcribe(audio) if len(audio) >= min_samples else ""
            if tail:
                parts.append(tail)

            text = " ".join(p.strip() for p in parts if p.strip())
            if not text:
                log.info("Nothing to transcribe.")
                self._notify_user("empty", "Nothing to transcribe", "I didn't hear any speech.")
                return

            self._injector.inject(text)
            self._notify_user("done", "Done", f"{len(text)} characters pasted at the cursor.")
        except Exception:
            log.exception("Error during transcription.")
            sounds.error(self._cfg.feedback.sound)
            self._notify_user("error", "Transcription failed", "See logs/stt.log for details.")
        finally:
            self._partials.clear()
            self._force_state(State.IDLE)

    def stop(self) -> None:
        self._hotkeys.stop()
        self._backend.close()
        self._executor.shutdown(wait=False)
        self._notifier.shutdown(wait=False)


__all__ = ["Controller", "State"]
