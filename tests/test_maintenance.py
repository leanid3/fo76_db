"""Копия базы, /healthz, /api/doctor, ограничение скачивания копии."""
import sqlite3

from fo76db import maintenance


def test_backup_is_valid_and_rotated(tmp_path):
    import time
    paths = []
    for _ in range(3):
        paths.append(maintenance.backup(tmp_path, keep=2))
        time.sleep(1.1)  # имя — с секундами
    left = sorted(p.name for p in tmp_path.glob("fo76-*.sqlite"))
    assert len(left) == 2 and paths[0].name not in left
    con = sqlite3.connect(paths[-1])
    assert con.execute("SELECT COUNT(*) FROM sqlite_master WHERE name='items'").fetchone()[0] == 1
    assert not list(tmp_path.glob("*.part"))


def test_backup_keeps_foreign_files(tmp_path):
    (tmp_path / "notes.txt").write_text("мои заметки")
    maintenance.backup(tmp_path, keep=1)
    assert (tmp_path / "notes.txt").exists()


def test_healthz_open_without_token(remote, monkeypatch):
    monkeypatch.setenv("FO76DB_TOKEN", "secret")
    r = remote.get("/healthz")
    assert r.status_code == 200 and r.json()["ok"] is True and "items" not in r.json()


def test_backup_download_local_only(client, remote, monkeypatch):
    monkeypatch.setenv("FO76DB_TOKEN", "secret")
    remote.cookies.set("fo76db_token", "secret")
    assert remote.get("/api/backup").status_code == 403
    r = client.get("/api/backup")
    assert r.status_code == 200 and r.content[:15] == b"SQLite format 3"


def test_doctor_structure(client):
    rows = client.get("/api/doctor").json()
    assert rows and all({"name", "ok", "detail", "hint"} <= set(r) for r in rows)
