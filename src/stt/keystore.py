"""Secure storage for the OpenAI API key (Windows credential store via keyring).

Centralises access so the backend, the CLI and the UI all use the same place.
The key is never written to configuration files.
"""

from __future__ import annotations

import logging
import os

log = logging.getLogger(__name__)

SERVICE = "stt-dictation"   # kept stable across renames: it is the
                            # key under which Windows already stores the
                            # secret, and changing it would orphan it
USERNAME = "openai_api_key"


def get_api_key() -> str | None:
    """Return the key stored in keyring, or None if absent or keyring fails."""
    try:
        import keyring

        return keyring.get_password(SERVICE, USERNAME)
    except Exception as exc:
        log.debug("keyring unavailable: %s", exc)
        return None


def set_api_key(key: str) -> bool:
    """Store the key in keyring. Returns True if saved successfully."""
    try:
        import keyring

        keyring.set_password(SERVICE, USERNAME, key)
        return True
    except Exception as exc:
        log.error("Could not save the API key: %s", exc)
        return False


def has_api_key(env_name: str = "OPENAI_API_KEY") -> bool:
    """True if a key is available via environment variable or keyring."""
    return bool(os.environ.get(env_name) or get_api_key())


__all__ = ["get_api_key", "set_api_key", "has_api_key", "SERVICE", "USERNAME"]
