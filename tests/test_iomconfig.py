"""Запись конфига IOM: sha1-блокировка, бэкап, сохранение inode (жёсткая ссылка), откат."""
import json
import os

import pytest

from fo76db import iomconfig


@pytest.fixture
def cfg(tmp_path):
    p = tmp_path / "inventOmaticStashConfig.json"
    p.write_text(iomconfig.dumps({"a": 1}, "\t"), encoding="utf-8")
    return p, tmp_path / "backups"


def test_load_and_exact(cfg):
    p, _ = cfg
    r = iomconfig.load(p)
    assert r["data"]["a"] == 1 and r["exact"]


def test_save_creates_backup_and_keeps_inode(cfg):
    p, root = cfg
    twin = p.parent / "twin.json"
    os.link(p, twin)  # игра видит файл по второй ссылке
    ino = p.stat().st_ino
    r = iomconfig.load(p)
    out = iomconfig.save({"a": 2}, r["sha1"], p, root)
    assert out["changed"] and p.stat().st_ino == ino
    assert json.loads(twin.read_text())["a"] == 2          # изменение видно по второй ссылке
    assert len(iomconfig.backups(p, root)) == 1


def test_save_rejects_stale_sha1(cfg):
    p, root = cfg
    with pytest.raises(iomconfig.IomError):
        iomconfig.save({"a": 2}, "0" * 40, p, root)
    assert json.loads(p.read_text())["a"] == 1


def test_save_unchanged_no_backup(cfg):
    p, root = cfg
    r = iomconfig.load(p)
    out = iomconfig.save(r["data"], r["sha1"], p, root)
    assert out["changed"] is False and not iomconfig.backups(p, root)


def test_restore_latest(cfg):
    p, root = cfg
    r = iomconfig.load(p)
    saved = iomconfig.save({"a": 2}, r["sha1"], p, root)
    out = iomconfig.restore_latest(saved["sha1"], p, root)
    assert json.loads(p.read_text())["a"] == 1 and out["ok"]


def test_comments_file_not_loadable(tmp_path):
    p = tmp_path / "c.json"
    p.write_text('{ // комментарий\n "a": 1 }', encoding="utf-8")
    with pytest.raises(iomconfig.IomError):
        iomconfig.load(p)


def test_failed_write_rolls_back(cfg, monkeypatch):
    p, root = cfg
    r = iomconfig.load(p)
    before = p.read_bytes()
    real_fsync = os.fsync
    state = {"n": 0}

    def flaky(fd):  # первый fsync — бэкап, второй — запись в конфиг: роняем его
        state["n"] += 1
        if state["n"] == 2:
            raise OSError("диск отвалился")
        return real_fsync(fd)
    monkeypatch.setattr(iomconfig.os, "fsync", flaky)
    with pytest.raises(OSError):
        iomconfig.save({"a": 2}, r["sha1"], p, root)
    assert p.read_bytes() == before
