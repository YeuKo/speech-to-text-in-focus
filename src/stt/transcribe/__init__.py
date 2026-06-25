"""Backends de transcripción (local con faster-whisper o API de OpenAI)."""

from stt.transcribe.base import TranscriberBackend, TranscriptionResult, create_backend

__all__ = ["TranscriberBackend", "TranscriptionResult", "create_backend"]
