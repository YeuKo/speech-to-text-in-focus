"""Recovery when the chosen microphone cannot be opened.

A headset gets unplugged, or another app holds the device: the recorder must fall
back to the Windows default instead of leaving the app unable to record.
"""

import sys

import pytest

from stt.audio.recorder import Recorder
from stt.config import AudioConfig


class FakeStream:
    def __init__(self, device):
        self.device = device
        self.started = False

    def start(self):
        self.started = True

    def stop(self):
        pass

    def close(self):
        pass


class FakeSD:
    """Opens only the devices in ``openable``; records what was attempted."""

    def __init__(self, openable):
        self._openable = openable
        self.attempts: list[int | None] = []
        self.streams: list[FakeStream] = []

    def query_devices(self):
        return [{"name": "Ghost mic", "max_input_channels": 1, "hostapi": 0}]

    def query_hostapis(self):
        return [{"name": "MME", "default_input_device": 0}]

    def InputStream(self, *, device=None, **_kwargs):   # noqa: N802 (mirrors sounddevice)
        self.attempts.append(device)
        if device not in self._openable:
            raise RuntimeError("Error opening InputStream: device unavailable")
        stream = FakeStream(device)
        self.streams.append(stream)
        return stream


@pytest.fixture
def sd(monkeypatch):
    def _install(openable):
        fake = FakeSD(openable)
        monkeypatch.setitem(sys.modules, "sounddevice", fake)
        return fake
    return _install


class TestOpeningTheMicrophone:
    def test_uses_the_configured_device(self, sd):
        fake = sd(openable={0})
        Recorder(AudioConfig(input_device="Ghost mic")).start()
        assert fake.attempts == [0]

    def test_falls_back_to_the_default_when_it_cannot_open(self, sd):
        """The configured microphone is gone; recording must still work."""
        fake = sd(openable={None})
        Recorder(AudioConfig(input_device="Ghost mic")).start()
        assert fake.attempts == [0, None]      # tried the device, then the default
        assert fake.streams[0].started

    def test_raises_when_even_the_default_fails(self, sd):
        """The controller relies on this to return to idle instead of pretending."""
        sd(openable=set())
        with pytest.raises(RuntimeError):
            Recorder(AudioConfig(input_device="auto")).start()

    def test_auto_does_not_retry(self, sd):
        fake = sd(openable=set())
        with pytest.raises(RuntimeError):
            Recorder(AudioConfig(input_device="auto")).start()
        assert fake.attempts == [None]
