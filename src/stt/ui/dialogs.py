"""Native Windows dialogs for a friendlier configuration experience.

- ``message_box``: simple notice (ctypes, no dependencies).
- ``ask_api_key``: prompts for the API key in a text field (tkinter, stdlib).
- ``edit_terms``: editor for the custom-words list (tkinter, stdlib).
- ``build_hotkey``: composes a shortcut from modifiers + one key (tkinter, stdlib).

**Every** window here runs on its own thread, via ``_dialog``. Opened straight from
a tray menu callback, a window is created inside the menu's modal message loop and
Windows leaves it unable to process input: it draws, but neither its buttons nor
its close button respond. Its own thread gives it its own message pump. That also
means none of them can return a value — they take an ``on_save`` callback.
"""

from __future__ import annotations

import gc
import logging
import threading
from collections.abc import Callable, Sequence

from stt.ui import known_combos, release_default_root

log = logging.getLogger(__name__)


def message_box(title: str, text: str, *, error: bool = False) -> None:
    """Show a notice on its own thread. If no GUI is available, log it instead.

    The dedicated thread is not an optimisation, it is what makes the dialog
    usable: called straight from a tray menu callback, ``MessageBoxW`` would be
    created inside the menu's own modal message loop, and Windows then leaves it
    unable to process clicks — the box appears but neither OK nor the close
    button respond. On its own thread it gets its own message pump.
    """

    def _show() -> None:
        try:
            import ctypes

            # MB_ICONERROR (0x10) or MB_ICONINFORMATION (0x40),
            # MB_SETFOREGROUND (0x10000) | MB_TOPMOST (0x40000).
            flags = (0x10 if error else 0x40) | 0x10000 | 0x40000
            ctypes.windll.user32.MessageBoxW(0, text, title, flags)
        except Exception:
            log.info("%s: %s", title, text)

    threading.Thread(target=_show, daemon=True, name="stt-msgbox").start()


def _force_foreground(root) -> None:
    """Force keyboard focus onto ``root`` even when opened from the tray menu.

    Windows enforces a foreground-lock timeout that silently ignores
    ``SetForegroundWindow`` calls from a process that wasn't already in the
    foreground (which is exactly our case: the window is created from a tray
    icon callback). Without this, the dialog is drawn on top but never
    receives keyboard input. Briefly attaching our input queue to the current
    foreground thread's is the standard workaround.
    """
    try:
        import ctypes

        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        root.update_idletasks()
        hwnd = user32.GetParent(root.winfo_id()) or root.winfo_id()
        fg_hwnd = user32.GetForegroundWindow()
        cur_thread = kernel32.GetCurrentThreadId()
        fg_thread = user32.GetWindowThreadProcessId(fg_hwnd, None) if fg_hwnd else 0
        attached = False
        if fg_thread and fg_thread != cur_thread:
            attached = bool(user32.AttachThreadInput(fg_thread, cur_thread, True))
        user32.SetForegroundWindow(hwnd)
        if attached:
            user32.AttachThreadInput(fg_thread, cur_thread, False)
    except Exception:
        log.debug("Could not force the dialog to the foreground.", exc_info=True)


def _dialog(title: str, build: Callable[[object], None], *, thread_name: str) -> None:
    """Run a Tk dialog on its own thread, cradle to grave.

    ``build`` receives the root window and fills it in. It runs on that thread,
    which is the only one allowed to touch the window afterwards.

    Returns as soon as the thread is started, so the tray menu is never blocked
    while a dialog is open — and, more importantly, the window is not created
    inside the menu's modal loop, where it could not process input at all.
    """

    def _run() -> None:
        try:
            import tkinter as tk
        except Exception:
            log.exception("tkinter unavailable: cannot open the %r dialog.", title)
            return

        root = None
        try:
            root = tk.Tk()
            root.title(title)
            root.attributes("-topmost", True)
            build(root)
            _force_foreground(root)
            root.mainloop()
        except Exception:
            log.exception("Error in the %r dialog.", title)
        finally:
            if root is not None:
                try:
                    root.destroy()
                except Exception:
                    pass
                # This thread owns the Tk interpreter's whole lifecycle, its
                # finalisation included: Tcl aborts if that happens on another
                # thread. See release_default_root and stt.ui.overlay.
                release_default_root(root)
            root = None
            gc.collect()

    threading.Thread(target=_run, daemon=True, name=thread_name).start()


