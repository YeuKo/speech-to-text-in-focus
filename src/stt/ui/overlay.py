"""Floating status pill: silent, at-a-glance feedback while dictating.

A small borderless window in a corner of the screen (next to the tray by default),
coloured by state, that goes away on its own. Unlike a Windows notification it
leaves nothing behind in the Action Center, which is what makes it bearable dozens
of times a day.

While recording it draws a row of bars that follow the microphone, so a glance
tells you not just *that* it is listening but that it is hearing **you** — a dead
row of bars is a muted or wrong input device, which used to be invisible until
the transcription came back empty. While transcribing the same bars run a wave of
their own, since there is no longer anything to listen to.

Tk is not thread-safe, so the window lives entirely on one dedicated thread: that
thread creates it, runs its event loop and is the only one that touches it. Other
threads just drop commands into a queue. Everything here is best-effort: if Tk is
unavailable or anything fails, dictation carries on without the pill.
"""

from __future__ import annotations

import gc
import logging
import math
import queue
import threading
from collections.abc import Callable

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

# Kinds that draw the wave, and where its motion comes from.
_LIVE = "recording"          # the microphone
_WORKING = "transcribing"    # nothing to hear: a wave of its own

# Kinds that describe a finished action: they hide themselves after a moment.
# The others (recording, transcribing) stay until the next event replaces them.
_AUTO_HIDE_MS: dict[str, int] = {
    "done": 1400, "empty": 1800, "error": 4000, "ready": 2500,
}

_FRAME_MS = 33     # ~30 fps while the pill is on screen
_IDLE_MS = 80      # while hidden: often enough to pick up the next command
_MARGIN = 16       # gap from the edge of the work area, in pixels

_OPACITY = 0.96
_FADE_IN = 0.22    # opacity added per frame while appearing
_FADE_OUT = 0.12   # and removed per frame while leaving, slower: exits read best soft

# The wave. Bars rather than a curve on purpose: Tk's canvas has no antialiasing,
# so a sine line comes out as a staircase while rectangles are pixel-crisp.
_BARS = 7
_BAR_W = 3
_BAR_GAP = 3
_BAR_MIN_H = 3
_BAR_MARGIN = 9              # clearance above and below the tallest bar
_WAVE_W = _BARS * _BAR_W + (_BARS - 1) * _BAR_GAP
_WAVE_GAP = 11               # between the wave and the text

_PHASE_STEP = 0.42           # how fast the ripple travels
_BAR_PHASE = 0.7             # phase offset between neighbouring bars
_SMOOTHING = 0.35            # how quickly the drawn level chases the real one
# How deep the ripple cuts. At 0 every bar is the same height and the wave is
# gone; at 1 the trough flattens bars to nothing, and since the average bar then
# only reaches half the measured level, the wave only reads when you raise your
# voice. What is left over is the height every bar keeps regardless.
_WAVE_DEPTH = 0.28

