"""Configuration loading and validation (TOML -> typed dataclasses).

Uses only the standard library (``tomllib``, available in Python 3.11+), so the
configuration can be loaded and tested without third-party dependencies or Windows.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any, get_origin

# ---------------------------------------------------------------------------
# Allowed values (validation)
# ---------------------------------------------------------------------------

BACKENDS = ("local", "openai")
DEVICES = ("auto", "cuda", "cpu")
COMPUTE_TYPES = ("auto", "int8", "int8_float16", "float16", "float32")
HOTKEY_MODES = ("toggle", "push_to_talk")
INJECTION_METHODS = ("clipboard", "type")
LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")


class ConfigError(ValueError):
    """Configuration error with a clear, user-facing message."""


# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------


@dataclass
class EngineConfig:
    backend: str = "local"
    language: str = "auto"  # ISO-639-1 (e.g. "en", "es") or "auto" to autodetect


@dataclass
class LocalConfig:
    model: str = "auto"
    device: str = "auto"
    compute_type: str = "auto"


@dataclass
class OpenAIConfig:
    model: str = "gpt-4o-transcribe"
    api_key_env: str = "OPENAI_API_KEY"
    # Trim silence before sending (reduces the billed duration).
    trim_silence: bool = True


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
    # Adaptive threshold: estimate background noise and adjust the cut on its own
    # (recommended).
    auto_threshold: bool = True
    # Fixed threshold (RMS, 0-1), used only when auto_threshold = false. See
    # --calibrate-mic.
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


def _default_rates() -> dict[str, float]:
    # USD per minute of audio (estimates; adjust if OpenAI changes pricing).
    return {
        "gpt-4o-transcribe": 0.006,
        "gpt-4o-mini-transcribe": 0.003,
        "whisper-1": 0.006,
    }


@dataclass
class UsageConfig:
    track: bool = True
    file: str = "logs/usage.csv"
    price_per_min: dict[str, float] = field(default_factory=_default_rates)


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
    usage: UsageConfig = field(default_factory=UsageConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)


# ---------------------------------------------------------------------------
# Building from a dict + validation
# ---------------------------------------------------------------------------


def _build_section(cls: type, data: dict[str, Any], section_name: str) -> Any:
    """Build a dataclass from a dict, rejecting unknown keys and checking the
    basic type of each field."""
    valid = {f.name: f for f in fields(cls)}
    unknown = set(data) - set(valid)
    if unknown:
        raise ConfigError(
            f"[{section_name}] contains unknown keys: {', '.join(sorted(unknown))}"
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
    """Lightweight type validation for the types used in the config."""
    # Annotations arrive as strings due to "from __future__ import annotations";
    # we map the few we use.
    simple = {
        "str": str,
        "int": int,
        "float": float,
        "bool": bool,
        "list[str]": list,
        "dict[str, str]": dict,
        "dict[str, float]": dict,
    }
    expected = simple.get(annotation if isinstance(annotation, str) else None)
    if expected is None:
        origin = get_origin(annotation)
        expected = origin or annotation

    # bool is a subclass of int: don't allow bool where int is expected, or vice versa.
    if expected is int and isinstance(value, bool):
        raise ConfigError(f"{dotted} must be an integer, not a boolean.")
    if expected is bool and not isinstance(value, bool):
        raise ConfigError(f"{dotted} must be true/false.")
    # Accept integers where a float is expected (e.g. 0 instead of 0.0).
    if expected is float and isinstance(value, int) and not isinstance(value, bool):
        return
    if not isinstance(value, expected):
        raise ConfigError(
            f"{dotted} has an invalid type: expected {getattr(expected, '__name__', expected)}."
        )


def _one_of(value: str, allowed: tuple[str, ...], dotted: str) -> None:
    if value not in allowed:
        raise ConfigError(f"{dotted} must be one of {allowed}, not {value!r}.")


def _validate(cfg: Config) -> None:
    _one_of(cfg.engine.backend, BACKENDS, "engine.backend")
    _one_of(cfg.local.device, DEVICES, "local.device")
    _one_of(cfg.local.compute_type, COMPUTE_TYPES, "local.compute_type")
    _one_of(cfg.hotkey.default_mode, HOTKEY_MODES, "hotkey.default_mode")
    _one_of(cfg.injection.method, INJECTION_METHODS, "injection.method")
    _one_of(cfg.logging.level.upper(), LOG_LEVELS, "logging.level")

    if cfg.audio.sample_rate <= 0:
        raise ConfigError("audio.sample_rate must be positive.")
    if cfg.audio.channels not in (1, 2):
        raise ConfigError("audio.channels must be 1 or 2.")
    if cfg.audio.silence_timeout_ms < 0:
        raise ConfigError("audio.silence_timeout_ms cannot be negative.")
    if not 0 < cfg.audio.silence_threshold < 1:
        raise ConfigError("audio.silence_threshold must be between 0 and 1 (e.g. 0.006).")
    if not cfg.hotkey.toggle or not cfg.hotkey.push_to_talk:
        raise ConfigError("hotkey.toggle and hotkey.push_to_talk cannot be empty.")
    if cfg.hotkey.toggle == cfg.hotkey.push_to_talk:
        raise ConfigError("hotkey.toggle and hotkey.push_to_talk must be different.")
    for model, rate in cfg.usage.price_per_min.items():
        if not isinstance(rate, (int, float)) or isinstance(rate, bool) or rate < 0:
            raise ConfigError(f"usage.price_per_min['{model}'] must be a number >= 0.")


def from_dict(data: dict[str, Any]) -> Config:
    """Build and validate a Config from a dict (e.g. parsed from TOML)."""
    known_sections = {f.name for f in fields(Config)}
    unknown = set(data) - known_sections
    if unknown:
        raise ConfigError(f"Unknown sections in the config: {', '.join(sorted(unknown))}")

    # Each section is a dataclass; build them validating keys and types.
    builders = {
        "engine": EngineConfig,
        "local": LocalConfig,
        "openai": OpenAIConfig,
        "hotkey": HotkeyConfig,
        "audio": AudioConfig,
        "injection": InjectionConfig,
        "dictionary": DictionaryConfig,
        "usage": UsageConfig,
        "logging": LoggingConfig,
    }
    kwargs: dict[str, Any] = {}
    for name, cls in builders.items():
        if name in data:
            if not isinstance(data[name], dict):
                raise ConfigError(f"Section [{name}] must be a TOML table.")
            kwargs[name] = _build_section(cls, data[name], name)

    cfg = Config(**kwargs)
    _validate(cfg)
    return cfg


def load(path: str | Path | None = None) -> Config:
    """Load the config from a TOML file. If ``path`` is None, return defaults."""
    if path is None:
        return Config()
    p = Path(path)
    if not p.exists():
        raise ConfigError(f"Configuration file does not exist: {p}")
    try:
        with p.open("rb") as fh:
            data = tomllib.load(fh)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"TOML syntax error in {p}: {exc}") from exc
    return from_dict(data)


__all__ = ["Config", "ConfigError", "load", "from_dict"]
