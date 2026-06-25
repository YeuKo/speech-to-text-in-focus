# Plan — Aplicación de transcripción STT para Windows

## 1. Objetivo

Aplicación de dictado por voz para Windows:

- Se activa con un **atajo de teclado global**.
- Captura el audio del micrófono mientras hablas.
- Transcribe con **Whisper** (modelo **local** por defecto, **API de OpenAI** como alternativa configurable).
- **Inyecta el texto** donde esté el foco del cursor (cualquier app: navegador, editor, chat…).
- Soporta un **diccionario de palabras propias** (nombres propios, jerga, términos técnicos).
- Uso personal al principio, con vistas a poder distribuirse a otros más adelante.

## 2. Decisiones clave (con recomendación)

| Decisión | Opciones | Recomendación |
|---|---|---|
| Lenguaje | Python / C#/.NET / Rust | **Python** — ecosistema Whisper maduro, desarrollo rápido. |
| Motor local | `openai-whisper` / **`faster-whisper`** / `whisper.cpp` | **`faster-whisper`** (CTranslate2): 4-5× más rápido, menos RAM, soporta CPU y GPU. |
| Modelo por defecto | tiny…large-v3 / **large-v3-turbo** / distil | **`large-v3-turbo`** si hay GPU; **`small`/`base`** en CPU pura. Configurable. |
| Modo de activación | Push-to-talk (mantener) / Toggle (pulsar para iniciar y parar) | **Ambos**, configurable. Por defecto **toggle** + auto-stop por silencio (VAD). |
| Inyección de texto | Simular tecleo / **Portapapeles + Ctrl+V** | **Portapapeles + Ctrl+V** (rápido y soporta Unicode/acentos), restaurando el portapapeles después. Tecleo como fallback. |
| Aceleración | CPU / **GPU (CUDA)** | Detectar automáticamente. GPU NVIDIA acelera mucho el modelo local. |

> Estas tres son las que más afectan al diseño: **modo de activación**, **método de inyección** y **CPU vs GPU**. Las dejo con valores por defecto sensatos y configurables.

## 3. Stack tecnológico

- **Lenguaje:** Python 3.11+
- **STT local:** `faster-whisper`
- **STT remoto:** `openai` (endpoint `audio.transcriptions`, modelo `whisper-1` / `gpt-4o-transcribe`)
- **Captura de audio:** `sounddevice` (+ `numpy`)
- **VAD (detección de voz/silencio):** `silero-vad` o el VAD integrado en faster-whisper
- **Atajo global:** `keyboard` (sencillo, requiere admin para algunos atajos) o `pynput` / API Win32 (`RegisterHotKey`)
- **Inyección de texto:** `pyperclip` + envío de Ctrl+V con `keyboard`/`pynput`; alternativa `pyautogui.write`
- **Bandeja del sistema (system tray):** `pystray` + `Pillow`
- **Config/GUI ajustes:** fichero `TOML` (`tomli`/`tomllib`) + pequeña ventana de ajustes (`PySide6` o `tkinter`)
- **Empaquetado:** `PyInstaller` (ejecutable `.exe`); más adelante instalador con Inno Setup / MSIX
- **Logging:** `logging` a fichero rotativo

## 4. Arquitectura / componentes

```
+-------------------+        +------------------+
|  Hotkey Listener  | -----> |   Controller     |
|  (global)         |        |  (máquina estados|
+-------------------+        |  idle/recording/ |
                             |  transcribing)   |
+-------------------+        +---------+--------+
|  System Tray UI   | <----------------|
|  (estado/menú)    |                  |
+-------------------+      +-----------v-----------+
                          |   Audio Recorder      |
+-------------------+     |  (sounddevice + VAD)  |
| Config Manager    |     +-----------+-----------+
| (TOML + perfiles) |                 |
+---------+---------+      +----------v-----------+
          |               |  Transcriber          |
          |               |  ┌─ LocalBackend       |
          +-------------->|  └─ OpenAIBackend       |
                          +----------+-----------+
                                     |
                          +----------v-----------+
                          |  Post-procesado       |
                          |  (diccionario,        |
                          |   puntuación, formato)|
                          +----------+-----------+
                                     |
                          +----------v-----------+
                          |  Text Injector        |
                          |  (portapapeles/teclear)|
                          +----------------------+
```

