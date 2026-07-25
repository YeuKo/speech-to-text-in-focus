"""Global keyboard shortcuts.

Two ways to trigger dictation, and only one is live at a time (``hotkey.mode``):

- ``separate``: one combination per mode, toggle and push-to-talk.
- ``gesture``: a single combination whose *gesture* picks the mode — hold it to
  talk, tap it twice for hands-free.

Registering only the chosen mode is deliberate. With both live, a user who set up
a gesture would still have two other combinations doing something else, and no
way to tell which one acted. See stt.gesture for the state machine; this module
only turns key events into presses and releases.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import TYPE_CHECKING

from stt.gesture import GestureRecogniser

if TYPE_CHECKING:
    from stt.config import HotkeyConfig

log = logging.getLogger(__name__)


def canonical_key(name: str | None) -> str:
    """Strip the side off a key name: "left windows" -> "windows".

    Keyboards report the physical key, configurations name the logical one.
    """
    key = (name or "").lower().strip()
    for side in ("left ", "right "):
        if key.startswith(side):
            return key[len(side):]
    return key


class HotkeyManager:
    def __init__(
        self,
        config: "HotkeyConfig",
        *,
        on_toggle: Callable[[], None],
        on_ptt_press: Callable[[], None],
        on_ptt_release: Callable[[], None],
    ) -> None:
        self._cfg = config
        self._on_toggle = on_toggle
        self._on_ptt_press = on_ptt_press
        self._on_ptt_release = on_ptt_release
        self._hook = None
        self._ptt_active = False

        parts = self._cfg.push_to_talk.lower().split("+")
        self._ptt_trigger = parts[-1]
        self._ptt_modifiers = parts[:-1]

        # The gesture reuses the controller's own actions: its "start" is a
        # push-to-talk press, and both of its ways of finishing are a release.
        gesture = self._cfg.gesture if self._cfg.mode == "gesture" else ""
        self._gesture_keys = [canonical_key(k) for k in gesture.split("+") if k.strip()]
        self._gesture_held = False
        self._down: set[str] = set()
        self._gesture = GestureRecogniser(
            on_start=_safe(on_ptt_press),
            on_stop=_safe(on_ptt_release),
            hold_ms=self._cfg.gesture_hold_ms,
            double_ms=self._cfg.gesture_double_ms,
        ) if self._gesture_keys else None

    def _mods_held(self) -> bool:
        import keyboard
        return all(keyboard.is_pressed(m) for m in self._ptt_modifiers)

    def start(self) -> None:
        import keyboard

        if self._cfg.mode == "separate":
            keyboard.add_hotkey(self._cfg.toggle, _safe(self._on_toggle), suppress=False)

        def _hook(event: keyboard.KeyboardEvent) -> None:
            self._track_gesture(keyboard, event)

            if self._cfg.mode != "separate":
                return
            if event.name != self._ptt_trigger:
                return
            if event.event_type == keyboard.KEY_DOWN and self._mods_held():
                if not self._ptt_active:
                    self._ptt_active = True
                    _safe(self._on_ptt_press)()
            elif event.event_type == keyboard.KEY_UP and self._ptt_active:
                self._ptt_active = False
                _safe(self._on_ptt_release)()

        self._hook = keyboard.hook(_hook)
        if self._gesture is not None:
            log.info("Shortcut registered — gesture: %s (hold to talk, double-tap "
                     "for hands-free)", self._cfg.gesture)
        else:
            log.info("Shortcuts registered — toggle: %s | push-to-talk: %s",
                     self._cfg.toggle, self._cfg.push_to_talk)

    def _track_gesture(self, keyboard, event) -> None:
        """Turn "all the gesture's keys are down" into presses and releases.

        The set of held keys is built from the events themselves rather than
        asked of ``keyboard.is_pressed``: that call depends on the library
        resolving names like "windows" to the right scan codes, which is exactly
        the layer most likely to differ between keyboards. What arrives in the
        event is what the keyboard actually sent.

        Checked on every event rather than bound as a hotkey because the gesture
        is usually two modifiers with no ordinary key — which the hotkey
        machinery does not handle — and the timing needs the moment of release.
        """
        if self._gesture is None:
            return

        name = canonical_key(event.name)
        if event.event_type == keyboard.KEY_DOWN:
            self._down.add(name)
        else:
            self._down.discard(name)

        held = all(key in self._down for key in self._gesture_keys)
        if held and not self._gesture_held:
            self._gesture_held = True
            self._gesture.press(time.monotonic())
        elif not held and self._gesture_held:
            self._gesture_held = False
            self._gesture.release(time.monotonic())

    def stop(self) -> None:
        import keyboard
        if self._gesture is not None:
            self._gesture.cancel()
            self._gesture_held = False
            self._down.clear()
        try:
            keyboard.remove_all_hotkeys()
            if self._hook:
                keyboard.unhook(self._hook)
        except Exception as exc:
            log.debug("Error releasing hotkeys: %s", exc)
        self._hook = None


def _safe(fn: Callable[[], None]) -> Callable[[], None]:
    """Prevent an error in the callback from killing the keyboard listener."""
    def wrapper() -> None:
        try:
            fn()
        except Exception:
            log.exception("Error in hotkey callback.")
    return wrapper


__all__ = ["HotkeyManager", "canonical_key"]
