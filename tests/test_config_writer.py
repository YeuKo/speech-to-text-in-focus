from stt.config_writer import persist_hotkey

SAMPLE = '''[hotkey]
toggle = "ctrl+alt+space"      # press to start/stop
push_to_talk = "ctrl+alt+v"    # hold to talk
default_mode = "toggle"
'''


class TestPersistHotkey:
    def test_updates_toggle_keeping_comment(self, tmp_path):
        p = tmp_path / "config.toml"
        p.write_text(SAMPLE, encoding="utf-8")
        assert persist_hotkey(p, "toggle", "ctrl+shift+r") is True
        text = p.read_text(encoding="utf-8")
        assert 'toggle = "ctrl+shift+r"' in text
        assert "# press to start/stop" in text          # comment preserved
        assert 'push_to_talk = "ctrl+alt+v"' in text     # other key untouched

    def test_updates_push_to_talk_only(self, tmp_path):
        p = tmp_path / "config.toml"
        p.write_text(SAMPLE, encoding="utf-8")
        persist_hotkey(p, "push_to_talk", "ctrl+alt+x")
        text = p.read_text(encoding="utf-8")
        assert 'push_to_talk = "ctrl+alt+x"' in text
        assert 'toggle = "ctrl+alt+space"' in text        # toggle untouched

    def test_invalid_key_rejected(self, tmp_path):
        p = tmp_path / "config.toml"
        p.write_text(SAMPLE, encoding="utf-8")
        assert persist_hotkey(p, "bogus", "ctrl+z") is False
        assert p.read_text(encoding="utf-8") == SAMPLE

    def test_appends_when_key_missing(self, tmp_path):
        p = tmp_path / "config.toml"
        p.write_text("[engine]\nbackend = \"local\"\n", encoding="utf-8")
        assert persist_hotkey(p, "toggle", "f9") is True
        assert 'toggle = "f9"' in p.read_text(encoding="utf-8")