def ask_api_key(on_save: Callable[[str], None]) -> None:
    """Ask for the OpenAI API key and hand it to ``on_save``."""

    def _build(root) -> None:
        import tkinter as tk

        root.resizable(False, False)
        tk.Label(root, text="Paste your OpenAI API key:",
                 font=("Segoe UI", 10)).pack(anchor="w", padx=16, pady=(14, 6))

        value = tk.StringVar()
        entry = tk.Entry(root, textvariable=value, show="•", width=48,
                         font=("Consolas", 10), relief="solid", borderwidth=1)
        entry.pack(fill="x", padx=16)

        note = tk.Label(root, text="It is stored in the Windows credential manager, "
                                   "never in a file.",
                        font=("Segoe UI", 9), fg="#666", anchor="w", justify="left",
                        wraplength=380)
        note.pack(fill="x", padx=16, pady=(6, 0))

        buttons = tk.Frame(root)
        buttons.pack(fill="x", padx=16, pady=14)
        save_btn = tk.Button(buttons, text="Save", width=12, state="disabled")
        tk.Button(buttons, text="Cancel", width=12,
                  command=root.destroy).pack(side="right", padx=(8, 0))
        save_btn.pack(side="right")

        def _refresh(*_args) -> None:
            key = value.get().strip()
            save_btn.config(state="normal" if key else "disabled")
            if key and not key.startswith("sk-"):
                note.config(text="Keys normally start with 'sk-' — check you pasted "
                                 "the whole thing.", fg="#8a5000")
            else:
                note.config(text="It is stored in the Windows credential manager, "
                                 "never in a file.", fg="#666")

        def _save(*_args) -> None:
            key = value.get().strip()
            if not key:
                return
            root.destroy()
            try:
                on_save(key)
            except Exception:
                log.exception("Error saving the API key.")

        save_btn.config(command=_save)
        value.trace_add("write", _refresh)
        root.bind("<Return>", _save)
        root.bind("<Escape>", lambda _e: root.destroy())
        entry.focus_set()

    _dialog("OpenAI API key", _build, thread_name="stt-apikey")


_TERMS_HELP = (
    "One name per line. These are passed to Whisper as context so it spells them\n"
    "the way you write them here — client names, people, products, jargon.\n"
    "Keep the list short (a dozen or so): it is a hint, and a long list dilutes it."
)


def edit_terms(current: Sequence[str], on_save: Callable[[list[str]], None]) -> None:
    """Open the custom-words editor. Calls ``on_save`` with the new list."""

    def _build(root) -> None:
        import tkinter as tk

        root.geometry("470x420")
        root.minsize(380, 300)

        tk.Label(root, text=_TERMS_HELP, justify="left", anchor="w",
                 font=("Segoe UI", 9), fg="#444").pack(fill="x", padx=14, pady=(12, 8))

        box = tk.Text(root, font=("Consolas", 11), undo=True,
                      relief="solid", borderwidth=1)
        box.pack(fill="both", expand=True, padx=14)
        box.insert("1.0", "\n".join(current))

        status = tk.Label(root, text="", font=("Segoe UI", 9), fg="#7a1f1f", anchor="w")
        status.pack(fill="x", padx=14)

        def _save() -> None:
            terms = [line.strip() for line in box.get("1.0", "end").splitlines()]
            terms = [t for t in terms if t]
            # A quoted term would have to be escaped through TOML and adds
            # nothing: reject it here where the user can still see why.
            if any('"' in t or "\\" in t for t in terms):
                status.config(text='Quotes and backslashes are not allowed in a term.')
                return
            root.destroy()
            try:
                on_save(terms)
            except Exception:
                log.exception("Error saving the custom words.")

        buttons = tk.Frame(root)
        buttons.pack(fill="x", padx=14, pady=12)
        tk.Button(buttons, text="Save", width=12, command=_save).pack(side="right")
        tk.Button(buttons, text="Cancel", width=12,
                  command=root.destroy).pack(side="right", padx=(0, 8))
        box.focus_set()

    _dialog("Custom words", _build, thread_name="stt-terms")


