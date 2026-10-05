"""Оптимизатор инвентаря и тайника: куда уходит вес и что можно убрать.

Каждой записи последнего снимка даётся не больше одного совета (по приоритету ADVICE). Вес в тайнике — weightInStash
(игра считает тайник без перков; импорт пишет его в inv_items.weight для container = stash).
"""
from __future__ import annotations

import json
import sqlite3
from collections import defaultdict

from . import legendary, plantransfer, rolls
from .importers.inventory import current_items_sql

STASH_LIMIT = 1200

# порядок = приоритет; текст действия показывается в таблице
ADVICE = {
    "spoiled": "выбросить или в компостер",
    "scrapbox": "в ящик для хлама (Fallout 1st)",
    "ammobox": "в ящик для патронов (Fallout 1st)",
    "learned_plan": "уже изучена: продать или передать",
    "unlearned_plan": "изучить",
    "scrip": "легендарка не подходит под нужные роллы: на скрип",
    "junk_scrap": "разобрать на компоненты",
    "duplicate": "дубликат: оставить один",
    "heavy": "тяжёлая стопка",
}
GEAR = {"weapon", "armor", "apparel"}


def _component_weights(c: sqlite3.Connection) -> dict[int, float]:
    """Вес одного компонента = вес «X Scrap» (предмет, который разбирается ровно в 1 такой компонент)."""
    out: dict[int, float] = {}
    for fid, w, scrap in c.execute(
            "SELECT formid, weight, json_extract(stats, '$.scrap') FROM items"
            " WHERE kind = 'misc' AND weight IS NOT NULL AND json_array_length(json_extract(stats, '$.scrap')) = 1"):
        s = json.loads(scrap)[0]
        if s.get("count") == 1:
            out.setdefault(s["formid"], w)
    return out


def _scrap_weight(c: sqlite3.Connection, formid: int | None, comp_w: dict[int, float]) -> float | None:
    """Вес компонентов от разбора одной штуки; None, если разбор неизвестен."""
    if formid is None:
        return None
    row = c.execute("SELECT json_extract(stats, '$.scrap') FROM items WHERE formid = ?", (formid,)).fetchone()
    scrap = json.loads(row[0]) if row and row[0] else []
    if not scrap or any(s["formid"] not in comp_w for s in scrap):
        return None
    return sum(comp_w[s["formid"]] * s["count"] for s in scrap)


