"""Transcription backends (local faster-whisper or OpenAI API)."""

from s2f.transcribe.base import TranscriberBackend, TranscriptionResult, create_backend

__all__ = ["TranscriberBackend", "TranscriptionResult", "create_backend"]