# --- shortcut builder -------------------------------------------------------

# Modifiers offered, in the canonical order a combination is written in.
_MODIFIERS: tuple[tuple[str, str], ...] = (
    ("ctrl", "Ctrl"), ("alt", "Alt"), ("shift", "Shift"), ("windows", "Win"),
)

# Keys offered as the final key: label shown -> name the "keyboard" library uses.
_KEYS: tuple[tuple[str, str], ...] = (
    *[(c, c.lower()) for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"],
    *[(d, d) for d in "0123456789"],
    *[(f"F{i}", f"f{i}") for i in range(1, 13)],
    ("Space", "space"), ("Enter", "enter"), ("Tab", "tab"),
    ("Insert", "insert"), ("Delete", "delete"),
    ("Home", "home"), ("End", "end"),
    ("Page up", "page up"), ("Page down", "page down"),
    ("Up", "up"), ("Down", "down"), ("Left", "left"), ("Right", "right"),
)
_KEY_BY_LABEL = dict(_KEYS)
_LABEL_BY_KEY = {k: label for label, k in _KEYS}

# Keys that work on their own because no one types them by accident.
_STANDALONE = frozenset(f"f{i}" for i in range(1, 25))

_SUGGESTIONS = "Suggested, free and easy on the left hand: Ctrl+Alt+A · S · Z · X · Q"


def _combo_note(mods: list[str], key: str) -> tuple[str, str]:
    """Judge a combination: returns ``(severity, message)``.

    ``severity`` is ``"blocked"`` (Windows keeps the combination, so it would
    never work), ``"warn"`` (usable but it already means something) or ``""``.
    """
    combo = "+".join([*mods, key])
    known = known_combos.describe(combo)
    if known is not None:
        tier, what = known
        if tier == "reserved":
            return "blocked", f"Windows reserves this one for {what}: it would never reach the app."
        return "warn", (f"Heads up: this is usually {what}. The other app still gets "
                        "the keystroke, so both things would happen.")

    # Generic caveats, for combinations not on the list.
    if "ctrl" in mods and "alt" in mods and (key.isdigit() or key == "e"):
        return "warn", ("Careful: on a Spanish keyboard Ctrl+Alt is AltGr, so this "
                        "also fires when typing @ # ~ € …")
    if "windows" in mods:
        return "warn", "Careful: Windows claims most Win+key combinations."
    if {"ctrl", "shift"} <= set(mods) and len(mods) == 2:
        return "warn", ("Heads up: editors and browsers use most of Ctrl+Shift, and "
                        "the other app still receives the keystroke.")
    return "", ""


def build_hotkey(
    title: str,
    current: str,
    taken: str,
    on_save: Callable[[str], None],
) -> None:
    """Compose a shortcut from tick boxes plus one key, and hand it to ``on_save``.

    Deliberately not a live capture: reading the real keystroke meant suspending
    the global hotkeys and fighting the tray's modal loop, which was fragile.
    Picking the parts is just as flexible and cannot get stuck.

    ``taken`` is the combination the other mode uses, rejected inline here.
    """

    def _build(root) -> None:
        import tkinter as tk
        from tkinter import ttk

        parts = [p.strip().lower() for p in current.split("+") if p.strip()]
        current_mods = {m for m, _ in _MODIFIERS if m in parts}
        current_key = parts[-1] if parts else ""

        root.resizable(False, False)

        tk.Label(root, text="Tick the modifiers and choose a key:",
                 font=("Segoe UI", 10)).grid(row=0, column=0, columnspan=4,
                                             sticky="w", padx=16, pady=(14, 8))

        mod_vars: dict[str, tk.BooleanVar] = {}
        row = tk.Frame(root)
        row.grid(row=1, column=0, columnspan=4, sticky="w", padx=16)
        for name, label in _MODIFIERS:
            var = tk.BooleanVar(value=name in current_mods)
            mod_vars[name] = var
            tk.Checkbutton(row, text=label, variable=var,
                           font=("Segoe UI", 10)).pack(side="left", padx=(0, 12))

        key_row = tk.Frame(root)
        key_row.grid(row=2, column=0, columnspan=4, sticky="w", padx=16, pady=(10, 0))
        tk.Label(key_row, text="Key:", font=("Segoe UI", 10)).pack(side="left")
        key_var = tk.StringVar(value=_LABEL_BY_KEY.get(current_key, ""))
        key_box = ttk.Combobox(key_row, textvariable=key_var, state="readonly",
                               width=12, values=[label for label, _ in _KEYS])
        key_box.pack(side="left", padx=8)

        preview = tk.Label(root, text="", font=("Consolas", 15, "bold"), fg="#205089")
        preview.grid(row=3, column=0, columnspan=4, padx=16, pady=(16, 2))
        note = tk.Label(root, text="", font=("Segoe UI", 9), fg="#8a5000",
                        wraplength=430, justify="left")
        note.grid(row=4, column=0, columnspan=4, sticky="w", padx=16)
        tk.Label(root, text=_SUGGESTIONS, font=("Segoe UI", 9), fg="#666",
                 wraplength=430, justify="left").grid(
            row=5, column=0, columnspan=4, sticky="w", padx=16, pady=(6, 0))

        buttons = tk.Frame(root)
        buttons.grid(row=6, column=0, columnspan=4, sticky="e", padx=16, pady=14)
        save_btn = tk.Button(buttons, text="Save", width=12, state="disabled")
        tk.Button(buttons, text="Cancel", width=12,
                  command=root.destroy).pack(side="right", padx=(8, 0))
        save_btn.pack(side="right")

        def _combo() -> str:
            mods = [m for m, _ in _MODIFIERS if mod_vars[m].get()]
            key = _KEY_BY_LABEL.get(key_var.get(), "")
            return "+".join([*mods, key]) if key else ""

        def _refresh(*_args) -> None:
            mods = [m for m, _ in _MODIFIERS if mod_vars[m].get()]
            key = _KEY_BY_LABEL.get(key_var.get(), "")
            combo = _combo()
            preview.config(text=" + ".join(
                p.capitalize() for p in combo.split("+")) if combo else "—")

            if not key:
                note.config(text="Choose a key.", fg="#7a1f1f")
                save_btn.config(state="disabled")
                return
            if not mods and key not in _STANDALONE:
                note.config(text="Add at least one modifier, or the shortcut would "
                                 "fire while you type.", fg="#7a1f1f")
                save_btn.config(state="disabled")
                return
            if combo == taken:
                note.config(text="That combination is already used by the other "
                                 "mode.", fg="#7a1f1f")
                save_btn.config(state="disabled")
                return
            severity, message = _combo_note(mods, key)
            note.config(text=message,
                        fg="#7a1f1f" if severity == "blocked" else "#8a5000")
            save_btn.config(state="disabled" if severity == "blocked" else "normal")

        def _save() -> None:
            combo = _combo()
            root.destroy()
            try:
                on_save(combo)
            except Exception:
                log.exception("Error applying the shortcut %r.", combo)

        save_btn.config(command=_save)
        for var in mod_vars.values():
            var.trace_add("write", _refresh)
        key_var.trace_add("write", _refresh)
        _refresh()

        key_box.focus_set()

    _dialog(f"Shortcut for {title}", _build, thread_name="stt-hotkey")


__all__ = ["message_box", "ask_api_key", "edit_terms", "build_hotkey"]
