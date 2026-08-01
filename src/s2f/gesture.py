"""One shortcut, two gestures: hold to talk, tap twice for hands-free.

Remembering two combinations and deciding the mode *before* speaking is the part
of dictation that never becomes second nature. With this, the gesture decides:

    press ── held ─────────── release ──▶ push-to-talk: stop and transcribe
      │
      └── released quickly ──┬── pressed again within double_ms ──▶ hands-free,
                             │       recording until the next press
                             └── nothing else ──▶ a short dictation: transcribe

Recording starts on the very first press, before it is known which gesture this
will turn out to be, so the start of a sentence is never lost.

Deliberately free of keyboard and clock: the time arrives as an argument and the
delay goes through an injected scheduler, so the whole thing can be tested
without pressing a key or sleeping.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable

log = logging.getLogger(__name__)

# What the recogniser is waiting for.
_IDLE = "idle"
_HOLDING = "holding"              # pressed, might become a hold or a tap
_WAITING_SECOND = "waiting"       # tapped once, a second tap turns it hands-free
_HANDS_FREE = "hands-free"        # recording until the next press


def _default_scheduler(delay_s: float, fn: Callable[[], None]) -> Callable[[], None]:
    timer = threading.Timer(delay_s, fn)
    timer.daemon = True
    timer.start()
    return timer.cancel


class GestureRecogniser:
    """Turns presses and releases of one combination into start/stop calls."""

    def __init__(
        self,
        *,
        on_start: Callable[[], None],
        on_stop: Callable[[], None],
        hold_ms: int = 250,
        double_ms: int = 350,
        scheduler: Callable[[float, Callable[[], None]], Callable[[], None]] | None = None,
    ) -> None:
        self._on_start = on_start
        self._on_stop = on_stop
        self._hold_s = hold_ms / 1000
        self._double_s = double_ms / 1000
        self._schedule = scheduler or _default_scheduler

        self._lock = threading.RLock()
        self._state = _IDLE
        self._pressed_at = 0.0
        self._cancel_wait: Callable[[], None] | None = None

    @property
    def state(self) -> str:
        return self._state

    @property
    def is_recording(self) -> bool:
        return self._state != _IDLE

    def press(self, now: float) -> None:
        with self._lock:
            if self._state == _IDLE:
                self._state = _HOLDING
                self._pressed_at = now
                self._on_start()
            elif self._state == _WAITING_SECOND:
                # The second tap: keep the recording going, hands free now.
                self._cancel_pending()
                self._state = _HANDS_FREE
                log.debug("Hands-free: recording until the next press.")
            elif self._state == _HANDS_FREE:
                self._state = _IDLE
                self._on_stop()
            # _HOLDING again is the keyboard auto-repeating: ignore.

    def release(self, now: float) -> None:
        with self._lock:
            if self._state != _HOLDING:
                return          # releases in hands-free mode mean nothing
            if now - self._pressed_at >= self._hold_s:
                self._state = _IDLE
                self._on_stop()
                return
            # Too short to be a hold. It is either a one-tap dictation or the
            # first half of a double tap; the recording continues either way.
            self._state = _WAITING_SECOND
            self._cancel_wait = self._schedule(self._double_s, self._second_never_came)

    def cancel(self) -> None:
        """Forget any gesture in progress, without stopping anything."""
        with self._lock:
            self._cancel_pending()
            self._state = _IDLE

    def _second_never_came(self) -> None:
        with self._lock:
            if self._state != _WAITING_SECOND:
                return
            self._cancel_wait = None
            self._state = _IDLE
        self._on_stop()

    def _cancel_pending(self) -> None:
        if self._cancel_wait is not None:
            try:
                self._cancel_wait()
            except Exception:
                log.debug("Could not cancel the double-tap timer.", exc_info=True)
            self._cancel_wait = None


__all__ = ["GestureRecogniser"]
