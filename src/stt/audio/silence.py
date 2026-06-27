"""Recorte de silencios de un audio.

Elimina los tramos sin voz (cabecera, cola y pausas largas) conservando un
pequeño margen alrededor del habla. Reduce la duración del audio que se envía
a la API de OpenAI —y por tanto el coste, que se factura por duración— sin
afectar a la inteligibilidad. El umbral se estima del propio audio (ruido de
fondo), así que se adapta a cualquier micrófono.
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
    """Devuelve el audio sin los tramos de silencio.

    - ``factor``: la voz es energía por encima de ruido_de_fondo * factor.
    - ``min_threshold``: umbral mínimo absoluto (RMS) por seguridad.
    - ``pad_ms``: margen conservado a cada lado de cada tramo de voz.

    Si no se detecta voz, devuelve el audio original (no arriesga a perderlo).
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

    # Expandir cada tramo de voz con un margen (padding) a ambos lados.
    pad = max(1, int(pad_ms / frame_ms))
    keep = np.zeros(n_frames, dtype=bool)
    idx = np.flatnonzero(speech)
    for i in idx:
        keep[max(0, i - pad) : min(n_frames, i + pad + 1)] = True

    result = frames[keep].reshape(-1)
    return np.ascontiguousarray(result, dtype=np.float32)


__all__ = ["trim_silence"]
