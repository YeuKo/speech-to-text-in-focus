from stt import hotkey
from stt.config import HotkeyConfig

# Scan codes, which is what the manager resolves modifiers by.
_CTRL, _WIN = 29, 91


class _Keyboard:
    """Just the two constants ``_track_gesture`` reads off the module."""

    KEY_DOWN = "down"
    KEY_UP = "up"


class _Event:
    def __init__(self, scan_code: int, event_type: str, when: float) -> None:
        self.name = "whatever"      # deliberately useless: scan codes decide
        self.scan_code = scan_code
        self.event_type = event_type
        self.time = when            # stamped in the hook, as the library does


def _manager() -> tuple[hotkey.HotkeyManager, list[str]]:
    """A manager wired to the ctrl+windows gesture, plus the log of what it did.

    ``gesture_hold_ms=0`` makes every release count as a hold, so a release stops
    the recording there and then instead of waiting out the double-tap window.
    What is under test here is which key events turn into presses and releases;
    deciding tap from hold is stt.gesture's job and has its own clock.
    """
    calls: list[str] = []
    cfg = HotkeyConfig(mode="gesture", gesture="ctrl+windows", gesture_hold_ms=0)
    mgr = hotkey.HotkeyManager(
        cfg,
        on_toggle=lambda: calls.append("toggle"),
        on_ptt_press=lambda: calls.append("start"),
        on_ptt_release=lambda: calls.append("stop"),
    )
    return mgr, calls


def _send(mgr, *events, at: float = 0.0) -> None:
    """Deliver key events, all stamped at second ``at``.

    The stamp matters as much as the order now: how long a key has been down is
    what tells a lost release from a fast tap.
    """
    for scan_code, event_type in events:
        mgr._track_gesture(_Keyboard, _Event(scan_code, event_type, at))


def _with_keyboard_state(pressed: dict[str, bool]):
    """Replace the Win32 lookup with a dict the test controls."""
    original = hotkey._is_down
    hotkey._is_down = lambda key: pressed.get(key)
    return original


class TestPhantomShortcut:
    """A release the hook never sees used to leave a key held forever."""

    def test_the_gesture_works_normally(self):
        mgr, calls = _manager()
        original = _with_keyboard_state({"ctrl": True, "windows": True})
        try:
            _send(mgr, (_CTRL, "down"), (_WIN, "down"), at=0.0)
            assert calls == ["start"]
            _send(mgr, (_WIN, "up"), (_CTRL, "up"), at=0.5)
            assert calls == ["start", "stop"]
        finally:
            hotkey._is_down = original

    def test_ctrl_alone_does_not_start_after_a_lost_release(self):
        """The reported bug: Ctrl on its own starting a recording."""
        mgr, calls = _manager()
        pressed = {"ctrl": True, "windows": True}
        original = _with_keyboard_state(pressed)
        try:
            _send(mgr, (_CTRL, "down"), (_WIN, "down"), at=0.0)
            calls.clear()
            # Windows swallows the release of the Windows key (a lock screen, a
            # UAC prompt), so only Ctrl's arrives.
            _send(mgr, (_CTRL, "up"), at=0.5)
            pressed["windows"] = False      # it is up; the hook simply never heard
            assert calls == ["stop"]

            # Ctrl on its own would have completed the gesture from the record.
            calls.clear()
            _send(mgr, (_CTRL, "down"), at=30.0)     # back from the lock screen
            assert calls == []
            assert "windows" not in mgr._down
        finally:
            hotkey._is_down = original

    def test_a_recording_ends_when_both_releases_are_lost(self):
        """Locking the screen mid-dictation must not record forever."""
        mgr, calls = _manager()
        pressed = {"ctrl": True, "windows": True}
        original = _with_keyboard_state(pressed)
        try:
            _send(mgr, (_CTRL, "down"), (_WIN, "down"), at=0.0)
            assert calls == ["start"]
            calls.clear()

            # Both keys let go where the hook cannot see it.
            pressed["ctrl"] = pressed["windows"] = False
            # Any later key event is enough to notice.
            _send(mgr, (_CTRL, "down"), at=30.0)
            assert calls == ["stop"]
        finally:
            hotkey._is_down = original

    def test_a_key_win32_cannot_answer_for_is_trusted(self):
        """Non-modifiers report None, and the event record has to stand."""
        mgr, calls = _manager()
        original = _with_keyboard_state({})      # every lookup returns None
        try:
            _send(mgr, (_CTRL, "down"), (_WIN, "down"), at=0.0)
            assert calls == ["start"]
        finally:
            hotkey._is_down = original

    def test_a_tap_already_over_is_not_a_phantom(self):
        """The other reported bug: the shortcut ignoring quick presses.

        The hook hands events over on its own thread, so by the time the press
        is handled the tap can already be finished and Windows honestly reports
        both keys as up. Nothing was lost there — the events are all present —
        and doubting them threw the tap away.
        """
        mgr, calls = _manager()
        original = _with_keyboard_state({"ctrl": False, "windows": False})
        try:
            _send(mgr, (_CTRL, "down"), (_WIN, "down"), at=0.0)
            assert calls == ["start"]
            assert mgr._down == {"ctrl": 0.0, "windows": 0.0}
        finally:
            hotkey._is_down = original

    def test_auto_repeat_does_not_rejuvenate_a_stuck_key(self):
        """A repeat of a key already down must not reset how long it is held."""
        mgr, _calls = _manager()
        original = _with_keyboard_state({"ctrl": True, "windows": True})
        try:
            _send(mgr, (_CTRL, "down"), at=0.0)
            _send(mgr, (_CTRL, "down"), at=5.0)
            assert mgr._down["ctrl"] == 0.0
        finally:
            hotkey._is_down = original


