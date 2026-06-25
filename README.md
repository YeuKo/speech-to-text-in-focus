# STT Dictation

Dictado por voz para **Windows**: pulsas un atajo global, hablas, y el texto se
transcribe e **inserta donde tengas el foco del cursor** (navegador, editor, chat…).

- Motor **local** por defecto con [`faster-whisper`](https://github.com/SYSTRAN/faster-whisper).
- Alternativa por **API de OpenAI** (configurable) por si el local va lento.
- **Diccionario de palabras propias** (nombres propios, jerga, términos técnicos).
- Dos modos de activación, configurables y con **atajos separados**:
  - **Toggle**: pulsas para empezar; para por silencio (VAD) o al repulsar.
  - **Push-to-talk**: mantienes pulsado mientras hablas.
- **Autodetección de hardware** (usa GPU NVIDIA/CUDA si está disponible, si no CPU).

> Estado: **Fase 0 — andamiaje**. La estructura y la configuración están listas;
> los componentes están esbozados con sus interfaces y se implementan en el MVP (Fase 1).
> Ver [PLAN.md](PLAN.md) para el roadmap completo.

## ⚠️ Plataforma: Windows nativo (no WSL)

Los atajos globales, la captura de micrófono y el pegado en la ventana con foco usan
APIs de Windows que **no funcionan dentro de WSL**. El código se puede editar desde WSL,
pero **ejecutarlo y probarlo requiere Python nativo de Windows**.

## Instalación (en Windows)

```powershell
# Requiere Python 3.11+ nativo de Windows
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[windows,dev]"
```

> Para acelerar el modelo local con GPU NVIDIA hace falta CUDA + cuDNN compatibles
> con CTranslate2. Si no hay GPU, funciona en CPU automáticamente (modelo más pequeño).

## Configuración

Copia el ejemplo y ajústalo:

```powershell
copy config.example.toml config.toml
```

La **API key de OpenAI** no se guarda en el fichero: se lee de la variable de entorno
indicada en `[openai].api_key_env` (por defecto `OPENAI_API_KEY`) o del almacén seguro
de Windows (`keyring`).

## Uso

```powershell
stt            # arranca en la bandeja del sistema
stt --config config.toml
```

## Desarrollo

```bash
pip install -e ".[dev]"
pytest          # tests (el post-procesado/diccionario es testeable sin Windows)
ruff check src tests
```

## Estructura

```
src/stt/
├── __main__.py          # arranque, CLI, bandeja
├── controller.py        # máquina de estados (idle/recording/transcribing)
├── config.py            # carga/validación de config TOML
├── logging_setup.py     # logging a fichero rotativo
├── hardware.py          # autodetección GPU/CPU y compute_type
├── hotkey.py            # atajos globales (toggle + push-to-talk)
├── postprocess.py       # diccionario y formateo (implementado + tests)
├── inject.py            # inyección de texto (portapapeles / tecleo)
├── audio/recorder.py    # captura de micrófono + VAD
├── transcribe/
│   ├── base.py          # Protocolo de backend + factory
│   ├── local.py         # faster-whisper
│   └── openai_api.py    # API de OpenAI
└── ui/                  # bandeja, ajustes, overlay
```
