"""Configuration loading and validation (TOML -> typed dataclasses).

Uses only the standard library (``tomllib``, available in Python 3.11+), so the
configuration can be loaded and tested without third-party dependencies or Windows.
"""

from __future__ import annotations

import logging
import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any, get_origin

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Allowed values (validation)
# ---------------------------------------------------------------------------

BACKENDS = ("local", "openai")
DEVICES = ("auto", "cuda", "cpu")
COMPUTE_TYPES = ("auto", "int8", "int8_float16", "float16", "float32")
SHORTCUT_MODES = ("separate", "gesture")
INJECTION_METHODS = ("clipboard", "type")
SOUND_MODES = ("system", "beeps", "off")
OVERLAY_POSITIONS = (
    "bottom-right", "bottom-center", "bottom-left",
    "top-right", "top-center", "top-left",
)
LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")


# Settings that changed name. The old key keeps working, mapped to the new one.
RENAMED_KEYS: dict[str, dict[str, str]] = {
    # use_vad used to control two unrelated things: stopping the recording on
    # silence, and asking Whisper to skip silent stretches. Turning the first one
    # off silently disabled the second, which is part of what stops the model
    # inventing text over silence.
    "audio": {"use_vad": "auto_stop"},
}

# Settings removed along the way, kept here so an older config.toml still loads.
RETIRED_KEYS: dict[str, tuple[str, ...]] = {
    # Native tray balloons: replaced by the floating status pill because Windows
    # keeps every balloon in the Action Center.
    "feedback": ("notifications",),
    # default_mode was only ever validated, never read: the mode is now chosen by
    # hotkey.mode, which actually decides what gets registered.
    "hotkey": ("default_mode",),
}


class ConfigError(ValueError):
    """Configuration error with a clear, user-facing message."""


# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------


@dataclass
class EngineConfig:
    backend: str = "local"
    # ISO-639-1 (e.g. "en", "es") or "auto" to autodetect. Naming the language
    # beats autodetection: Whisper guesses from the first seconds of audio, and a
    # short or noisy opening makes it transcribe into the wrong language outright.
    language: str = "es"


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
    # How dictation is triggered:
    #   "separate" -> two shortcuts, one per mode (toggle and push-to-talk)
    #   "gesture"  -> one shortcut for both: hold it to talk, tap it twice for
    #                 hands-free. Only the chosen mode's shortcuts are registered,
    #                 so there is never a second combination doing something else.
    mode: str = "gesture"
    toggle: str = "ctrl+alt+space"
    push_to_talk: str = "ctrl+alt+v"
    # The single combination used when mode = "gesture". Two bare modifiers work
    # well ("ctrl+windows"): nothing types them by accident.
    gesture: str = "ctrl+windows"
    # Held for longer than this, it is push-to-talk; shorter, it waits to see if a
    # second tap arrives.
    gesture_hold_ms: int = 250
    # How long to wait for that second tap. Windows gives a double click 500 ms by
    # default, and that is the rhythm a hand already has; letting go of two
    # modifiers and finding them again is if anything slower than clicking twice.
    gesture_double_ms: int = 500