**Interfaz común de backends** (clave para conmutar local/API sin tocar el resto):

```python
class TranscriberBackend(Protocol):
    def transcribe(self, audio: np.ndarray, *, sample_rate: int,
                   language: str | None, prompt: str | None) -> str: ...
```

- `LocalBackend` → `faster_whisper.WhisperModel(...)`
- `OpenAIBackend` → `client.audio.transcriptions.create(...)`

## 5. Flujo de funcionamiento

1. La app arranca minimizada en la **bandeja del sistema**; carga config y (si es local) precarga el modelo en memoria.
2. El usuario pulsa el **atajo global** → empieza la grabación (indicador visual + sonido opcional).
3. El audio se acumula; el **VAD** detecta el fin del habla (silencio) o el usuario vuelve a pulsar el atajo (toggle).
4. El audio va al **backend** seleccionado (local o API) con el `prompt`/diccionario aplicado.
5. El texto pasa por **post-procesado** (sustituciones del diccionario, mayúsculas, puntuación).
6. El **Text Injector** copia el resultado al portapapeles y envía **Ctrl+V** en la ventana con foco; restaura el portapapeles previo.
7. Vuelta a estado *idle*.

## 6. Diccionario de palabras propias

Tres mecanismos combinables (de menor a mayor coste):

1. **`initial_prompt` de Whisper** — se pasa una lista de términos como contexto ("Vocabulario: Fjgca, Anthropic, Kubernetes, ...") para sesgar el reconocimiento. Funciona en local y API. Limitado en longitud pero muy efectivo para nombres propios.
2. **Sustitución por reglas (post-procesado)** — diccionario `mal_reconocido → correcto`, incluyendo coincidencia **fuzzy** (`rapidfuzz`) para captar variantes fonéticas ("anthropik" → "Anthropic").
3. **(Avanzado / opcional)** *hotwords* / *biasing* a nivel de decodificación si se usa whisper.cpp con `--grammar`/word boost.

Formato propuesto en config:

```toml
[dictionary]
terms = ["Anthropic", "Kubernetes", "Fjgca", "Grafana"]

[dictionary.replacements]
"anthropik" = "Anthropic"
"cubernetes" = "Kubernetes"
```

## 7. Configuración local vs API

```toml
[engine]
backend = "local"          # "local" | "openai"
language = "es"            # o "auto"

[local]
model = "large-v3-turbo"   # tiny|base|small|medium|large-v3|large-v3-turbo|distil-*
device = "auto"           # auto|cpu|cuda
compute_type = "auto"     # int8|int8_float16|float16...

[openai]
model = "gpt-4o-transcribe"   # o "whisper-1"
api_key_env = "OPENAI_API_KEY"  # leer de variable de entorno, NO hardcodear

[hotkey]
mode = "toggle"           # toggle | push_to_talk
combo = "ctrl+alt+space"

[audio]
silence_timeout_ms = 1500
```

- La **API key** se lee de variable de entorno o almacén seguro de Windows (`keyring`), nunca en texto plano.
- Conmutar backend = cambiar una línea o un toggle en la bandeja; misma interfaz interna.

## 8. Roadmap por fases

**Fase 0 — Andamiaje (0,5 día)**
- Estructura del repo, `pyproject.toml`, entorno virtual, `git init`, logging, config TOML.

**Fase 1 — MVP funcional (núcleo)**
- Captura de audio con sounddevice.
- Backend local con faster-whisper (modelo pequeño).
- Atajo global (toggle) + inyección por portapapeles.
- Probar el bucle completo: atajo → hablar → texto en el foco.

