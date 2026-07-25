"""System tray icon (a microphone) with a colour state indicator and a menu.

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

# Languages offered in the menu. Not the ninety-nine Whisper knows: the ones worth
# one click, with any other ISO-639-1 code still settable in config.toml.
_LANGUAGES: tuple[tuple[str, str], ...] = (
    ("auto", "Detect automatically"),
    ("es", "Español"),
    ("en", "English"),
    ("fr", "Français"),
    ("de", "Deutsch"),
    ("it", "Italiano"),
    ("pt", "Português"),
)

# Sound modes offered in the menu: config value -> label.
_SOUND_LABELS: tuple[tuple[str, str], ...] = (
    ("system", "Windows sounds (soft)"),
    ("beeps", "Beeps (loud)"),
    ("off", "Silent"),
)


def _fmt_combo(combo: str) -> str:
    """Human-friendly label, e.g. 'ctrl+alt+space' -> 'Ctrl + Alt + Space'."""
    return " + ".join(part.capitalize() for part in combo.split("+"))


def _make_image(color: tuple[int, int, int]):
    """Draw a microphone silhouette in ``color`` on a transparent 64x64 canvas.

    Windows renders tray icons at 16x16 (more at high DPI), so the shape is kept
    deliberately chunky: a capsule, a thick U bracket and a stem. Thinner
    details (a base bar, a grille) turn to mush once downscaled.
    """
    from PIL import Image, ImageDraw

    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    fill = color + (255,)
    draw.rounded_rectangle([25, 2, 39, 38], radius=7, fill=fill)   # capsule
    draw.arc([13, 18, 51, 56], start=0, end=180, fill=fill, width=8)  # bracket
    draw.rectangle([29, 54, 35, 62], fill=fill)                    # stem
    return img


class TrayIcon:
    def __init__(
        self,
        *,
        current_toggle: Callable[[], str],
        current_ptt: Callable[[], str],
        on_set_hotkey: Callable[[str, Callable[[], None]], None],
        on_quit: Callable[[], None],
        on_help: Callable[[], None],
        on_toggle_auto_stop: Callable[[], None],
        is_auto_stop: Callable[[], bool],
        on_open_config: Callable[[], None],
        on_open_usage: Callable[[], None],
        on_set_engine: Callable[[str], None],
        current_engine: Callable[[], str],
        on_set_api_key: Callable[[], None],
        on_set_sound: Callable[[str], None],
        current_sound: Callable[[], str],
        on_toggle_overlay: Callable[[], None],
        overlay_enabled: Callable[[], bool],
        on_edit_terms: Callable[[], None],
        on_set_microphone: Callable[[str], None],
        current_microphone: Callable[[], str],
        on_set_language: Callable[[str], None],
        current_language: Callable[[], str],
        current_gesture: Callable[[], str],
        current_mode: Callable[[], str],
        on_set_mode: Callable[[str], None],
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
        self._on_set_sound = on_set_sound
        self._current_sound = current_sound
        self._on_toggle_overlay = on_toggle_overlay
        self._overlay_enabled = overlay_enabled
        self._on_edit_terms = on_edit_terms
        self._on_set_microphone = on_set_microphone
        self._current_microphone = current_microphone
        self._on_set_language = on_set_language
        self._current_language = current_language
        self._current_gesture = current_gesture
        self._current_mode = current_mode
        self._on_set_mode = on_set_mode
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

        # One place for everything about triggering dictation: the mode on top,
        # and below it only the combinations that mode actually uses.
        def _in_mode(name: str):
            return lambda item: self._current_mode() == name

        shortcuts_menu = pystray.Menu(
            pystray.MenuItem(
                "One shortcut: hold to talk, tap twice for hands-free",
                lambda icon, item: self._handle_set_mode("gesture"),
                checked=_in_mode("gesture"), radio=True,
            ),
            pystray.MenuItem(
                "Two shortcuts: one to toggle, one to hold",
                lambda icon, item: self._handle_set_mode("separate"),
                checked=_in_mode("separate"), radio=True,
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                lambda item: f"Shortcut: {_fmt_combo(self._current_gesture())}…",
                lambda icon, item: self._handle_set_hotkey("gesture"),
                visible=_in_mode("gesture"),
            ),
            pystray.MenuItem(
                lambda item: f"Toggle dictation: {_fmt_combo(self._current_toggle())}…",
                lambda icon, item: self._handle_set_hotkey("toggle"),
                visible=_in_mode("separate"),
            ),
            pystray.MenuItem(
                lambda item: f"Push-to-talk: {_fmt_combo(self._current_ptt())}…",
                lambda icon, item: self._handle_set_hotkey("push_to_talk"),
                visible=_in_mode("separate"),
            ),
        )

        feedback_menu = pystray.Menu(
            *[self._sound_item(value, label) for value, label in _SOUND_LABELS],
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "Floating status pill",
                self._handle_toggle_overlay,
                checked=lambda item: self._overlay_enabled(),
            ),
        )

        menu = pystray.Menu(
            pystray.MenuItem(lambda item: self._shortcut_summary(), None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "Auto-stop on silence",
                self._handle_toggle_auto,
                checked=lambda item: self._is_auto_stop(),
            ),
            pystray.MenuItem("Change shortcut", shortcuts_menu),
            pystray.MenuItem("Microphone", self._microphone_menu()),
            pystray.MenuItem("Language", self._language_menu()),
            pystray.MenuItem("Feedback", feedback_menu),
            pystray.MenuItem("Custom words…", self._handle_edit_terms),
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
            title=self._tooltip("idle"),
            menu=menu,
        )

    def _shortcut_summary(self) -> str:
        """The line at the top of the menu: how to dictate, right now."""
        if self._current_mode() == "gesture":
            combo = _fmt_combo(self._current_gesture())
            return f"Hold {combo} to talk · tap twice for hands-free"
        return (f"Toggle: {_fmt_combo(self._current_toggle())} · "
                f"Hold: {_fmt_combo(self._current_ptt())}")

    def _language_menu(self):
        """Radio list of languages. Forcing the wrong one makes Whisper translate
        rather than fail, which is confusing enough to deserve a menu."""
        import pystray

        def _item(code: str, label: str):
            return pystray.MenuItem(
                label,
                lambda icon, item: self._handle_set_language(code),
                checked=lambda item: self._current_language() == code,
                radio=True,
            )

        return pystray.Menu(*[_item(code, label) for code, label in _LANGUAGES])

    def _microphone_menu(self):
        """Radio list of the available microphones, built once at startup.

        Plugging a headset in later will not show up until the app restarts:
        pystray takes its item list when the menu is created.
        """
        import pystray

        from stt.audio.devices import list_input_devices

        def _item(value: str, label: str):
            return pystray.MenuItem(
                label,
                lambda icon, item: self._handle_set_microphone(value),
                checked=lambda item: self._current_microphone() == value,
                radio=True,
            )

        items = [_item("auto", "Windows default"), pystray.Menu.SEPARATOR]
        for dev in list_input_devices():
            label = dev.name if len(dev.name) <= 46 else dev.name[:45] + "…"
            items.append(_item(dev.name, f"{label} (default)" if dev.is_default else label))
        return pystray.Menu(*items)

    def _sound_item(self, value: str, label: str):
        """One radio item of the sound-mode selector."""
        import pystray

        return pystray.MenuItem(
            label,
            lambda icon, item: self._handle_set_sound(value),
            checked=lambda item: self._current_sound() == value,
            radio=True,
        )

    # Handlers accept the (icon, item) pystray passes; we ignore them.
    def _handle_toggle_auto(self, *args) -> None:
        try:
            self._on_toggle_auto_stop()
        except Exception:
            log.exception("Error toggling auto-stop.")
        if self._icon is not None:
            self._icon.update_menu()

    def _handle_set_sound(self, mode: str) -> None:
        try:
            self._on_set_sound(mode)
        except Exception:
            log.exception("Error changing the sound mode.")
        self.refresh()

    def _handle_edit_terms(self, *args) -> None:
        try:
            self._on_edit_terms()
        except Exception:
            log.exception("Error opening the custom-words editor.")

    def _handle_set_language(self, code: str) -> None:
        try:
            self._on_set_language(code)
        except Exception:
            log.exception("Error switching language.")
        self.refresh()

    def _handle_set_microphone(self, name: str) -> None:
        try:
            self._on_set_microphone(name)
        except Exception:
            log.exception("Error switching microphone.")
        self.refresh()

    def _handle_toggle_overlay(self, *args) -> None:
        try:
            self._on_toggle_overlay()
        except Exception:
            log.exception("Error toggling the status pill.")
        self.refresh()

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

    def _handle_set_mode(self, mode: str) -> None:
        try:
            self._on_set_mode(mode)
        except Exception:
            log.exception("Error switching shortcut mode.")
        self.refresh()

    def _handle_set_hotkey(self, which: str) -> None:
        """Open the shortcut builder for one mode. The menu refreshes when it saves."""
        try:
            self._on_set_hotkey(which, self.refresh)
        except Exception:
            log.exception("Error opening the shortcut builder.")

    def refresh(self) -> None:
        """Re-render the menu (e.g. after a hotkey or engine change)."""
        if self._icon is not None:
            self._icon.update_menu()

    def _handle_quit(self, *args) -> None:
        """Take the icon down first, then shut everything else down.

        Order matters: pressing Quit must make the app disappear at once. Closing
        the backend and the worker pools first would leave the icon sitting there
        for as long as that takes, which reads as "Quit does nothing".
        """
        self.stop()
        try:
            self._on_quit()
        except Exception:
            log.exception("Error while shutting down.")

    def set_state(self, state: str) -> None:
        """Update the icon colour and tooltip based on the state."""
        if self._icon is None:
            return
        img = self._images.get(state)
        if img is not None:
            self._icon.icon = img
        self._icon.title = self._tooltip(state)

    def _tooltip(self, state: str) -> str:
        """Hover text: the state plus what to press next (silent feedback)."""
        label = _LABELS.get(state, state)
        combo = _fmt_combo(self._current_toggle())
        if state == "idle":
            return f"STT — {label} · press {combo} to dictate"
        if state == "recording":
            return f"STT — {label} · press {combo} to stop"
        return f"STT — {label}"

    def run(self) -> None:
        """Blocking: start the tray event loop (main thread)."""
        self._build()
        self._icon.run()

    def stop(self) -> None:
        if self._icon is not None:
            self._icon.stop()


__all__ = ["TrayIcon"]