@dataclass
class AudioConfig:
    sample_rate: int = 16000
    channels: int = 1
    silence_timeout_ms: int = 1500
    # Stop recording on its own after a pause. Off by default: being cut off
    # mid-thought is worse than pressing the shortcut again, and the pause that
    # feels natural differs per person. Switchable from the tray.
    auto_stop: bool = False
    # Transcribe while you speak, in chunks of roughly this many seconds, so that
    # releasing the shortcut leaves only the last moments to process. Chunks are
    # cut on a pause, never mid-word. 0 transcribes everything at the end.
    #
    # Whisper is markedly worse on short isolated fragments, and the seams are
    # where words go missing. Long enough to give the model something to work
    # with on its own, still well inside the single 30-second window it decodes,
    # so a chunk is never split across two.
    chunk_seconds: float = 12.0
    # Cut anyway after this long without a pause, so talking non-stop still gets
    # the benefit.
    chunk_max_seconds: float = 20.0
    # Prime each chunk with the tail of what has been transcribed so far, rather
    # than decoding it as if the dictation began there. This is what carries the
    # thread of a sentence across a cut, and it costs neither time nor money.
    # Turn it off if the model ever starts repeating phrases it already wrote.
    chunk_context: bool = True
    # Have Whisper skip the silent stretches of the recording. Unrelated to
    # auto_stop despite both being "VAD": this one guards against the model
    # inventing text over silence, so it stays on regardless.
    vad_filter: bool = True
    # Adaptive threshold: estimate background noise and adjust the cut on its own
    # (recommended).
    auto_threshold: bool = True
    # Fixed threshold (RMS, 0-1), used only when auto_threshold = false. See
    # --calibrate-mic.
    silence_threshold: float = 0.006
    # Which microphone to record from: "auto" uses the Windows default, or give
    # part of a device name ("Microphone Array"). See --list-devices.
    input_device: str = "auto"
    # Input gain applied as the audio is captured. Raise it if you have to lean
    # into the microphone: it makes speech detection more sensitive too, since
    # that is what decides when you started talking. See --calibrate-mic.
    gain: float = 1.0
    # Level out the recording before transcribing, so quiet speech reaches the
    # model as loudly as close speech. This is what a browser's automatic gain
    # control does for a web app, and Whisper transcribes better for it.
    auto_gain: bool = True


@dataclass
class FeedbackConfig:
    """How the app tells you what it is doing."""

    # "system" -> Windows' own speech sounds (soft, follow the volume mixer),
    # "beeps"  -> synthesized tones (loud, cut through anything), "off" -> silent.
    sound: str = "system"
    # Small floating pill showing recording / transcribing / done. Silent and it
    # leaves nothing behind, so it is the visual feedback (native Windows
    # notifications were tried and dropped: they pile up in the Action Center).
    overlay: bool = True
    # Which corner of the screen it appears in, taskbar excluded.
    overlay_position: str = "bottom-right"


@dataclass
class InjectionConfig:
    method: str = "clipboard"
    restore_clipboard: bool = True
    paste_delay_ms: int = 80


@dataclass
class DictionaryConfig:
    terms: list[str] = field(default_factory=list)
    replacements: dict[str, str] = field(default_factory=dict)
    # Also correct words that merely *resemble* a term (needs rapidfuzz). Helps
    # with names the model spells phonetically, at the risk of rewriting an
    # ordinary word that happens to look like one of your terms.
    fuzzy: bool = False


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
    feedback: FeedbackConfig = field(default_factory=FeedbackConfig)
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

    # A renamed setting keeps working under its old name, so upgrading never
    # silently changes what someone configured on purpose.
    renames = RENAMED_KEYS.get(section_name, {})
    if any(old in data for old in renames):
        data = dict(data)
        for old, new in renames.items():
            if old in data:
                value = data.pop(old)
                if new not in data:        # an explicit new key wins
                    data[new] = value
                log.warning("[%s] %s is now called %s.", section_name, old, new)

    # Settings that used to exist are ignored with a note rather than rejected:
    # a config file written by an older version must never stop the app booting.
    retired = set(data) & set(RETIRED_KEYS.get(section_name, ()))
    if retired:
        log.warning(
            "[%s] ignoring settings that no longer exist: %s",
            section_name, ", ".join(sorted(retired)),
        )
        data = {k: v for k, v in data.items() if k not in retired}

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
    _one_of(cfg.hotkey.mode, SHORTCUT_MODES, "hotkey.mode")
    if cfg.hotkey.mode == "gesture" and not cfg.hotkey.gesture:
        raise ConfigError('hotkey.gesture cannot be empty when mode = "gesture".')
    _one_of(cfg.feedback.sound, SOUND_MODES, "feedback.sound")
    _one_of(cfg.feedback.overlay_position, OVERLAY_POSITIONS, "feedback.overlay_position")
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
    if not 0 < cfg.audio.gain <= 20:
        raise ConfigError("audio.gain must be between 0 and 20 (1.0 = no change).")
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
        "feedback": FeedbackConfig,
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
