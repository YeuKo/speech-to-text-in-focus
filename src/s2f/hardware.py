"""Hardware autodetection to pick device, compute type and model.

Detection is defensive: if the dependencies (ctranslate2/torch) are missing or
anything fails, it falls back to CPU without raising. This lets the module be
imported and tested even on machines without a GPU or faster-whisper (e.g. WSL).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

log = logging.getLogger(__name__)

# Default model per hardware tier (used when local.model = "auto").
_MODEL_GPU = "large-v3-turbo"
_MODEL_CPU = "small"


@dataclass(frozen=True)
class Hardware:
    device: str  # "cuda" | "cpu"
    compute_type: str  # e.g. "float16" | "int8"
    has_cuda: bool


def _detect_cuda() -> bool:
    """Return True if a CUDA GPU usable by CTranslate2 is available."""
    # CTranslate2 is the engine behind faster-whisper, so it is the source of truth.
    try:
        import ctranslate2

        if ctranslate2.get_cuda_device_count() > 0:
            return True
    except Exception as exc:  # ImportError or CUDA runtime errors
        log.debug("CTranslate2 reports no CUDA: %s", exc)

    # Fallback: PyTorch, if it happens to be installed.
    try:
        import torch

        return bool(torch.cuda.is_available())
    except Exception as exc:
        log.debug("PyTorch reports no CUDA: %s", exc)
    return False


def detect(device: str = "auto", compute_type: str = "auto") -> Hardware:
    """Resolve the effective device and compute type from the config.

    - ``device="auto"`` -> use CUDA if available, otherwise CPU.
    - ``compute_type="auto"`` -> float16 on GPU, int8 on CPU (good balance).
    """
    has_cuda = _detect_cuda()

    if device == "auto":
        resolved_device = "cuda" if has_cuda else "cpu"
    else:
        resolved_device = device
        if device == "cuda" and not has_cuda:
            log.warning("device=cuda was requested but no GPU was detected; using CPU.")
            resolved_device = "cpu"

    if compute_type == "auto":
        resolved_compute = "float16" if resolved_device == "cuda" else "int8"
    else:
        resolved_compute = compute_type

    hw = Hardware(device=resolved_device, compute_type=resolved_compute, has_cuda=has_cuda)
    log.info("Hardware: device=%s compute_type=%s (cuda=%s)",
             hw.device, hw.compute_type, hw.has_cuda)
    return hw


def resolve_model(model: str, hw: Hardware) -> str:
    """Resolve ``local.model``; if it is "auto", pick one based on the hardware."""
    if model != "auto":
        return model
    chosen = _MODEL_GPU if hw.has_cuda else _MODEL_CPU
    log.info("Auto-selected model: %s", chosen)
    return chosen


__all__ = ["Hardware", "detect", "resolve_model"]
