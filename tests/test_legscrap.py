"""Цепочка разбора легендарок: назначенный персонаж, правила LegeScrap, защита."""
import sqlite3

from fo76db import db, legscrap


def _con(tmp_path):
    c = db.connect(tmp_path / "t.sqlite")
    c.row_factory = sqlite3.Row
    for cid, name, prio in ((1, "a", 0), (2, "b", 5), (3, "c", 100)):
        c.execute("INSERT INTO characters(id, account, name) VALUES (?, 'acc', ?)", (cid, name))
        c.execute("INSERT INTO profiles(character_id, priority) VALUES (?, ?) ON CONFLICT(character_id) DO UPDATE SET priority = ?",
                  (cid, prio, prio))
    # Bloodied ★1 выучили a и b; Furious ★1 — только c; Rapid ★2 — все
    mods = {1: {"Bloodied": 1, "Rapid": 1}, 2: {"Bloodied": 1, "Rapid": 1}, 3: {"Furious": 1, "Rapid": 1}}
    for cid in (1, 2, 3):
        for name, st in (("Bloodied", 1), ("Furious", 1)):
            c.execute("INSERT INTO known_legendary_mods(character_id, name, stars, learned) VALUES (?, ?, ?, ?)",
                      (cid, name, st, int(name in mods[cid])))
        c.execute("INSERT INTO known_legendary_mods(character_id, name, stars, learned) VALUES (?, 'Rapid', 2, 1)", (cid,))
    c.commit()
    return c


def test_designated_is_highest_priority_among_unlearned(tmp_path):
    ch = legscrap.Chain(_con(tmp_path))
    assert ch.designated[("Bloodied", 1)] == 3      # не выучил только c
    assert ch.designated[("Furious", 1)] == 1       # a выше b, оба не выучили
    assert ch.designated[("Rapid", 2)] is None      # выучено всеми


def test_item_advice(tmp_path):
    ch = legscrap.Chain(_con(tmp_path))
    assert legscrap.item_advice(ch, 3, [("Bloodied", 1)])["type"] == "self"
    assert legscrap.item_advice(ch, 1, [("Bloodied", 1)])["target"] == 3
    assert legscrap.item_advice(ch, 1, [("Rapid", 2)])["type"] == "learned"
    assert legscrap.item_advice(ch, 1, [None]) is None


def test_excluded_only_effects_for_others(tmp_path):
    ch = legscrap.Chain(_con(tmp_path))
    assert "bloodied" in legscrap.excluded_for(ch, 1) and "furious" not in legscrap.excluded_for(ch, 1)
    assert "furious" in legscrap.excluded_for(ch, 3)


def test_build_rules_keeps_manual_exclusions(tmp_path):
    r = legscrap.build_rules(_con(tmp_path), {"name": "LegeScrap", "excluded": ["two shot", "Bloodied"], "hotkey": "G"}, keep_manual=True)
    first = r["rules"][0]
    assert first["characterName"] == "a" and first["checkCharacterName"] and first["hotkey"] == "G"
    assert first["excluded"].count("Bloodied") + first["excluded"].count("bloodied") == 1 and "two shot" in first["excluded"]


def test_protected_unique_and_godroll(tmp_path):
    c = _con(tmp_path)
    c.execute("INSERT INTO protected_items(kind, name_en) VALUES ('unique', 'Holy Fire')")
    c.execute("INSERT INTO protected_items(kind, name_en, scope, s1, s2, s3, s4) VALUES ('godroll', 'x', 'weapon', 'Bloodied|Quad', 'Explosive', 'Swift', 'Nothing')")
    c.commit()
    ch = legscrap.Chain(c)
    assert legscrap.protected_reason(ch, formid=None, name="-EXP holyfire", category="weapon", slots=[]) == "уникальный"
    slots = [{"star": 1, "text": "Bloodied", "en": "Bloodied", "ru": None}, {"star": 2, "text": "Explosive", "en": "Explosive", "ru": None}]
    assert legscrap.protected_reason(ch, formid=None, name="Gun", category="weapon", slots=slots) is None  # две звезды — обычный
    slots.append({"star": 3, "text": "Swift", "en": "Swift", "ru": None})
    assert legscrap.protected_reason(ch, formid=None, name="Gun", category="weapon", slots=slots).startswith("годролл")
    slots.append({"star": 4, "text": "Whatever", "en": "Whatever", "ru": None})  # 4★ в оценку не входит
    assert legscrap.protected_reason(ch, formid=None, name="Gun", category="weapon", slots=slots).startswith("годролл")
    assert legscrap.protected_reason(ch, formid=None, name="Gun", category="armor", slots=slots) is None
    slots[2]["en"] = slots[2]["text"] = "Lightweight"
    assert legscrap.protected_reason(ch, formid=None, name="Gun", category="weapon", slots=slots) is None


def test_manual_exclusions_dropped_by_default(tmp_path):
    r = legscrap.build_rules(_con(tmp_path), {"name": "LegeScrap", "excluded": ["two shot"]})
    assert "two shot" not in r["rules"][0]["excluded"]


def test_new_unprotected_baseline_then_new(tmp_path):
    c = _con(tmp_path)
    assert legscrap.new_unprotected(c, set()) == []     # первый запуск только запоминает
    assert legscrap.new_unprotected(c, {"x"}) == []


def test_protect_names_added_to_every_rule(tmp_path):
    r = legscrap.build_rules(_con(tmp_path), {"name": "LegeScrap", "excluded": []}, protect=["V63-BERTHA", "Whacker Smacker"])
    for rule in r["rules"]:
        assert "V63-BERTHA" in rule["excluded"] and "Whacker Smacker" in rule["excluded"]


def test_accounts_beside_legendary_mods(tmp_path):
    from fo76db.importers import inventory
    (tmp_path / "itemsmod.ini").write_text('{"characterInventories": {"main": {"AccountInfoData": {"name": "RedTiger936"}}}}')
    assert inventory._accounts_beside(tmp_path / "LegendaryMods.ini") == {"main": "RedTiger936"}
    assert inventory._accounts_beside(tmp_path / "nope" / "LegendaryMods.ini") == {}
