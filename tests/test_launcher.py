"""Лаунчер: диагностика, установка/откат архива мода, перенос данных — на временных каталогах, без игры и ffdec."""
import tarfile

import pytest

from fo76db import launcher


@pytest.fixture
def env(tmp_path, monkeypatch):
    data = tmp_path / "Data"
    data.mkdir()
    monkeypatch.setattr(launcher.config, "game_data", lambda: data)
    monkeypatch.setattr(launcher, "_backup_root", lambda: tmp_path / "backups")
    monkeypatch.setattr(launcher, "built_path", lambda: tmp_path / "built" / launcher.BA2)
    return data, tmp_path


def test_install_backs_up_and_rollback_restores(env):
    data, tmp = env
    (data / launcher.BA2).write_bytes(b"orig")
    orig = tmp / "backups" / "_backup_20260101" / "Data" / launcher.BA2
    orig.parent.mkdir(parents=True)
    orig.write_bytes(b"orig")
    with pytest.raises(launcher.LauncherError):
        launcher.mod_install()  # сборки ещё нет
    b = launcher.built_path()
    b.parent.mkdir()
    b.write_bytes(b"fork")
    r = launcher.mod_install()
    assert r["changed"] and (data / launcher.BA2).read_bytes() == b"fork"
    assert open(r["backup"], "rb").read() == b"orig"
    assert not launcher.mod_install()["changed"]  # повтор — без записи
    launcher.mod_rollback()
    assert (data / launcher.BA2).read_bytes() == b"orig"


def test_diagnose_flags_missing_fork_in_config():
    st = {"ba2": {"path": "x", "sha1": "a"}, "built": {"sha1": "a"}, "config": {"modFork": None, "markConfig": False},
          "plan": {"exists": True, "mtime": "t"}, "tools": {"java": True, "ffdec": True, "swc": True},
          "running": {"game": False, "serve": True}, "ba2_mtime": None}
    rows = {r["name"]: r["ok"] for r in launcher.diagnose(st)}
    assert rows["Конфиг знает форк (modFork)"] is False and rows["Метки (markConfig)"] is False
    assert rows["Установлен собранный форк"] is True and rows["План цепочки"] is True


def test_import_rejects_path_traversal(tmp_path):
    bad = tmp_path / "bad.tar.gz"
    src = tmp_path / "x.txt"
    src.write_text("1")
    with tarfile.open(bad, "w:gz") as t:
        t.add(src, "../evil.txt")
    with pytest.raises(launcher.LauncherError):
        launcher.import_bundle(bad, tmp_path / "root")
    assert not (tmp_path / "evil.txt").exists()


def test_launcher_page_and_status(client):
    assert client.get("/launcher").status_code == 200
    r = client.get("/api/launcher/status")
    assert r.status_code == 200 and r.json()["checks"]
    assert client.post("/api/launcher/install", json={}).status_code == 400  # без confirm


def test_legscrap_write_blocked_with_fork(client):
    from fo76db import chainplan
    from fo76db.web.common import con
    c = con()
    chainplan.set_fork(c, True)
    try:
        assert client.get("/api/legscrap/preview").status_code == 409
        assert client.post("/api/legscrap/apply", json={"sha1": "x"}).status_code == 409
        assert "chain-scrap" in client.get("/protected").text
    finally:
        chainplan.set_fork(c, False)


def test_deploy_requires_confirm(client):
    assert client.post("/api/launcher/deploy", json={}).status_code == 400
    with pytest.raises(launcher.LauncherError):
        launcher.deploy(False)


def test_fork_dir_prefers_bundled(tmp_path, monkeypatch):
    (tmp_path / "mod-fork/tools").mkdir(parents=True)
    (tmp_path / "mod-fork/tools/ba2.py").write_text("")
    monkeypatch.setattr(launcher.db, "ROOT", tmp_path)
    monkeypatch.setattr(launcher.config, "load", lambda: {"mod_fork_dir": ""})
    assert launcher.fork_dir() == tmp_path / "mod-fork"


def test_parse_version_and_mismatch(tmp_path, monkeypatch):
    assert launcher._parse_version("VERSION:Number = 2.85;\n FORK_VERSION:int = 3;") == {"version": 2.85, "fork": 3}
    assert launcher._parse_version("static const VERSION:Number = 3.0;") == {"version": 3.0, "fork": None}
    assert launcher._parse_version("нет") is None
    monkeypatch.setattr(launcher, "source_version", lambda: {"version": 2.85, "fork": 1})
    monkeypatch.setattr(launcher, "ba2_version", lambda p: {"version": 2.9, "fork": None})
    monkeypatch.setattr(launcher, "original_ba2", lambda: tmp_path / "x.ba2")
    monkeypatch.setattr(launcher.config, "game_data", lambda: tmp_path)
    assert launcher.mod_versions()["compatible"] is False
