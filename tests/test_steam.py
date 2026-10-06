"""Steam: парсеры на сохранённых ответах API, схема, замеры онлайна, уведомления о патчах и смене сборки."""
import json
from pathlib import Path

import pytest

from fo76db import db, notify, steam
from fo76db.sources import steam as src

DATA = Path(__file__).parent / "fixtures"


@pytest.fixture
def con():
    c = db.connect()
    for t in ("steam_news", "online_samples", "meta", "events"):
        c.execute(f"DELETE FROM {t}")
    c.commit()
    return c


def test_parse_news():
    news = src.parse_news(json.loads((DATA / "steam_news.json").read_text(encoding="utf-8")))
    assert len(news) == 8
    patches = [n for n in news if n["patch"]]
    assert patches and all(n["gid"].isdigit() for n in news)
    assert "Update Notes" in patches[0]["title"]
    assert len(patches[0]["date"]) == 16 and patches[0]["date"][10] == "T"


def test_parse_players():
    assert src.parse_players(json.loads((DATA / "steam_players.json").read_text())) == 4506
    with pytest.raises(ValueError):
        src.parse_players({"response": {"result": 42}})


def test_parse_appmanifest():
    m = src.parse_appmanifest((DATA / "appmanifest_1151340.acf").read_text())
    assert m["buildid"] == "22334455" and m["size"] == 88123456789 and m["updated"]
    assert src.parse_appmanifest('"AppState" { }') is None


def test_refresh_news_and_online(con, monkeypatch):
    news = src.parse_news(json.loads((DATA / "steam_news.json").read_text(encoding="utf-8")))
    monkeypatch.setattr(src, "fetch_news", lambda count=40: news)
    monkeypatch.setattr(src, "fetch_players", lambda: 5000)
    r = steam.refresh_news(con)
    assert r["total"] == 8 and r["new_patches"] >= 1
    assert steam.refresh_news(con)["new_patches"] == 0  # повтор ничего нового не находит
    assert steam.sample_online(con) == 5000
    o = steam.online(con, 7)
    assert o["now"] == 5000 and o["peak24h"] == 5000 and len(o["points"]) == 1


def test_refresh_survives_network_error(con, monkeypatch):
    def boom(*a, **k):
        raise OSError("нет сети")
    monkeypatch.setattr(src, "fetch_news", boom)
    monkeypatch.setattr(src, "fetch_players", boom)
    r = steam.refresh(con)
    assert len(r["errors"]) == 2 and db.get_meta(con, "steam_error")


def test_notify_seeds_old_patches_silently(con, monkeypatch):
    sent = []
    monkeypatch.setattr(notify, "send", lambda t, b: sent.append(t))
    monkeypatch.setattr(notify.dumps, "list_releases", lambda: [])
    monkeypatch.setattr(notify.updatecheck, "refresh", lambda c: None)
    monkeypatch.setattr(notify.updatecheck, "info", lambda c: {"latest": None, "available": False})
    monkeypatch.setattr(steam.gamepaths, "steam_build", lambda: None)
    con.execute("INSERT INTO steam_news VALUES ('1', 'Fallout 76 Update Notes - old', '2026-01-01T00:00', 'u', 'x', 1)")
    con.commit()
    notify.check(con)
    assert not [t for t in sent if "обновлению" in t]
    con.execute("INSERT INTO steam_news VALUES ('2', 'Fallout 76 Update Notes - new', '2026-02-01T00:00', 'u', 'x', 1)")
    con.commit()
    notify.check(con)
    assert len([t for t in sent if "обновлению" in t]) == 1
    notify.check(con)
    assert len([t for t in sent if "обновлению" in t]) == 1  # без повторов


def test_check_build(con, monkeypatch):
    build = {"buildid": "1", "size": 1, "updated": "2026-10-01T10:00", "library": "/x"}
    monkeypatch.setattr(steam.gamepaths, "steam_build", lambda: build)
    assert steam.check_build(con) is None  # первый запуск только запоминает
    assert steam.check_build(con) is None
    build["buildid"] = "2"
    assert steam.check_build(con) == {"old": "1", "new": "2"}
    assert con.execute("SELECT count(*) FROM events WHERE source = 'steam'").fetchone()[0] == 1


def test_steam_api(client, con, monkeypatch):
    con.execute("INSERT INTO online_samples VALUES (datetime('now', 'localtime'), 123)")
    con.commit()
    assert client.get("/api/steam/online?days=1").json()["now"] == 123
    assert client.get("/api/steam/news").status_code == 200
    assert client.get("/updates").status_code == 200