def analyze(c: sqlite3.Connection, chars: list[dict], *, scrapbox: bool = False, ammobox: bool = False,
            heavy: float = 10.0, limit: float = STASH_LIMIT) -> dict:
    labels = {ch["id"]: ch["label"] for ch in chars}
    # схемы: изучить / передать / продать — общая логика со страницей «Схемы»
    plan_move = {(m["character_id"], m["container"], m["formid"]): m for m in plantransfer.moves(c, labels)}
    want_list = rolls.compile_wants(rolls.wants(c))
    leg_names = legendary.names(c) if want_list else {}
    comp_w = _component_weights(c)

    rows = []
    for r in c.execute(current_items_sql()):
        raw = json.loads(r["raw"] or "{}")
        if raw.get("isQuestItem"):
            continue
        rows.append({
            "character_id": r["character_id"], "container": r["container"], "name": r["name"],
            "category": r["category"], "id": r["formid"], "count": r["count"], "stars": r["stars"],
            "legendary": r["legendary"], "equipped": bool(r["equipped"]),
            "unit": r["weight"] or 0.0, "weight": round((r["weight"] or 0.0) * r["count"], 2),
            "learned": bool(r["learned"]), "raw": raw,
        })

    advice = []

    def add(row: dict, kind: str, saving: float | None, note: str = "", count: int | None = None) -> None:
        row["advised"] = True
        advice.append({
            "type": kind, "action": ADVICE[kind], "note": note,
            "character_id": row["character_id"], "character": labels.get(row["character_id"], "?"),
            "container": row["container"], "name": row["name"], "id": row["id"], "category": row["category"],
            "stars": row["stars"], "legendary": row["legendary"], "count": row["count"] if count is None else count,
            "weight": row["weight"], "saving": None if saving is None else round(saving, 2),
            "key": f"{row['name']}|{row['stars']}|{row['legendary'] or ''}",
        })

    candidates = [r for r in rows if not r["equipped"] and r["weight"] > 0]

    for r in candidates:
        raw = r["raw"]
        if raw.get("isSpoiled"):
            add(r, "spoiled", r["weight"])
        elif scrapbox and raw.get("canGoIntoScrapStash"):
            add(r, "scrapbox", r["weight"])
        elif ammobox and r["category"] == "ammo":
            add(r, "ammobox", r["weight"])
        elif (m := plan_move.get((r["character_id"], r["container"], r["id"]))) is not None:
            if m["action"] == "learn":
                add(r, "unlearned_plan", r["weight"], ("ещё нужна: " + ", ".join(m["need_labels"])) if m["need"] else "")
            else:
                add(r, "learned_plan", r["weight"],
                    ("передать: " + ", ".join(m["need_labels"])) if m["need"] else "изучена у всех персонажей")
        elif r["stars"] and want_list:
            slots, _ = legendary.slots(r["legendary"], r["stars"], leg_names)
            g = rolls.grade(slots, r["category"], want_list)
            if g and g["grade"] == "scrip":
                add(r, "scrip", r["weight"], f"{r['stars']}★, ни одна звезда не совпала с хотелками")
        elif r["category"] == "junk" and raw.get("scrapAllowed"):
            per = _scrap_weight(c, r["id"], comp_w)
            if scrapbox:
                add(r, "junk_scrap", r["weight"], "компоненты уйдут в ящик для хлама")
            elif per is not None:
                if per * r["count"] < r["weight"] - 0.005:  # иначе разбор не облегчит (наборы, коробки)
                    add(r, "junk_scrap", r["weight"] - per * r["count"], f"компоненты весят {per * r['count']:.2f}")
            else:
                add(r, "junk_scrap", None, "состав разбора неизвестен")

    # Дубликаты снаряжения по всем персонажам: оставляем одну штуку (надетую или самую лёгкую по месту хранения)
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for r in rows:
        if r["category"] in GEAR or r["stars"]:
            groups[(r["name"], r["stars"], r["legendary"])].append(r)
    for g in groups.values():
        if sum(r["count"] for r in g) < 2:
            continue
        if not g[0]["stars"] and any(r["count"] > 1 for r in g):
            continue  # складывается в стопку (гранаты, мины, фейерверки) — это расходник, а не дубликат
        places: dict[str, int] = defaultdict(int)
        for r in g:
            places[f"{labels.get(r['character_id'], '?')}/{'тайник' if r['container'] == 'stash' else 'инв.'}"] += r["count"]
        where = ", ".join(f"{k} ×{n}" if n > 1 else k for k, n in places.items())
        keep = max(g, key=lambda r: (r["equipped"], r["container"] == "player", -r["unit"]))
        # одна строка совета на персонажа и место хранения, а не на каждую копию
        extra: dict[tuple, list] = {}
        for r in g:
            if r.get("advised") or r["equipped"] or r["unit"] <= 0:
                continue
            n = r["count"] - 1 if r is keep else r["count"]
            if n > 0:
                e = extra.setdefault((r["character_id"], r["container"]), [r, 0, 0.0])
                e[1] += n
                e[2] += r["unit"] * n
                r["advised"] = True
        for first, n, saving in extra.values():
            add(first, "duplicate", saving, "есть: " + where, count=n)
            advice[-1]["weight"] = round(sum(x["weight"] for x in g if x["character_id"] == first["character_id"]
                                             and x["container"] == first["container"]), 2)

    for r in candidates:
        if not r.get("advised") and r["weight"] >= heavy:
            add(r, "heavy", None, "")

    # Итоги по персонажам
    summary = {ch["id"]: {**ch, "limit": limit, "player": 0.0, "stash": 0.0, "saving_player": 0.0, "saving_stash": 0.0,
                          "categories": defaultdict(lambda: {"player": 0.0, "stash": 0.0})} for ch in chars}
    for r in rows:
        s = summary.get(r["character_id"])
        if s is None:
            continue
        s[r["container"]] += r["weight"]
        s["categories"][r["category"]][r["container"]] += r["weight"]
    for a in advice:
        if a["saving"]:
            summary[a["character_id"]]["saving_" + a["container"]] += a["saving"]
    out = []
    for s in summary.values():
        if not s["player"] and not s["stash"]:
            continue
        cats = sorted(({"category": k, "player": round(v["player"], 1), "stash": round(v["stash"], 1)}
                       for k, v in s["categories"].items()), key=lambda x: -(x["player"] + x["stash"]))
        out.append({**s, "player": round(s["player"], 1), "stash": round(s["stash"], 1),
                    "saving_player": round(s["saving_player"], 1), "saving_stash": round(s["saving_stash"], 1),
                    "categories": [x for x in cats if x["player"] or x["stash"]]})
    return {"characters": out, "advice": advice, "types": ADVICE}
