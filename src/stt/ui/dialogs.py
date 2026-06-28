"""Diálogos nativos de Windows para una configuración más amable.

- ``message_box``: aviso modal sencillo (ctypes, sin dependencias).
- ``ask_api_key``: pide la API key en un cuadro de texto (tkinter, stdlib).
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)


def message_box(title: str, text: str, *, error: bool = False) -> None:
    """Muestra un cuadro de mensaje modal. Si no hay GUI, lo registra en el log."""
    try:
        import ctypes

        # MB_ICONERROR (0x10) o MB_ICONINFORMATION (0x40), MB_SYSTEMMODAL (0x1000).
        flags = (0x10 if error else 0x40) | 0x1000
        ctypes.windll.user32.MessageBoxW(0, text, title, flags)
    except Exception:
        log.info("%s: %s", title, text)


def ask_api_key() -> str | None:
    """Pide la API key con un diálogo. Devuelve la key (sin espacios) o None."""
    try:
        import tkinter as tk
        from tkinter import simpledialog

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        value = simpledialog.askstring(
            "OpenAI API key",
            "Paste your OpenAI API key (starts with 'sk-'):",
            show="*",
            parent=root,
        )
        root.destroy()
        return value.strip() if value else None
    except Exception:
        log.exception("No se pudo abrir el diálogo de API key.")
        return None


__all__ = ["message_box", "ask_api_key"]
