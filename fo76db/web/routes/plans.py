"""Легендарные моды, схемы (изучено/мулы), роллы, оптимизация."""
from __future__ import annotations

import json

from fastapi import APIRouter, Body, HTTPException, Request
from fastapi.responses import HTMLResponse

from ... import chainplan, iomconfig, legendary, legscrap, optimize, plantransfer, rolls
from ...importers.inventory import current_items_sql
from ...db import set_meta
from ..common import CHARS_SQL, con, page

router = APIRouter()


@router.get("/legendary", response_class=HTMLResponse, include_in_schema=False)
def legendary_page(request: Request):
    return page(request, "legendary.html")


@router.get("/plans", response_class=HTMLResponse, include_in_schema=False)
def plans_page(request: Request):
    chars = con().execute("SELECT * FROM characters ORDER BY account, name").fetchall()
    return page(request, "plans.html", chars=chars)


@router.get("/api/legendary/effects")
def api_legendary_effects():
    """Подсказки для поиска по звёздам: {звезда: [{en, ru, desc}]}."""
    return legendary.catalog(con())


@router.get("/api/legendary")
def api_legendary():
    c = con()
    chars = [dict(r) for r in c.execute(
        "SELECT c.id, coalesce(p.label, c.name) AS name, max(k.taken_at) AS taken_at FROM characters c"
        " JOIN known_legendary_mods k ON k.character_id = c.id LEFT JOIN profiles p ON p.character_id = c.id"
        " GROUP BY c.id ORDER BY 2")]
    mods: dict[str, dict] = {}
    # английские описания приоритетнее: у русского клиента свой перевод
    for r in c.execute("SELECT * FROM known_legendary_mods ORDER BY name_local IS NOT NULL"):
        m = mods.setdefault(f"{r['name']}|{r['stars']}", {
            "name": r["name"], "stars": r["stars"], "description": json.loads(r["description"] or "{}"), "local": []})
        m[f"c{r['character_id']}"] = bool(r["learned"])
        if r["name_local"] and r["name_local"] not in m["local"]:
            m["local"].append(r["name_local"])
    return {"characters": chars, "mods": sorted(mods.values(), key=lambda m: (m["stars"] or 0, m["name"]))}


@router.get("/api/plans")
def api_plans():
    c = con()
    chars = [dict(r) for r in c.execute(CHARS_SQL + " ORDER BY c.account, label")]
    known: dict[int, dict[int, str]] = {}
    for r in c.execute("SELECT * FROM known_recipes"):
        known.setdefault(r["formid"], {})[r["character_id"]] = r["source"]
    rows = c.execute(
        "SELECT i.formid, printf('%08X', i.formid) AS id, i.name_ru, i.name_en, i.kind, ba.update_name AS added_update,"
        " json_extract(i.stats, '$.in_lvli') AS in_lvli,"
        " (SELECT p.name_ru FROM recipes r JOIN items p ON p.formid = r.product WHERE r.plan = i.formid LIMIT 1) AS product"
        " FROM items i LEFT JOIN builds ba ON ba.tag = i.added_build"
        " WHERE i.kind IN ('plan', 'recipe') AND i.status = 'ok' AND json_extract(i.stats, '$.teaches') = 1").fetchall()
    out = []
    for r in rows:
        d = dict(r)
        for ch in chars:
            d[f"c{ch['id']}"] = known.get(r["formid"], {}).get(ch["id"])
        out.append(d)
    return {"characters": chars, "plans": out}


@router.get("/api/plans/moves")
def api_plan_moves():
    """Схемы в инвентаре: изучить, передать (кому) или продать."""
    c = con()
    chars = [dict(r) for r in c.execute(CHARS_SQL + " ORDER BY c.account, label")]
    return {"characters": chars, "learners": sorted(plantransfer.learners(c)),
            "moves": plantransfer.moves(c, {ch["id"]: ch["label"] for ch in chars}), "actions": plantransfer.ACTIONS}


@router.post("/api/mule")
def api_mule(character_id: int = Body(...), mule: bool = Body(...)):
    """Отметить персонажа складом (ему не предлагаются схемы) — без изменения имени и цвета."""
    c = con()
    c.execute("INSERT INTO profiles(character_id, mule) VALUES (?, ?) ON CONFLICT(character_id) DO UPDATE SET mule = excluded.mule",
              (character_id, int(mule)))
    c.commit()
    return {"ok": True}