class TestGestureTiming:
    """Key events in, gestures out: the two halves working together.

    stt.gesture is tested on its own with a clock it is handed; what these check
    is that the clock it gets here is the one the keys moved by, not the one the
    callback happens to run at.
    """

    def _manager(self) -> tuple[hotkey.HotkeyManager, list[str]]:
        calls: list[str] = []
        cfg = HotkeyConfig(mode="gesture", gesture="ctrl+windows",
                           gesture_hold_ms=250, gesture_double_ms=500)
        mgr = hotkey.HotkeyManager(
            cfg,
            on_toggle=lambda: calls.append("toggle"),
            on_ptt_press=lambda: calls.append("start"),
            on_ptt_release=lambda: calls.append("stop"),
        )
        return mgr, calls

    def test_two_quick_taps_reach_hands_free(self):
        """The whole gesture, timed the way fingers actually make it."""
        mgr, calls = self._manager()
        # Windows sees nothing held: the taps are over before this code runs.
        original = _with_keyboard_state({"ctrl": False, "windows": False})
        try:
            _send(mgr, (_CTRL, "down"), (_WIN, "down"), at=0.00)
            _send(mgr, (_WIN, "up"), (_CTRL, "up"), at=0.09)      # one tap
            _send(mgr, (_CTRL, "down"), (_WIN, "down"), at=0.31)  # and the second
            assert calls == ["start"]            # one recording, still running
            assert mgr._gesture.state == "hands-free"
        finally:
            hotkey._is_down = original

    def test_a_long_press_is_still_push_to_talk(self):
        mgr, calls = self._manager()
        original = _with_keyboard_state({"ctrl": True, "windows": True})
        try:
            _send(mgr, (_CTRL, "down"), (_WIN, "down"), at=0.0)
            _send(mgr, (_WIN, "up"), (_CTRL, "up"), at=3.0)
            assert calls == ["start", "stop"]
        finally:
            hotkey._is_down = original


class TestCanonicalKey:
    def test_scan_code_beats_a_localised_name(self):
        assert hotkey.canonical_key("windows izquierda", _WIN) == "windows"
        assert hotkey.canonical_key("control", _CTRL) == "ctrl"

    def test_name_is_used_without_a_scan_code(self):
        assert hotkey.canonical_key("left windows") == "windows"
        assert hotkey.canonical_key("mayúsculas") == "shift"
