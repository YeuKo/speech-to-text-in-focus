"""Inyección de texto en la ventana con foco (portapapeles + Ctrl+V)."""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from stt.config import InjectionConfig

log = logging.getLogger(__name__)


class TextInjector:
    def __init__(self, config: "InjectionConfig") -> None:
        self._cfg = config

    def inject(self, text: str) -> None:
        if not text:
            return
        if self._cfg.method == "clipboard":
            self._inject_clipboard(text)
        else:
            self._inject_typing(text)

    def _inject_clipboard(self, text: str) -> None:
        import keyboard
        import pyperclip

        previous: str | None = None
        if self._cfg.restore_clipboard:
            try:
                previous = pyperclip.paste()
            except Exception as exc:
                log.debug("No se pudo leer el portapapeles previo: %s", exc)

        try:
            pyperclip.copy(text)
            time.sleep(self._cfg.paste_delay_ms / 1000)
            keyboard.send("ctrl+v")
            log.info("Pegado: %d caracteres.", len(text))
        finally:
            if previous is not None:
                time.sleep(0.15)  # esperar a que el Ctrl+V aterrice antes de restaurar
                try:
                    pyperclip.copy(previous)
                except Exception as exc:
                    log.debug("No se pudo restaurar el portapapeles: %s", exc)

    def _inject_typing(self, text: str) -> None:
        import keyboard
        keyboard.write(text, delay=0.008)
        log.info("Tecleado: %d caracteres.", len(text))


__all__ = ["TextInjector"]
