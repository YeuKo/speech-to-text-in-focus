"""Every setting reachable from the tray menu must survive a restart.

Two of them did not: unticking "Auto-stop on silence" or switching engine only
changed memory, so the next start silently undid it. The bug is invisible until
someone restarts, which is exactly when it is most confusing — so this checks the
wiring rather than trusting each new handler to remember.
"""

import ast
import pathlib

MAIN = pathlib.Path(__file__).resolve().parents[1] / "src" / "stt" / "__main__.py"

# The tray constructor argument -> the handler that must write to config.toml.
# A setting that is deliberately session-only would be listed here with a reason.
SETTINGS_FROM_THE_MENU = {
    "on_toggle_auto_stop",
    "on_set_engine",
    "on_set_sound",
    "on_toggle_overlay",
    "on_set_microphone",
    "on_set_language",
    "on_set_mode",
    "on_edit_terms",
    "on_set_hotkey",
}


def _tray_call(tree: ast.Module) -> ast.Call:
    return next(node for node in ast.walk(tree)
                if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "TrayIcon")


def _function_named(tree: ast.Module, name: str) -> ast.FunctionDef | None:
    return next((n for n in ast.walk(tree)
                 if isinstance(n, ast.FunctionDef) and n.name == name), None)


def _persists(tree: ast.Module, handler: str) -> bool:
    """Does this handler (or anything it defines) call persist_value/persist_hotkey?"""
    fn = _function_named(tree, handler)
    if fn is None:
        return False
    return any(
        isinstance(node, ast.Call)
        and getattr(node.func, "id", "") in {"persist_value", "persist_hotkey"}
        for node in ast.walk(fn)
    )


class TestMenuSettingsAreSaved:
    def test_every_handler_writes_to_the_config(self):
        tree = ast.parse(MAIN.read_text(encoding="utf-8"))
        call = _tray_call(tree)

        forgetful = []
        for keyword in call.keywords:
            if keyword.arg not in SETTINGS_FROM_THE_MENU:
                continue
            handler = getattr(keyword.value, "id", None)   # a plain function name
            if handler is None:
                forgetful.append(f"{keyword.arg} (inline lambda: cannot persist)")
            elif not _persists(tree, handler):
                forgetful.append(f"{keyword.arg} -> {handler}()")

        assert not forgetful, (
            "these menu settings change memory only and are lost on restart: "
            + ", ".join(forgetful)
        )

    def test_the_list_matches_what_the_tray_actually_takes(self):
        """Guards the guard: a renamed argument must not silently drop a check."""
        tree = ast.parse(MAIN.read_text(encoding="utf-8"))
        passed = {k.arg for k in _tray_call(tree).keywords}
        assert SETTINGS_FROM_THE_MENU <= passed, (
            f"no longer passed to TrayIcon: {sorted(SETTINGS_FROM_THE_MENU - passed)}"
        )
