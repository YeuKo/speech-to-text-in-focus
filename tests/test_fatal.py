"""A startup failure must reach the user even when nobody is watching stderr.

A desktop shortcut starts the app with ``pythonw``, which has no console and no
``sys.stderr``: printing there is a silent no-op. Before this, a second copy of
the app refused to start and said so into the void.
"""

import sys
import types

import pytest

from s2f import __main__ as main


@pytest.fixture
def shown(monkeypatch):
    """Collects what would have been put on screen.

    ``s2f.ui.dialogs`` needs Windows to import, so it is replaced rather than
    imported; ``_fatal`` looks it up lazily, which makes that possible.
    """
    calls = []
    fake = types.ModuleType("s2f.ui.dialogs")
    fake.message_box = lambda title, text, **kwargs: calls.append((title, text))
    monkeypatch.setitem(sys.modules, "s2f.ui.dialogs", fake)
    monkeypatch.setattr(main.time, "sleep", lambda _seconds: None)
    return calls


def test_dialog_when_there_is_no_console(monkeypatch, shown):
    """The pythonw shortcut case: the dialog is the only channel left."""
    monkeypatch.setattr(main, "_has_console", lambda: False)
    monkeypatch.setattr(main.paths, "is_frozen", lambda: False)

    main._fatal("Already running", "look in the tray")

    assert shown == [("Already running", "look in the tray")]


def test_no_dialog_when_a_console_can_show_it(monkeypatch, shown, capsys):
    """Run from a terminal, stderr is enough: a popup would only be in the way."""
    monkeypatch.setattr(main, "_has_console", lambda: True)
    monkeypatch.setattr(main.paths, "is_frozen", lambda: False)

    main._fatal("Configuration error", "line 3 is not valid TOML")

    assert shown == []
    assert "line 3 is not valid TOML" in capsys.readouterr().err


def test_packaged_build_always_gets_the_dialog(monkeypatch, shown):
    """Frozen builds keep showing it, console attached or not."""
    monkeypatch.setattr(main, "_has_console", lambda: True)
    monkeypatch.setattr(main.paths, "is_frozen", lambda: True)

    main._fatal("Configuration error", "line 3 is not valid TOML")

    assert len(shown) == 1
