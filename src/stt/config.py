"""Carga y validación de la configuración (TOML -> dataclasses tipadas).

Usa solo la librería estándar (``tomllib``, disponible en Python 3.11+), de modo que
la configuración se puede cargar y testear sin dependencias de terceros ni Windows.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any, get_origin

# ---------------------------------------------------------------------------
# Valores permitidos (validación)
# ---------------------------------------------------------------------------

BACKENDS = ("local", "openai")
DEVICES = ("auto", "cuda", "cpu")
COMPUTE_TYPES = ("auto", "int8", "int8_float16", "float16", "float32")
HOTKEY_MODES = ("toggle", "push_to_talk")
INJECTION_METHODS = ("clipboard", "type")
LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")


class ConfigError(ValueError):
    """Error de configuración con un mensaje claro para el usuario."""


# ---------------------------------------------------------------------------
# Secciones
# ---------------------------------------------------------------------------


@dataclass
class EngineConfig:
    backend: str = "local"
    language: str = "es"  # ISO-639-1 o "auto"


@dataclass
class LocalConfig:
    model: str = "auto"
    device: str = "auto"
    compute_type: str = "auto"


@dataclass
class OpenAIConfig:
    model: str = "gpt-4o-transcribe"
    api_key_env: str = "OPENAI_API_KEY"


@dataclass
class HotkeyConfig:
    toggle: str = "ctrl+alt+space"
    push_to_talk: str = "ctrl+alt+v"
    default_mode: str = "toggle"


@dataclass
class AudioConfig:
    sample_rate: int = 16000
    channels: int = 1
    silence_timeout_ms: int = 1500
    use_vad: bool = True
    # Umbral adaptativo: estima el ruido de fondo y ajusta el corte solo (recomendado).
    auto_threshold: bool = True
    # Umbral fijo (RMS, 0-1) usado solo si auto_threshold = false. Ver --calibrate-mic.
    silence_threshold: float = 0.006


@dataclass
class InjectionConfig:
    method: str = "clipboard"
    restore_clipboard: bool = True
    paste_delay_ms: int = 80


@dataclass
class DictionaryConfig:
    terms: list[str] = field(default_factory=list)
    replacements: dict[str, str] = field(default_factory=dict)


@dataclass
class LoggingConfig:
    level: str = "INFO"
    dir: str = "logs"


@dataclass
class Config:
    engine: EngineConfig = field(default_factory=EngineConfig)
    local: LocalConfig = field(default_factory=LocalConfig)
    openai: OpenAIConfig = field(default_factory=OpenAIConfig)
    hotkey: HotkeyConfig = field(default_factory=HotkeyConfig)
    audio: AudioConfig = field(default_factory=AudioConfig)
    injection: InjectionConfig = field(default_factory=InjectionConfig)
    dictionary: DictionaryConfig = field(default_factory=DictionaryConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)


# ---------------------------------------------------------------------------
# Construcción desde dict + validación
# ---------------------------------------------------------------------------


def _build_section(cls: type, data: dict[str, Any], section_name: str) -> Any:
    """Crea una dataclass a partir de un dict, rechazando claves desconocidas
    y comprobando los tipos básicos de cada campo."""
    valid = {f.name: f for f in fields(cls)}
    unknown = set(data) - set(valid)
    if unknown:
        raise ConfigError(
            f"[{section_name}] contiene claves desconocidas: {', '.join(sorted(unknown))}"
        )

    kwargs: dict[str, Any] = {}
    for name, f in valid.items():
        if name not in data:
            continue
        value = data[name]
        _check_type(value, f.type, f"{section_name}.{name}")
        kwargs[name] = value
    return cls(**kwargs)


def _check_type(value: Any, annotation: Any, dotted: str) -> None:
    """Validación de tipos ligera para los tipos usados en la config."""
    # Anotaciones vienen como strings por "from __future__ import annotations":
    # mapeamos las pocas que usamos.
    simple = {
        "str": str,
        "int": int,
        "float": float,
        "bool": bool,
        "list[str]": list,
        "dict[str, str]": dict,
    }
    expected = simple.get(annotation if isinstance(annotation, str) else None)
    if expected is None:
        origin = get_origin(annotation)
        expected = origin or annotation

    # bool es subclase de int: no permitir bool donde se espera int y viceversa.
    if expected is int and isinstance(value, bool):
        raise ConfigError(f"{dotted} debe ser un entero, no un booleano.")
    if expected is bool and not isinstance(value, bool):
        raise ConfigError(f"{dotted} debe ser true/false.")
    # Aceptar enteros donde se espera un float (p. ej. 0 en vez de 0.0).
    if expected is float and isinstance(value, int) and not isinstance(value, bool):
        return
    if not isinstance(value, expected):
        raise ConfigError(
            f"{dotted} tiene un tipo inválido: se esperaba {getattr(expected, '__name__', expected)}."
        )


def _one_of(value: str, allowed: tuple[str, ...], dotted: str) -> None:
    if value not in allowed:
        raise ConfigError(f"{dotted} debe ser uno de {allowed}, no {value!r}.")


def _validate(cfg: Config) -> None:
    _one_of(cfg.engine.backend, BACKENDS, "engine.backend")
    _one_of(cfg.local.device, DEVICES, "local.device")
    _one_of(cfg.local.compute_type, COMPUTE_TYPES, "local.compute_type")
    _one_of(cfg.hotkey.default_mode, HOTKEY_MODES, "hotkey.default_mode")
    _one_of(cfg.injection.method, INJECTION_METHODS, "injection.method")
    _one_of(cfg.logging.level.upper(), LOG_LEVELS, "logging.level")

    if cfg.audio.sample_rate <= 0:
        raise ConfigError("audio.sample_rate debe ser positivo.")
    if cfg.audio.channels not in (1, 2):
        raise ConfigError("audio.channels debe ser 1 o 2.")
    if cfg.audio.silence_timeout_ms < 0:
        raise ConfigError("audio.silence_timeout_ms no puede ser negativo.")
    if not 0 < cfg.audio.silence_threshold < 1:
        raise ConfigError("audio.silence_threshold debe estar entre 0 y 1 (p. ej. 0.006).")
    if not cfg.hotkey.toggle or not cfg.hotkey.push_to_talk:
        raise ConfigError("Los atajos hotkey.toggle y hotkey.push_to_talk no pueden estar vacíos.")
    if cfg.hotkey.toggle == cfg.hotkey.push_to_talk:
        raise ConfigError("hotkey.toggle y hotkey.push_to_talk deben ser distintos.")


def from_dict(data: dict[str, Any]) -> Config:
    """Construye y valida una Config a partir de un dict (p. ej. de TOML)."""
    known_sections = {f.name for f in fields(Config)}
    unknown = set(data) - known_sections
    if unknown:
        raise ConfigError(f"Secciones desconocidas en la config: {', '.join(sorted(unknown))}")

    # Cada sección es una dataclass; las construimos validando claves y tipos.
    builders = {
        "engine": EngineConfig,
        "local": LocalConfig,
        "openai": OpenAIConfig,
        "hotkey": HotkeyConfig,
        "audio": AudioConfig,
        "injection": InjectionConfig,
        "dictionary": DictionaryConfig,
        "logging": LoggingConfig,
    }
    kwargs: dict[str, Any] = {}
    for name, cls in builders.items():
        if name in data:
            if not isinstance(data[name], dict):
                raise ConfigError(f"La sección [{name}] debe ser una tabla TOML.")
            kwargs[name] = _build_section(cls, data[name], name)

    cfg = Config(**kwargs)
    _validate(cfg)
    return cfg


def load(path: str | Path | None = None) -> Config:
    """Carga la config desde un fichero TOML. Si ``path`` es None o no existe,
    devuelve la configuración por defecto."""
    if path is None:
        return Config()
    p = Path(path)
    if not p.exists():
        raise ConfigError(f"No existe el fichero de configuración: {p}")
    try:
        with p.open("rb") as fh:
            data = tomllib.load(fh)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"Error de sintaxis TOML en {p}: {exc}") from exc
    return from_dict(data)


__all__ = ["Config", "ConfigError", "load", "from_dict"]
