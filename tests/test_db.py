"""Схема и миграции: пустая база и база старой схемы."""
import sqlite3

from fo76db import db


def test_connect_empty(tmp_path):
    con = db.connect(tmp_path / "x.sqlite")
    assert con.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    cols = {r[1] for r in con.execute("PRAGMA table_info(events)")}
    assert {"source", "ext_key", "data"} <= cols


def test_connect_idempotent(tmp_path):
    p = tmp_path / "x.sqlite"
    db.connect(p).close()
    db.connect(p).close()  # повторные миграции не падают (duplicate column)


def test_migrate_old_schema(tmp_path):
    p = tmp_path / "old.sqlite"
    old = sqlite3.connect(p)
    old.execute("CREATE TABLE events (id INTEGER PRIMARY KEY, kind TEXT NOT NULL, title TEXT NOT NULL,"
                " start TEXT NOT NULL, end TEXT, source_url TEXT, note TEXT)")  # без source/ext_key/data
    old.commit()
    old.close()
    con = db.connect(p)
    assert "ext_key" in {r[1] for r in con.execute("PRAGMA table_info(events)")}


def test_schema_checked_once_per_process(tmp_path, monkeypatch):
    p = tmp_path / "x.sqlite"
    db.connect(p).close()
    calls = []
    monkeypatch.setattr(db, "_migrate", lambda con: calls.append(1))
    db.connect(p).close()
    assert not calls  # второй connect схему не перепроверяет


def test_busy_timeout(tmp_path):
    con = db.connect(tmp_path / "x.sqlite")
    assert con.execute("PRAGMA busy_timeout").fetchone()[0] == 30000
