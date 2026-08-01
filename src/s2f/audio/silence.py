"""Level analysis for an audio buffer: is there speech, how loud, where.

``trim_silence`` removes voiceless stretches (leading, trailing and long pauses)
while keeping a small margin around speech. This reduces the duration of the
audio sent to the OpenAI API — and therefore the cost, which is billed by
duration — without hurting intelligibility.

``has_speech`` answers the cheaper question "is there any voice in here at all?",
used to skip transcription entirely on a recording that caught only silence.

``normalise_level`` evens out the volume before transcribing, so speech recorded
from across the room reaches the model as loudly as speech into the microphone.

Both estimate the threshold from the audio itself (its background noise), so they
adapt to any microphone with no calibration.
"""

from __future__ import annotations

import logging

import numpy as np

log = logging.getLogger(__name__)

# RMS of ordinary speech into a nearby microphone. Used as a ceiling for the
# adaptive threshold: without it, audio that is speech from start to end would
# raise its own noise estimate so high that nothing counted as speech.
SPEECH_LEVEL = 0.02


def _frame_rms(audio: np.ndarray, sample_rate: int, frame_ms: int) -> np.ndarray:
    """Per-frame RMS energy. Empty if the audio is shorter than two frames."""
    frame_len = max(1, int(sample_rate * frame_ms / 1000))
    n_frames = audio.size // frame_len
    if n_frames < 2:
        return np.zeros(0, dtype=np.float32)
    frames = audio[: n_frames * frame_len].reshape(n_frames, frame_len)
    return np.sqrt(np.mean(frames ** 2, axis=1))


def _speech_threshold(rms: np.ndarray, factor: float, min_threshold: float) -> float:
    """Energy above which a frame counts as speech, from the audio's own noise."""
    noise_floor = float(np.percentile(rms, 10))
    return min(max(noise_floor * factor, min_threshold), SPEECH_LEVEL)


def has_speech(
    audio: np.ndarray,
    sample_rate: int,
    *,
    frame_ms: int = 30,
    factor: float = 3.0,
    min_threshold: float = 0.004,
    min_speech_ms: int = 200,
) -> bool:
    """True if the audio holds at least ``min_speech_ms`` of voice.

    Whisper asked to transcribe silence does not stay quiet: it invents text, and
    with an ``initial_prompt`` it tends to echo the prompt back (the dictionary
    terms). Checking first is both a correctness fix and a saving — no GPU work
    and no API call for a recording that caught nothing.

    ``min_speech_ms`` is deliberately short so a one-word dictation still counts.
    """
    rms = _frame_rms(audio, sample_rate, frame_ms)
    if rms.size == 0:
        return False

    threshold = _speech_threshold(rms, factor, min_threshold)
    speech_frames = int(np.count_nonzero(rms >= threshold))
    needed = max(1, int(min_speech_ms / frame_ms))
    log.debug(
        "Speech check: %d/%d frames above %.4f (need %d).",
        speech_frames, rms.size, threshold, needed,
    )
    return speech_frames >= needed


def trim_silence(
    audio: np.ndarray,
    sample_rate: int,
    *,
    frame_ms: int = 30,
    factor: float = 3.0,
    min_threshold: float = 0.004,
    pad_ms: int = 200,
) -> np.ndarray:
    """Return the audio without the silent stretches.

    - ``factor``: speech is energy above background_noise * factor.
    - ``min_threshold``: absolute minimum threshold (RMS) for safety.
    - ``pad_ms``: margin kept on each side of every speech stretch.

    If no speech is detected, returns the original audio (never risks losing it).
    """
    if audio.size == 0:
        return audio

    rms = _frame_rms(audio, sample_rate, frame_ms)
    if rms.size == 0:
        return audio

    frame_len = max(1, int(sample_rate * frame_ms / 1000))
    n_frames = rms.size
    frames = audio[: n_frames * frame_len].reshape(n_frames, frame_len)

    # No SPEECH_LEVEL ceiling here, unlike has_speech: trimming errs towards
    # keeping audio (worst case it returns everything), so a strict threshold is
    # safe, while a decision to skip transcription must not be over-strict.
    noise_floor = float(np.percentile(rms, 10))
    threshold = max(noise_floor * factor, min_threshold)

    speech = rms >= threshold
    if not speech.any():
        return audio

    # Expand each speech stretch with a margin (padding) on both sides.
    pad = max(1, int(pad_ms / frame_ms))
    keep = np.zeros(n_frames, dtype=bool)
    for i in np.flatnonzero(speech):
        keep[max(0, i - pad) : min(n_frames, i + pad + 1)] = True

    result = frames[keep].reshape(-1)
    return np.ascontiguousarray(result, dtype=np.float32)


def normalise_level(
    audio: np.ndarray,
    *,
    target_peak: float = 0.9,
    max_gain: float = 12.0,
) -> np.ndarray:
    """Scale the audio so its loud moments land near ``target_peak``.

    This is the job a browser's automatic gain control does for a web app, and it
    is why the same voice at the same distance sounds louder in a browser tab than
    in a program that records the raw signal. Whisper transcribes a well-levelled
    recording noticeably better.

    Loudness is measured at the 99.5th percentile rather than the true peak, so a
    single click or keystroke cannot decide the gain for the whole recording.
    ``max_gain`` caps the amplification (about 21 dB), so a nearly empty recording
    is not turned into loud noise. Audio already within a fifth of the target is
    returned untouched: the model gains nothing from the last decibel.
    """
    if audio.size == 0:
        return audio

    loud = float(np.percentile(np.abs(audio), 99.5))
    if loud <= 0:
        return audio

    gain = min(target_peak / loud, max_gain)
    if gain < 1.2:
        return audio
    log.debug("Levelling the recording: %.1fx (loud=%.4f).", gain, loud)
    return np.clip(audio * gain, -1.0, 1.0).astype(np.float32)


__all__ = ["has_speech", "normalise_level", "trim_silence"]
