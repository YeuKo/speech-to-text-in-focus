"""Native Windows dialogs for a friendlier configuration experience.

- ``message_box``: simple modal notice (ctypes, no dependencies).
- ``ask_api_key``: prompts for the API key in a text field (tkinter, stdlib).
"""

from __future__ import annotations

import logging
import re

log = logging.getLogger(__name__)

# tkinter keysym -> "keyboard" library modifier name.
_MOD_KEYSYMS = {
    "Control_L": "ctrl", "Control_R": "ctrl",
    "Alt_L": "alt", "Alt_R": "alt", "Meta_L": "alt", "Meta_R": "alt",
    "Shift_L": "shift", "Shift_R": "shift",
    "Super_L": "windows", "Super_R": "windows", "Win_L": "windows", "Win_R": "windows",
}
# tkinter keysym -> "keyboard" library key name (for non-trivial keys).
_KEY_KEYSYMS = {
    "Return": "enter", "Escape": "esc", "Tab": "tab", "space": "space",
    "BackSpace": "backspace", "Delete": "delete", "Insert": "insert",
    "Prior": "page up", "Next": "page down", "Home": "home", "End": "end",
    "Up": "up", "Down": "down", "Left": "left", "Right": "right",
}
_MOD_ORDER = ("ctrl", "alt", "shift", "windows")


def _key_name(keysym: str) -> str:
    """Map a tkinter keysym for a non-modifier key to a 'keyboard' name."""
    if keysym in _KEY_KEYSYMS:
        return _KEY_KEYSYMS[keysym]
    if len(keysym) == 1:
        return keysym.lower()
    if re.fullmatch(r"F\d{1,2}", keysym):
        return keysym.lower()
    return keysym.lower()


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


def capture_hotkey() -> str | None:
    """Open a small window that listens for a key combination and returns it.

    The user presses the desired combo (e.g. Ctrl+Alt+R); it is shown live and
    confirmed with Save. Returns the combination as a "keyboard" string
    (e.g. "ctrl+alt+r") or None if cancelled.
    """
    try:
        import tkinter as tk
    except Exception:
        log.exception("tkinter unavailable for hotkey capture.")
        return None

    held: list[str] = []
    captured: dict[str, str | None] = {"combo": None}

    root = tk.Tk()
    root.title("Set shortcut")
    root.attributes("-topmost", True)
    root.geometry("400x160")
    root.resizable(False, False)

    tk.Label(root, text="Press the desired key combination…",
             font=("Segoe UI", 10)).pack(pady=(20, 6))
    combo_var = tk.StringVar(value="—")
    tk.Label(root, textvariable=combo_var, font=("Consolas", 14, "bold")).pack(pady=4)

    buttons = tk.Frame(root)
    buttons.pack(pady=12)
    save_btn = tk.Button(buttons, text="Save", width=10, state="disabled",
                         command=root.destroy)
    cancel_btn = tk.Button(buttons, text="Cancel", width=10,
                           command=lambda: (captured.update(combo=None), root.destroy()))
    save_btn.grid(row=0, column=0, padx=6)
    cancel_btn.grid(row=0, column=1, padx=6)

    def _refresh() -> None:
        if captured["combo"]:
            combo_var.set(captured["combo"])
        elif held:
            combo_var.set(" + ".join(held) + " + …")
        else:
            combo_var.set("—")

    def on_press(event) -> str:
        ks = event.keysym
        if ks in _MOD_KEYSYMS:
            name = _MOD_KEYSYMS[ks]
            if name not in held:
                held.append(name)
            _refresh()
            return "break"
        trigger = _key_name(ks)
        if trigger:
            mods = [m for m in _MOD_ORDER if m in held]
            captured["combo"] = "+".join(mods + [trigger])
            save_btn.config(state="normal")
            _refresh()
        return "break"

    def on_release(event) -> str:
        ks = event.keysym
        if ks in _MOD_KEYSYMS and _MOD_KEYSYMS[ks] in held:
            held.remove(_MOD_KEYSYMS[ks])
            _refresh()
        return "break"

    root.bind("<KeyPress>", on_press)
    root.bind("<KeyRelease>", on_release)
    root.protocol("WM_DELETE_WINDOW", lambda: (captured.update(combo=None), root.destroy()))
    root.focus_force()
    root.mainloop()
    return captured["combo"]


__all__ = ["message_box", "ask_api_key", "capture_hotkey"]
