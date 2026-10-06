"""Переключатели вкладок, блоков и внешних сервисов: хранение, отказ источников, меню, страница «Раздел отключён»."""
import pytest

from fo76db import events, features, steam, updatecheck
from fo76db.sources import steam as steam_src


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(features, "FILE", tmp_path / "features.json")
    monkeypatch.setattr(features, "_cache", None)


def test_defaults_and_save():
    assert features.service_on("steam") and features.page_on("events") and features.on("events.online")
    features.save({"service:steam": False, "page:events": False})
    assert not features.service_on("steam") and not features.page_on("events")
    assert not features.on("events.online")  # страница выключена
    features.save({"service:steam": True})
    assert features.service_on("steam") and "service:steam" not in features._saved()  # значение по умолчанию не хранится


def test_unknown_key_rejected():
    for bad in ({"page:nope": False}, {"steam": False}, {"service:steam": "no"}):
        with pytest.raises(ValueError):
            features.save(bad)


def test_section_hidden_when_service_off():
    features.save({"service:steam": False})
    assert not features.on("events.online") and features.on("events.checklist")


def test_page_for_path():
    assert features.page_for_path("/") == "catalog" and features.page_for_path("/item/0000ABCD") == "catalog"
    assert features.page_for_path("/home") is None and features.page_for_path("/settings") is None


def test_update_check_default_follows_config(monkeypatch):
    monkeypatch.setattr(features.config, "load", lambda: {"update_check": False})
    assert not updatecheck.enabled()
    features.save({"service:updates": True})  # явный выбор перекрывает config.toml
    assert updatecheck.enabled()


def test_disabled_service_blocks_requests(monkeypatch):
    features.save({"service:steam": False})
    with pytest.raises(features.ServiceOff):
        steam_src.fetch_players()
    assert steam.refresh_if_stale(None) is None and steam.refresh(None)["disabled"]


def test_events_skip_when_all_services_off():
    features.save({"service:falloutbuilds": False, "service:wiki": False})
    assert events.refresh_if_stale(None) is None


def test_notifications_can_be_muted(monkeypatch):
    from fo76db import notify
    sent = []
    monkeypatch.setattr(notify, "send", lambda t, b, k="": sent.append(t))
    notify._notify("rolls", "a", "b")
    features.save({"notify:rolls": False})
    notify._notify("rolls", "c", "d")
    notify._notify("events", "e", "f")
    assert sent == ["a", "e"]
    assert [n["on"] for n in features.describe()["notifications"] if n["key"] == "notify:rolls"] == [False]


def test_web(client):
    assert client.get("/api/features").json()["services"]
    assert client.post("/api/features", json={"page:achievements": False}).status_code == 200
    r = client.get("/achievements")
    assert r.status_code == 200 and "отключён" in r.text
    assert 'href="/achievements"' not in client.get("/events").text  # пункта нет в меню
    assert client.post("/api/features", json={"page:glossary": "x"}).status_code == 400
    client.post("/api/features", json={"page:achievements": True, "service:steam": False})
    assert 'style="margin-bottom:16px" hidden' in client.get("/updates").text
    assert client.get("/settings").status_code == 200
