import numpy as np

from stt.audio.silence import has_speech, normalise_level, trim_silence

SR = 16000


def _tone(seconds: float, amp: float = 0.3, freq: int = 220) -> np.ndarray:
    t = np.arange(int(SR * seconds)) / SR
    return (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def _silence(seconds: float) -> np.ndarray:
    return np.zeros(int(SR * seconds), dtype=np.float32)


class TestTrimSilence:
    def test_empty_audio(self):
        out = trim_silence(np.zeros(0, dtype=np.float32), SR)
        assert out.size == 0

    def test_pure_silence_returns_original(self):
        # With no detectable speech, it must not risk losing the audio.
        audio = _silence(2.0)
        out = trim_silence(audio, SR)
        assert out.size == audio.size

    def test_removes_long_silence(self):
        # 1s speech + 5s silence + 1s speech -> should be considerably shorter.
        audio = np.concatenate([_tone(1.0), _silence(5.0), _tone(1.0)])
        out = trim_silence(audio, SR)
        assert out.size < audio.size
        # Keeps at least the speech (2s) and no more than the original.
        assert out.size >= int(SR * 1.5)

    def test_keeps_speech_with_padding(self):
        # Speech-only audio: should barely trim (some edge loss from framing).
        audio = _tone(2.0)
        out = trim_silence(audio, SR)
        assert out.size >= int(SR * 1.8)

    def test_trailing_silence_trimmed(self):
        audio = np.concatenate([_tone(1.0), _silence(4.0)])
        out = trim_silence(audio, SR)
        assert out.size < int(SR * 2.0)  # most of the trailing silence was removed


def _noise(seconds: float, amp: float = 0.002) -> np.ndarray:
    """Faint background hiss: a quiet room, no voice."""
    rng = np.random.default_rng(1234)
    return (rng.standard_normal(int(SR * seconds)) * amp).astype(np.float32)


class TestHasSpeech:
    def test_empty_audio(self):
        assert has_speech(np.zeros(0, dtype=np.float32), SR) is False

    def test_too_short_audio(self):
        assert has_speech(_tone(0.01), SR) is False

    def test_pure_silence(self):
        assert has_speech(_silence(3.0), SR) is False

    def test_room_noise_only(self):
        """The reported bug: auto-stop fired but nothing was said."""
        assert has_speech(_noise(4.0), SR) is False

    def test_loud_room_noise_only(self):
        # A noisy room must still not read as speech (relative threshold).
        assert has_speech(_noise(4.0, amp=0.01), SR) is False

    def test_speech_after_silence(self):
        audio = np.concatenate([_silence(2.0), _tone(1.0), _silence(2.0)])
        assert has_speech(audio, SR) is True

    def test_speech_only(self):
        # Wall-to-wall speech: its own noise floor is high, so the threshold
        # ceiling is what keeps this from reading as silence.
        assert has_speech(_tone(2.0), SR) is True

    def test_quiet_speech_over_noise(self):
        audio = _noise(3.0) + np.concatenate([_silence(1.0), _tone(1.0, amp=0.05), _silence(1.0)])
        assert has_speech(audio, SR) is True

    def test_single_short_word_counts(self):
        # ~250 ms of voice: a one-word dictation must not be discarded.
        audio = np.concatenate([_silence(0.5), _tone(0.25), _silence(0.5)])
        assert has_speech(audio, SR) is True

    def test_click_does_not_count(self):
        # A 30 ms keystroke is not speech.
        audio = np.concatenate([_silence(1.0), _tone(0.03, amp=0.5), _silence(2.0)])
        assert has_speech(audio, SR) is False


def _peak(audio: np.ndarray) -> float:
    return float(np.max(np.abs(audio)))


class TestNormaliseLevel:
    def test_quiet_speech_is_brought_up(self):
        """Speech recorded from across the room must reach the model loud enough."""
        out = normalise_level(_tone(1.0, amp=0.08))
        assert 0.8 < _peak(out) <= 1.0

    def test_loud_audio_is_left_alone(self):
        audio = _tone(1.0, amp=0.8)      # within the dead zone of the target
        assert normalise_level(audio) is audio

    def test_never_exceeds_full_scale(self):
        for amp in (0.001, 0.02, 0.2, 0.95):
            assert _peak(normalise_level(_tone(0.5, amp=amp))) <= 1.0

    def test_amplification_is_capped(self):
        """A nearly empty recording must not be blown up into loud noise."""
        out = normalise_level(_tone(1.0, amp=0.001), max_gain=4.0)
        assert _peak(out) <= 0.001 * 4.0 + 1e-6

    def test_a_lone_click_does_not_set_the_gain(self):
        # Speech at 0.05 with one 0.9 spike: the spike is ignored (99.5th pct),
        # so the speech still gets amplified.
        audio = np.concatenate([_tone(1.0, amp=0.05), _tone(0.005, amp=0.9)])
        out = normalise_level(audio)
        assert _peak(out) > 0.9

    def test_empty_and_silent_audio(self):
        assert normalise_level(np.zeros(0, dtype=np.float32)).size == 0
        silent = _silence(1.0)
        assert normalise_level(silent) is silent
