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


# Windows names its keys in the system's language, so a Spanish machine reports
# "windows izquierda" and "mayusculas" where an English one says "left windows"
# and "shift". Scan codes do not move: these are the same on every PC keyboard,
# and they settle the modifiers without knowing any language.
_MODIFIER_SCAN_CODES: dict[int, str] = {
    29: "ctrl",                 # both control keys
    42: "shift", 54: "shift",   # left and right
    56: "alt",                  # AltGr arrives as ctrl+alt
    91: "windows", 92: "windows",
    58: "caps lock",
}

# Virtual-key codes for the modifiers, to ask Windows whether a key really is
# down. Two for "windows" because the left and right keys are separate keys with
# one name. Only modifiers are listed: the gesture is made of modifiers, and they
# are the ones whose release can go missing.
_MODIFIER_VK: dict[str, tuple[int, ...]] = {
    "ctrl": (0x11,),                # VK_CONTROL
    "shift": (0x10,),               # VK_SHIFT
    "alt": (0x12,),                 # VK_MENU
    "windows": (0x5B, 0x5C),        # VK_LWIN, VK_RWIN
}

# How long a key has to have been down before its being held is worth doubting.
#
# A release that went missing leaves a key down for as long as the user is away —
# seconds, usually much longer. A key pressed a moment ago has lost nothing: what
# looks like a contradiction there is just this code running late (see
# _event_time). Asking Windows about it answers about *now*, and the answer to a
# question about a keypress that has already come and gone is "not pressed" — so
# the check used to throw away perfectly good taps, the quick ones first.
_STALE_AFTER_S = 1.0

# Side markers, in the languages Windows is likely to be running in.
_SIDES = ("left", "right", "izquierda", "derecha", "izq", "der",
          "gauche", "droite", "links", "rechts", "sinistra", "destra")

# The few localised names worth mapping back; anything else keeps its own name.
_KEY_ALIASES: dict[str, str] = {
    "mayusculas": "shift", "mayúsculas": "shift", "may": "shift",
    "control": "ctrl", "ctr": "ctrl",
    "espacio": "space", "entrar": "enter", "intro": "enter",
    "tabulador": "tab", "retroceso": "backspace",
    "suprimir": "delete", "supr": "delete", "insertar": "insert",
    "inicio": "home", "fin": "end",
    "bloq mayus": "caps lock", "bloq mayús": "caps lock",
}


def canonical_key(name: str | None, scan_code: int | None = None) -> str:
    """The language-independent name of a key, as configurations spell it.

    The scan code decides for modifiers, because that is the one thing that does
    not change with the system language. Everything else falls back to the
    reported name, with the side stripped and the common Spanish names mapped.
    """
    if scan_code is not None and scan_code in _MODIFIER_SCAN_CODES:
        return _MODIFIER_SCAN_CODES[scan_code]

    key = (name or "").lower().strip()
    for side in _SIDES:
        if key.startswith(f"{side} "):
            key = key[len(side) + 1:]
            break
        if key.endswith(f" {side}"):
            key = key[: -len(side) - 1]
            break
    return _KEY_ALIASES.get(key, key).strip()


def _event_time(event) -> float:
    """When the key actually moved, not when this code got round to it.

    ``keyboard`` stamps each event inside its low-level hook and then puts it on
    a queue for a second thread to hand out. Between the stamp and the callback
    there is a wait of unknown length — negligible when the app is idle, a good
    fraction of a second while it is transcribing or fading the status pill in.

    Timing a gesture by the clock at the moment of the callback therefore
    stretches it by however busy the app happened to be: a tap of 100 ms could
    measure as 400 and be read as push-to-talk instead. The stamp does not drift
    like that.
    """
    when = getattr(event, "time", None)
    # The same clock the library stamps with (time.time), so the two never mix.
    return float(when) if when is not None else time.time()


def _is_down(key: str) -> bool | None:
    """Ask Windows whether ``key`` is physically down right now.

    None when there is no answer to be had: a key that is not a modifier, or no
    Win32 to ask. The caller then has to trust the events it saw.
    """
    codes = _MODIFIER_VK.get(key)
    if codes is None:
        return None
    try:
        import ctypes

        user32 = ctypes.windll.user32
        # GetAsyncKeyState's high bit is "down at this instant", unlike the low
        # bit, which only says the key was pressed since the last call.
        return any(user32.GetAsyncKeyState(vk) & 0x8000 for vk in codes)
    except Exception:
        return None


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
        # Key -> when it went down, so a key held a long time can be told from
        # one just pressed. Only the first press counts: auto-repeat must not
        # make an old key look young.
        self._down: dict[str, float] = {}
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

        # Nothing was being watched until now, so whatever the user was holding
        # while the shortcuts were suspended is not ours to remember.
        self._down.clear()
        self._gesture_held = False

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

        name = canonical_key(event.name, getattr(event, "scan_code", None))
        when = _event_time(event)
        if event.event_type == keyboard.KEY_DOWN:
            self._down.setdefault(name, when)
        else:
            self._down.pop(name, None)

        # Whenever the record says the gesture is down, make sure it really is.
        # Checked on the way in and while it is held: a missed release means
        # either a shortcut that fires on its own or a recording that never ends,
        # depending on whether it goes missing before or during one.
        held = all(key in self._down for key in self._gesture_keys)
        if held and self._forget_stale(when):
            held = all(key in self._down for key in self._gesture_keys)
        if held and not self._gesture_held:
            self._gesture_held = True
            self._gesture.press(when)
        elif not held and self._gesture_held:
            self._gesture_held = False
            self._gesture.release(when)

    def _forget_stale(self, now: float) -> bool:
        """Drop keys held only on paper, and say whether any had to go.

        ``_down`` is built from the events the hook sees, and a release it never
        sees leaves a key held forever. That happens: locking the screen with
        Win+L, a UAC prompt, Ctrl+Alt+Del or switching virtual desktop all go
        through the secure desktop, where a user-process hook stops receiving
        events — let go of the key over there and nobody sees it come up.

        The cost was a shortcut that fired on its own: with the gesture on
        ctrl+windows and "windows" stuck down, pressing Ctrl alone was enough to
        start recording. Lose both releases mid-dictation — lock the screen while
        talking — and the recording never ends instead. So the record is checked
        against what Windows says is actually pressed.

        Only for keys that have been down a while, though (_STALE_AFTER_S).
        Windows answers about this instant, and a key tapped and let go before
        this code ran is honestly reported as up — which made the check condemn
        the very taps it was meant to protect, and the double tap with them.
        """
        stale = {key for key, since in self._down.items()
                 if now - since >= _STALE_AFTER_S and _is_down(key) is False}
        if not stale:
            return False
        for key in stale:
            del self._down[key]
        log.info(
            "Ignoring a phantom shortcut: %s looked held but is not pressed — a key "
            "release went missing (locking the screen or a system shortcut can eat "
            "one).", ", ".join(sorted(stale)),
        )
        return True

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
