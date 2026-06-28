"""Global keyboard shortcuts: independent toggle and push-to-talk."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from stt.config import HotkeyConfig

log = logging.getLogger(__name__)


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

    def _mods_held(self) -> bool:
        import keyboard
        return all(keyboard.is_pressed(m) for m in self._ptt_modifiers)

    def start(self) -> None:
        import keyboard

        keyboard.add_hotkey(self._cfg.toggle, _safe(self._on_toggle), suppress=False)

        def _hook(event: keyboard.KeyboardEvent) -> None:
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
        log.info(
            "Hotkeys registered — toggle: %s | push-to-talk: %s",
            self._cfg.toggle,
            self._cfg.push_to_talk,
        )

    def stop(self) -> None:
        import keyboard
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


__all__ = ["HotkeyManager"]
