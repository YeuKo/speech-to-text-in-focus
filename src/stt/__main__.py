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
import time
import wave
from collections.abc import Callable
from pathlib import Path

from stt import __version__, config, logging_setup, paths, postprocess, single_instance

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
        help="Synthesize speech with the Windows voice, transcribe it and show the "
             "result. No mic needed.",
    )
    parser.add_argument(
        "--calibrate-mic",
        action="store_true",
        help="Measure your microphone level and recommend a value for audio.silence_threshold.",
    )
    parser.add_argument(
        "--list-devices",
        action="store_true",
        help="List the microphones you can record from (for audio.input_device).",
    )
    parser.add_argument(
        "--debug-keys",
        action="store_true",
        help="Show what your keyboard reports for 20 seconds, and whether the "
             "configured gesture matches. Use it when a shortcut does nothing.",
    )
    parser.add_argument(
        "--set-api-key",
        action="store_true",
        help="Store your OpenAI API key securely in the Windows credential store (keyring).",
    )
    parser.add_argument(
        "--allow-multiple",
        action="store_true",
        help="Start even if another copy is already running (they will share the "
             "shortcuts, so expect a fight over the microphone).",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser.parse_args(argv)


def _fatal(title: str, message: str) -> None:
    """Report a startup failure through every channel available.

    A packaged build runs without a console, so a message on stderr would vanish;
    the dialog is the only thing the user would ever see.
    """
    print(f"{title}: {message}", file=sys.stderr)
    log.error("%s: %s", title, message)
    if paths.is_frozen():
        try:
            from stt.ui.dialogs import message_box

            message_box(title, message, error=True)
            time.sleep(8)   # daemon thread: give the dialog time to be read
        except Exception:
            pass


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

def _list_devices() -> int:
    from stt.audio.devices import list_input_devices

    devices = list_input_devices()
    if not devices:
        log.error("No microphones found.")
        return 1

    print("Microphones available for recording:\n")
    for dev in devices:
        mark = "*" if dev.is_default else " "
        print(f" {mark} {dev.name}   ({dev.channels} ch)")
    print("\n  * = Windows default (what audio.input_device = \"auto\" uses)")
    print("\nTo pick one, put part of its name in config.toml:")
    print('  [audio]\n  input_device = "Microphone Array"')
    print("Or choose it from the tray menu -> Microphone.")
    return 0


def _debug_keys(cfg: "config.Config", seconds: float = 20.0) -> int:
    """Show what the keyboard actually reports, and whether the gesture matches.

    When a shortcut "does nothing", the question is always the same: is the key
    arriving, and under what name? Everything else is guesswork without this.
    """
    import keyboard

    from stt.hotkey import canonical_key

    wanted = [canonical_key(k) for k in cfg.hotkey.gesture.split("+") if k.strip()]
    down: set[str] = set()
    seen: set[str] = set()
    matched = False

    print(f"Watching the keyboard for {seconds:.0f} seconds.")
    print(f"Configured gesture: {cfg.hotkey.gesture!r} -> looking for {wanted}")
    print("Press it a few times: hold it, and tap it twice.\n")

    def _on_event(event) -> None:
        nonlocal matched
        name = canonical_key(event.name, event.scan_code)
        if event.event_type == keyboard.KEY_DOWN:
            down.add(name)
        else:
            down.discard(name)
        seen.add(name)
        hit = bool(wanted) and all(k in down for k in wanted)
        matched = matched or hit
        print(f"  {event.event_type:4s} name={str(event.name)!r:16s} "
              f"canonical={name!r:12s} scan={event.scan_code:<5} "
              f"held={sorted(down)}{'   <-- GESTURE MATCHES' if hit else ''}")

    keyboard.hook(_on_event)
    time.sleep(seconds)
    keyboard.unhook_all()

    print("\n--- summary ---")
    print(f"Keys seen: {sorted(seen) if seen else 'NONE — no key events arrived at all'}")
    if not wanted:
        print("No gesture configured.")
    elif matched:
        print(f"The gesture {wanted} was detected: the keyboard side works.")
    else:
        missing = [k for k in wanted if k not in seen]
        print(f"The gesture {wanted} never matched.")
        if missing:
            print(f"Never arrived under that name: {missing}")
            print("Use one of the names listed above in [hotkey] gesture instead.")
    return 0


def _calibrate_mic(cfg: "config.Config", seconds: float = 5.0) -> int:
    import numpy as np
    import sounddevice as sd

    from stt.audio.devices import describe_current, resolve_input_device

    sr = cfg.audio.sample_rate
    rms_values: list[float] = []

    log.info("=== MICROPHONE CALIBRATION ===")
    log.info("Microphone: %s", describe_current(cfg.audio.input_device))
    log.info("Current gain: %.1fx", cfg.audio.gain)
    log.info("Speak normally, from where you usually sit, for %.0f seconds...", seconds)

    def _cb(indata, frames, t, status):
        rms_values.append(float(np.sqrt(np.mean(indata ** 2))))

    device = resolve_input_device(cfg.audio.input_device)
    with sd.InputStream(samplerate=sr, channels=1, dtype="float32",
                        blocksize=1024, device=device, callback=_cb):
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

    # Speech is detected from about 0.004 RMS upwards (see audio/silence.py), so a
    # quiet microphone needs gain before that check can see it at all.
    _TARGET_SPEECH = 0.05
    if p50 < 0.02:
        suggested = min(20.0, round(_TARGET_SPEECH / max(p50, 0.001), 1))
        log.warning(
            "Your speech is quiet (%.4f). The recording works, but detection is "
            "close to its floor: it may not notice you started talking, and you "
            "would have to lean into the microphone.", p50,
        )
        log.warning("Try this in config.toml [audio]:  gain = %.1f", suggested)
        log.warning(
            "If that is not the microphone you speak into, list them with "
            "'stt --list-devices' and pick one (tray menu -> Microphone)."
        )
    else:
        log.info("Speech level is healthy; no extra gain needed.")
    return 0


# ---------------------------------------------------------------------------
# Normal startup (dictation)
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    resolved_config = paths.resolve_config(args.config)
    try:
        cfg = config.load(resolved_config)
    except config.ConfigError as exc:
        _fatal("Configuration error", str(exc))
        return 2
    # Path used by the tray's "Open config file" item (even if it doesn't exist yet).
    config_path = resolved_config or paths.app_dir() / paths.CONFIG_NAME
    # Anchor logs and the usage file to the folder holding the config, so a
    # packaged app never writes relative to whatever directory it was started in.
    data_dir = paths.anchor(cfg, resolved_config)

    logging_setup.setup(cfg.logging.level, cfg.logging.dir)
    log.info("Speech to Text in Focus %s — backend=%s, language=%s",
             __version__, cfg.engine.backend, cfg.engine.language)
    log.info("Config: %s | data: %s", resolved_config or "defaults", data_dir)

    if args.set_api_key:
        return _set_api_key()

    if args.selftest:
        return _selftest(cfg)

    if args.list_devices:
        return _list_devices()

    if args.debug_keys:
        return _debug_keys(cfg)

    if args.calibrate_mic:
        return _calibrate_mic(cfg)

    if sys.platform != "win32":
        log.error(
            "Dictation mode requires native Windows. "
            "From WSL run: python.exe -m stt  (or use the Windows executable)."
        )
        return 1

    # Before anything grabs the microphone or the shortcuts.
    if not args.allow_multiple and not single_instance.acquire():
        _fatal(
            "Already running",
            "Speech to Text in Focus is already running — look for the microphone "
            "in the system tray.\n\nIf you really want a second copy (to test a "
            "different configuration), start it with --allow-multiple.",
        )
        return 3

    from stt.controller import Controller

    controller = Controller(cfg)

    # Try to start with a tray icon; if pystray fails, fall back to a simple wait
    # loop (the app still works, just without the indicator).
    tray = None
    try:
        from stt import keystore
        from stt.config_writer import persist_value
        from stt.ui.dialogs import ask_api_key, build_hotkey, edit_terms, message_box
        from stt.ui.help import open_config, open_instructions, open_usage_report
        from stt.ui.overlay import StatusOverlay
        from stt.ui.tray import TrayIcon

        overlay = StatusOverlay(cfg.feedback.overlay_position)
        _template = paths.bundled_file(paths.TEMPLATE_NAME)

        def _set_hotkey(which: str, done: Callable[[], None]) -> None:
            """Open the builder for one mode; apply and persist what it returns."""
            def _apply(combo: str) -> None:
                controller.suspend_hotkeys()
                ok, msg = controller.apply_hotkey(which, combo)
                if ok:
                    persist_value(config_path, "hotkey", which, combo)
                else:
                    message_box("Could not set shortcut", msg, error=True)
                done()

            labels = {"toggle": "toggle dictation", "push_to_talk": "push-to-talk",
                      "gesture": "hold / double-tap"}
            current = getattr(cfg.hotkey, which)
            taken = next((getattr(cfg.hotkey, n) for n in ("toggle", "push_to_talk", "gesture")
                          if n != which and getattr(cfg.hotkey, n)), "")
            build_hotkey(labels[which], current, taken, _apply,
                         modifiers_only=which == "gesture")

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

        def _set_sound(mode: str) -> None:
            controller.set_sound_mode(mode)
            persist_value(config_path, "feedback", "sound", mode)

        def _toggle_overlay() -> None:
            enabled = not controller.overlay_enabled()
            controller.set_overlay(enabled)
            persist_value(config_path, "feedback", "overlay", enabled)
            if not enabled:
                overlay.hide()

        def _user_event(kind: str, title: str, message: str) -> None:
            """Single sink for pipeline events; each channel opts in separately."""
            if cfg.feedback.overlay:
                overlay.show(kind, title)

        def _set_mode(mode: str) -> None:
            ok, msg = controller.set_shortcut_mode(mode)
            if ok:
                persist_value(config_path, "hotkey", "mode", mode)
            else:
                message_box("Could not switch shortcut mode", msg, error=True)

        def _set_microphone(name: str) -> None:
            controller.set_microphone(name)   # picked up by the next recording
            persist_value(config_path, "audio", "input_device", name)

        def _edit_terms_dialog() -> None:
            def _save(terms: list[str]) -> None:
                controller.set_terms(terms)   # applies to the next dictation
                if not persist_value(config_path, "dictionary", "terms", terms):
                    message_box(
                        "Could not save the custom words",
                        "The list is active for this session but could not be written "
                        "to config.toml. See logs/stt.log.",
                        error=True,
                    )

            edit_terms(controller.current_terms(), _save)

        def _set_api_key_dialog() -> None:
            def _save(key: str) -> None:
                if keystore.set_api_key(key):
                    message_box("API key saved", "Your OpenAI API key was saved securely.")
                else:
                    message_box("Error", "Could not save the API key.", error=True)

            ask_api_key(_save)

        tray = TrayIcon(
            current_toggle=lambda: cfg.hotkey.toggle,
            current_ptt=lambda: cfg.hotkey.push_to_talk,
            on_set_hotkey=_set_hotkey,
            on_quit=lambda: (controller.stop(), overlay.stop()),
            on_help=lambda: open_instructions(cfg),
            on_toggle_auto_stop=lambda: controller.set_auto_stop(not controller.is_auto_stop()),
            is_auto_stop=controller.is_auto_stop,
            on_open_config=lambda: open_config(config_path, _template),
            on_open_usage=lambda: open_usage_report(cfg),
            on_set_engine=_set_engine,
            current_engine=controller.current_backend,
            on_set_api_key=_set_api_key_dialog,
            on_set_sound=_set_sound,
            current_sound=controller.sound_mode,
            on_toggle_overlay=_toggle_overlay,
            overlay_enabled=controller.overlay_enabled,
            on_edit_terms=_edit_terms_dialog,
            on_set_microphone=_set_microphone,
            current_microphone=controller.current_microphone,
            current_gesture=lambda: cfg.hotkey.gesture,
            current_mode=controller.shortcut_mode,
            on_set_mode=_set_mode,
        )
        controller.set_on_state_change(tray.set_state)
        controller.set_on_notify(_user_event)
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

                    message_box("Speech to Text in Focus", controller.startup_warning)
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

    log.info("Stopped.")
    if tray is not None:
        # A tray app has to vanish the instant Quit is pressed. Returning normally
        # would not: at interpreter exit, concurrent.futures joins its worker
        # threads, so a transcription still in flight (or a stuck keyboard hook)
        # would keep the process alive with no icon left to stop it. Nothing is
        # pending — log records are flushed as they are written and each
        # transcription's usage is recorded when it finishes — so exit now.
        os._exit(0)
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
