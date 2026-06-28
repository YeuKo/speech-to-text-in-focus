"""Genera y abre una página de instrucciones (en inglés) en el navegador.

El HTML se construye con los atajos y ajustes reales del usuario, así siempre
refleja su configuración. Pensado para que otra persona entienda la app rápido.
"""

from __future__ import annotations

import html
import logging
import os
import tempfile
import webbrowser
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from stt.config import Config

log = logging.getLogger(__name__)


def _build_html(cfg: "Config") -> str:
    toggle = html.escape(cfg.hotkey.toggle)
    ptt = html.escape(cfg.hotkey.push_to_talk)
    backend = html.escape(cfg.engine.backend)
    auto_stop = "on" if cfg.audio.use_vad else "off (manual)"
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>STT Dictation — Instructions</title>
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
<h1>🎙️ STT Dictation</h1>
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
<p>You hear a rising beep when recording starts and a falling beep when it stops.
The tray icon turns <span style="color:#dc3c3c">red</span> while recording and
<span style="color:#e0a528">orange</span> while transcribing.</p>

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

<h2>Custom words (proper nouns)</h2>
<p>Add names or jargon under <code>[dictionary]</code> in <code>config.toml</code>
so they are recognised correctly (e.g. brand names, people, technical terms).</p>

<h2>Local vs OpenAI</h2>
<p>In <code>config.toml</code>, set <code>backend</code> under <code>[engine]</code>:</p>
<ul>
  <li><b>local</b> — runs on your computer. Free and private. Faster with an
      NVIDIA GPU (CUDA 12.x).</li>
  <li><b>openai</b> — uses the OpenAI API. Needs your own API key
      (run <code>stt --set-api-key</code>). Billed by audio length; silences are
      trimmed automatically to reduce cost, and each transcription's estimated
      cost is logged to <code>logs/usage.csv</code>.</li>
</ul>

<h2>Troubleshooting</h2>
<ul>
  <li><b>It cuts me off too soon</b> — turn off “Auto-stop on silence”, or raise
      <code>silence_timeout_ms</code> in <code>config.toml</code>.</li>
  <li><b>Shortcut does nothing</b> — another app may use the same combo; change
      <code>toggle</code> / <code>push_to_talk</code> in <code>config.toml</code>.</li>
  <li><b>Text doesn't paste</b> — some elevated windows block paste; try a normal
      app first. Logs are in <code>logs/stt.log</code>.</li>
</ul>

<p style="color:#8a93a5; margin-top:2.5em; font-size:.9em;">Quit anytime from the
tray icon → Quit.</p>
</body>
</html>"""


def open_instructions(cfg: "Config") -> None:
    """Escribe las instrucciones a un HTML temporal y lo abre en el navegador."""
    try:
        path = os.path.join(tempfile.gettempdir(), "stt_instructions.html")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(_build_html(cfg))
        if hasattr(os, "startfile"):
            os.startfile(path)  # Windows: abre con el navegador por defecto
        else:
            webbrowser.open(f"file://{path}")
        log.info("Instrucciones abiertas: %s", path)
    except Exception:
        log.exception("No se pudieron abrir las instrucciones.")


__all__ = ["open_instructions"]
