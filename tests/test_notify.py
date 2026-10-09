"""Уведомления: порядок ключей в `notified` и запись уведомлений для браузера."""
from fo76db import db, notify


def test_mark_drops_oldest_first(tmp_path):
    con = db.connect(tmp_path / "t.sqlite")
    old = [f"k{i:04d}" for i in range(500)]
    notify._mark(con, old, {"a-new"})
    seq = notify._sent(con)
    assert len(seq) == 500 and seq[-1] == "a-new" and "k0000" not in seq and "k0001" in seq


def test_send_stores_for_browser(tmp_path, monkeypatch):
    path = tmp_path / "t.sqlite"
    monkeypatch.setattr(notify, "connect", lambda: db.connect(path))
    monkeypatch.setattr(notify.shutil, "which", lambda _: None)
    notify.send("Заголовок", "текст", "events")
    rows = db.connect(path).execute("SELECT kind, title, body FROM notifications").fetchall()
    assert [tuple(r) for r in rows] == [("events", "Заголовок", "текст")]


def test_push_telegram_and_ntfy(monkeypatch):
    from fo76db import config, notify
    sent = []
    monkeypatch.setattr(config, "load", lambda *a, **k: {"ntfy_topic": "t", "ntfy_server": "http://n.example", "telegram_token": "123:abc", "telegram_chat_id": 42})
    monkeypatch.setattr(notify, "_post_json", lambda url, payload: sent.append((url, payload)) or {})
    assert notify.test() == {"ntfy": None, "telegram": None}
    assert sent[0][0] == "http://n.example" and sent[1][0] == "https://api.telegram.org/bot123:abc/sendMessage"
    assert sent[1][1]["chat_id"] == "42"


def test_push_without_channels(monkeypatch):
    from fo76db import config, notify
    monkeypatch.setattr(config, "load", lambda *a, **k: {})
    assert notify.test() == {}
