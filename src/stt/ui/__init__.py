"""User interface: system tray icon, dialogs, floating status pill and help pages."""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)


def release_default_root(root) -> None:
    """Clear tkinter's module-level reference to ``root`` after destroying it.

    tkinter remembers the first ``Tk`` instance ever created in
    ``tkinter._default_root`` and never clears it, not even on ``destroy()``.
    Left dangling, CPython finalises that interpreter from the main thread when
    the process exits — and Tcl aborts on it: *"Tcl_AsyncDelete: async handler
    deleted by the wrong thread"*. For windows created outside the main thread
    (our dialogs and the status pill) that turns into a crash on quit.
    """
    try:
        import tkinter

        if getattr(tkinter, "_default_root", None) is root:
            tkinter._default_root = None
    except Exception:
        log.debug("Could not clear tkinter's default root.", exc_info=True)


__all__ = ["release_default_root"]
