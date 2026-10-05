"""Проверка новой версии: сравнение версий, кэш, скрытие, API."""
import json

import pytest

from fo76db import db, updatecheck


def test_parse_and_compare():
    assert updatecheck.parse("v2026.10.5.3") == (2026, 10, 5, 3)
    assert updatecheck.parse("2026.10.5") < updatecheck.parse("v2026.10.5.3") < updatecheck.parse("2026.10.6")
    assert updatecheck.parse("v1.0.0-rc1") is None and updatecheck.parse("") is None


@pytest.fixture
def con(tmp_path):
    return db.connect(tmp_path / "u.sqlite")


def _latest(tag):
    return lambda: {"tag": tag, "name": tag, "url": f"https://github.com/x/y/releases/tag/{tag}", "date": "2026-10-06"}


def test_newer_available_and_dismiss(con, monkeypatch):
    monkeypatch.setattr(updatecheck, "_fetch", _latest("v2999.1.1"))
    updatecheck.refresh(con)
    u = updatecheck.info(con)
    assert u["newer"] and u["available"] and u["latest"]["tag"] == "v2999.1.1"
    updatecheck.dismiss(con, "v2999.1.1")
    u = updatecheck.info(con)
    assert u["newer"] and not u["available"]  # скрыта, но «Настройки» про неё знают
    monkeypatch.setattr(updatecheck, "_fetch", _latest("v2999.1.2"))
    updatecheck.refresh(con, force=True)
    assert updatecheck.info(con)["available"]  # следующая версия снова предлагается


def test_same_version_no_banner(con, monkeypatch):
    monkeypatch.setattr(updatecheck, "_fetch", _latest("v" + updatecheck.__version__))
    updatecheck.refresh(con)
    assert not updatecheck.info(con)["newer"]


def test_cached_between_calls(con, monkeypatch):
    calls = []
    monkeypatch.setattr(updatecheck, "_fetch", lambda: calls.append(1) or _latest("v2999.1.1")())
    updatecheck.refresh(con)
    updatecheck.refresh(con)
    assert len(calls) == 1
    updatecheck.refresh(con, force=True)
    assert len(calls) == 2


def test_error_is_recorded_not_raised(con, monkeypatch):
    def boom():
        raise OSError("нет сети")
    monkeypatch.setattr(updatecheck, "_fetch", boom)
    updatecheck.refresh(con)
    u = updatecheck.info(con)
    assert u["error"] and not u["newer"] and u["latest"] is None


def test_disabled(con, monkeypatch):
    monkeypatch.setattr(updatecheck, "enabled", lambda: False)
    monkeypatch.setattr(updatecheck, "_fetch", lambda: pytest.fail("запрос при отключённой проверке"))
    updatecheck.refresh(con, force=True)


def test_api_update(client, monkeypatch):
    monkeypatch.setattr(updatecheck, "_fetch", _latest("v2999.1.1"))
    r = client.get("/api/update", params={"refresh": "true"})
    assert r.status_code == 200 and r.json()["available"]
    assert client.post("/api/update/dismiss", json={"tag": "v2999.1.1"}).status_code == 200
    assert not client.get("/api/update").json()["available"]
    json.dumps(r.json())
