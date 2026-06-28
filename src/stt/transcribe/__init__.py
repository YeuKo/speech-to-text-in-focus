"""Transcription backends (local faster-whisper or OpenAI API)."""

from stt.transcribe.base import TranscriberBackend, TranscriptionResult, create_backend

__all__ = ["TranscriberBackend", "TranscriptionResult", "create_backend"]
