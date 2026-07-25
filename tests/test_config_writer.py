import tomllib

from stt.config_writer import persist_hotkey, persist_value

SAMPLE = '''[hotkey]
toggle = "ctrl+alt+space"      # press to start/stop
push_to_talk = "ctrl+alt+v"    # hold to talk
default_mode = "toggle"
'''

SAMPLE_SECTIONS = '''[engine]
backend = "local"

[feedback]
sound = "system"          # soft Windows cues
overlay = true

[logging]
level = "INFO"
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


class TestPersistValue:
    def _write(self, tmp_path, text=SAMPLE_SECTIONS):
        p = tmp_path / "config.toml"
        p.write_text(text, encoding="utf-8")
        return p

    def test_updates_string_keeping_comment(self, tmp_path):
        p = self._write(tmp_path)
        assert persist_value(p, "feedback", "sound", "beeps") is True
        text = p.read_text(encoding="utf-8")
        assert 'sound = "beeps"' in text
        assert "# soft Windows cues" in text

    def test_writes_booleans_as_toml(self, tmp_path):
        p = self._write(tmp_path)
        persist_value(p, "feedback", "overlay", False)
        data = tomllib.loads(p.read_text(encoding="utf-8"))
        assert data["feedback"]["overlay"] is False

    def test_writes_a_list_of_strings(self, tmp_path):
        p = self._write(tmp_path, '[dictionary]\nterms = ["Anthropic"]   # proper nouns\n')
        assert persist_value(p, "dictionary", "terms", ["Acme S.L.", "Grafana"]) is True
        text = p.read_text(encoding="utf-8")
        assert tomllib.loads(text)["dictionary"]["terms"] == ["Acme S.L.", "Grafana"]
        assert "# proper nouns" in text

    def test_replaces_a_multiline_list_whole(self, tmp_path):
        """A list spread over several lines must not be left half-rewritten."""
        p = self._write(
            tmp_path,
            '[dictionary]\nterms = [\n  "One",\n  "Two",\n]\n\n[logging]\nlevel = "INFO"\n',
        )
        persist_value(p, "dictionary", "terms", ["Three"])
        data = tomllib.loads(p.read_text(encoding="utf-8"))
        assert data["dictionary"]["terms"] == ["Three"]
        assert data["logging"]["level"] == "INFO"

    def test_empty_list(self, tmp_path):
        p = self._write(tmp_path, '[dictionary]\nterms = ["One"]\n')
        persist_value(p, "dictionary", "terms", [])
        assert tomllib.loads(p.read_text(encoding="utf-8"))["dictionary"]["terms"] == []

    def test_escapes_awkward_values(self, tmp_path):
        p = self._write(tmp_path, '[dictionary]\nterms = ["One"]\n')
        assert persist_value(p, "dictionary", "terms", ['say "hi"', "back\\slash"]) is True
        assert tomllib.loads(p.read_text(encoding="utf-8"))["dictionary"]["terms"] == [
            'say "hi"', "back\\slash",
        ]

    def test_refuses_to_write_over_broken_toml(self, tmp_path):
        """If the file cannot be parsed, leave it alone rather than guess."""
        original = '[feedback\nsound = "system"\n'   # missing bracket
        p = self._write(tmp_path, original)
        assert persist_value(p, "feedback", "sound", "off") is False
        assert p.read_text(encoding="utf-8") == original

    def test_stays_inside_its_section(self, tmp_path):
        """A key with the same name in another section must not be touched."""
        p = self._write(tmp_path, '[a]\nlevel = "INFO"\n\n[b]\nlevel = "INFO"\n')
        persist_value(p, "b", "level", "DEBUG")
        data = tomllib.loads(p.read_text(encoding="utf-8"))
        assert data["a"]["level"] == "INFO"
        assert data["b"]["level"] == "DEBUG"

    def test_adds_key_to_existing_section(self, tmp_path):
        p = self._write(tmp_path, "[feedback]\nsound = \"system\"\n\n[logging]\nlevel = \"INFO\"\n")
        persist_value(p, "feedback", "overlay", True)
        data = tomllib.loads(p.read_text(encoding="utf-8"))
        assert data["feedback"] == {"sound": "system", "overlay": True}
        assert data["logging"]["level"] == "INFO"   # following section intact

    def test_appends_missing_section(self, tmp_path):
        p = self._write(tmp_path, '[engine]\nbackend = "local"\n')
        persist_value(p, "feedback", "sound", "off")
        data = tomllib.loads(p.read_text(encoding="utf-8"))
        assert data["feedback"]["sound"] == "off"

    def test_creates_file_from_scratch(self, tmp_path):
        p = tmp_path / "config.toml"
        assert persist_value(p, "feedback", "sound", "off", example_path=tmp_path / "nope") is True
        data = tomllib.loads(p.read_text(encoding="utf-8"))
        assert data["feedback"]["sound"] == "off"
