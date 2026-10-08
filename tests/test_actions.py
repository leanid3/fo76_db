"""Таблица действий: импорт правил конфига, сборка конфига, порядок и ручные правила."""
import copy
import sqlite3

from fo76db import actions, db


def _con(tmp_path):
    c = db.connect(tmp_path / "t.sqlite")
    c.row_factory = sqlite3.Row
    return c


def _cfg():
    return {
        "scrapConfig": {"enabled": True, "configs": [
            {"name": "Junk", "enabled": True, "hotkey": "G", "testRun": False, "excluded": ["x"], "weird": 1},
            {"name": "Other", "enabled": True, "hotkey": "H"},
        ]},
        "transferConfig": [{"name": "To box", "enabled": True, "hotkey": "F", "types": ["JUNK"]}],
    }


def test_import_is_idempotent_and_keeps_unknown_fields(tmp_path):
    c = _con(tmp_path)
    assert actions.import_rules(c, _cfg())["added"] == 3
    assert actions.import_rules(c, _cfg()) == {"added": 0, "skipped": 3}
    a = c.execute("SELECT * FROM actions WHERE name='Junk'").fetchone()
    assert a["type"] == "scrap" and a["test_run"] == 0 and '"weird"' in a["raw"]


def test_build_replaces_imported_and_keeps_manual(tmp_path):
    c = _con(tmp_path)
    cfg = _cfg()
    actions.import_rules(c, cfg)
    c.execute("DELETE FROM actions WHERE name='Other'")  # «Other» остаётся ручным
    c.execute("UPDATE actions SET test_run=1, character='leanid2', account='acc' WHERE name='Junk'")
    c.commit()
    res = actions.build_config(c, cfg)
    sc = res["data"]["scrapConfig"]["configs"]
    assert [r["name"] for r in sc] == ["Junk", "Other"]
    assert sc[0]["testRun"] is True and sc[0]["characterName"] == "leanid2" and sc[0]["checkAccountName"] is True
    assert sc[0]["weird"] == 1 and "fo76db" in sc[0] and "fo76db" not in sc[1]
    # повторная сборка поверх результата не плодит дубликатов
    again = actions.build_config(c, res["data"])
    assert len(again["data"]["scrapConfig"]["configs"]) == 2
    assert cfg == _cfg()  # исходные данные не изменены


def test_order_and_after(tmp_path):
    c = _con(tmp_path)
    for n, o, aft in (("a", 0, 2), ("b", 1, None), ("c", 2, None)):
        c.execute("INSERT INTO actions(name, type, ord, after_id) VALUES (?, 'scrap', ?, ?)", (n, o, aft))
    c.commit()
    assert [r["name"] for r in actions.ordered(c)] == ["b", "a", "c"]


def test_fork_only_skipped_and_testrun_explicit(tmp_path):
    c = _con(tmp_path)
    c.execute("INSERT INTO actions(name, type) VALUES ('use', 'consume')")
    c.execute("INSERT INTO actions(name, type, filter) VALUES ('s', 'scrap', '{\"legendaryEffects\":[{\"name\":\"Aegis\",\"stars\":4}]}')")
    c.commit()
    res = actions.build_config(c, copy.deepcopy(_cfg()))
    assert len(res["skipped"]) == 2 and res["written"] == 0
    fork = _cfg() | {"modFork": {"name": "fo76db", "version": 1}}
    res = actions.build_config(c, fork)
    assert res["written"] == 1
    new = next(r for r in res["data"]["scrapConfig"]["configs"] if r["name"] == "s")
    assert new["testRun"] is True


def test_api_crud_order_and_page(client):
    r = client.post("/api/actions", json={"name": "A", "type": "scrap", "hotkey": "g", "filter": {"excluded": ["x"]}})
    b = client.post("/api/actions", json={"name": "B", "type": "consume"}).json()["id"]
    a = r.json()["id"]
    assert client.post("/api/actions", json={"type": "nope"}).status_code == 400
    assert client.post("/api/actions/order", json={"ids": [b, a]}).status_code == 200
    items = client.get("/api/actions").json()["items"]
    assert [i["name"] for i in items if i["id"] in (a, b)] == ["B", "A"]
    assert client.patch(f"/api/actions/{a}", json={"enabled": False, "filter": "{bad"}).status_code == 400
    assert client.post("/api/actions/bulk", json={"ids": [a, b], "values": {"test_run": False}}).status_code == 200
    assert client.delete(f"/api/actions/{a}").status_code == 200
    assert client.get("/actions").status_code == 200
