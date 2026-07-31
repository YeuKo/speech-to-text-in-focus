from stt import hotkey
from stt.config import HotkeyConfig

# Scan codes, which is what the manager resolves modifiers by.
_CTRL, _WIN = 29, 91


class _Keyboard:
    """Just the two constants ``_track_gesture`` reads off the module."""

    KEY_DOWN = "down"
    KEY_UP = "up"


class _Event:
    def __init__(self, scan_code: int, event_type: str) -> None:
        self.name = "whatever"      # deliberately useless: scan codes decide
        self.scan_code = scan_code
        self.event_type = event_type


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


def _send(mgr, *events) -> None:
    for scan_code, event_type in events:
        mgr._track_gesture(_Keyboard, _Event(scan_code, event_type))


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
            _send(mgr, (_CTRL, "down"), (_WIN, "down"))
            assert calls == ["start"]
            _send(mgr, (_WIN, "up"), (_CTRL, "up"))
            assert calls == ["start", "stop"]
        finally:
            hotkey._is_down = original

    def test_ctrl_alone_does_not_start_after_a_lost_release(self):
        """The reported bug: Ctrl on its own starting a recording."""
        mgr, calls = _manager()
        pressed = {"ctrl": True, "windows": True}
        original = _with_keyboard_state(pressed)
        try:
            _send(mgr, (_CTRL, "down"), (_WIN, "down"))
            calls.clear()
            # Windows swallows the release of the Windows key (a lock screen, a
            # UAC prompt), so only Ctrl's arrives.
            _send(mgr, (_CTRL, "up"))
            pressed["windows"] = False      # it is up; the hook simply never heard
            assert calls == ["stop"]

            # Ctrl on its own would have completed the gesture from the record.
            calls.clear()
            _send(mgr, (_CTRL, "down"))
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
            _send(mgr, (_CTRL, "down"), (_WIN, "down"))
            assert calls == ["start"]
            calls.clear()

            # Both keys let go where the hook cannot see it.
            pressed["ctrl"] = pressed["windows"] = False
            # Any later key event is enough to notice.
            _send(mgr, (_CTRL, "down"))
            assert calls == ["stop"]
        finally:
            hotkey._is_down = original

    def test_a_key_win32_cannot_answer_for_is_trusted(self):
        """Non-modifiers report None, and the event record has to stand."""
        mgr, calls = _manager()
        original = _with_keyboard_state({})      # every lookup returns None
        try:
            _send(mgr, (_CTRL, "down"), (_WIN, "down"))
            assert calls == ["start"]
        finally:
            hotkey._is_down = original


class TestCanonicalKey:
    def test_scan_code_beats_a_localised_name(self):
        assert hotkey.canonical_key("windows izquierda", _WIN) == "windows"
        assert hotkey.canonical_key("control", _CTRL) == "ctrl"

    def test_name_is_used_without_a_scan_code(self):
        assert hotkey.canonical_key("left windows") == "windows"
        assert hotkey.canonical_key("mayúsculas") == "shift"
