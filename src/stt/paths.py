"""Where the app's files live, in a checkout and once packaged.

In a git checkout everything sits next to the sources, which is what you want
while developing. Once packaged that stops working: the folder holding the
executable may be read-only (Program Files), and the working directory a shortcut
starts in is anyone's guess, so writing ``config.toml`` or ``logs/`` relative to it
either fails or scatters files.

The rule here is that **the folder holding config.toml is the data folder**, and
anything the app writes goes inside it. That folder is chosen once at startup:

1. ``--config`` if given — the user is explicit, obey.
2. ``config.toml`` next to the executable, so an unzipped portable copy keeps
   everything together and can be deleted in one go.
3. ``%APPDATA%\\speech-to-text-in-focus``, for when the executable's folder is read-only.
"""

from __future__ import annotations

import logging
import os
import shutil
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from stt.config import Config

log = logging.getLogger(__name__)

APP_NAME = "speech-to-text-in-focus"
CONFIG_NAME = "config.toml"
TEMPLATE_NAME = "config.example.toml"


def is_frozen() -> bool:
    """True when running from a PyInstaller build rather than a checkout."""
    return getattr(sys, "frozen", False)


def bundle_dir() -> Path:
    """Folder holding the read-only files shipped with the app."""
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass)
    return Path(__file__).resolve().parents[2]     # src/stt/paths.py -> repo root


def bundled_file(name: str) -> Path:
    """Path to a file shipped with the app (the config template, an icon…)."""
    return bundle_dir() / name


def app_dir() -> Path:
    """Folder the app runs from: the executable's when packaged, else the checkout.

    In a checkout this is the repo root rather than the current directory. Following
    the cwd meant that starting ``stt`` from anywhere else — a shell sitting in the
    user's home, a shortcut — silently ignored the config.toml in the checkout and
    dropped a fresh one wherever the user happened to be standing.

    Falls back to the cwd when the sources are not in a checkout (an installed,
    non-editable copy), where the folder above the package is site-packages and has
    no business holding anyone's settings.
    """
    if is_frozen():
        return Path(sys.executable).resolve().parent
    root = bundle_dir()
    return root if (root / "pyproject.toml").exists() else Path.cwd()


def user_data_dir() -> Path:
    """``%APPDATA%\\speech-to-text-in-focus``, or its equivalent off Windows."""
    appdata = os.environ.get("APPDATA")
    base = Path(appdata) if appdata else Path.home() / ".config"
    return base / APP_NAME


def is_writable(directory: Path) -> bool:
    """Whether we can actually create files in ``directory``.

    Tested by writing, not by asking: on Windows the permission bits say little
    about what the ACLs and virtualisation will allow.
    """
    probe = directory / ".stt-write-test"
    try:
        directory.mkdir(parents=True, exist_ok=True)
        probe.touch()
        probe.unlink()
        return True
    except OSError:
        return False


def resolve_config(explicit: Path | None) -> Path | None:
    """Find the config file to use, creating it from the template if packaged.

    Returns None when there is nothing to read and nothing was created, which
    means "run on defaults" — the usual case in a checkout with no config.toml.
    """
    if explicit is not None:
        return explicit

    for candidate in (app_dir() / CONFIG_NAME, user_data_dir() / CONFIG_NAME):
        if candidate.exists():
            return candidate

    if not is_frozen():
        return None     # a checkout without config.toml: defaults are fine

    # A packaged first run: give the user a file to edit, next to the app when
    # that is writable so a portable copy stays self-contained.
    target = app_dir() if is_writable(app_dir()) else user_data_dir()
    return _create_from_template(target / CONFIG_NAME)


def _create_from_template(destination: Path) -> Path | None:
    template = bundled_file(TEMPLATE_NAME)
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        if template.exists():
            shutil.copy(template, destination)
        else:
            destination.write_text("# Speech to Text in Focus configuration\n", encoding="utf-8")
        log.info("Created %s", destination)
        return destination
    except OSError as exc:
        log.warning("Could not create %s: %s", destination, exc)
        return None


def anchor(cfg: "Config", config_path: Path | None) -> Path:
    """Make the paths inside ``cfg`` absolute, relative to the data folder.

    Everything the app writes (``logging.dir``, ``usage.file``) is configured as a
    relative path, which would otherwise land wherever the process happens to have
    been started. Resolving them once here keeps the rest of the code unaware of
    the difference between a checkout and a packaged app.

    Returns the data folder.
    """
    data_dir = config_path.parent if config_path is not None else Path.cwd()

    log_dir = Path(cfg.logging.dir)
    if not log_dir.is_absolute():
        cfg.logging.dir = str(data_dir / log_dir)

    usage_file = Path(cfg.usage.file)
    if not usage_file.is_absolute():
        cfg.usage.file = str(data_dir / usage_file)

    return data_dir


__all__ = [
    "anchor",
    "app_dir",
    "bundle_dir",
    "bundled_file",
    "is_frozen",
    "is_writable",
    "resolve_config",
    "user_data_dir",
]
