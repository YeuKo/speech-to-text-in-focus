"""System tray icon with a colour state indicator and a menu.

- blue   -> idle
- red    -> recording
- orange -> transcribing

``run()`` is blocking (it starts the tray event loop) and must be called on the
main thread. ``set_state()`` is safe to call from other threads.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

log = logging.getLogger(__name__)

# RGB per state (key = State.value)
_COLORS: dict[str, tuple[int, int, int]] = {
    "idle": (90, 120, 160),          # greyish blue
    "recording": (220, 60, 60),      # red
    "transcribing": (235, 165, 40),  # orange
}

_LABELS: dict[str, str] = {
    "idle": "Idle",
    "recording": "Recording…",
    "transcribing": "Transcribing…",
}


def _make_image(color: tuple[int, int, int]):
    from PIL import Image, ImageDraw

    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse([6, 6, size - 6, size - 6], fill=color + (255,))
    return img


class TrayIcon:
    def __init__(
        self,
        *,
        current_toggle: Callable[[], str],
        current_ptt: Callable[[], str],
        on_set_hotkey: Callable[[str], None],
        on_quit: Callable[[], None],
        on_help: Callable[[], None],
        on_toggle_auto_stop: Callable[[], None],
        is_auto_stop: Callable[[], bool],
        on_open_config: Callable[[], None],
        on_open_usage: Callable[[], None],
        on_set_engine: Callable[[str], None],
        current_engine: Callable[[], str],
        on_set_api_key: Callable[[], None],
    ) -> None:
        self._current_toggle = current_toggle
        self._current_ptt = current_ptt
        self._on_set_hotkey = on_set_hotkey
        self._on_quit = on_quit
        self._on_help = on_help
        self._on_toggle_auto_stop = on_toggle_auto_stop
        self._is_auto_stop = is_auto_stop
        self._on_open_config = on_open_config
        self._on_open_usage = on_open_usage
        self._on_set_engine = on_set_engine
        self._current_engine = current_engine
        self._on_set_api_key = on_set_api_key
        self._icon = None
        self._images = {state: _make_image(rgb) for state, rgb in _COLORS.items()}

    def _build(self):
        import pystray

        engine_menu = pystray.Menu(
            pystray.MenuItem(
                "Local (free, on-device)",
                lambda icon, item: self._handle_set_engine("local"),
                checked=lambda item: self._current_engine() == "local",
                radio=True,
            ),
            pystray.MenuItem(
                "OpenAI API (needs key)",
                lambda icon, item: self._handle_set_engine("openai"),
                checked=lambda item: self._current_engine() == "openai",
                radio=True,
            ),
        )

        shortcuts_menu = pystray.Menu(
            pystray.MenuItem(
                lambda item: f"Change toggle ({self._current_toggle()})…",
                lambda icon, item: self._handle_set_hotkey("toggle"),
            ),
            pystray.MenuItem(
                lambda item: f"Change push-to-talk ({self._current_ptt()})…",
                lambda icon, item: self._handle_set_hotkey("push_to_talk"),
            ),
        )

        menu = pystray.Menu(
            pystray.MenuItem(lambda item: f"Toggle dictation: {self._current_toggle()}",
                             None, enabled=False),
            pystray.MenuItem(lambda item: f"Push-to-talk: {self._current_ptt()}",
                             None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "Auto-stop on silence",
                self._handle_toggle_auto,
                checked=lambda item: self._is_auto_stop(),
            ),
            pystray.MenuItem("Change shortcut", shortcuts_menu),
            pystray.MenuItem("Engine", engine_menu),
            pystray.MenuItem("Set OpenAI API key…", self._handle_set_key),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Open config file", self._handle_open_config),
            pystray.MenuItem("Usage / cost", self._handle_open_usage),
            pystray.MenuItem("Help / Instructions", self._handle_help),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", self._handle_quit),
        )
        self._icon = pystray.Icon(
            "stt",
            icon=self._images["idle"],
            title="STT — Idle",
            menu=menu,
        )

    # Handlers accept the (icon, item) pystray passes; we ignore them.
    def _handle_toggle_auto(self, *args) -> None:
        try:
            self._on_toggle_auto_stop()
        except Exception:
            log.exception("Error toggling auto-stop.")
        if self._icon is not None:
            self._icon.update_menu()

    def _handle_help(self, *args) -> None:
        try:
            self._on_help()
        except Exception:
            log.exception("Error opening help.")

    def _handle_open_config(self, *args) -> None:
        try:
            self._on_open_config()
        except Exception:
            log.exception("Error opening the config file.")

    def _handle_open_usage(self, *args) -> None:
        try:
            self._on_open_usage()
        except Exception:
            log.exception("Error opening the usage report.")

    def _handle_set_engine(self, name: str) -> None:
        try:
            self._on_set_engine(name)
        except Exception:
            log.exception("Error switching engine.")
        if self._icon is not None:
            self._icon.update_menu()

    def _handle_set_key(self, *args) -> None:
        try:
            self._on_set_api_key()
        except Exception:
            log.exception("Error saving the API key.")

    def _handle_set_hotkey(self, which: str) -> None:
        try:
            self._on_set_hotkey(which)
        except Exception:
            log.exception("Error capturing the hotkey.")
        self.refresh()

    def refresh(self) -> None:
        """Re-render the menu (e.g. after a hotkey or engine change)."""
        if self._icon is not None:
            self._icon.update_menu()

    def _handle_quit(self, *args) -> None:
        try:
            self._on_quit()
        finally:
            self.stop()

    def set_state(self, state: str) -> None:
        """Update the icon colour and tooltip based on the state."""
        if self._icon is None:
            return
        img = self._images.get(state)
        if img is not None:
            self._icon.icon = img
        self._icon.title = f"STT — {_LABELS.get(state, state)}"

    def run(self) -> None:
        """Blocking: start the tray event loop (main thread)."""
        self._build()
        self._icon.run()

    def stop(self) -> None:
        if self._icon is not None:
            self._icon.stop()


__all__ = ["TrayIcon"]
