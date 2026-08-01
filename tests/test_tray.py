"""Shutdown behaviour of the tray icon.

"Quit does nothing" was the worst bug of the lot, so the ordering it depends on is
pinned down here. pystray itself is not involved: a fake stands in for the icon.
"""

import pytest

pytest.importorskip("PIL")  # the icon is drawn with Pillow

from s2f.ui.tray import TrayIcon  # noqa: E402  (must come after importorskip)


class FakeIcon:
    def __init__(self, log):
        self._log = log
        self.stopped = False

    def stop(self):
        self.stopped = True
        self._log.append("icon.stop")

    def update_menu(self):
        pass


def _tray(on_quit, log):
    tray = TrayIcon(
        current_toggle=lambda: "ctrl+alt+d", current_ptt=lambda: "ctrl+alt+f",
        on_set_hotkey=lambda *a: None, on_quit=on_quit, on_help=lambda: None,
        on_toggle_auto_stop=lambda: None, is_auto_stop=lambda: True,
        on_open_config=lambda: None, on_open_usage=lambda: None,
        on_set_engine=lambda n: None, current_engine=lambda: "local",
        on_set_api_key=lambda: None, on_set_sound=lambda m: None,
        current_sound=lambda: "off", on_toggle_overlay=lambda: None,
        overlay_enabled=lambda: True, on_edit_terms=lambda: None,
        on_set_microphone=lambda n: None, current_microphone=lambda: "auto",
        current_gesture=lambda: "ctrl+windows",
        current_mode=lambda: "separate", on_set_mode=lambda m: None,
        on_set_language=lambda c: None, current_language=lambda: "auto",
    )
    tray._icon = FakeIcon(log)
    return tray


class TestQuit:
    def test_icon_goes_away_before_the_cleanup(self):
        """Cleaning up first would leave the icon on screen for as long as closing
        the model and the worker pools takes, which reads as "Quit did nothing"."""
        log = []
        tray = _tray(lambda: log.append("on_quit"), log)
        tray._handle_quit()
        assert log == ["icon.stop", "on_quit"]

    def test_a_failing_cleanup_still_removes_the_icon(self):
        log = []

        def _boom():
            log.append("on_quit")
            raise RuntimeError("backend refused to close")

        tray = _tray(_boom, log)
        tray._handle_quit()          # must not propagate
        assert tray._icon.stopped
        assert log == ["icon.stop", "on_quit"]

    def test_quit_before_the_icon_exists(self):
        tray = _tray(lambda: None, [])
        tray._icon = None
        tray._handle_quit()          # no icon yet: must not raise
