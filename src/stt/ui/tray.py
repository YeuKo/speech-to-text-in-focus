"""Icono en la bandeja del sistema con indicador de estado por color y menú.

- azul    -> en espera (idle)
- rojo    -> grabando
- naranja -> transcribiendo

``run()`` es bloqueante (arranca el bucle de eventos de la bandeja) y debe
llamarse en el hilo principal. ``set_state()`` se puede llamar desde otros hilos.
Las etiquetas están en inglés para uso por terceros.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

log = logging.getLogger(__name__)

# RGB por estado (clave = State.value)
_COLORS: dict[str, tuple[int, int, int]] = {
    "idle": (90, 120, 160),          # azul grisáceo
    "recording": (220, 60, 60),      # rojo
    "transcribing": (235, 165, 40),  # naranja
}

_LABELS: dict[str, str] = {
    "idle": "Idle",
    "recording": "Recording…",
    "transcribing": "Transcribing…",
}


def _make_image(color: tuple[int, int, int]):
    from PIL import Image, ImageDraw

    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse([6, 6, size - 6, size - 6], fill=color + (255,))
    return img


class TrayIcon:
    def __init__(
        self,
        *,
        toggle_hotkey: str,
        ptt_hotkey: str,
        on_quit: Callable[[], None],
        on_help: Callable[[], None],
        on_toggle_auto_stop: Callable[[], None],
        is_auto_stop: Callable[[], bool],
        on_open_config: Callable[[], None],
        on_open_usage: Callable[[], None],
    ) -> None:
        self._toggle = toggle_hotkey
        self._ptt = ptt_hotkey
        self._on_quit = on_quit
        self._on_help = on_help
        self._on_toggle_auto_stop = on_toggle_auto_stop
        self._is_auto_stop = is_auto_stop
        self._on_open_config = on_open_config
        self._on_open_usage = on_open_usage
        self._icon = None
        self._images = {state: _make_image(rgb) for state, rgb in _COLORS.items()}

    def _build(self):
        import pystray

        menu = pystray.Menu(
            pystray.MenuItem(f"Toggle dictation: {self._toggle}", None, enabled=False),
            pystray.MenuItem(f"Push-to-talk: {self._ptt}", None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "Auto-stop on silence",
                self._handle_toggle_auto,
                checked=lambda item: self._is_auto_stop(),
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Open config file", self._handle_open_config),
            pystray.MenuItem("Usage / cost", self._handle_open_usage),
            pystray.MenuItem("Help / Instructions", self._handle_help),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", self._handle_quit),
        )
        self._icon = pystray.Icon(
            "stt",
            icon=self._images["idle"],
            title="STT — Idle",
            menu=menu,
        )

    # Los handlers aceptan (icon, item) que pasa pystray; los ignoramos.
    def _handle_toggle_auto(self, *args) -> None:
        try:
            self._on_toggle_auto_stop()
        except Exception:
            log.exception("Error al cambiar el modo de auto-stop.")
        if self._icon is not None:
            self._icon.update_menu()

    def _handle_help(self, *args) -> None:
        try:
            self._on_help()
        except Exception:
            log.exception("Error al abrir la ayuda.")

    def _handle_open_config(self, *args) -> None:
        try:
            self._on_open_config()
        except Exception:
            log.exception("Error al abrir la configuración.")

    def _handle_open_usage(self, *args) -> None:
        try:
            self._on_open_usage()
        except Exception:
            log.exception("Error al abrir el informe de uso.")

    def _handle_quit(self, *args) -> None:
        try:
            self._on_quit()
        finally:
            self.stop()

    def set_state(self, state: str) -> None:
        """Actualiza el color del icono y el tooltip según el estado."""
        if self._icon is None:
            return
        img = self._images.get(state)
        if img is not None:
            self._icon.icon = img
        self._icon.title = f"STT — {_LABELS.get(state, state)}"

    def run(self) -> None:
        """Bloqueante: arranca el bucle de la bandeja (hilo principal)."""
        self._build()
        self._icon.run()

    def stop(self) -> None:
        if self._icon is not None:
            self._icon.stop()


__all__ = ["TrayIcon"]
