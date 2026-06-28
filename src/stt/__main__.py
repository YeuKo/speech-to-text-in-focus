"""Application entry point."""

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
    parser = argparse.ArgumentParser(prog="stt", description="Voice dictation with Whisper.")
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Path to the TOML config file (default: config.toml if present).",
    )
    parser.add_argument(
        "--selftest",
        action="store_true",
        help="Synthesize speech with the Windows voice, transcribe it and show the result. No mic needed.",
    )
    parser.add_argument(
        "--calibrate-mic",
        action="store_true",
        help="Measure your microphone level and recommend a value for audio.silence_threshold.",
    )
    parser.add_argument(
        "--set-api-key",
        action="store_true",
        help="Store your OpenAI API key securely in the Windows credential store (keyring).",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser.parse_args(argv)


def _resolve_config_path(arg: Path | None) -> Path | None:
    if arg is not None:
        return arg
    default = Path("config.toml")
    return default if default.exists() else None


# ---------------------------------------------------------------------------
# Self-test mode
# ---------------------------------------------------------------------------

_SELFTEST_TEXT = (
    "Hello, this is a transcription test. "
    "The model recognises anthropik, cubernetes and Grafana."
)


def _selftest(cfg: "config.Config") -> int:
    import numpy as np

    from stt.transcribe import create_backend

    log.info("=== SELF-TEST ===")
    log.info("Test text: %r", _SELFTEST_TEXT)

    # Generate a 16 kHz mono WAV with the Windows voice (SAPI).
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    wav_path = tmp.name
    tmp.close()

    ps_script = (
        "Add-Type -AssemblyName System.Speech; "
        "$fmt = [System.Speech.AudioFormat.SpeechAudioFormatInfo]::new("
        "16000,"
        "[System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen,"
        "[System.Speech.AudioFormat.AudioChannel]::Mono); "
        "$s = [System.Speech.Synthesis.SpeechSynthesizer]::new(); "
        "$s.Rate = -2; "
        f'$s.SetOutputToWaveFile("{wav_path}", $fmt); '
        f'$s.Speak("{_SELFTEST_TEXT}"); '
        "$s.Dispose();"
    )
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command", ps_script],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            log.error("Failed to generate SAPI audio:\n%s", result.stderr)
            return 1
    except FileNotFoundError:
        log.error("powershell.exe not found. Self-test requires Windows.")
        return 1

    # Load the WAV into a numpy float32 array.
    with wave.open(wav_path, "rb") as wf:
        raw = wf.readframes(wf.getnframes())
        sr = wf.getframerate()
        nch = wf.getnchannels()

    audio = np.frombuffer(raw, dtype="<i2").astype("float32") / 32768.0
    if nch > 1:
        audio = audio.reshape(-1, nch).mean(axis=1)
    log.info("Generated audio: %.1f s at %d Hz.", len(audio) / sr, sr)

    backend = create_backend(cfg)
    backend.load()
    prompt = postprocess.build_prompt(cfg.dictionary.terms)
    lang = cfg.engine.language if cfg.engine.language != "auto" else None
    transcription = backend.transcribe(audio, sample_rate=sr, language=lang, prompt=prompt)
    text = postprocess.apply(transcription.text, cfg.dictionary.replacements)
    backend.close()

    log.info("Transcribed in %.1fs:", transcription.elapsed_s or 0)
    log.info("  Expected : %r", _SELFTEST_TEXT)
    log.info("  Got      : %r", text)

    try:
        os.unlink(wav_path)
    except OSError:
        pass

    return 0


# ---------------------------------------------------------------------------
# Store the API key in keyring
# ---------------------------------------------------------------------------

def _set_api_key() -> int:
    import getpass

    from stt import keystore

    print("Paste your OpenAI API key (it will not be shown as you type):")
    try:
        key = getpass.getpass("API key: ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return 1

    if not key:
        log.error("No key entered.")
        return 1
    if not key.startswith("sk-"):
        log.warning("The key does not start with 'sk-'; are you sure it is correct? Saving anyway.")

    if not keystore.set_api_key(key):
        return 1
    log.info("API key stored securely in the Windows credential store.")
    log.info("To use it: switch the engine to OpenAI (config file or tray menu).")
    return 0


# ---------------------------------------------------------------------------
# Microphone calibration
# ---------------------------------------------------------------------------

def _calibrate_mic(cfg: "config.Config", seconds: float = 5.0) -> int:
    import numpy as np
    import sounddevice as sd

    sr = cfg.audio.sample_rate
    rms_values: list[float] = []

    log.info("=== MICROPHONE CALIBRATION ===")
    log.info("Speak normally for %.0f seconds...", seconds)

    def _cb(indata, frames, t, status):
        rms_values.append(float(np.sqrt(np.mean(indata ** 2))))

    with sd.InputStream(samplerate=sr, channels=1, dtype="float32",
                        blocksize=1024, callback=_cb):
        sd.sleep(int(seconds * 1000))

    if not rms_values:
        log.error("No audio captured. Is the microphone connected and permitted?")
        return 1

    arr = np.array(rms_values)
    p10, p50, p90 = (float(np.percentile(arr, p)) for p in (10, 50, 90))
    # Recommended threshold: between silence (p10) and speech (p50), leaning low
    # so it does not cut on the valleys of speech.
    recommended = round(max(0.002, p10 + (p50 - p10) * 0.4), 4)

    log.info("RMS levels  -> silence~%.4f  speech(median)~%.4f  peaks~%.4f", p10, p50, p90)
    log.info("Current threshold: %.4f", cfg.audio.silence_threshold)
    log.info("Recommended      : %.4f", recommended)
    log.info("Put this in config.toml [audio]:  silence_threshold = %.4f", recommended)
    return 0


# ---------------------------------------------------------------------------
# Normal startup (dictation)
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    resolved_config = _resolve_config_path(args.config)
    try:
        cfg = config.load(resolved_config)
    except config.ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2
    # Path used by the tray's "Open config file" item (even if it doesn't exist yet).
    config_path = resolved_config or Path("config.toml")

    logging_setup.setup(cfg.logging.level, cfg.logging.dir)
    log.info("STT Dictation %s — backend=%s, language=%s",
             __version__, cfg.engine.backend, cfg.engine.language)

    if args.set_api_key:
        return _set_api_key()

    if args.selftest:
        return _selftest(cfg)

    if args.calibrate_mic:
        return _calibrate_mic(cfg)

    if sys.platform != "win32":
        log.error(
            "Dictation mode requires native Windows. "
            "From WSL run: python.exe -m stt  (or use the Windows executable)."
        )
        return 1

    from stt.controller import Controller

    controller = Controller(cfg)

    # Try to start with a tray icon; if pystray fails, fall back to a simple wait
    # loop (the app still works, just without the indicator).
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
        log.warning("Could not start the tray icon; running without an indicator.", exc_info=True)

    try:
        controller.start()
        log.info("Ready. Toggle=%s | Push-to-talk=%s.", cfg.hotkey.toggle, cfg.hotkey.push_to_talk)
        if tray is not None:
            log.info("Tray icon active. Use 'Quit' in the menu to exit.")
            if controller.startup_warning:
                try:
                    from stt.ui.dialogs import message_box

                    message_box("STT Dictation", controller.startup_warning)
                except Exception:
                    pass
            tray.run()  # blocks until "Quit" is chosen
        else:
            _wait_for_ctrl_c()
    except Exception:
        log.exception("Failed to start.")
        return 1
    finally:
        controller.stop()

    return 0


def _wait_for_ctrl_c() -> None:
    stop_event = threading.Event()

    def _sigint(sig, frame):
        log.info("Shutting down (Ctrl+C)...")
        stop_event.set()

    signal.signal(signal.SIGINT, _sigint)
    log.info("Press Ctrl+C to exit.")
    stop_event.wait()


if __name__ == "__main__":
    raise SystemExit(main())
