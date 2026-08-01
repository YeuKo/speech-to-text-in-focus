"""Keep a second copy of the app from running alongside the first.

Two instances do not crash, they do something worse: both register the same
global shortcuts, so one keystroke starts two recordings, both fight over the
microphone and both paste their transcription. Double-clicking the executable
twice is an easy mistake to make, and nothing on screen would explain the mess.

A named Windows mutex is the standard way to notice: the first process creates
it, any later one finds it already there. Windows releases it when the process
ends, however it ends, so a crash cannot leave the app permanently blocked.
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)

# Global\ makes it machine-wide rather than per-session. The name is arbitrary
# but must not change: it is the handshake between two copies of the app.
_MUTEX_NAME = r"Global\s2f-dictation-single-instance"

_ERROR_ALREADY_EXISTS = 183

_handle = None      # kept alive for the process's lifetime, on purpose


def acquire() -> bool:
    """True if this process is the only one running.

    False means another copy already holds the mutex. Off Windows, or if the
    call fails for any reason, returns True: refusing to start over a broken
    check would be worse than the problem it guards against.
    """
    global _handle
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.windll.kernel32
        kernel32.CreateMutexW.argtypes = [wintypes.LPCVOID, wintypes.BOOL, wintypes.LPCWSTR]
        kernel32.CreateMutexW.restype = wintypes.HANDLE

        handle = kernel32.CreateMutexW(None, True, _MUTEX_NAME)
        last_error = kernel32.GetLastError()

        if not handle:
            log.debug("Could not create the single-instance mutex (error %d).", last_error)
            return True
        if last_error == _ERROR_ALREADY_EXISTS:
            kernel32.CloseHandle(handle)
            log.info("Another copy is already running.")
            return False

        _handle = handle      # released by Windows when the process exits
        return True
    except Exception:
        log.debug("Single-instance check unavailable.", exc_info=True)
        return True


__all__ = ["acquire"]
