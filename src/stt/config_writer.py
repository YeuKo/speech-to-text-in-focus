"""Minimal, comment-preserving writes back to config.toml.

Only updates the specific hotkey lines via a targeted regex, leaving the rest of
the file (comments, layout) untouched. Used by the tray's shortcut capture so
changes survive restarts. The standard library has no comment-preserving TOML
writer, hence this focused approach.
"""

from __future__ import annotations

import logging
import re
import shutil
from pathlib import Path

log = logging.getLogger(__name__)


def persist_hotkey(
    config_path: str | Path,
    which: str,
    combo: str,
    example_path: str | Path = "config.example.toml",
) -> bool:
    """Persist a hotkey value (which = "toggle" or "push_to_talk") to config.toml.

    Returns True if the file was updated. Best-effort: failures are logged and
    return False (the in-memory/runtime change still applies regardless).
    """
    if which not in ("toggle", "push_to_talk"):
        return False
    try:
        p = Path(config_path)
        if not p.exists():
            ex = Path(example_path)
            if ex.exists():
                shutil.copy(ex, p)
            else:
                p.write_text("[hotkey]\n", encoding="utf-8")

        text = p.read_text(encoding="utf-8")
        pattern = re.compile(rf'^(\s*{re.escape(which)}\s*=\s*)"[^"]*"(.*)$', re.MULTILINE)

        def _repl(m: re.Match[str]) -> str:
            return f'{m.group(1)}"{combo}"{m.group(2)}'

        new_text, n = pattern.subn(_repl, text, count=1)
        if n == 0:
            # Key not present: append a [hotkey] entry at the end.
            new_text = text.rstrip() + f'\n\n[hotkey]\n{which} = "{combo}"\n'

        p.write_text(new_text, encoding="utf-8")
        return True
    except Exception:
        log.exception("Could not persist the hotkey to %s.", config_path)
        return False


__all__ = ["persist_hotkey"]
