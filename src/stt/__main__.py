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
    parser.add_argument(
        "--calibrate-mic",
        action="store_true",
        help="Mide el nivel de tu micrófono y recomienda un valor para audio.silence_threshold.",
    )
    parser.add_argument(
        "--set-api-key",
        action="store_true",
        help="Guarda tu API key de OpenAI de forma segura en el almacén de Windows (keyring).",
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
# Guardar API key en keyring
# ---------------------------------------------------------------------------

def _set_api_key() -> int:
    import getpass

    from stt import keystore

    print("Pega tu API key de OpenAI (no se mostrará al escribir):")
    try:
        key = getpass.getpass("API key: ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return 1

    if not key:
        log.error("No se introdujo ninguna key.")
        return 1
    if not key.startswith("sk-"):
        log.warning("La key no empieza por 'sk-'; ¿seguro que es correcta? Se guardará igualmente.")

    if not keystore.set_api_key(key):
        return 1
    log.info("API key guardada de forma segura en el almacén de Windows.")
    log.info("Para usarla: cambia el engine a OpenAI (config o menú de la bandeja).")
    return 0


# ---------------------------------------------------------------------------
# Calibración de micrófono
# ---------------------------------------------------------------------------

def _calibrate_mic(cfg: "config.Config", seconds: float = 5.0) -> int:
    import numpy as np
    import sounddevice as sd

    sr = cfg.audio.sample_rate
    block = 1024
    rms_values: list[float] = []

    log.info("=== CALIBRACIÓN DE MICRÓFONO ===")
    log.info("Habla con normalidad durante %.0f segundos...", seconds)

    def _cb(indata, frames, t, status):
        rms_values.append(float(np.sqrt(np.mean(indata ** 2))))

    with sd.InputStream(samplerate=sr, channels=1, dtype="float32",
                        blocksize=block, callback=_cb):
        sd.sleep(int(seconds * 1000))

    if not rms_values:
        log.error("No se capturó audio. ¿Micrófono conectado y con permisos?")
        return 1

    arr = np.array(rms_values)
    p10, p50, p90 = (float(np.percentile(arr, p)) for p in (10, 50, 90))
    # Umbral recomendado: a medio camino entre el silencio (p10) y la voz (p50),
    # tirando hacia abajo para no cortar en los valles de la voz.
    recommended = round(max(0.002, p10 + (p50 - p10) * 0.4), 4)

    log.info("Niveles RMS  -> silencio≈%.4f  voz(mediana)≈%.4f  picos≈%.4f", p10, p50, p90)
    log.info("Umbral actual: %.4f", cfg.audio.silence_threshold)
    log.info("Recomendado  : %.4f", recommended)
    log.info("Pon esto en config.toml [audio]:  silence_threshold = %.4f", recommended)
    return 0


# ---------------------------------------------------------------------------
# Arranque normal (dictado)
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    resolved_config = _resolve_config_path(args.config)
    try:
        cfg = config.load(resolved_config)
    except config.ConfigError as exc:
        print(f"Error de configuración: {exc}", file=sys.stderr)
        return 2
    # Ruta para el ítem "Open config file" del tray (aunque aún no exista).
    config_path = resolved_config or Path("config.toml")

    logging_setup.setup(cfg.logging.level, cfg.logging.dir)
    log.info("STT Dictation %s — backend=%s, idioma=%s", __version__, cfg.engine.backend, cfg.engine.language)

    if args.set_api_key:
        return _set_api_key()

    if args.selftest:
        return _selftest(cfg)

    if args.calibrate_mic:
        return _calibrate_mic(cfg)

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
        from stt import keystore
        from stt.ui.dialogs import ask_api_key, message_box
        from stt.ui.help import open_config, open_instructions, open_usage_report
        from stt.ui.tray import TrayIcon

        def _set_engine(name: str) -> None:
            if name == "openai" and not keystore.has_api_key():
                message_box(
                    "OpenAI API key required",
                    "To use the OpenAI engine you need an API key.\n\n"
                    "Use the tray menu → 'Set OpenAI API key…' first.",
                )
                return
            ok, msg = controller.switch_backend(name)
            if not ok:
                message_box("Could not switch engine", msg, error=True)

        def _set_api_key_dialog() -> None:
            key = ask_api_key()
            if not key:
                return
            if keystore.set_api_key(key):
                message_box("API key saved", "Your OpenAI API key was saved securely.")
            else:
                message_box("Error", "Could not save the API key.", error=True)

        tray = TrayIcon(
            toggle_hotkey=cfg.hotkey.toggle,
            ptt_hotkey=cfg.hotkey.push_to_talk,
            on_quit=controller.stop,
            on_help=lambda: open_instructions(cfg),
            on_toggle_auto_stop=lambda: controller.set_auto_stop(not controller.is_auto_stop()),
            is_auto_stop=controller.is_auto_stop,
            on_open_config=lambda: open_config(config_path),
            on_open_usage=lambda: open_usage_report(cfg),
            on_set_engine=_set_engine,
            current_engine=controller.current_backend,
            on_set_api_key=_set_api_key_dialog,
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
            log.info("Icono en la bandeja activo. Usa 'Quit' en el menú para cerrar.")
            if controller.startup_warning:
                try:
                    from stt.ui.dialogs import message_box

                    message_box("STT Dictation", controller.startup_warning)
                except Exception:
                    pass
            tray.run()  # bloqueante hasta que se elija "Quit"
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
