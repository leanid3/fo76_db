"""Настройки: кэш load(), атомарная запись, порча paths.json."""
import json

from fo76db import config


def test_write_atomic_replaces_and_leaves_no_tmp(tmp_path):
    f = tmp_path / "a.json"
    config.write_atomic(f, "1")
    config.write_atomic(f, "2")
    assert f.read_text() == "2" and [p.name for p in tmp_path.iterdir()] == ["a.json"]


def test_load_cache_follows_env(monkeypatch):
    monkeypatch.setenv("FO76DB_TOKEN", "a")
    assert config.load()["token"] == "a"
    monkeypatch.setenv("FO76DB_TOKEN", "b")
    assert config.load()["token"] == "b"


def test_load_returns_copy():
    config.load()["inventory"].append("мусор")
    assert "мусор" not in config.load()["inventory"]


def test_save_paths_roundtrip_and_corruption(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(config, "PATHS_FILE", tmp_path / "paths.json")
    config.save_paths({"game_data": "/x/Data"})
    assert config.saved_paths() == {"game_data": "/x/Data"}
    (tmp_path / "paths.json").write_text("{oops")
    with caplog.at_level("WARNING"):
        assert config.saved_paths() == {}
    assert "paths.json" in caplog.text
    assert json.loads(json.dumps({})) == {}
