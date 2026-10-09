"""Главная, инвентарь, персонажи и профили, история выгрузок."""
from __future__ import annotations


from fastapi import APIRouter, Body, HTTPException, Request
from fastapi.responses import HTMLResponse

from ... import autotags, legendary, rolls
from ...importers.inventory import current_items_sql, item_key
from ..common import _color, CHARS_SQL, con, page

router = APIRouter()


@router.get("/inventory", response_class=HTMLResponse, include_in_schema=False)
def inventory_page(request: Request):
    chars = con().execute(
        "SELECT c.*, (SELECT max(taken_at) FROM inv_snapshots s WHERE s.character_id = c.id) AS taken_at"
        " FROM characters c ORDER BY account, name").fetchall()
    return page(request, "inventory.html", chars=chars)


@router.get("/home", response_class=HTMLResponse, include_in_schema=False)
def home_page(request: Request):
    return page(request, "home.html")


@router.get("/api/inventory")
def api_inventory():
    c = con()
    rows = c.execute(
        f"SELECT CASE WHEN ii.formid IS NOT NULL THEN printf('%08X', ii.formid) END AS id, ii.account, ii.character, ii.character_id,"
        f" ii.container, ii.name, ii.category, ii.count,"
        f" ii.weight, ii.value, ii.level, ii.stars, ii.legendary, ii.learned, ii.equipped, ii.taken_at,"
        f" i.name_ru, i.name_en, i.kind, (SELECT group_concat(c.name, ', ') FROM known_recipes k JOIN characters c ON c.id = k.character_id"
        f" WHERE k.formid = ii.formid) AS learned_by"
        f" FROM ({current_items_sql()}) ii LEFT JOIN items i ON i.formid = ii.formid").fetchall()
    tags: dict[str, list[int]] = {}
    for r in c.execute("SELECT key, tag_id FROM item_tags"):
        tags.setdefault(r[0], []).append(r[1])
    names = dict(c.execute("SELECT key, name FROM display_names").fetchall())
    autotags.ensure(c)
    atags = autotags.by_formid(c)
    leg = legendary.names(c)
    wants = rolls.compile_wants(rolls.wants(c))
    out = []
    for r in rows:
        d = dict(r)
        d["key"] = item_key(d["name"], d["stars"], d["legendary"])
        d["tags"] = tags.get(d["key"], [])
        d["display"] = names.get(d["key"])
        d["atags"] = atags.get(int(d["id"], 16), []) if d["id"] else []
        d["slots"], d["leg_extra"] = legendary.slots(d["legendary"], d["stars"], leg)
        d["roll"] = rolls.grade(d["slots"], d["category"], wants) if d["stars"] else None
        out.append(d)
    return out


# ---------- профили и теги ----------

@router.get("/api/profiles")
def api_profiles():
    c = con()
    return {"characters": [dict(r) for r in c.execute(CHARS_SQL + " ORDER BY c.account, c.name")],
            "accounts": [dict(r) for r in c.execute(
                "SELECT DISTINCT c.account, a.label, a.color FROM characters c LEFT JOIN account_labels a ON a.account = c.account"
                " ORDER BY c.account")]}


@router.post("/api/profiles")
def api_profile_save(character_id: int = Body(...), label: str | None = Body(None), color: str | None = Body(None),
                     mule: bool = Body(False), priority: int = Body(100)):
    c = con()
    c.execute("INSERT INTO profiles(character_id, label, color, mule, priority) VALUES (?, ?, ?, ?, ?)"
              " ON CONFLICT(character_id) DO UPDATE SET label = excluded.label, color = excluded.color, mule = excluded.mule,"
              " priority = excluded.priority",
              (character_id, (label or "").strip() or None, _color(color), int(mule), max(0, min(priority, 999))))
    c.commit()
    return {"ok": True}


@router.post("/api/accounts")
def api_account_save(account: str = Body(...), label: str | None = Body(None), color: str | None = Body(None)):
    c = con()
    c.execute("INSERT INTO account_labels(account, label, color) VALUES (?, ?, ?) ON CONFLICT(account)"
              " DO UPDATE SET label = excluded.label, color = excluded.color", (account, (label or "").strip() or None, _color(color)))
    c.commit()
    return {"ok": True}


