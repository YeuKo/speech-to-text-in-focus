# STT Dictation

> Press a hotkey, speak, and your words are typed wherever your cursor is — in any Windows app.

A lightweight voice‑dictation tool for **Windows**. It transcribes your speech with
[Whisper](https://github.com/openai/whisper) and pastes the result into the focused
window (browser, editor, chat, email…). It runs **locally by default** (free and
private), with an optional **OpenAI API** backend for machines without a capable GPU.

![Python](https://img.shields.io/badge/python-3.11%2B-blue)
![Platform](https://img.shields.io/badge/platform-Windows-0078D6)
![License](https://img.shields.io/badge/license-MIT-green)

## Features

- 🎙️ **Global hotkeys** — toggle mode (press to start/stop) and push‑to‑talk, independently configurable.
- 🧠 **Local Whisper** via [`faster-whisper`](https://github.com/SYSTRAN/faster-whisper) — free, private, GPU‑accelerated.
- ☁️ **OpenAI API backend** — optional fallback; switchable at runtime from the tray.
- 🖱️ **Pastes at the cursor** — clipboard + Ctrl+V (Unicode‑safe), restoring your previous clipboard.
- 📒 **Custom dictionary** — bias recognition toward proper nouns and fix common mistranscriptions.
- 🔇 **Adaptive silence detection** — auto‑stops on silence, adapting to any microphone; or fully manual.
- 🟢 **System tray UI** — colour‑coded state, engine switch, settings, help and usage, all in one menu.
- 💸 **Cost tracking** — for the API backend, estimates and logs the cost of each transcription.
- 🔒 **Secure & private** — local‑first; the API key is stored in the OS credential store, never in files.
- ⚡ **Auto hardware detection** — uses an NVIDIA GPU (CUDA 12.x) if available, otherwise CPU.

## Requirements

- **Windows 10/11** (the hotkeys, microphone capture and paste use Windows APIs).
- **Python 3.11+** (native Windows build from [python.org](https://www.python.org/) — not the Microsoft Store stub).
- *Optional, for GPU acceleration:* an NVIDIA GPU with the **CUDA 12.x Toolkit** installed.

> The code can be edited from WSL/Linux, but it must **run on native Windows** —
> global hotkeys, microphone access and clipboard paste do not work inside WSL.

## Installation

```powershell
git clone https://github.com/fjgca/stt-dictation.git
cd stt-dictation

python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[windows]"

copy config.example.toml config.toml   # optional: customise settings
```

## Usage

```powershell
stt
```

The app starts in the **system tray**. Then:

| Action | How |
|---|---|
| **Dictate (toggle)** | Press `Ctrl+Alt+Space`, speak, press again (or stop on silence). |
| **Dictate (push‑to‑talk)** | Hold `Ctrl+Alt+V` while speaking, release to transcribe. |
| **Switch engine / mode** | Right‑click the tray icon → *Engine* / *Auto‑stop on silence*. |
| **Settings, help, usage** | Tray menu → *Open config file* / *Help* / *Usage / cost*. |
| **Quit** | Tray menu → *Quit*. |

Shortcuts and everything else are configured in `config.toml` (see `config.example.toml`).

### Command‑line tools

```powershell
stt --selftest        # synthesize speech with the Windows voice and transcribe it (no mic)
stt --calibrate-mic   # measure your microphone and recommend a silence threshold
stt --set-api-key     # store your OpenAI API key securely (keyring)
stt --version
```

## Local vs OpenAI

| | **Local** (default) | **OpenAI API** |
|---|---|---|
| Cost | Free | Billed per audio minute |
| Privacy | Audio never leaves your PC | Audio sent to OpenAI |
| Speed | Fast with a GPU; slower on CPU | Fast on any machine |
| Setup | None | Your own API key |

Switch anytime from the tray → **Engine**. For the API backend, set your key via the
tray (**Set OpenAI API key…**) or `stt --set-api-key`; silences are trimmed before
sending to keep the bill low, and each transcription's estimated cost is recorded to
`logs/usage.csv` (viewable from the tray → *Usage / cost*).

### GPU acceleration

`faster-whisper` needs the **CUDA 12.x** runtime (`cublas64_12.dll`, cuDNN). Install the
[CUDA 12.x Toolkit](https://developer.nvidia.com/cuda-toolkit-archive) (it can coexist
with newer CUDA versions). Without a usable GPU the app falls back to CPU automatically
with a smaller model.

## Custom dictionary

Improve recognition of names and jargon in `config.toml`:

```toml
[dictionary]
terms = ["Anthropic", "Kubernetes", "Grafana"]   # biases Whisper towards these

[dictionary.replacements]                          # fixes applied after transcription
"anthropik" = "Anthropic"
"cubernetes" = "Kubernetes"
```

## Privacy & security

- **Local‑first:** with the default `local` backend, audio is processed entirely on
  your machine and never leaves it.
- **API key:** stored in the Windows Credential Manager via [`keyring`](https://github.com/jaraco/keyring),
  read from there or from the `OPENAI_API_KEY` environment variable — never written to
  config files or logs.
- **Logs:** transcribed text is only written to the log file at `DEBUG` level; at the
  default `INFO` level only its length is recorded.
- **No secrets in the repo:** `config.toml`, `logs/` and downloaded models are git‑ignored.

## How it works

```
Hotkey ─▶ Controller (state machine) ─▶ Recorder (mic + VAD)
                  │                              │
                  ▼                              ▼
            Tray UI (status)            Transcriber backend
                                        ├─ Local (faster-whisper)
                                        └─ OpenAI API
                                               │
                                               ▼
                                   Post‑process (dictionary)
                                               │
                                               ▼
                                   Text injector (clipboard ▶ Ctrl+V)
```

```
src/stt/
├── __main__.py          # entry point, CLI, tray wiring
├── controller.py        # state machine (idle / recording / transcribing)
├── config.py            # typed TOML config + validation
├── hardware.py          # GPU/CPU autodetection
├── hotkey.py            # global shortcuts (toggle + push-to-talk)
├── postprocess.py       # dictionary and replacements
├── inject.py            # text injection (clipboard / typing)
├── sounds.py            # audible feedback
├── keystore.py          # secure API-key storage
├── usage.py             # API cost tracking
├── audio/               # microphone capture + silence trimming
├── transcribe/          # backend interface + local / OpenAI implementations
└── ui/                  # tray icon, dialogs, help pages
```

## Development

```bash
pip install -e ".[dev]"     # core + dev tools
pytest                       # unit tests (config, dictionary, silence, usage)
ruff check src tests
```

The pure‑logic modules (config, dictionary, silence trimming, usage) are covered by
tests and run on any platform; the Windows‑specific parts are tested manually.

## Roadmap

- [x] Local + OpenAI backends with runtime switching
- [x] Adaptive silence detection and manual mode
- [x] Tray UI, custom dictionary, cost tracking
- [ ] Packaged `.exe` installer (PyInstaller)
- [ ] Streaming / partial results
- [ ] Per‑application profiles

## License

[MIT](LICENSE) © fjgca
