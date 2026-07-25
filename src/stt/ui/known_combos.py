"""What a key combination already does, so the user is warned before taking it.

Deliberately a short, static list: the aim is to catch the combinations everybody
knows — the ones whose collision would be obvious in hindsight — not to model
every application's keymap. Two tiers:

- ``RESERVED``: Windows intercepts these, so the app would never even see them.
- ``COMMON``: widely used. The app does not swallow the keystroke, so the other
  application still acts on it: pressing Ctrl+S to dictate would also save.

Nothing here is a hard rule beyond the reserved ones; the builder shows the note
and lets the user decide.
"""

from __future__ import annotations

# Canonical order in which a combination is written.
_MOD_ORDER = ("ctrl", "alt", "shift", "windows")

RESERVED: dict[str, str] = {
    "ctrl+alt+delete": "the Windows security screen",
    "ctrl+shift+escape": "the Task Manager",
    "ctrl+alt+tab": "the window switcher",
    "alt+tab": "switching windows",
    "alt+f4": "closing the active window",
    "windows+l": "locking the session",
    "windows+tab": "Task View",
}

COMMON: dict[str, str] = {
    # The universal editing set.
    "ctrl+a": "Select all",
    "ctrl+b": "Bold, or the bookmarks bar in browsers",
    "ctrl+c": "Copy",
    "ctrl+d": "Bookmark the page, or duplicate",
    "ctrl+e": "Jump to the search box",
    "ctrl+f": "Find",
    "ctrl+g": "Find next",
    "ctrl+h": "History in browsers, Replace in editors",
    "ctrl+i": "Italic",
    "ctrl+j": "Downloads",
    "ctrl+k": "Insert a link, or search",
    "ctrl+l": "Jump to the address bar",
    "ctrl+n": "New window",
    "ctrl+o": "Open",
    "ctrl+p": "Print",
    "ctrl+r": "Reload",
    "ctrl+s": "Save",
    "ctrl+t": "New tab",
    "ctrl+u": "Underline, or view source",
    "ctrl+v": "Paste",
    "ctrl+w": "Close the tab",
    "ctrl+x": "Cut",
    "ctrl+y": "Redo",
    "ctrl+z": "Undo",
    "ctrl+tab": "Next tab",
    "ctrl+enter": "Send, in mail and chat apps",
    "ctrl+space": "Autocomplete in editors, or switch input language",
    # Browsers and editors, second tier.
    "ctrl+shift+c": "Inspect element",
    "ctrl+shift+d": "Duplicate, or the debug panel",
    "ctrl+shift+e": "The file explorer in VS Code",
    "ctrl+shift+f": "Find in files",
    "ctrl+shift+g": "Source control in VS Code",
    "ctrl+shift+i": "Developer tools",
    "ctrl+shift+j": "The developer console",
    "ctrl+shift+k": "Delete line in VS Code",
    "ctrl+shift+l": "Select every occurrence in VS Code",
    "ctrl+shift+m": "The problems panel in VS Code",
    "ctrl+shift+n": "New incognito window",
    "ctrl+shift+o": "Go to symbol, or the bookmark manager",
    "ctrl+shift+p": "The command palette, or a private window",
    "ctrl+shift+s": "Save as",
    "ctrl+shift+t": "Reopen the last closed tab",
    "ctrl+shift+v": "Paste without formatting",
    "ctrl+shift+w": "Close the window",
    "ctrl+shift+x": "Extensions in VS Code",
    "ctrl+shift+z": "Redo",
    # Alt.
    "alt+left": "Back",
    "alt+right": "Forward",
    "alt+d": "Jump to the address bar",
    "alt+enter": "Properties, or full screen",
    "alt+space": "The window menu",
    # Windows key: the system acts on these too.
    "windows+a": "Quick settings",
    "windows+d": "Show the desktop",
    "windows+e": "File Explorer",
    "windows+g": "The Game Bar",
    "windows+h": "Windows' own voice typing",
    "windows+i": "Settings",
    "windows+p": "Project / second screen",
    "windows+r": "Run",
    "windows+s": "Search",
    "windows+v": "Clipboard history",
    "windows+x": "The quick link menu",
    # Function keys.
    "f1": "Help",
    "f2": "Rename",
    "f3": "Find next",
    "f5": "Refresh",
    "f6": "Cycle panes, or the address bar",
    "f7": "Caret browsing in browsers",
    "f11": "Full screen",
    "f12": "Developer tools",
}


def normalise(combo: str) -> str:
    """Rewrite a combination with its modifiers in canonical order."""
    parts = [p.strip().lower() for p in combo.split("+") if p.strip()]
    mods = [m for m in _MOD_ORDER if m in parts]
    keys = [p for p in parts if p not in _MOD_ORDER]
    return "+".join(mods + keys)


def describe(combo: str) -> tuple[str, str] | None:
    """Return ``(tier, what_it_does)`` for a known combination, else None.

    ``tier`` is ``"reserved"`` (Windows keeps it) or ``"common"``.
    """
    key = normalise(combo)
    if key in RESERVED:
        return "reserved", RESERVED[key]
    if key in COMMON:
        return "common", COMMON[key]
    return None


__all__ = ["COMMON", "RESERVED", "describe", "normalise"]
