"""Generate and open help pages (in English) in the browser.

The HTML is built with the user's real shortcuts and settings, so it always
reflects their configuration. Designed so another person can understand the app
quickly.
"""

from __future__ import annotations

import csv
import html
import logging
import os
import shutil
import tempfile
import webbrowser
from pathlib import Path
from typing import TYPE_CHECKING

from stt.audio.devices import describe_current

if TYPE_CHECKING:
    from stt.config import Config

log = logging.getLogger(__name__)


def _open(path: str | Path) -> None:
    """Open a file with the system's default application."""
    if hasattr(os, "startfile"):
        os.startfile(str(path))  # Windows
    else:
        webbrowser.open(f"file://{path}")


def _write_temp(name: str, content: str) -> str:
    path = os.path.join(tempfile.gettempdir(), name)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)
    return path


_SOUND_TEXT = {
    "system": "Windows sounds (soft)",
    "beeps": "beeps (loud)",
    "off": "silent",
}


def _build_html(cfg: "Config") -> str:
    toggle = html.escape(cfg.hotkey.toggle)
    ptt = html.escape(cfg.hotkey.push_to_talk)
    backend = html.escape(cfg.engine.backend)
    auto_stop = "on" if cfg.audio.use_vad else "off (manual)"
    sound = _SOUND_TEXT.get(cfg.feedback.sound, html.escape(cfg.feedback.sound))
    overlay = "on" if cfg.feedback.overlay else "off"
    n_terms = len(cfg.dictionary.terms)
    microphone = html.escape(describe_current(cfg.audio.input_device))
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Speech to Text in Focus — Instructions</title>
<style>
  body {{ font-family: Segoe UI, system-ui, sans-serif; max-width: 760px;
         margin: 40px auto; padding: 0 20px; color: #1c2230; line-height: 1.55; }}
  h1 {{ color: #2563a8; }}
  h2 {{ margin-top: 1.8em; border-bottom: 1px solid #e2e6ee; padding-bottom: .2em; }}
  kbd {{ background:#eef1f6; border:1px solid #c9d0dd; border-radius:5px;
         padding:2px 7px; font-family:Consolas,monospace; font-size:.92em; }}
  code {{ background:#f4f6fa; padding:1px 5px; border-radius:4px; }}
  .pill {{ display:inline-block; background:#eaf2fb; color:#205089; border-radius:999px;
           padding:2px 12px; font-size:.85em; }}
  table {{ border-collapse: collapse; width:100%; margin:.5em 0; }}
  td, th {{ border:1px solid #e2e6ee; padding:8px 10px; text-align:left; }}
  .tip {{ background:#f3faf3; border-left:4px solid #4caf50; padding:10px 14px; }}
</style>
</head>
<body>
<h1>🎙️ Speech to Text in Focus</h1>
<p class="pill">Backend: {backend} &nbsp;•&nbsp; Auto-stop: {auto_stop}</p>

<p>Speak and have your words typed wherever your cursor is. Works in any app:
browser, editor, chat, email.</p>

<h2>How to dictate</h2>
<table>
  <tr><th>Mode</th><th>Shortcut</th><th>How</th></tr>
  <tr>
    <td><b>Toggle</b></td><td><kbd>{toggle}</kbd></td>
    <td>Press once to start, take your time, then press again to stop
        (or it stops on silence if auto-stop is on). Then the text is pasted.</td>
  </tr>
  <tr>
    <td><b>Push-to-talk</b></td><td><kbd>{ptt}</kbd></td>
    <td>Hold while speaking, release to transcribe.</td>
  </tr>
</table>
<h2>How you know what it is doing</h2>
<p>The microphone in the tray turns <span style="color:#dc3c3c">red</span> while
recording and <span style="color:#e0a528">orange</span> while transcribing; hover it
to see the state and the shortcut to press next.</p>
<p>Under tray → <b>Feedback</b> you pick how you are told, in two independent
channels:</p>
<ul>
  <li><b>Sound</b> — <i>Windows sounds</i> (soft, follow your volume), <i>Beeps</i>
      (loud) or <i>Silent</i>. Currently: <b>{sound}</b>.</li>
  <li><b>Floating status pill</b> — a small note above the tray that says what is
      happening and fades on its own. Currently: <b>{overlay}</b>.</li>
</ul>
<div class="tip">The pill is the quiet option: set the sound to <i>Silent</i> and
you still see everything. Native Windows notifications were tried and removed —
Windows keeps every one of them in the Action Center, which piles up fast.</div>

<h2>Stop modes (tray menu)</h2>
<p>Right-click the tray icon and toggle <b>“Auto-stop on silence”</b>:</p>
<ul>
  <li><b>On</b> — recording stops automatically after a short pause. Best for
      quick dictation.</li>
  <li><b>Off (manual)</b> — recording continues no matter how long you pause;
      it only stops when you press <kbd>{toggle}</kbd> again. Best when you want
      to think out loud without being cut off.</li>
</ul>
<div class="tip">This toggle applies to the current session. To set the default
permanently, edit <code>use_vad</code> under <code>[audio]</code> in
<code>config.toml</code>.</div>

<h2>Custom words (client and product names)</h2>
<p>Tray → <b>Custom words…</b> opens a list, one name per line. They are sent to
Whisper as context before each transcription, so it spells them the way you wrote
them. Changes apply to your next dictation — no restart.</p>
<p>It biases the model, it does not force it: expect a clear improvement on names
it was mangling, not perfection. Keep the list to <b>a dozen or so</b> names —
Whisper only reads about 224 tokens of context, so a long list dilutes every
entry. Currently loaded: <b>{n_terms}</b>.</p>
<div class="tip">Set <code>fuzzy = true</code> under <code>[dictionary]</code> in
<code>config.toml</code> and near-misses are fixed after transcribing:
<i>iberdrolla</i> → <b>Iberdrola</b>, <i>telefonica</i> → <b>Telefónica</b>. It only
looks at words of five letters or more, so everyday words are safe. When a name
comes out split in two ("iber drola"), similarity cannot see it — add an exact fix
under <code>[dictionary.replacements]</code>
(<code>"iber drola" = "Iberdrola"</code>), which always works.</div>

<h2>Local vs OpenAI</h2>
<p>Switch anytime from the tray menu → <b>Engine</b> (or set <code>backend</code>
under <code>[engine]</code> in <code>config.toml</code>):</p>
<ul>
  <li><b>Local</b> — runs on your computer. Free and private. Faster with an
      NVIDIA GPU (CUDA 12.x).</li>
  <li><b>OpenAI API</b> — uses the OpenAI API. Needs your own API key: set it from
      the tray menu → <b>Set OpenAI API key…</b> (or <code>stt --set-api-key</code>).
      Billed by audio length; silences are trimmed automatically to reduce cost,
      and each transcription's estimated cost is logged and shown under
      tray → <b>Usage / cost</b>.</li>
</ul>

<h2>Troubleshooting</h2>
<ul>
  <li><b>It cuts me off too soon</b> — turn off “Auto-stop on silence”, or raise
      <code>silence_timeout_ms</code> in <code>config.toml</code>.</li>
  <li><b>Nothing is pasted although I recorded</b> — if the recording caught no
      speech (a stray noise can trigger the auto-stop before you say anything) it
      is discarded on purpose rather than transcribed: asked to transcribe
      silence, Whisper invents text — usually your own vocabulary list. The log
      says <code>No speech in the recording</code>.</li>
  <li><b>It only hears me if I lean into the microphone</b> — first check
      tray → <b>Microphone</b>: <i>Windows default</i> is often not the one you talk
      into (a plugged-in headset outranks the laptop's array). Currently recording
      from <b>{microphone}</b>. If that is right, run
      <code>stt --calibrate-mic</code>: it measures your voice and suggests a
      <code>gain</code> for <code>config.toml</code>. Browsers apply automatic gain
      control to the microphone, which is why the same voice sounds louder in a web
      page than in an app that records the raw signal.</li>
  <li><b>Shortcut does nothing</b> — another app is probably using the same
      combination. Build a different one in tray → <b>Change shortcut</b>: tick the
      modifiers, pick a key, and it warns you about the risky ones.</li>
  <li><b>Text doesn't paste</b> — some elevated windows block paste; try a normal
      app first. Logs are in <code>logs/stt.log</code>.</li>
</ul>

<p style="color:#8a93a5; margin-top:2.5em; font-size:.9em;">Quit anytime from the
tray icon → Quit.</p>
</body>
</html>"""


def open_instructions(cfg: "Config") -> None:
    """Write the instructions to a temp HTML file and open it in the browser."""
    try:
        path = _write_temp("stt_instructions.html", _build_html(cfg))
        _open(path)
        log.info("Instructions opened: %s", path)
    except Exception:
        log.exception("Could not open the instructions.")


def open_config(config_path: str | Path, example_path: str | Path = "config.example.toml") -> None:
    """Open config.toml. If it doesn't exist, create it from the example if available."""
    try:
        p = Path(config_path)
        if not p.exists():
            ex = Path(example_path)
            if ex.exists():
                shutil.copy(ex, p)
                log.info("Created %s from the example.", p)
        if p.exists():
            _open(p)
        else:
            log.warning("No configuration file to open: %s", p)
    except Exception:
        log.exception("Could not open the configuration.")


def _build_usage_html(cfg: "Config") -> str:
    path = Path(cfg.usage.file)
    rows: list[dict[str, str]] = []
    if path.exists():
        try:
            with path.open(newline="", encoding="utf-8") as fh:
                rows = list(csv.DictReader(fh))
        except OSError as exc:
            log.debug("Could not read the usage file: %s", exc)

    style = (
        "body{font-family:Segoe UI,system-ui,sans-serif;max-width:760px;margin:40px auto;"
        "padding:0 20px;color:#1c2230;line-height:1.5;}"
        "h1{color:#2563a8;}table{border-collapse:collapse;width:100%;margin-top:1em;}"
        "td,th{border:1px solid #e2e6ee;padding:7px 10px;text-align:left;font-size:.95em;}"
        "th{background:#f4f6fa;}.total{font-size:1.2em;margin:1em 0;}"
        ".empty{background:#f4f6fa;padding:24px;border-radius:8px;text-align:center;color:#5a6072;}"
    )

    if not rows:
        body = (
            '<p class="empty">No transcriptions yet.<br><br>'
            "Cost is only tracked when using the <b>openai</b> backend. "
            "The <b>local</b> backend runs on your computer and is free.</p>"
        )
    else:
        total = 0.0
        total_secs = 0.0
        for r in rows:
            try:
                total += float(r.get("cost", 0))
                total_secs += float(r.get("seconds", 0))
            except (TypeError, ValueError):
                continue
        recent = rows[-200:]
        trail = "" if len(rows) <= 200 else f"<p>Showing the last 200 of {len(rows)} entries.</p>"
        cells = "".join(
            f"<tr><td>{html.escape(r.get('timestamp',''))}</td>"
            f"<td>{html.escape(r.get('model',''))}</td>"
            f"<td>{html.escape(r.get('seconds',''))}</td>"
            f"<td>${html.escape(r.get('cost',''))}</td></tr>"
            for r in recent
        )
        body = (
            f'<p class="total"><b>Total estimated cost: ${total:.4f} USD</b> '
            f"across {len(rows)} transcriptions ({total_secs/60:.1f} min of audio sent).</p>"
            "<p style='color:#8a93a5;font-size:.9em;'>Estimate based on configured "
            "per-minute rates, not the exact amount billed by OpenAI.</p>"
            f"{trail}"
            "<table><tr><th>When</th><th>Model</th><th>Seconds</th><th>Cost</th></tr>"
            f"{cells}</table>"
        )

    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        f"<title>Speech to Text in Focus — Usage &amp; Cost</title><style>{style}</style></head>"
        f"<body><h1>💸 Usage &amp; Cost</h1>{body}</body></html>"
    )


def open_usage_report(cfg: "Config") -> None:
    """Generate and open a usage/cost report (always works, even with no data)."""
    try:
        path = _write_temp("stt_usage.html", _build_usage_html(cfg))
        _open(path)
        log.info("Usage report opened: %s", path)
    except Exception:
        log.exception("Could not open the usage report.")


__all__ = ["open_instructions", "open_config", "open_usage_report"]
