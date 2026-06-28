"""Genera y abre una página de instrucciones (en inglés) en el navegador.

El HTML se construye con los atajos y ajustes reales del usuario, así siempre
refleja su configuración. Pensado para que otra persona entienda la app rápido.
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

if TYPE_CHECKING:
    from stt.config import Config

log = logging.getLogger(__name__)


def _open(path: str | Path) -> None:
    """Abre un archivo con la aplicación por defecto del sistema."""
    if hasattr(os, "startfile"):
        os.startfile(str(path))  # Windows
    else:
        webbrowser.open(f"file://{path}")


def _write_temp(name: str, content: str) -> str:
    path = os.path.join(tempfile.gettempdir(), name)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)
    return path


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
        path = _write_temp("stt_instructions.html", _build_html(cfg))
        _open(path)
        log.info("Instrucciones abiertas: %s", path)
    except Exception:
        log.exception("No se pudieron abrir las instrucciones.")


def open_config(config_path: str | Path, example_path: str | Path = "config.example.toml") -> None:
    """Abre el config.toml. Si no existe, lo crea desde el ejemplo si está disponible."""
    try:
        p = Path(config_path)
        if not p.exists():
            ex = Path(example_path)
            if ex.exists():
                shutil.copy(ex, p)
                log.info("Creado %s desde el ejemplo.", p)
        if p.exists():
            _open(p)
        else:
            log.warning("No hay fichero de configuración para abrir: %s", p)
    except Exception:
        log.exception("No se pudo abrir la configuración.")


def _build_usage_html(cfg: "Config") -> str:
    path = Path(cfg.usage.file)
    rows: list[dict[str, str]] = []
    if path.exists():
        try:
            with path.open(newline="", encoding="utf-8") as fh:
                rows = list(csv.DictReader(fh))
        except OSError as exc:
            log.debug("No se pudo leer el uso: %s", exc)

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
        f"<title>STT Dictation — Usage &amp; Cost</title><style>{style}</style></head>"
        f"<body><h1>💸 Usage &amp; Cost</h1>{body}</body></html>"
    )


def open_usage_report(cfg: "Config") -> None:
    """Genera y abre un informe de uso/coste (siempre funciona, aun sin datos)."""
    try:
        path = _write_temp("stt_usage.html", _build_usage_html(cfg))
        _open(path)
        log.info("Informe de uso abierto: %s", path)
    except Exception:
        log.exception("No se pudo abrir el informe de uso.")


__all__ = ["open_instructions", "open_config", "open_usage_report"]