@router.get("/api/home")
def api_home():
    """Итоги по персонажам и категориям для главной."""
    c = con()
    cur = current_items_sql()
    chars = {r["id"]: {**dict(r), "player": 0, "stash": 0, "player_weight": 0, "stash_weight": 0, "taken_at": None,
                       "plans": 0, "mods": 0} for r in c.execute(CHARS_SQL)}
    for r in c.execute(f"SELECT character_id, container, count(*) AS n, sum(coalesce(weight, 0) * count) AS w, max(taken_at) AS t"
                       f" FROM ({cur}) GROUP BY character_id, container"):
        ch = chars[r["character_id"]]
        ch[r["container"]] = r["n"]
        ch[r["container"] + "_weight"] = round(r["w"] or 0, 1)
        ch["taken_at"] = r["t"]
    for r in c.execute("SELECT character_id, count(*) FROM known_recipes GROUP BY 1"):
        chars[r[0]]["plans"] = r[1]
    for r in c.execute("SELECT character_id, count(*), max(taken_at) FROM known_legendary_mods WHERE learned GROUP BY 1"):
        chars[r[0]]["mods"] = r[1]
        chars[r[0]]["taken_at"] = chars[r[0]]["taken_at"] or r[2]
    cats = [dict(r) for r in c.execute(
        f"SELECT category, container, count(*) AS rows, sum(count) AS count, round(sum(coalesce(weight, 0) * count), 1) AS weight"
        f" FROM ({cur}) GROUP BY category, container ORDER BY category")]
    return {"characters": sorted(chars.values(), key=lambda x: (x["account"], x["label"])), "categories": cats}


@router.get("/history", response_class=HTMLResponse, include_in_schema=False)
def history_page(request: Request):
    chars = [dict(r) for r in con().execute(
        CHARS_SQL + " WHERE c.id IN (SELECT character_id FROM inv_snapshots) ORDER BY c.account, label")]
    return page(request, "history.html", chars=chars)


@router.get("/api/snapshots")
def api_snapshots(character_id: int, archived: bool = False):
    return [dict(r) for r in con().execute(
        "SELECT s.id, s.taken_at, s.source, s.archived, count(ii.rowid) AS rows,"
        " sum(ii.container = 'player') AS player, sum(ii.container = 'stash') AS stash,"
        " round(sum(coalesce(ii.weight, 0) * ii.count), 1) AS weight"
        " FROM inv_snapshots s LEFT JOIN inv_items ii ON ii.snapshot_id = s.id"
        " WHERE s.character_id = ? AND (? OR NOT s.archived) GROUP BY s.id ORDER BY s.taken_at DESC, s.id DESC",
        (character_id, archived))]


@router.get("/api/diff")
def api_diff(a: int, b: int):
    """Что изменилось между снимками a (раньше) и b (позже) одного персонажа."""
    c = con()
    snaps = {r["id"]: r["character_id"] for r in c.execute("SELECT id, character_id FROM inv_snapshots WHERE id IN (?, ?)", (a, b))}
    if len(set(snaps.values())) != 1 or len(snaps) != 2:
        raise HTTPException(400, "Сравниваются два снимка одного персонажа")
    items: dict[tuple, dict] = {}
    for r in c.execute("SELECT * FROM inv_items WHERE snapshot_id IN (?, ?)", (a, b)):
        k = (r["name"], r["stars"], r["legendary"] or "")
        d = items.setdefault(k, {"name": r["name"], "stars": r["stars"], "legendary": r["legendary"], "category": r["category"],
                                 "id": f"{r['formid']:08X}" if r["formid"] else None,
                                 "a_player": 0, "a_stash": 0, "b_player": 0, "b_stash": 0})
        d[f"{'a' if r['snapshot_id'] == a else 'b'}_{r['container']}"] += r["count"]
    out = []
    for d in items.values():
        ta, tb = d["a_player"] + d["a_stash"], d["b_player"] + d["b_stash"]
        if not ta:
            d["change"] = "added"
        elif not tb:
            d["change"] = "removed"
        elif ta != tb:
            d["change"] = "count"
        elif d["a_player"] != d["b_player"]:
            d["change"] = "moved"
        else:
            continue
        d["delta"] = tb - ta
        out.append(d)
    return out


@router.post("/api/snapshots/archive")
def api_snapshots_archive(character_id: int = Body(...), keep: int = Body(...)):
    """Скрыть старые снимки, оставив последние keep (≥1). Данные не удаляются."""
    c = con()
    ids = [r[0] for r in c.execute("SELECT id FROM inv_snapshots WHERE character_id = ? ORDER BY taken_at DESC, id DESC",
                                   (character_id,))][max(keep, 1):]
    c.executemany("UPDATE inv_snapshots SET archived = 1 WHERE id = ?", [(i,) for i in ids])
    c.commit()
    return {"ok": True, "archived": len(ids)}


@router.post("/api/snapshots/{sid}/unarchive")
def api_snapshot_unarchive(sid: int):
    c = con()
    c.execute("UPDATE inv_snapshots SET archived = 0 WHERE id = ?", (sid,))
    c.commit()
    return {"ok": True}
