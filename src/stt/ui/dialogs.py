"""Native Windows dialogs for a friendlier configuration experience.

- ``message_box``: simple modal notice (ctypes, no dependencies).
- ``ask_api_key``: prompts for the API key in a text field (tkinter, stdlib).
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)


def message_box(title: str, text: str, *, error: bool = False) -> None:
    """Show a modal message box. If no GUI is available, log it instead."""
    try:
        import ctypes

        # MB_ICONERROR (0x10) or MB_ICONINFORMATION (0x40), MB_SYSTEMMODAL (0x1000).
        flags = (0x10 if error else 0x40) | 0x1000
        ctypes.windll.user32.MessageBoxW(0, text, title, flags)
    except Exception:
        log.info("%s: %s", title, text)


def ask_api_key() -> str | None:
    """Prompt for the API key with a dialog. Returns the key (stripped) or None."""
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
        log.exception("Could not open the API key dialog.")
        return None


__all__ = ["message_box", "ask_api_key"]
