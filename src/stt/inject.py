"""Inyección de texto en la ventana con foco.

Esbozo de Fase 0: define la interfaz. La implementación (Windows) se completa en
el MVP. Por defecto se usa el portapapeles + Ctrl+V (rápido y soporta Unicode/
acentos), restaurando el contenido previo del portapapeles. Alternativa: teclear.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from stt.config import InjectionConfig

log = logging.getLogger(__name__)


class TextInjector:
    def __init__(self, config: "InjectionConfig") -> None:
        self._cfg = config

    def inject(self, text: str) -> None:
        """Inserta ``text`` donde esté el foco del cursor."""
        if not text:
            return
        if self._cfg.method == "clipboard":
            self._inject_clipboard(text)
        else:
            self._inject_typing(text)

    def _inject_clipboard(self, text: str) -> None:
        raise NotImplementedError(
            "Pendiente Fase 1: guardar portapapeles, pyperclip.copy(text), "
            "keyboard.send('ctrl+v'), y restaurar si restore_clipboard."
        )

    def _inject_typing(self, text: str) -> None:
        raise NotImplementedError("Pendiente Fase 1: keyboard.write(text).")


__all__ = ["TextInjector"]
