"""Atajos de teclado globales (toggle y push-to-talk).

Esbozo de Fase 0: define el registro de los dos atajos y los callbacks. La
implementación con la librería ``keyboard`` (Windows) se completa en el MVP.

- Toggle: una pulsación dispara ``on_toggle`` (alterna grabación).
- Push-to-talk: ``on_ptt_press`` al pulsar y ``on_ptt_release`` al soltar.
"""

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
        self._registered = False

    def start(self) -> None:
        """Registra los atajos globales."""
        raise NotImplementedError(
            "Pendiente Fase 1: registrar con keyboard.add_hotkey (toggle) y "
            "keyboard.on_press_key/on_release_key (push-to-talk)."
        )

    def stop(self) -> None:
        """Libera los atajos registrados."""
        if not self._registered:
            return
        raise NotImplementedError("Pendiente Fase 1: keyboard.remove_all_hotkeys().")


__all__ = ["HotkeyManager"]
