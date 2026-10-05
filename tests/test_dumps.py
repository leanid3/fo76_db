"""Загрузка выгрузок: список разрешённых адресов, повторы, атомарная запись."""
import io
import urllib.error

import pytest

from fo76db.sources import dumps


def test_check_url():
    dumps._check_url("https://github.com/x/y/releases/download/t/a.7z")
    dumps._check_url("https://objects.githubusercontent.com/a")
    for bad in ("http://github.com/a", "https://evil.example/a", "https://github.com.evil.example/a", "file:///etc/passwd"):
        with pytest.raises(ValueError):
            dumps._check_url(bad)


class _Resp(io.BytesIO):
    headers = {"Content-Length": "5"}


def test_fetch_atomic_and_size_check(tmp_path, monkeypatch):
    monkeypatch.setattr(dumps, "CACHE", tmp_path)
    monkeypatch.setattr(dumps, "_open", lambda url: _Resp(b"hello"))
    p = dumps.fetch({"tag": "t", "assets": {"a.csv": "https://github.com/a"}}, "a.csv")
    assert p.read_bytes() == b"hello" and not list(p.parent.glob("*.part"))


def test_fetch_truncated_leaves_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(dumps, "CACHE", tmp_path)
    monkeypatch.setattr(dumps, "_open", lambda url: _Resp(b"hel"))
    with pytest.raises(OSError):
        dumps.fetch({"tag": "t", "assets": {"a.csv": "https://github.com/a"}}, "a.csv")
    assert not list((tmp_path / "t").glob("*"))


def test_open_retries_5xx(monkeypatch):
    calls = []

    def fake(req, timeout):
        calls.append(1)
        if len(calls) < 3:
            raise urllib.error.HTTPError(req.full_url, 503, "x", {}, None)
        return "ok"
    monkeypatch.setattr(dumps.urllib.request, "urlopen", fake)
    monkeypatch.setattr(dumps.time, "sleep", lambda s: None)
    assert dumps._open("https://api.github.com/x") == "ok" and len(calls) == 3
