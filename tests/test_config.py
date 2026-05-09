"""Tests for zig.config — config loading, coercion, and save/load round-trips."""
from zig.config import Config, _coerce, load, save


class TestCoerce:
    def test_defaults_on_empty(self):
        cfg = _coerce({})
        assert cfg == Config()

    def test_strips_unknown_keys(self):
        cfg = _coerce({"interval_seconds": 30.0, "unknown_future_key": "ignored"})
        assert cfg.interval_seconds == 30.0
        assert not hasattr(cfg, "unknown_future_key")

    def test_invalid_method_falls_back(self):
        cfg = _coerce({"method": "telekinesis"})
        assert cfg.method == "both"

    def test_valid_methods_accepted(self):
        for m in ("mouse", "key", "both"):
            assert _coerce({"method": m}).method == m

    def test_interval_below_min_falls_back(self):
        cfg = _coerce({"interval_seconds": 0.1})
        assert cfg.interval_seconds == 45.0

    def test_interval_non_numeric_falls_back(self):
        cfg = _coerce({"interval_seconds": "not-a-number"})
        assert cfg.interval_seconds == 45.0

    def test_interval_valid(self):
        cfg = _coerce({"interval_seconds": 60.0})
        assert cfg.interval_seconds == 60.0

    def test_bool_coercion(self):
        cfg = _coerce({"smart_pause": 0, "pause_on_screen_share": 1})
        assert cfg.smart_pause is False
        assert cfg.pause_on_screen_share is True

    def test_skipped_version_preserved(self):
        cfg = _coerce({"skipped_version": "0.4.0"})
        assert cfg.skipped_version == "0.4.0"


class TestLoadSaveRoundTrip:
    def test_defaults_when_no_file(self, tmp_path, monkeypatch):
        monkeypatch.setenv("APPDATA", str(tmp_path))
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        cfg = load()
        assert cfg == Config()

    def test_round_trip(self, tmp_path, monkeypatch):
        monkeypatch.setenv("APPDATA", str(tmp_path))
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

        original = Config(interval_seconds=30.0, method="mouse", hotkey="ctrl+shift+f13")
        save(original)
        loaded = load()

        assert loaded.interval_seconds == 30.0
        assert loaded.method == "mouse"
        assert loaded.hotkey == "ctrl+shift+f13"

    def test_corrupt_json_returns_defaults(self, tmp_path, monkeypatch):
        monkeypatch.setenv("APPDATA", str(tmp_path))
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

        config_file = tmp_path / "noidle" / "config.json"
        config_file.parent.mkdir(parents=True)
        config_file.write_text("{this is not json}", encoding="utf-8")

        cfg = load()
        assert cfg == Config()

    def test_non_dict_json_returns_defaults(self, tmp_path, monkeypatch):
        monkeypatch.setenv("APPDATA", str(tmp_path))
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

        config_file = tmp_path / "noidle" / "config.json"
        config_file.parent.mkdir(parents=True)
        config_file.write_text("[1, 2, 3]", encoding="utf-8")

        cfg = load()
        assert cfg == Config()

    def test_atomic_write_no_tmp_left(self, tmp_path, monkeypatch):
        monkeypatch.setenv("APPDATA", str(tmp_path))
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

        save(Config())
        tmp_files = list((tmp_path / "noidle").glob("*.tmp"))
        assert tmp_files == [], f"Unexpected .tmp files: {tmp_files}"