**Fase 2 — Calidad de reconocimiento**
- VAD / auto-stop por silencio.
- Diccionario (initial_prompt + sustituciones fuzzy).
- Selección de idioma y modelo por config.

**Fase 3 — Backend OpenAI + UX**
- `OpenAIBackend` + conmutador local/API.
- Bandeja del sistema con estado e indicador visual + sonidos.
- Ventana de ajustes básica.

**Fase 4 — Robustez y distribución**
- Manejo de errores (sin micro, sin GPU, API caída → fallback).
- Empaquetado con PyInstaller; arranque con Windows.
- Instalador (Inno Setup) para terceros.

## 9. Empaquetado / distribución

- **Personal:** `.exe` con PyInstaller + acceso directo / arranque automático.
- **Terceros:** instalador Inno Setup o MSIX; asistente de primer uso (elegir modelo, descargar pesos, permisos de micro).
- Modelos locales: descarga bajo demanda (no empaquetar pesos grandes en el `.exe`).

## 10. Mejoras sugeridas

- **Streaming / latencia baja:** transcribir por *chunks* mientras hablas para ver texto parcial, en vez de esperar al final.
- **Indicador visual flotante** (overlay) cerca del cursor mostrando "🎙️ escuchando…".
- **Sonidos de feedback** al iniciar/terminar (muy útil sin mirar la pantalla).
- **Modo comando de voz:** "nueva línea", "borra eso", "punto", "coma", "en mayúsculas".
- **Perfiles por aplicación:** distinto diccionario/idioma según la app con foco (p. ej. código en VS Code vs email).
- **Historial de transcripciones** local (con opción de desactivar por privacidad).
- **Auto-puntuación y formateo** (Whisper ya puntúa; añadir reglas para listas, code blocks…).
- **Detección automática de idioma** o cambio rápido es↔en con un segundo atajo.
- **Fallback inteligente:** si el local tarda más de X s o falla, reintentar por API automáticamente.
- **Privacidad primero:** todo local por defecto; avisar claramente cuando se envía audio a OpenAI.
- **Métricas de uso** (tiempo de transcripción, RTF) para ajustar modelo/calidad.
- **Soporte de portapapeles seguro:** guardar y restaurar el contenido previo tras el Ctrl+V.
- **Tests:** unidades para post-procesado/diccionario; prueba E2E del bucle con audio grabado.

## 11. Riesgos / retos técnicos

- **Atajos globales y foco:** algunos atajos requieren permisos de administrador; conflictos con atajos de otras apps. Probar `RegisterHotKey` Win32 si `keyboard` da problemas.
- **Inyección en apps con foco:** ciertas apps (juegos, ventanas elevadas) bloquean SendInput/paste; documentar limitaciones.
- **Rendimiento local en CPU:** modelos grandes pueden ir lentos; de ahí el fallback a API y la elección de modelo turbo/distil.
- **Latencia de carga del modelo:** precargar al iniciar para que el primer dictado no espere.
- **Coste/privacidad de la API:** dejar claro el envío de audio; control de gasto.

## 12. Estructura de proyecto propuesta

```
stt/
├── pyproject.toml
├── README.md
├── config.example.toml
├── src/stt/
│   ├── __main__.py          # arranque, bandeja
│   ├── controller.py        # máquina de estados
│   ├── config.py            # carga/validación TOML
│   ├── hotkey.py            # atajo global
│   ├── audio/recorder.py    # captura + VAD
│   ├── transcribe/
│   │   ├── base.py          # Protocolo de backend
│   │   ├── local.py         # faster-whisper
│   │   └── openai_api.py    # API OpenAI
│   ├── postprocess.py       # diccionario, puntuación
│   ├── inject.py            # portapapeles / tecleo
│   └── ui/                  # bandeja, ajustes, overlay
└── tests/
```
```
