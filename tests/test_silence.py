import numpy as np

from stt.audio.silence import trim_silence

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
        # Sin voz detectable, no debe arriesgar a perder el audio.
        audio = _silence(2.0)
        out = trim_silence(audio, SR)
        assert out.size == audio.size

    def test_removes_long_silence(self):
        # 1s voz + 5s silencio + 1s voz -> debe quedar bastante más corto.
        audio = np.concatenate([_tone(1.0), _silence(5.0), _tone(1.0)])
        out = trim_silence(audio, SR)
        assert out.size < audio.size
        # Conserva al menos la voz (2s) y no más que el original.
        assert out.size >= int(SR * 1.5)

    def test_keeps_speech_with_padding(self):
        # Audio solo voz: apenas debe recortar (algo de borde por el framing).
        audio = _tone(2.0)
        out = trim_silence(audio, SR)
        assert out.size >= int(SR * 1.8)

    def test_trailing_silence_trimmed(self):
        audio = np.concatenate([_tone(1.0), _silence(4.0)])
        out = trim_silence(audio, SR)
        assert out.size < int(SR * 2.0)  # se quitó la mayor parte del silencio final