_PAD = 13                    # inner margin, left of the wave and right of the text
_ACCENT_W = 5                # the coloured edge

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

    def __init__(
        self,
        position: str = _DEFAULT_POSITION,
        level: Callable[[], float] | None = None,
    ) -> None:
        self._commands: queue.Queue[tuple] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._failed = False
        self._position = position if position in OVERLAY_POSITIONS else _DEFAULT_POSITION
        # Polled once a frame from the Tk thread rather than pushed from the audio
        # callback: the drawing side wants the latest value and nothing else, and
        # the audio callback must never be made to wait on the UI.
        self._level = level

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

    def _read_level(self) -> float:
        """The microphone level, clamped. Never raises: this runs every frame."""
        if self._level is None:
            return 0.0
        try:
            return max(0.0, min(1.0, float(self._level())))
        except Exception:
            return 0.0

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
            from tkinter import font as tkfont
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

        try:
            root.withdraw()
            root.overrideredirect(True)   # no title bar, no taskbar button
            root.attributes("-topmost", True)
            root.attributes("-alpha", 0.0)
            root.configure(bg=_BG)

            text_font = tkfont.Font(family="Segoe UI", size=11)
            # Measured from the font rather than fixed, so the pill keeps its
            # proportions when Windows is scaling text at 125% or 150%.
            height = text_font.metrics("linespace") + 20

            canvas = tk.Canvas(root, bg=_BG, highlightthickness=0, bd=0, height=height)
            canvas.pack(fill="both", expand=True)
            _make_non_activating(root)
        except Exception:
            # Give up for good rather than let every event start another thread
            # that dies the same way.
            self._failed = True
            log.warning("Could not build the status pill.", exc_info=True)
            try:
                root.destroy()
                release_default_root(root)
            except Exception:
                pass
            return

        state = {
            "hide_job": None,
            "transient": False,
            "visible": False,
            "fading": "in",      # "in" or "out"
            "opacity": 0.0,
            "kind": "",
            "phase": 0.0,
            "level": 0.0,
            "bars": [],
        }

        def _cancel_hide() -> None:
            if state["hide_job"] is not None:
                try:
                    root.after_cancel(state["hide_job"])
                except Exception:
                    pass
                state["hide_job"] = None

        def _layout(kind: str, text: str) -> None:
            """Redraw the pill for a new state and place it in its corner."""
            accent = _ACCENTS.get(kind, _DEFAULT_ACCENT)
            wave = kind in (_LIVE, _WORKING)

            w = _ACCENT_W + _PAD + text_font.measure(text) + _PAD
            if wave:
                w += _WAVE_W + _WAVE_GAP

            canvas.delete("all")
            state["bars"] = []
            canvas.config(width=w, height=height)
            # The accent as a thick left edge and a hairline border, as before.
            canvas.create_rectangle(0, 0, _ACCENT_W, height, fill=accent, width=0)
            canvas.create_rectangle(0, 0, w - 1, height - 1, outline=accent, width=1)

            x = _ACCENT_W + _PAD
            if wave:
                mid = height / 2
                for i in range(_BARS):
                    bx = x + i * (_BAR_W + _BAR_GAP)
                    state["bars"].append(canvas.create_rectangle(
                        bx, mid - _BAR_MIN_H / 2, bx + _BAR_W, mid + _BAR_MIN_H / 2,
                        fill=accent, width=0,
                    ))
                x += _WAVE_W + _WAVE_GAP
            canvas.create_text(x, height / 2, text=text, fill=_FG,
                               font=text_font, anchor="w")

            # Size and place it while still hidden. Moving it after deiconify()
            # does not take: an overrideredirect window maps at +0+0 and keeps
            # that position, which is why the pill used to appear in the
            # top-left corner instead of by the tray.
            root.update_idletasks()
            area = _work_area(root.winfo_screenwidth(), root.winfo_screenheight())
            px, py = _corner(self._position, w, height, area)
            root.geometry(f"{w}x{height}+{px}+{py}")

        def _animate() -> None:
            """One frame: fade the window, then move the bars."""
            if state["fading"] == "in":
                if state["opacity"] < _OPACITY:
                    state["opacity"] = min(_OPACITY, state["opacity"] + _FADE_IN)
                    root.attributes("-alpha", state["opacity"])
            else:
                state["opacity"] = max(0.0, state["opacity"] - _FADE_OUT)
                root.attributes("-alpha", state["opacity"])
                if state["opacity"] <= 0.0:
                    state["visible"] = False
                    state["level"] = 0.0
                    root.withdraw()
                    return

            bars = state["bars"]
            if not bars:
                return

            if state["kind"] == _LIVE:
                target = self._read_level()
            else:
                # Transcribing: nothing to listen to, so the bars breathe on
                # their own. A frozen row would read as a hung app.
                target = 0.45 + 0.2 * math.sin(state["phase"] * 1.6)

            state["level"] += (target - state["level"]) * _SMOOTHING
            state["phase"] += _PHASE_STEP

            mid = height / 2
            span = height - 2 * _BAR_MARGIN - _BAR_MIN_H
            for i, item in enumerate(bars):
                # Each bar sits a little further along the wave than its
                # neighbour: that offset is what reads as a travelling ripple
                # rather than a row going up and down in unison.
                envelope = (1.0 - _WAVE_DEPTH) + _WAVE_DEPTH * math.sin(
                    state["phase"] + i * _BAR_PHASE)
                bar_h = _BAR_MIN_H + span * state["level"] * envelope
                x0, _, x1, _ = canvas.coords(item)
                canvas.coords(item, x0, mid - bar_h / 2, x1, mid + bar_h / 2)

        def _hide() -> None:
            _cancel_hide()
            state["transient"] = False
            state["fading"] = "out"

        def _show(kind: str, text: str) -> None:
            _cancel_hide()
            state["kind"] = kind
            state["fading"] = "in"
            _layout(kind, text)
            if not state["visible"]:
                state["opacity"] = 0.0
                root.attributes("-alpha", 0.0)
                root.deiconify()
                state["visible"] = True
            root.attributes("-topmost", True)   # reassert: other windows may have jumped ahead
            log.debug("Status pill at %s (%s).", root.winfo_geometry(), self._position)

            delay = _AUTO_HIDE_MS.get(kind)
            state["transient"] = delay is not None
            if delay is not None:
                state["hide_job"] = root.after(delay, _hide)

        def _tick() -> None:
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

            if state["visible"]:
                try:
                    _animate()
                except Exception:
                    # A dropped frame must never take the pill down with it.
                    log.debug("Error animating the status pill.", exc_info=True)

            root.after(_FRAME_MS if state["visible"] else _IDLE_MS, _tick)

        root.after(_IDLE_MS, _tick)
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
            root = canvas = text_font = None
            state["bars"] = []
            gc.collect()


__all__ = ["StatusOverlay"]
