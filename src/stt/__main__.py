"""Punto de entrada de la aplicación."""

from __future__ import annotations

import argparse
import logging
import os
import signal
import subprocess
import sys
import tempfile
import threading
import wave
from pathlib import Path

from stt import __version__, config, logging_setup, postprocess

log = logging.getLogger("stt")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="stt", description="Dictado por voz con Whisper.")
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Ruta al fichero de configuración TOML (por defecto: config.toml si existe).",
    )
    parser.add_argument(
        "--selftest",
        action="store_true",
        help="Genera audio con la voz de Windows, transcribe y muestra el resultado. No requiere micro.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser.parse_args(argv)


def _resolve_config_path(arg: Path | None) -> Path | None:
    if arg is not None:
        return arg
    default = Path("config.toml")
    return default if default.exists() else None


# ---------------------------------------------------------------------------
# Modo selftest
# ---------------------------------------------------------------------------

_SELFTEST_TEXT = (
    "Hola, esta es una prueba de transcripción. "
    "El modelo reconoce anthropik, cubernetes y Grafana."
)


def _selftest(cfg: "config.Config") -> int:
    import numpy as np
    from stt.transcribe import create_backend

    log.info("=== SELFTEST ===")
    log.info("Texto de prueba: %r", _SELFTEST_TEXT)

    # Generar WAV a 16 kHz mono con la voz de Windows (SAPI)
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    wav_path = tmp.name
    tmp.close()

    ps_script = (
        "Add-Type -AssemblyName System.Speech; "
        "$fmt = [System.Speech.AudioFormat.SpeechAudioFormatInfo]::new("
        "16000,"
        "[System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen,"
        "[System.Speech.AudioFormat.AudioChannel]::Mono); "
        f"$s = [System.Speech.Synthesis.SpeechSynthesizer]::new(); "
        "$s.Rate = -2; "
        f'$s.SetOutputToWaveFile("{wav_path}", $fmt); '
        f'$s.Speak("{_SELFTEST_TEXT}"); '
        "$s.Dispose();"
    )
    try:
        r = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command", ps_script],
            capture_output=True, text=True, timeout=30,
        )
        if r.returncode != 0:
            log.error("Error al generar audio SAPI:\n%s", r.stderr)
            return 1
    except FileNotFoundError:
        log.error("powershell.exe no encontrado. El selftest requiere Windows.")
        return 1

    # Cargar WAV → numpy float32
    with wave.open(wav_path, "rb") as wf:
        raw = wf.readframes(wf.getnframes())
        sr = wf.getframerate()
        nch = wf.getnchannels()

    audio = __import__("numpy").frombuffer(raw, dtype="<i2").astype("float32") / 32768.0
    if nch > 1:
        audio = audio.reshape(-1, nch).mean(axis=1)
    log.info("Audio generado: %.1f s a %d Hz.", len(audio) / sr, sr)

    # Transcribir
    backend = create_backend(cfg)
    backend.load()
    prompt = postprocess.build_prompt(cfg.dictionary.terms)
    lang = cfg.engine.language if cfg.engine.language != "auto" else None
    result = backend.transcribe(audio, sample_rate=sr, language=lang, prompt=prompt)
    text = postprocess.apply(result.text, cfg.dictionary.replacements)
    backend.close()

    log.info("Transcrito en %.1fs:", result.elapsed_s or 0)
    log.info("  Esperado : %r", _SELFTEST_TEXT)
    log.info("  Obtenido : %r", text)

    try:
        os.unlink(wav_path)
    except OSError:
        pass

    return 0


# ---------------------------------------------------------------------------
# Arranque normal (dictado)
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        cfg = config.load(_resolve_config_path(args.config))
    except config.ConfigError as exc:
        print(f"Error de configuración: {exc}", file=sys.stderr)
        return 2

    logging_setup.setup(cfg.logging.level, cfg.logging.dir)
    log.info("STT Dictation %s — backend=%s, idioma=%s", __version__, cfg.engine.backend, cfg.engine.language)

    if args.selftest:
        return _selftest(cfg)

    if sys.platform != "win32":
        log.error(
            "El modo dictado requiere Windows nativo. "
            "En WSL ejecuta: python.exe -m stt  (o usa el ejecutable en Windows)."
        )
        return 1

    from stt.controller import Controller

    controller = Controller(cfg)

    # Intentar arrancar con icono en la bandeja; si pystray falla, caer a un
    # bucle de espera simple (la app sigue funcionando, solo sin indicador).
    tray = None
    try:
        from stt.ui.tray import TrayIcon

        tray = TrayIcon(
            toggle_hotkey=cfg.hotkey.toggle,
            ptt_hotkey=cfg.hotkey.push_to_talk,
            on_quit=controller.stop,
        )
        controller.set_on_state_change(tray.set_state)
    except Exception:
        log.warning("No se pudo iniciar la bandeja; modo sin indicador.", exc_info=True)

    try:
        controller.start()
        log.info(
            "Listo. Toggle=%s | Push-to-talk=%s.",
            cfg.hotkey.toggle,
            cfg.hotkey.push_to_talk,
        )
        if tray is not None:
            log.info("Icono en la bandeja activo. Usa 'Salir' en el menú para cerrar.")
            tray.run()  # bloqueante hasta que se elija "Salir"
        else:
            _wait_for_ctrl_c(controller)
    except Exception:
        log.exception("Fallo al iniciar.")
        return 1
    finally:
        controller.stop()

    return 0


def _wait_for_ctrl_c(controller) -> None:
    stop_event = threading.Event()

    def _sigint(sig, frame):
        log.info("Cerrando (Ctrl+C)...")
        stop_event.set()

    signal.signal(signal.SIGINT, _sigint)
    log.info("Pulsa Ctrl+C para salir.")
    stop_event.wait()


if __name__ == "__main__":
    raise SystemExit(main())
