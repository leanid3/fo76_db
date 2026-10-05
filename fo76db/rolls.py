"""Нужные роллы легендарок: сохранённые наборы «эффект на звезде» и оценка инвентаря по ним.

Хотелка (`leg_wants`) — название, тип (оружие, броня, любое) и шаблоны для звёзд 1–4. Пустой шаблон — любой эффект.
Шаблон сравнивается с эффектом на своей звезде (`legendary.slots`): с текстом описания, английским и русским
названием, без учёта регистра. Работают `*` и `?`, варианты через `|` (`Bloodied|Furious`). Так же ищут поля звёзд
на странице «Инвентарь».

Оценка легендарного предмета по лучшей подходящей хотелке:
- `god`: совпали все заполненные звёзды;
- `partial`: совпала хотя бы одна звезда (заготовка: остальные эффекты можно заменить в верстаке);
- `scrip`: для этого типа хотелки есть, но ни одна звезда не совпала, значит на скрип;
- `None`: хотелок для этого типа нет.

Уведомления: у хотелки с `notify` о каждом новом полном совпадении сообщаем один раз (`leg_want_seen`). Совпадения,
которые уже были при создании или правке хотелки, отмечаются увиденными без уведомления.
"""
from __future__ import annotations

import re
import sqlite3

from . import legendary
from .importers.inventory import current_items_sql, item_key

SCOPES = {"any": "Любое", "weapon": "Оружие", "armor": "Броня"}
GRADES = {"god": "Год-ролл", "partial": "Частично", "scrip": "На скрип"}
# Категории инвентаря, к которым относится тип хотелки (легендарная одежда редка, но бывает)
SCOPE_CATS = {"weapon": {"weapon"}, "armor": {"armor", "apparel"}}


def matcher(q: str | None):
    """Функция slot -> bool для шаблона звезды; None, если шаблон пустой."""
    alts = [a.strip().lower() for a in (q or "").split("|") if a.strip()]
    if not alts:
        return None
    tests = []
    for a in alts:
        if re.search(r"[*?]", a):
            rx = re.compile(re.escape(a).replace(r"\*", ".*").replace(r"\?", "."))
            tests.append(rx.search)
        else:
            tests.append(lambda v, a=a: a in v)
    return lambda slot: any(t((slot.get(f) or "").lower()) for f in ("text", "en", "ru") for t in tests)


def wants(c: sqlite3.Connection) -> list[dict]:
    return [dict(r) for r in c.execute("SELECT * FROM leg_wants ORDER BY name COLLATE NOCASE, id")]


def compile_wants(ws: list[dict]) -> list[tuple[dict, list]]:
    out = []
    for w in ws:
        pats = [(i, m) for i in range(4) if (m := matcher(w[f"s{i + 1}"]))]
        if pats:
            out.append((w, pats))
    return out


def grade(slots: list[dict], category: str | None, compiled: list[tuple[dict, list]]) -> dict | None:
    """{grade, want_id, want, hits: [номера звёзд], need} по лучшей хотелке или None."""
    best, applied = None, False
    for w, pats in compiled:
        if w["scope"] != "any" and category not in SCOPE_CATS.get(w["scope"], ()):
            continue
        applied = True
        hits = [i + 1 for i, m in pats if i < len(slots) and m(slots[i])]
        rank = (len(hits) == len(pats), len(hits), -len(pats))
        if best is None or rank > best[0]:
            best = (rank, w, hits, len(pats))
    if not applied:
        return None
    (full, n, _), w, hits, need = best
    g = "god" if full else "partial" if n else "scrip"
    return {"grade": g, "want_id": w["id"] if n else None, "want": w["name"] if n else None, "hits": hits, "need": need}


def graded_inventory(c: sqlite3.Connection) -> list[dict]:
    """Все легендарные предметы последних снимков с оценкой."""
    compiled = compile_wants(wants(c))
    lookup = legendary.names(c)
    out = []
    for r in c.execute(f"SELECT * FROM ({current_items_sql()}) WHERE stars > 0"):
        d = dict(r)
        d["slots"], d["leg_extra"] = legendary.slots(d["legendary"], d["stars"], lookup)
        d["key"] = item_key(d["name"], d["stars"], d["legendary"])
        d["roll"] = grade(d["slots"], d["category"], compiled)
        out.append(d)
    return out


def full_matches(c: sqlite3.Connection, want: dict) -> list[dict]:
    """Предметы, у которых совпали все заполненные звёзды хотелки: [{seen_key, character_id, name, ...}]."""
    compiled = compile_wants([want])
    if not compiled:
        return []
    lookup = legendary.names(c)
    out = []
    for r in c.execute(f"SELECT * FROM ({current_items_sql()}) WHERE stars > 0"):
        slots, _ = legendary.slots(r["legendary"], r["stars"], lookup)
        g = grade(slots, r["category"], compiled)
        if g and g["grade"] == "god":
            out.append({"seen_key": f"{r['character_id']}|{item_key(r['name'], r['stars'], r['legendary'])}",
                        "character_id": r["character_id"], "name": r["name"], "container": r["container"], "slots": slots})
    return out


def baseline(c: sqlite3.Connection, want_id: int) -> None:
    """Текущие совпадения хотелки — уже увиденные: уведомлять только о том, что появится потом."""
    w = c.execute("SELECT * FROM leg_wants WHERE id = ?", (want_id,)).fetchone()
    if w:
        c.executemany("INSERT OR IGNORE INTO leg_want_seen(want_id, key) VALUES (?, ?)",
                      [(want_id, m["seen_key"]) for m in full_matches(c, dict(w))])


def new_matches(c: sqlite3.Connection) -> list[tuple[dict, dict]]:
    """Новые полные совпадения хотелок с уведомлениями: [(хотелка, предмет)]. Отмечает их увиденными."""
    out = []
    for w in wants(c):
        if not w["notify"]:
            continue
        seen = {r[0] for r in c.execute("SELECT key FROM leg_want_seen WHERE want_id = ?", (w["id"],))}
        for m in full_matches(c, w):
            if m["seen_key"] not in seen:
                out.append((w, m))
                c.execute("INSERT OR IGNORE INTO leg_want_seen(want_id, key) VALUES (?, ?)", (w["id"], m["seen_key"]))
    c.commit()
    return out


def save(c: sqlite3.Connection, data: dict) -> int:
    """Создать или изменить хотелку; возвращает id."""
    name = (data.get("name") or "").strip()
    scope = data.get("scope") or "any"
    pats = [(data.get(f"s{i}") or "").strip() or None for i in range(1, 5)]
    if not name:
        raise ValueError("Нужно название")
    if scope not in SCOPES:
        raise ValueError("Тип: any, weapon или armor")
    if not any(pats):
        raise ValueError("Заполните хотя бы одну звезду")
    vals = (name, scope, *pats, int(bool(data.get("notify", True))))
    with c:
        if data.get("id"):
            wid = int(data["id"])
            c.execute("UPDATE leg_wants SET name = ?, scope = ?, s1 = ?, s2 = ?, s3 = ?, s4 = ?, notify = ? WHERE id = ?", (*vals, wid))
            c.execute("DELETE FROM leg_want_seen WHERE want_id = ?", (wid,))
        else:
            wid = c.execute("INSERT INTO leg_wants(name, scope, s1, s2, s3, s4, notify) VALUES (?, ?, ?, ?, ?, ?, ?)", vals).lastrowid
        baseline(c, wid)
    return wid
