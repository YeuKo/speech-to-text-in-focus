import pytest

from stt import config


class TestFeedbackSection:
    def test_defaults(self):
        cfg = config.from_dict({})
        assert cfg.feedback.sound == "system"
        assert cfg.feedback.overlay is True
        assert cfg.feedback.overlay_position == "bottom-right"

    @pytest.mark.parametrize("mode", config.SOUND_MODES)
    def test_accepts_every_sound_mode(self, mode):
        cfg = config.from_dict({"feedback": {"sound": mode}})
        assert cfg.feedback.sound == mode

    def test_rejects_unknown_sound_mode(self):
        with pytest.raises(config.ConfigError, match="feedback.sound"):
            config.from_dict({"feedback": {"sound": "vibrate"}})

    @pytest.mark.parametrize("position", config.OVERLAY_POSITIONS)
    def test_accepts_every_overlay_position(self, position):
        cfg = config.from_dict({"feedback": {"overlay_position": position}})
        assert cfg.feedback.overlay_position == position

    def test_rejects_unknown_overlay_position(self):
        with pytest.raises(config.ConfigError, match="feedback.overlay_position"):
            config.from_dict({"feedback": {"overlay_position": "middle"}})

    def test_rejects_non_boolean_overlay(self):
        with pytest.raises(config.ConfigError, match="true/false"):
            config.from_dict({"feedback": {"overlay": "yes"}})

    def test_rejects_unknown_key(self):
        with pytest.raises(config.ConfigError, match="unknown keys"):
            config.from_dict({"feedback": {"volume": 5}})


class TestAudioDefaults:
    def test_auto_stop_is_off_and_the_vad_filter_is_on(self):
        """Turning auto-stop off must not stop Whisper skipping silence: that is
        what keeps it from inventing text over a pause."""
        cfg = config.from_dict({})
        assert cfg.audio.auto_stop is False
        assert cfg.audio.vad_filter is True


class TestRenamedKeys:
    def test_use_vad_still_configures_auto_stop(self, caplog):
        """An existing config.toml must keep meaning what its author intended."""
        cfg = config.from_dict({"audio": {"use_vad": True}})
        assert cfg.audio.auto_stop is True
        assert cfg.audio.vad_filter is True      # untouched by the old key
        assert "use_vad" in caplog.text

    def test_the_new_name_wins_when_both_are_present(self):
        cfg = config.from_dict({"audio": {"use_vad": True, "auto_stop": False}})
        assert cfg.audio.auto_stop is False

    def test_the_old_name_is_still_type_checked(self):
        with pytest.raises(config.ConfigError, match="true/false"):
            config.from_dict({"audio": {"use_vad": "yes"}})


class TestRetiredKeys:
    def test_a_removed_setting_does_not_stop_the_app(self, caplog):
        """A config.toml written by an older version must still load."""
        cfg = config.from_dict({"feedback": {"notifications": False, "sound": "off"}})
        assert cfg.feedback.sound == "off"
        assert not hasattr(cfg.feedback, "notifications")
        assert "notifications" in caplog.text

    def test_still_rejects_a_genuine_typo(self):
        with pytest.raises(config.ConfigError, match="unknown keys"):
            config.from_dict({"feedback": {"notification": False}})