@router.post("/api/known")
def api_known(character_id: int = Body(...), formid: str = Body(...), known: bool = Body(...)):
    c = con()
    fid = int(formid, 16)
    if known:
        c.execute("INSERT INTO known_recipes(character_id, formid, source) VALUES (?, ?, 'manual') ON CONFLICT DO NOTHING", (character_id, fid))
    else:
        c.execute("DELETE FROM known_recipes WHERE character_id = ? AND formid = ? AND source = 'manual'", (character_id, fid))
    c.commit()
    return {"ok": True}


@router.get("/api/known")
def api_known_list(character_id: int):
    """Изученные схемы персонажа: {FormID: auto|manual}."""
    return {f"{r[0]:08X}": r[1] for r in con().execute(
        "SELECT formid, source FROM known_recipes WHERE character_id = ?", (character_id,))}


@router.post("/api/known/bulk")
def api_known_bulk(character_id: int = Body(...), formids: list[str] = Body(...), known: bool = Body(...)):
    c = con()
    fids = [(character_id, int(f, 16)) for f in formids]
    if known:
        c.executemany("INSERT INTO known_recipes(character_id, formid, source) VALUES (?, ?, 'manual') ON CONFLICT DO NOTHING", fids)
    else:  # автоматические отметки (схема видна в инвентаре как изученная) вручную не снимаются
        c.executemany("DELETE FROM known_recipes WHERE character_id = ? AND formid = ? AND source = 'manual'", fids)
    c.commit()
    return {"ok": True, "count": len(fids)}


@router.get("/api/updates/plans")
def api_updates_plans(character_id: int):
    """Сколько схем и рецептов каждого обновления изучено у персонажа."""
    rows = con().execute(
        "SELECT b.update_name, count(DISTINCT i.formid) AS total, count(DISTINCT k.formid) AS known"
        " FROM items i JOIN builds b ON b.tag = i.added_build"
        " LEFT JOIN known_recipes k ON k.formid = i.formid AND k.character_id = ?"
        " WHERE i.kind IN ('plan', 'recipe') AND i.status = 'ok' AND json_extract(i.stats, '$.teaches') = 1"
        " GROUP BY b.update_name", (character_id,))
    return {r["update_name"] or "—": {"total": r["total"], "known": r["known"]} for r in rows}


@router.get("/optimize", response_class=HTMLResponse, include_in_schema=False)
def optimize_page(request: Request):
    return page(request, "optimize.html", limit=optimize.STASH_LIMIT)


@router.get("/api/optimize")
def api_optimize(scrapbox: bool = False, ammobox: bool = False, heavy: float = 10.0, limit: float = optimize.STASH_LIMIT):
    c = con()
    chars = [dict(r) for r in c.execute(CHARS_SQL + " ORDER BY c.account, label")]
    return optimize.analyze(c, chars, scrapbox=scrapbox, ammobox=ammobox, heavy=max(heavy, 0.1), limit=limit)


@router.get("/rolls", response_class=HTMLResponse, include_in_schema=False)
def rolls_page(request: Request):
    return page(request, "rolls.html", SCOPES=rolls.SCOPES, GRADES=rolls.GRADES)


@router.get("/api/rolls")
def api_rolls():
    """Хотелки с числом совпадений и все легендарные предметы с оценкой."""
    c = con()
    items = rolls.graded_inventory(c)
    ws = rolls.wants(c)
    for w in ws:
        w["god"] = sum(1 for d in items if d["roll"] and d["roll"]["want_id"] == w["id"] and d["roll"]["grade"] == "god")
        w["partial"] = sum(1 for d in items if d["roll"] and d["roll"]["want_id"] == w["id"] and d["roll"]["grade"] == "partial")
    keep = ("formid", "name", "category", "count", "stars", "legendary", "equipped", "container", "character_id", "character",
            "account", "key", "slots", "leg_extra", "roll", "weight")
    return {"wants": ws, "items": [{k: d[k] for k in keep} | {"id": f"{d['formid']:08X}" if d["formid"] else None} for d in items]}


@router.post("/api/rolls")
def api_roll_save(data: dict = Body(...)):
    try:
        return {"id": rolls.save(con(), data)}
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.delete("/api/rolls/{want_id}")
def api_roll_delete(want_id: int):
    c = con()
    c.execute("DELETE FROM leg_wants WHERE id = ?", (want_id,))
    c.commit()
    return {"ok": True}


# ---------- разбор легендарок и защита ----------

@router.get("/protected", response_class=HTMLResponse, include_in_schema=False)
def protected_page(request: Request):
    return page(request, "protected.html", SCOPES=rolls.SCOPES, FORK=chainplan.fork_on(con()))


