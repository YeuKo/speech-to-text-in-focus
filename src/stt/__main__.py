"""Punto de entrada de la aplicación.

En Fase 0 deja el arranque cableado: parseo de CLI, carga de configuración y
logging. El bucle de la bandeja del sistema y el registro de atajos se activan
en fases posteriores (requieren Windows nativo).
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from stt import __version__, config, logging_setup

log = logging.getLogger("stt")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="stt", description="Dictado por voz con Whisper.")
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Ruta al fichero de configuración TOML (por defecto: config.toml si existe).",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser.parse_args(argv)


def _resolve_config_path(arg: Path | None) -> Path | None:
    if arg is not None:
        return arg
    default = Path("config.toml")
    return default if default.exists() else None


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        cfg = config.load(_resolve_config_path(args.config))
    except config.ConfigError as exc:
        print(f"Error de configuración: {exc}", file=sys.stderr)
        return 2

    logging_setup.setup(cfg.logging.level, cfg.logging.dir)
    log.info("STT Dictation %s — backend=%s, idioma=%s", __version__, cfg.engine.backend, cfg.engine.language)

    # Importación perezosa: el controlador arrastra dependencias pesadas.
    from stt.controller import Controller

    controller = Controller(cfg)
    try:
        controller.start()
    except NotImplementedError as exc:
        log.warning("Componente pendiente de implementar (Fase 1+): %s", exc)
    except Exception:  # noqa: BLE001 — en el arranque queremos el traceback en el log
        log.exception("Fallo al iniciar el controlador.")
        return 1

    log.info(
        "Andamiaje listo. Atajos configurados -> toggle=%s, push-to-talk=%s. "
        "El bucle de bandeja y los atajos se activan en Fase 1+ (Windows).",
        cfg.hotkey.toggle,
        cfg.hotkey.push_to_talk,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
