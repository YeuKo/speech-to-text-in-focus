"""Handing over audio while the user is still speaking.

The win is latency: releasing the shortcut should leave only the last seconds to
transcribe. The risk is losing or duplicating audio at the seams, or cutting a
word in half — so these tests feed the recorder's audio callback by hand and
check exactly what comes out.
"""

import sys

import numpy as np
import pytest

from s2f.audio.recorder import Recorder
from s2f.config import AudioConfig

SR = 16000
BLOCK = 1024                       # what sounddevice hands us each time


class FakeSD:
    """Enough of sounddevice for Recorder.start() to succeed."""

    def query_devices(self):
        return [{"name": "mic", "max_input_channels": 1, "hostapi": 0}]

    def query_hostapis(self):
        return [{"name": "MME", "default_input_device": 0}]

    def InputStream(self, **_kwargs):   # noqa: N802 (mirrors sounddevice)
        return type("S", (), {"start": lambda s: None, "stop": lambda s: None,
                              "close": lambda s: None})()


@pytest.fixture
def recorder(monkeypatch):
    """A started recorder that collects the chunks it releases."""
    monkeypatch.setitem(sys.modules, "sounddevice", FakeSD())
    chunks: list[np.ndarray] = []

    def _make(**cfg_kwargs):
        cfg = AudioConfig(**cfg_kwargs)
        rec = Recorder(cfg, on_chunk=chunks.append)
        rec.start()
        return rec

    return _make, chunks


def _feed(rec: Recorder, seconds: float, *, loud: bool) -> None:
    """Push audio through the callback the way the sound card would."""
    rng = np.random.default_rng(0)
    for _ in range(int(seconds * SR / BLOCK)):
        block = rng.standard_normal((BLOCK, 1)).astype(np.float32)
        block *= 0.3 if loud else 0.0005
        rec._callback(block, BLOCK, None, None)


class TestChunking:
    def test_nothing_is_released_before_the_minimum(self, recorder):
        make, chunks = recorder
        rec = make(chunk_seconds=6.0)
        _feed(rec, 3.0, loud=True)
        _feed(rec, 1.0, loud=False)       # a pause, but too early to cut
        assert chunks == []

    def test_a_chunk_is_released_on_the_first_pause(self, recorder):
        make, chunks = recorder
        rec = make(chunk_seconds=2.0)
        _feed(rec, 3.0, loud=True)        # past the minimum, still talking
        assert chunks == []               # must not cut mid-word
        _feed(rec, 0.3, loud=False)       # pause: now it can cut
        assert len(chunks) == 1
        assert 3.0 <= len(chunks[0]) / SR <= 3.5

    def test_a_non_stop_talker_is_cut_anyway(self, recorder):
        make, chunks = recorder
        rec = make(chunk_seconds=2.0, chunk_max_seconds=5.0)
        _feed(rec, 6.0, loud=True)        # never pauses
        assert len(chunks) == 1
        assert len(chunks[0]) / SR >= 5.0

    def test_no_audio_is_lost_or_duplicated_across_the_seams(self, recorder):
        """The chunks plus the tail must add up to everything that was recorded."""
        make, chunks = recorder
        rec = make(chunk_seconds=2.0)
        for _ in range(3):
            _feed(rec, 2.5, loud=True)
            _feed(rec, 0.3, loud=False)
        tail = rec.stop()

        total = sum(len(c) for c in chunks) + len(tail)
        expected = sum(int(s * SR / BLOCK) * BLOCK for s in (2.5, 0.3) * 3)
        assert total == expected
        assert len(chunks) == 3

    def test_disabled_by_configuration(self, recorder):
        make, chunks = recorder
        rec = make(chunk_seconds=0)
        _feed(rec, 10.0, loud=True)
        _feed(rec, 1.0, loud=False)
        assert chunks == []
        assert len(rec.stop()) / SR > 10      # everything comes out at the end

    def test_stopping_returns_only_what_was_not_handed_over(self, recorder):
        make, chunks = recorder
        rec = make(chunk_seconds=2.0)
        _feed(rec, 2.5, loud=True)
        _feed(rec, 0.3, loud=False)           # releases a chunk
        _feed(rec, 1.0, loud=True)            # this is the tail
        tail = rec.stop()
        assert len(chunks) == 1
        # The cut happens on the first quiet block, so whatever pause came after
        # it stays in the tail along with the second stretch of speech.
        assert 1.0 <= len(tail) / SR <= 1.4

    def test_a_failing_consumer_does_not_break_recording(self, recorder, monkeypatch):
        monkeypatch.setitem(sys.modules, "sounddevice", FakeSD())
        rec = Recorder(AudioConfig(chunk_seconds=2.0),
                       on_chunk=lambda _c: (_ for _ in ()).throw(RuntimeError("boom")))
        rec.start()
        _feed(rec, 2.5, loud=True)
        _feed(rec, 0.3, loud=False)           # the consumer raises here
        _feed(rec, 1.0, loud=True)
        assert len(rec.stop()) / SR >= 0.9    # recording carried on
