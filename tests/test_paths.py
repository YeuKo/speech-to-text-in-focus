"""Where the app reads and writes once it is packaged.

The bug this guards against is silent: a build that writes config.toml or logs/
relative to whatever folder the shortcut happened to start in, or into a read-only
Program Files, and only shows up as "my settings do not stick".
"""

import pytest

from stt import config, paths


class TestIsWritable:
    def test_a_normal_folder(self, tmp_path):
        assert paths.is_writable(tmp_path) is True

    def test_a_path_that_cannot_be_created(self, tmp_path):
        # A file where a folder would have to be: mkdir and touch both fail.
        blocker = tmp_path / "blocker"
        blocker.write_text("x", encoding="utf-8")
        assert paths.is_writable(blocker / "inside") is False

    def test_leaves_nothing_behind(self, tmp_path):
        paths.is_writable(tmp_path)
        assert list(tmp_path.iterdir()) == []


class TestResolveConfig:
    def test_explicit_path_wins(self, tmp_path):
        explicit = tmp_path / "elsewhere.toml"
        assert paths.resolve_config(explicit) == explicit

    def test_a_checkout_without_config_runs_on_defaults(self, tmp_path, monkeypatch):
        monkeypatch.setattr(paths, "is_frozen", lambda: False)
        monkeypatch.setattr(paths, "app_dir", lambda: tmp_path)
        monkeypatch.setattr(paths, "user_data_dir", lambda: tmp_path / "appdata")
        assert paths.resolve_config(None) is None

    def test_config_next_to_the_app_is_preferred(self, tmp_path, monkeypatch):
        local = tmp_path / "config.toml"
        local.write_text("", encoding="utf-8")
        appdata = tmp_path / "appdata"
        appdata.mkdir()
        (appdata / "config.toml").write_text("", encoding="utf-8")
        monkeypatch.setattr(paths, "app_dir", lambda: tmp_path)
        monkeypatch.setattr(paths, "user_data_dir", lambda: appdata)
        assert paths.resolve_config(None) == local

    def test_packaged_first_run_creates_it_next_to_the_app(self, tmp_path, monkeypatch):
        """A portable copy keeps everything together, so it can be deleted in one go."""
        template = tmp_path / "config.example.toml"
        template.write_text('[engine]\nbackend = "local"\n', encoding="utf-8")
        app = tmp_path / "app"
        app.mkdir()
        monkeypatch.setattr(paths, "is_frozen", lambda: True)
        monkeypatch.setattr(paths, "app_dir", lambda: app)
        monkeypatch.setattr(paths, "user_data_dir", lambda: tmp_path / "appdata")
        monkeypatch.setattr(paths, "bundled_file", lambda name: tmp_path / name)

        created = paths.resolve_config(None)
        assert created == app / "config.toml"
        assert 'backend = "local"' in created.read_text(encoding="utf-8")

    def test_falls_back_to_appdata_when_the_app_folder_is_read_only(
        self, tmp_path, monkeypatch,
    ):
        """Installed under Program Files, writing next to the executable fails."""
        template = tmp_path / "config.example.toml"
        template.write_text("[engine]\n", encoding="utf-8")
        appdata = tmp_path / "appdata"
        monkeypatch.setattr(paths, "is_frozen", lambda: True)
        monkeypatch.setattr(paths, "app_dir", lambda: tmp_path / "program files")
        monkeypatch.setattr(paths, "user_data_dir", lambda: appdata)
        monkeypatch.setattr(paths, "bundled_file", lambda name: tmp_path / name)
        monkeypatch.setattr(paths, "is_writable", lambda d: d == appdata)

        assert paths.resolve_config(None) == appdata / "config.toml"


class TestAnchor:
    def test_relative_paths_follow_the_config(self, tmp_path):
        cfg = config.from_dict({})
        data_dir = paths.anchor(cfg, tmp_path / "config.toml")
        assert data_dir == tmp_path
        assert cfg.logging.dir == str(tmp_path / "logs")
        assert cfg.usage.file == str(tmp_path / "logs" / "usage.csv")

    def test_absolute_paths_are_left_alone(self, tmp_path):
        absolute = tmp_path / "somewhere" / "else"
        cfg = config.from_dict({
            "logging": {"dir": str(absolute)},
            "usage": {"file": str(absolute / "u.csv")},
        })
        paths.anchor(cfg, tmp_path / "config.toml")
        assert cfg.logging.dir == str(absolute)
        assert cfg.usage.file == str(absolute / "u.csv")

    def test_without_a_config_file_it_anchors_to_the_cwd(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        cfg = config.from_dict({})
        assert paths.anchor(cfg, None) == tmp_path


class TestBundledFiles:
    def test_the_template_ships_with_the_app(self):
        """packaging/stt.spec copies it in; the app needs it on a first run."""
        assert paths.bundled_file(paths.TEMPLATE_NAME).exists()

    @pytest.mark.parametrize("name", ["config.example.toml", "assets/stt.ico"])
    def test_files_listed_in_the_spec_exist(self, name):
        assert (paths.bundle_dir() / name).exists(), f"{name} is in stt.spec but missing"
