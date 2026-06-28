"""Silence trimming for an audio buffer.

Removes voiceless stretches (leading, trailing and long pauses) while keeping a
small margin around speech. This reduces the duration of the audio sent to the
OpenAI API — and therefore the cost, which is billed by duration — without
hurting intelligibility. The threshold is estimated from the audio itself
(background noise), so it adapts to any microphone.
"""

from __future__ import annotations

import logging

import numpy as np

log = logging.getLogger(__name__)


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

    frame_len = max(1, int(sample_rate * frame_ms / 1000))
    n_frames = audio.size // frame_len
    if n_frames < 2:
        return audio

    frames = audio[: n_frames * frame_len].reshape(n_frames, frame_len)
    rms = np.sqrt(np.mean(frames ** 2, axis=1))

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


__all__ = ["trim_silence"]