@router.get("/api/protected")
def api_protected():
    """Список защиты, предметы в инвентаре под защитой и кандидаты из избранного."""
    c = con()
    chain = legscrap.Chain(c)
    items = []
    for r in c.execute(f"SELECT * FROM ({current_items_sql()}) WHERE stars > 0"):
        slots, _ = legendary.slots(r["legendary"], r["stars"], chain.lookup)
        raw = json.loads(r["raw"] or "{}")
        why = legscrap.protected_reason(chain, formid=r["formid"], name=r["name"], category=r["category"], slots=slots)
        if why:
            items.append({"character": r["character"], "container": r["container"], "name": r["name"], "stars": r["stars"],
                          "legendary": r["legendary"], "reason": why, "count": r["count"],
                          "marked": bool(raw.get("favorite") or raw.get("isTransferLocked"))})
    return {"rows": [dict(r) for r in c.execute("SELECT * FROM protected_items ORDER BY kind DESC, name_en COLLATE NOCASE")],
            "items": items, "suggest": legscrap.suggest_from_inventory(c), "scopes": rolls.SCOPES}


@router.post("/api/protected")
def api_protected_add(data: dict = Body(...)):
    c = con()
    try:
        if data.get("kind") == "unique":
            name = (data.get("name") or "").strip()
            if not name:
                raise ValueError("Нужно название")
            c.execute("INSERT INTO protected_items(kind, name_en, source) VALUES ('unique', ?, 'manual')", (name,))
            c.commit()
            return {"ok": True}
        return {"id": legscrap.add_godroll(c, data.get("name") or "", data.get("scope") or "any",
                                           [data.get(f"s{i}") for i in range(1, 4)])}
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.delete("/api/protected/{pid}")
def api_protected_delete(pid: int):
    c = con()
    c.execute("DELETE FROM protected_items WHERE id = ?", (pid,))
    c.commit()
    return {"ok": True}


@router.post("/api/protected/fill")
def api_protected_fill(what: str = Body(..., embed=True)):
    """Наполнение: unique — с вики fandom, godroll — стартовые «хорошие» эффекты, inventory — эффекты из избранного."""
    c = con()
    if what == "unique":
        try:
            return legscrap.import_unique(c)
        except Exception as e:  # сеть, вики недоступна
            raise HTTPException(502, f"Вики недоступна: {e}")
    if what == "godroll":
        return {"added": legscrap.seed_godrolls(c)}
    if what == "inventory":
        n = 0
        for g in legscrap.suggest_from_inventory(c):
            legscrap.add_good(c, g["scope"], g["star"], g["effect"])
            n += 1
        return {"added": n}
    raise HTTPException(400, "unique | godroll | inventory")


def _no_fork() -> None:
    """С форком мода правила разбора ведёт таблица «Действия» (chain-scrap); старый LegeScrap дублировал бы их."""
    if chainplan.fork_on(con()):
        raise HTTPException(409, "Включён форк мода: правила разбора и передачи ведутся на странице «Действия» (chain-scrap, chain-give, chain-take)")


@router.get("/api/legscrap/preview")
def api_legscrap_preview(keep_manual: bool = False):
    _no_fork()
    """Правила LegeScrap по персонажам: что будет записано в конфиг игры (без записи)."""
    try:
        cur = iomconfig.load()
    except iomconfig.IomError as e:
        raise HTTPException(400, str(e))
    plan = legscrap.plan_config(con(), cur["data"], keep_manual)
    if plan.get("error"):
        raise HTTPException(400, plan["error"])
    return {"characters": plan["characters"], "replaced": plan["replaced"], "protect_names": plan["protect_names"],
            "collisions": plan["collisions"], "sha1": cur["sha1"], "path": cur["path"]}


@router.post("/api/legscrap/apply")
def api_legscrap_apply(sha1: str = Body(..., embed=True), keep_manual: bool = Body(False)):
    """Записать правила в конфиг IOM (бэкап и сохранение inode — в iomconfig.save). Только по явной кнопке."""
    _no_fork()
    try:
        cur = iomconfig.load()
        plan = legscrap.plan_config(con(), cur["data"], keep_manual)
        if plan.get("error"):
            raise HTTPException(400, plan["error"])
        r = iomconfig.save(plan["data"], sha1)
        c = con()
        set_meta(c, "legscrap_names", json.dumps(plan["protect_names"], ensure_ascii=False))
        c.commit()
        return r
    except iomconfig.IomError as e:
        raise HTTPException(400, str(e))
