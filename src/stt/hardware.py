"""Autodetección de hardware para elegir dispositivo, precisión y modelo.

La detección es defensiva: si las dependencias (ctranslate2/torch) no están
instaladas o falla algo, cae a CPU sin romper. Así el módulo se puede importar
y testear incluso en entornos sin GPU ni faster-whisper (p. ej. WSL).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

log = logging.getLogger(__name__)

# Modelo por defecto según el hardware (usado cuando local.model = "auto").
_MODEL_GPU = "large-v3-turbo"
_MODEL_CPU = "small"


@dataclass(frozen=True)
class Hardware:
    device: str  # "cuda" | "cpu"
    compute_type: str  # p. ej. "float16" | "int8"
    has_cuda: bool


def _detect_cuda() -> bool:
    """Devuelve True si hay una GPU CUDA utilizable por CTranslate2."""
    # CTranslate2 es la base de faster-whisper; es la fuente de verdad.
    try:
        import ctranslate2  # type: ignore

        count = ctranslate2.get_cuda_device_count()
        if count > 0:
            return True
    except Exception as exc:  # ImportError o errores del runtime CUDA
        log.debug("CTranslate2 no reporta CUDA: %s", exc)

    # Plan B: PyTorch, por si está disponible.
    try:
        import torch  # type: ignore

        return bool(torch.cuda.is_available())
    except Exception as exc:
        log.debug("PyTorch no reporta CUDA: %s", exc)
    return False


def detect(device: str = "auto", compute_type: str = "auto") -> Hardware:
    """Resuelve el dispositivo y la precisión efectivos a partir de la config.

    - ``device="auto"`` -> usa CUDA si está disponible, si no CPU.
    - ``compute_type="auto"`` -> float16 en GPU, int8 en CPU (buen equilibrio).
    """
    has_cuda = _detect_cuda()

    if device == "auto":
        resolved_device = "cuda" if has_cuda else "cpu"
    else:
        resolved_device = device
        if device == "cuda" and not has_cuda:
            log.warning("Se pidió device=cuda pero no se detecta GPU; usando CPU.")
            resolved_device = "cpu"

    if compute_type == "auto":
        resolved_compute = "float16" if resolved_device == "cuda" else "int8"
    else:
        resolved_compute = compute_type

    hw = Hardware(device=resolved_device, compute_type=resolved_compute, has_cuda=has_cuda)
    log.info("Hardware: device=%s compute_type=%s (cuda=%s)", hw.device, hw.compute_type, hw.has_cuda)
    return hw


def resolve_model(model: str, hw: Hardware) -> str:
    """Resuelve ``local.model``; si es "auto", elige según el hardware."""
    if model != "auto":
        return model
    chosen = _MODEL_GPU if hw.has_cuda else _MODEL_CPU
    log.info("Modelo automático: %s", chosen)
    return chosen


__all__ = ["Hardware", "detect", "resolve_model"]
