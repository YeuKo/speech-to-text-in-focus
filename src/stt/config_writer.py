"""Minimal, comment-preserving writes back to config.toml.

Only the targeted ``key = value`` line inside its section is rewritten, leaving
the rest of the file (comments, layout, ordering) untouched. Used by the tray so
settings changed from the menu survive a restart. The standard library has no
comment-preserving TOML writer, hence this focused approach.
"""

from __future__ import annotations

import logging
import re
import shutil
import tomllib
from collections.abc import Sequence
from pathlib import Path

from stt.paths import TEMPLATE_NAME, bundled_file

log = logging.getLogger(__name__)

_HOTKEYS = ("toggle", "push_to_talk")

Value = "str | bool | float | Sequence[str]"


def _toml_literal(value: str | bool | float | Sequence[str]) -> str:
    """Render a scalar or a list of strings as a TOML literal."""
    if isinstance(value, bool):  # before int: bool is a subclass of int
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, str):
        return f'"{_escape(value)}"'
    return "[" + ", ".join(f'"{_escape(str(v))}"' for v in value) + "]"


def _escape(value: str) -> str:
    """Escape a value for a TOML basic string (newlines included: they are illegal
    inside one, and a stray line break would otherwise corrupt the file)."""
    out = value.replace("\\", "\\\\").replace('"', '\\"')
    return out.replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")


def _section_span(text: str, section: str) -> tuple[int, int] | None:
    """Return the (start, end) offsets of ``[section]``'s body, or None."""
    header = re.search(rf"^\[{re.escape(section)}\]\s*$", text, re.MULTILINE)
    if header is None:
        return None
    body_start = header.end()
    nxt = re.search(r"^\[", text[body_start:], re.MULTILINE)
    return body_start, body_start + nxt.start() if nxt else len(text)


def persist_value(
    config_path: str | Path,
    section: str,
    key: str,
    value: str | bool | float | Sequence[str],
    example_path: str | Path | None = None,
) -> bool:
    """Persist ``key = value`` inside ``[section]`` of the config file.

    ``value`` may be a string, a boolean, a number or a list of strings.

    Returns True if the file was updated. Best-effort: failures are logged and
    return False (the in-memory/runtime change still applies regardless). The
    result is parsed before being written, so a bad edit is dropped rather than
    left in the user's config.
    """
    literal = _toml_literal(value)
    try:
        p = Path(config_path)
        if not p.exists():
            ex = Path(example_path) if example_path else bundled_file(TEMPLATE_NAME)
            if ex.exists():
                shutil.copy(ex, p)
            else:
                p.write_text(f"[{section}]\n", encoding="utf-8")

        text = p.read_text(encoding="utf-8")
        span = _section_span(text, section)

        if span is None:
            # Section absent: append it at the end of the file.
            new_text = f"{text.rstrip()}\n\n[{section}]\n{key} = {literal}\n"
        else:
            start, end = span
            body = text[start:end]
            # Keep any trailing comment on the line; only the value is replaced.
            # A list value may span several lines, so it is matched up to its
            # closing bracket instead of to the end of the line.
            old_value = r"\[[^\]]*\]" if literal.startswith("[") else r"[^#\n]*?"
            pattern = re.compile(
                rf"^(\s*{re.escape(key)}\s*=\s*){old_value}(\s*(?:#.*)?)$", re.MULTILINE
            )

            def _repl(m: re.Match[str]) -> str:
                # A function (not a template) so backslashes in the value are
                # literal. Group 2 is the trailing comment, if any.
                return f"{m.group(1)}{literal}{m.group(2)}"

            new_body, n = pattern.subn(_repl, body, count=1)
            if n == 0:
                # Key absent in an existing section: add it right after the header.
                new_body = f"\n{key} = {literal}" + body
            new_text = text[:start] + new_body + text[end:]

        # Never hand back a broken config: this writer edits text with regexes,
        # so the outcome is parsed before it replaces the user's file.
        try:
            tomllib.loads(new_text)
        except tomllib.TOMLDecodeError:
            log.error("Refusing to write %s: the edit would break the TOML syntax.", p)
            return False

        p.write_text(new_text, encoding="utf-8")
        return True
    except Exception:
        log.exception("Could not persist %s.%s to %s.", section, key, config_path)
        return False


def persist_hotkey(
    config_path: str | Path,
    which: str,
    combo: str,
    example_path: str | Path | None = None,
) -> bool:
    """Persist a hotkey (``which`` = "toggle" or "push_to_talk") to config.toml."""
    if which not in _HOTKEYS:
        return False
    return persist_value(config_path, "hotkey", which, combo, example_path)


__all__ = ["persist_value", "persist_hotkey"]
