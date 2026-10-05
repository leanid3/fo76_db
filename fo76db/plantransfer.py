"""Схемы в инвентаре между персонажами: изучить, передать или продать.

Для каждой схемы из последних снимков смотрим, кто её уже знает (`known_recipes` плюс пометка «изучено» в самой
выгрузке), и решаем:
- `learn`: держатель её не знает и сам учит схемы;
- `give`: держатель знает или это склад, а кто-то из учеников не знает: передать им;
- `sell`: все ученики уже знают: продать, выбросить или отдать другим игрокам.

Ученики — персонажи, о которых есть данные (снимок инвентаря или изученные схемы), кроме складов (`profiles.mule`).
Про персонажей без данных ничего не утверждаем: у них схема может быть и изучена.
"""
from __future__ import annotations

import sqlite3
from collections import defaultdict

from .importers.inventory import current_items_sql

ACTIONS = {"learn": "Изучить", "give": "Передать", "sell": "Продать"}


def learners(c: sqlite3.Connection) -> set[int]:
    with_data = {r[0] for r in c.execute("SELECT character_id FROM inv_snapshots UNION SELECT character_id FROM known_recipes")}
    mules = {r[0] for r in c.execute("SELECT character_id FROM profiles WHERE mule = 1")}
    return with_data - mules


def moves(c: sqlite3.Connection, labels: dict[int, str]) -> list[dict]:
    """[{id, formid, name, name_ru, character_id, holder, container, count, action, need, need_labels, known_labels}]."""
    learn = learners(c)
    known: dict[int, set[int]] = defaultdict(set)
    for cid, fid in c.execute("SELECT character_id, formid FROM known_recipes"):
        known[fid].add(cid)
    out = []
    for r in c.execute(
            f"SELECT ii.*, i.name_ru, i.name_en FROM ({current_items_sql()}) ii JOIN items i ON i.formid = ii.formid"
            " WHERE i.kind IN ('plan', 'recipe')"):
        fid, holder = r["formid"], r["character_id"]
        kn = set(known.get(fid, ())) | ({holder} if r["learned"] else set())
        need = sorted((cid for cid in learn if cid not in kn), key=lambda i: labels.get(i, ""))
        if holder in need:
            action = "learn"
            need.remove(holder)
        else:
            action = "give" if need else "sell"
        out.append({
            "id": f"{fid:08X}", "formid": fid, "name": r["name"], "name_ru": r["name_ru"], "name_en": r["name_en"],
            "character_id": holder, "holder": labels.get(holder, "?"), "container": r["container"], "count": r["count"],
            "action": action, "need": need, "need_labels": [labels.get(i, "?") for i in need],
            "known_labels": sorted(labels.get(i, "?") for i in kn if i in labels),
        })
    return out
