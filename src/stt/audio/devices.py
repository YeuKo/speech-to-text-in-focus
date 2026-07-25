"""Enumerate the microphones available for recording.

Windows exposes the same physical microphone several times, once per audio API
(MME, DirectSound, WASAPI, WDM-KS), so a raw device list is mostly duplicates.
This keeps one entry per name, which is also what ``sounddevice`` matches on when
a device is given by name — the form stored in the config, since device indices
shift as headsets are plugged in and out.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

log = logging.getLogger(__name__)

# Entries Windows lists as capture devices that are not a microphone: the API
# mappers ("pick whatever is default", which is what "auto" already does) and the
# loopback of an output. Matched case-insensitively, in English and Spanish.
_NOT_A_MICROPHONE = (
    "sound mapper", "asignador de sonido",
    "primary sound capture", "controlador primario",
    "altavoz de pc", "pc speaker",
)


def _is_microphone(name: str) -> bool:
    low = name.lower()
    if any(bad in low for bad in _NOT_A_MICROPHONE):
        return False
    # WDM-KS exposes the loopback of an output as "Input (… Speaker)".
    return not (low.startswith("input (") and "speaker" in low)


@dataclass(frozen=True)
class InputDevice:
    name: str
    channels: int
    is_default: bool


def list_input_devices() -> list[InputDevice]:
    """Microphones available for recording, default first. Empty if unavailable."""
    try:
        import sounddevice as sd

        default_index = sd.default.device[0]
        devices = sd.query_devices()
        apis = sd.query_hostapis()
    except Exception:
        log.warning("Could not query the audio devices.", exc_info=True)
        return []

    default_name = _default_input_name(sd, devices, default_index)

    candidates: dict[str, int] = {}
    kernel_only: set[str] = set()
    for dev in devices:
        try:
            if dev["max_input_channels"] <= 0:
                continue
            name = str(dev["name"]).strip()
            channels = int(dev["max_input_channels"])
            api = str(apis[dev["hostapi"]]["name"])
        except (IndexError, KeyError, TypeError, ValueError):
            continue
        if not name or not _is_microphone(name):
            continue
        if "WDM-KS" in api:
            # The raw driver view of a device. It demands exclusive access, so
            # opening it usually fails; every real microphone is also listed
            # through MME/DirectSound/WASAPI, so these are only kept if nothing
            # else offers them.
            kernel_only.add(name)
            continue
        candidates.setdefault(name, channels)

    if not candidates:
        log.debug("Only kernel-streaming devices found; offering them anyway.")
        candidates = {n: 1 for n in kernel_only}

    names = _drop_truncated(candidates)
    result = [InputDevice(n, candidates[n], n == default_name) for n in names]
    result.sort(key=lambda d: (not d.is_default, d.name.lower()))
    return result


def _default_input_name(sd, devices, default_index) -> str:
    """Full name of the default microphone.

    Asks WASAPI first: ``sounddevice`` defaults to MME, whose names are cut to 31
    characters, and two devices can share that prefix — expanding the short form
    by guesswork would mark the wrong one as default.
    """
    try:
        for api in sd.query_hostapis():
            if "WASAPI" in str(api.get("name", "")):
                idx = api.get("default_input_device")
                if isinstance(idx, int) and idx >= 0:
                    return str(devices[idx]["name"]).strip()
    except (IndexError, KeyError, TypeError, AttributeError):
        log.debug("Could not read WASAPI's default input.", exc_info=True)

    try:
        if isinstance(default_index, int) and default_index >= 0:
            return str(devices[default_index]["name"]).strip()
    except (IndexError, KeyError, TypeError):
        pass
    return ""


def _drop_truncated(names: dict[str, int]) -> list[str]:
    """Keep the full name when the same device also appears cut short.

    The same microphone shows up once per audio API, and MME caps names at 31
    characters, so "Microphone Array (Realtek(R) Au" and "Microphone Array
    (Realtek(R) Audio)" are one device. Matching by name is by substring, so the
    longer name still finds it.
    """
    ordered = sorted(names, key=len, reverse=True)
    kept: list[str] = []
    for name in ordered:
        if not any(longer.startswith(name) for longer in kept):
            kept.append(name)
    return kept


# Which audio API to open a microphone through, best first. MME leads because it
# accepts any sample rate (we record at 16 kHz while the device usually runs at
# 48 kHz) and never refuses a device another app is already using; WDM-KS is last
# because it wants exclusive access to the driver.
_API_PREFERENCE = ("MME", "DirectSound", "WASAPI", "WDM-KS")


def _api_rank(api_name: str) -> int:
    for i, preferred in enumerate(_API_PREFERENCE):
        if preferred.lower() in api_name.lower():
            return i
    return len(_API_PREFERENCE)


def resolve_input_device(configured: str) -> int | None:
    """Turn the configured microphone into a concrete device index.

    ``None`` means "let Windows choose", which is what ``"auto"`` asks for.

    Resolving to an index is not an optimisation: passing a name straight to
    ``sounddevice`` raises ``ValueError: Multiple input devices found`` whenever
    more than one entry matches, and since Windows lists the same microphone once
    per audio API, a plain name matches three or four of them.
    """
    if not configured or configured == "auto":
        return None
    if configured.isdigit():
        return int(configured)

    try:
        import sounddevice as sd

        devices = sd.query_devices()
        apis = sd.query_hostapis()
    except Exception:
        log.warning("Could not query the audio devices.", exc_info=True)
        return None

    matches: list[tuple[int, int, int]] = []   # (match quality, api rank, index)
    for index, dev in enumerate(devices):
        try:
            if dev["max_input_channels"] <= 0:
                continue
            name = str(dev["name"]).strip()
            api = str(apis[dev["hostapi"]]["name"])
        except (IndexError, KeyError, TypeError):
            continue

        if name == configured:
            quality = 0
        elif name.startswith(configured):
            quality = 1          # the user stored a fragment of the full name
        elif configured.startswith(name):
            # The listed name is the short form MME cut to 31 characters. Weakest
            # match by far: two devices can share those first characters, so a
            # bluetooth headset must not win over the one actually named.
            quality = 2
        else:
            continue
        matches.append((quality, _api_rank(api), index))

    if not matches:
        log.warning("Microphone %r not found; using the Windows default.", configured)
        return None

    matches.sort()
    chosen = matches[0][2]
    log.debug("Microphone %r -> device %d (%s).", configured, chosen,
              apis[devices[chosen]["hostapi"]]["name"])
    return chosen


def describe_current(configured: str) -> str:
    """One-line description of the microphone in use, for logs and reports."""
    if configured != "auto":
        return configured
    devices = [d for d in list_input_devices() if d.is_default]
    return f"{devices[0].name} (Windows default)" if devices else "Windows default"


__all__ = ["InputDevice", "describe_current", "list_input_devices", "resolve_input_device"]
