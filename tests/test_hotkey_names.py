"""Key names arrive in the system's language; configurations are written in one.

This is what made the gesture shortcut silently never fire: on a Spanish Windows
the library reports "windows izquierda", which never matched the configured
"windows". Scan codes are the fix — they are the same on every PC keyboard — so
the cases below are taken from a real Spanish machine's --debug-keys output.
"""

import pytest

from stt.hotkey import canonical_key


class TestSpanishWindows:
    """Exactly what --debug-keys printed on the machine where it failed."""

    @pytest.mark.parametrize(("reported", "scan", "expected"), [
        ("windows izquierda", 91, "windows"),
        ("ctrl", 29, "ctrl"),
        ("mayusculas", 42, "shift"),
        ("S", 31, "s"),
    ])
    def test_reported_names_become_configuration_names(self, reported, scan, expected):
        assert canonical_key(reported, scan) == expected

    def test_the_gesture_now_matches(self):
        held = {canonical_key("ctrl", 29), canonical_key("windows izquierda", 91)}
        assert all(key in held for key in ("ctrl", "windows"))


class TestEnglishWindows:
    @pytest.mark.parametrize(("reported", "scan", "expected"), [
        ("left windows", 91, "windows"),
        ("right ctrl", 29, "ctrl"),
        ("shift", 54, "shift"),
        ("alt", 56, "alt"),
    ])
    def test_still_works(self, reported, scan, expected):
        assert canonical_key(reported, scan) == expected


class TestWithoutAScanCode:
    """Configured names are parsed with no event behind them."""

    @pytest.mark.parametrize(("written", "expected"), [
        ("windows", "windows"),
        ("Ctrl", "ctrl"),
        ("left windows", "windows"),
        ("windows izquierda", "windows"),
        ("mayusculas", "shift"),
        ("espacio", "space"),
        ("f9", "f9"),
        ("", ""),
    ])
    def test_normalised_by_name_alone(self, written, expected):
        assert canonical_key(written) == expected

    def test_none_is_survivable(self):
        assert canonical_key(None) == ""


class TestOrdinaryKeys:
    def test_a_letter_keeps_its_name_whatever_the_scan_code(self):
        """Letters move with the layout, so only modifiers go by scan code."""
        assert canonical_key("q", 16) == "q"
        assert canonical_key("ñ", 39) == "ñ"

    def test_an_unknown_name_is_left_alone(self):
        assert canonical_key("play/pause media", 0) == "play/pause media"
