"""Floating status pill: silent, at-a-glance feedback while dictating.

A small borderless window in a corner of the screen (next to the tray by default),
coloured by state, that goes away on its own. Unlike a Windows notification it
leaves nothing behind in the Action Center, which is what makes it bearable dozens
of times a day.

Tk is not thread-safe, so the window lives entirely on one dedicated thread: that
thread creates it, runs its event loop and is the only one that touches it. Other
threads just drop commands into a queue. Everything here is best-effort: if Tk is
unavailable or anything fails, dictation carries on without the pill.
"""

from __future__ import annotations

import gc
import logging
import queue
import threading

from stt.config import OVERLAY_POSITIONS
from stt.ui import release_default_root

log = logging.getLogger(__name__)

# Accent colour per event kind.
_ACCENTS: dict[str, str] = {
    "loading": "#5a7ca8",       # muted blue: starting up
    "ready": "#43a047",         # green
    "recording": "#dc3c3c",     # red
    "transcribing": "#e0a528",  # orange
    "done": "#43a047",
    "empty": "#5a7ca8",
    "error": "#dc3c3c",
}
_DEFAULT_ACCENT = "#5a7ca8"
_BG = "#1f232b"
_FG = "#f2f4f8"

# Kinds that describe a finished action: they hide themselves after a moment.
# The others (recording, transcribing) stay until the next event replaces them.
_AUTO_HIDE_MS: dict[str, int] = {
    "done": 1400, "empty": 1800, "error": 4000, "ready": 2500,
}

_POLL_MS = 60      # how often the Tk thread drains the command queue
_MARGIN = 16       # gap from the edge of the work area, in pixels

_DEFAULT_POSITION = "bottom-right"   # next to the tray, where the state it reports lives


def _work_area(fallback_w: int, fallback_h: int) -> tuple[int, int, int, int]:
    """Desktop rectangle excluding the taskbar, as (left, top, right, bottom)."""
    try:
        import ctypes
        from ctypes import wintypes

        rect = wintypes.RECT()
        # SPI_GETWORKAREA = 0x0030
        if ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0):
            return rect.left, rect.top, rect.right, rect.bottom
    except Exception:
        log.debug("Could not read the work area; using the full screen.", exc_info=True)
    return 0, 0, fallback_w, fallback_h


def _corner(position: str, w: int, h: int, area: tuple[int, int, int, int]) -> tuple[int, int]:
    """Top-left coordinates that place a w x h pill in the requested corner."""
    left, top, right, bottom = area
    x = left + _MARGIN if position.endswith("left") else right - w - _MARGIN
    y = top + _MARGIN if position.startswith("top") else bottom - h - _MARGIN
    return x, y


def _make_non_activating(root) -> None:
    """Stop the pill from ever taking focus.

    Critical, not cosmetic: the transcription is pasted into whatever window has
    focus, so a status window that steals it would paste into itself.
    """
    try:
        import ctypes

        user32 = ctypes.windll.user32
        hwnd = user32.GetParent(root.winfo_id()) or root.winfo_id()
        # GWL_EXSTYLE = -20, WS_EX_NOACTIVATE = 0x08000000, WS_EX_TOOLWINDOW = 0x80
        style = user32.GetWindowLongW(hwnd, -20)
        user32.SetWindowLongW(hwnd, -20, style | 0x08000000 | 0x80)
    except Exception:
        log.debug("Could not mark the pill as non-activating.", exc_info=True)


