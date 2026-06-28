"""Almacenamiento seguro de la API key de OpenAI (keyring de Windows).

Centraliza el acceso para que el backend, la CLI y la UI usen el mismo sitio.
La key nunca se guarda en ficheros de configuración.
"""

from __future__ import annotations

import logging
import os

log = logging.getLogger(__name__)

SERVICE = "stt-dictation"
USERNAME = "openai_api_key"


def get_api_key() -> str | None:
    """Devuelve la key guardada en keyring, o None si no hay o keyring falla."""
    try:
        import keyring

        return keyring.get_password(SERVICE, USERNAME)
    except Exception as exc:
        log.debug("keyring no disponible: %s", exc)
        return None


def set_api_key(key: str) -> bool:
    """Guarda la key en keyring. Devuelve True si se guardó correctamente."""
    try:
        import keyring

        keyring.set_password(SERVICE, USERNAME, key)
        return True
    except Exception as exc:
        log.error("No se pudo guardar la API key: %s", exc)
        return False


def has_api_key(env_name: str = "OPENAI_API_KEY") -> bool:
    """True si hay key disponible por variable de entorno o en keyring."""
    return bool(os.environ.get(env_name) or get_api_key())


__all__ = ["get_api_key", "set_api_key", "has_api_key", "SERVICE", "USERNAME"]