class StatusOverlay:
    """Thread-safe handle to the pill. Starts its Tk thread on first use."""

    def __init__(self, position: str = _DEFAULT_POSITION) -> None:
        self._commands: queue.Queue[tuple] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._failed = False
        self._position = position if position in OVERLAY_POSITIONS else _DEFAULT_POSITION

    # --- public API (safe from any thread) ----------------------------------

    def show(self, kind: str, text: str) -> None:
        """Display ``text`` with the accent of ``kind``."""
        if self._ensure_started():
            self._commands.put(("show", kind, text))

    def hide(self) -> None:
        self._commands.put(("hide",))

    def stop(self) -> None:
        self._commands.put(("stop",))

    # --- internals ----------------------------------------------------------

    def _ensure_started(self) -> bool:
        """Start the Tk thread on first use. False if it is unusable."""
        with self._lock:
            if self._failed:
                return False
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(
                    target=self._run, daemon=True, name="stt-overlay"
                )
                self._thread.start()
            return True

    def _run(self) -> None:
        try:
            import tkinter as tk
        except Exception:
            self._failed = True
            log.warning("tkinter is unavailable: no floating status pill.", exc_info=True)
            return

        try:
            root = tk.Tk()
        except Exception:
            self._failed = True
            log.warning("Could not create the status pill window.", exc_info=True)
            return

        root.withdraw()
        root.overrideredirect(True)   # no title bar, no taskbar button
        root.attributes("-topmost", True)
        root.attributes("-alpha", 0.95)
        root.configure(bg=_DEFAULT_ACCENT)

        label = tk.Label(
            root, text="", bg=_BG, fg=_FG,
            font=("Segoe UI", 11), padx=16, pady=9, anchor="w",
        )
        # The accent shows through as a thick left edge and a hairline border.
        label.pack(fill="both", expand=True, padx=(6, 1), pady=1)
        _make_non_activating(root)

        state = {"hide_job": None, "transient": False}

        def _cancel_hide() -> None:
            if state["hide_job"] is not None:
                try:
                    root.after_cancel(state["hide_job"])
                except Exception:
                    pass
                state["hide_job"] = None

        def _hide() -> None:
            _cancel_hide()
            state["transient"] = False
            root.withdraw()

        def _show(kind: str, text: str) -> None:
            _cancel_hide()
            root.configure(bg=_ACCENTS.get(kind, _DEFAULT_ACCENT))
            label.config(text=text)
            # Size and place it while still hidden. Moving it after deiconify()
            # does not take: an overrideredirect window maps at +0+0 and keeps
            # that position, which is why the pill used to appear in the
            # top-left corner instead of by the tray.
            root.update_idletasks()
            w, h = root.winfo_reqwidth(), root.winfo_reqheight()
            area = _work_area(root.winfo_screenwidth(), root.winfo_screenheight())
            x, y = _corner(self._position, w, h, area)
            root.geometry(f"{w}x{h}+{x}+{y}")
            root.deiconify()
            root.attributes("-topmost", True)   # reassert: other windows may have jumped ahead
            log.debug("Status pill at %s (%s).", root.winfo_geometry(), self._position)

            delay = _AUTO_HIDE_MS.get(kind)
            state["transient"] = delay is not None
            if delay is not None:
                state["hide_job"] = root.after(delay, _hide)

        def _poll() -> None:
            stopping = False
            try:
                while True:
                    cmd = self._commands.get_nowait()
                    if cmd[0] == "show":
                        _show(cmd[1], cmd[2])
                    elif cmd[0] == "hide":
                        # A finished-state pill keeps its moment on screen.
                        if not state["transient"]:
                            _hide()
                    elif cmd[0] == "stop":
                        stopping = True
            except queue.Empty:
                pass
            except Exception:
                log.debug("Error updating the status pill.", exc_info=True)

            if stopping:
                root.quit()
                return
            root.after(_POLL_MS, _poll)

        root.after(_POLL_MS, _poll)
        try:
            root.mainloop()
        except Exception:
            log.debug("The status pill loop ended with an error.", exc_info=True)
        finally:
            try:
                root.destroy()
            except Exception:
                pass
            # This thread must own the Tk interpreter's whole lifecycle, its
            # finalisation included (see release_default_root). Tk widgets hold
            # each other (master <-> children), so destroy() alone leaves a
            # reference cycle that only the cyclic collector can break — and that
            # would run on whichever thread triggers it, normally the main one at
            # exit, which Tcl aborts on. So drop the references and collect here.
            release_default_root(root)
            root = label = None
            gc.collect()


__all__ = ["StatusOverlay"]
