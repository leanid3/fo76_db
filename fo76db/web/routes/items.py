"""Каталог, карточка предмета, теги, вишлист, сохранённые поиски, вики-подсказки."""
from __future__ import annotations

import json
import re

from fastapi import APIRouter, Body, HTTPException, Request
from fastapi.responses import HTMLResponse, Response

from ... import autotags, obtain
from ...importers.inventory import current_items_sql
from ...sources import fo76wiki
from ..common import _color, con, page

router = APIRouter()


# ---------- страницы ----------

@router.get("/", response_class=HTMLResponse, include_in_schema=False)
def catalog_page(request: Request):
    updates = [r[0] for r in con().execute(
        "SELECT DISTINCT b.update_name FROM builds b WHERE b.update_name IS NOT NULL ORDER BY b.vkey DESC")]
    return page(request, "catalog.html", updates=updates)


@router.get("/glossary", response_class=HTMLResponse, include_in_schema=False)
def glossary_page(request: Request):
    return page(request, "glossary.html")


@router.get("/item/{formid}", response_class=HTMLResponse, include_in_schema=False)
def item_page(request: Request, formid: str):
    c = con()
    fid = int(formid, 16)
    item = c.execute(
        "SELECT i.*, ba.version AS added_version, ba.update_name AS added_update, ba.date AS added_date,"
        " ba.released AS added_released, br.version AS removed_version FROM items i LEFT JOIN builds ba ON ba.tag = i.added_build"
        " LEFT JOIN builds br ON br.tag = i.removed_build WHERE formid = ?", (fid,)).fetchone()
    if not item:
        raise HTTPException(404, "Предмет не найден")
    stats = json.loads(item["stats"] or "{}")

    def names(fids):
        if not fids:
            return {}
        q = ",".join("?" * len(fids))
        return {r["formid"]: r for r in c.execute(f"SELECT formid, name_en, name_ru, kind FROM items WHERE formid IN ({q})", list(fids))}

    recipes = [dict(r) for r in c.execute("SELECT * FROM recipes WHERE product = ?", (fid,))]
    teaches = [dict(r) for r in c.execute("SELECT * FROM recipes WHERE plan = ?", (fid,))]
    for r in recipes + teaches:
        r["components"] = json.loads(r["components"] or "[]")
    ref = names({r["plan"] for r in recipes if r["plan"]} | {r["product"] for r in teaches if r["product"]}
                | {x["formid"] for r in recipes + teaches for x in r["components"]} | {x["formid"] for x in stats.get("scrap", [])})
    owners = c.execute(
        f"SELECT character, account, container, sum(count) AS count FROM ({current_items_sql()}) WHERE formid = ?"
        " GROUP BY character_id, container ORDER BY character", (fid,)).fetchall()
    learned_by = c.execute(
        "SELECT c.id, c.name, k.source FROM known_recipes k JOIN characters c ON c.id = k.character_id WHERE k.formid = ?", (fid,)).fetchall()
    same_name = c.execute(
        "SELECT formid, kind, status, edid FROM items WHERE name_en = ? AND formid != ? ORDER BY status, formid",
        (item["name_en"], fid)).fetchall()
    wished = c.execute("SELECT 1 FROM wishlist WHERE formid = ?", (fid,)).fetchone() is not None
    autotags.ensure(c)
    atags = autotags.ordered(r[0] for r in c.execute("SELECT tag FROM item_auto_tags WHERE formid = ?", (fid,)))
    return page(request, "item.html", atags=atags, item=item, stats=stats, recipes=recipes, teaches=teaches, ref=ref,
                owners=owners, learned_by=learned_by, same_name=same_name, wished=wished, obtain=obtain.how_to_get(c, fid),
                CATEGORIES=obtain.CATEGORIES)


@router.get("/updates", response_class=HTMLResponse, include_in_schema=False)
def updates_page(request: Request):
    c = con()
    rows = c.execute(
        "SELECT b.update_name, min(coalesce(b.released, b.date)) AS date, min(b.version) AS version, i.kind, count(*) AS n"
        " FROM items i JOIN builds b ON b.tag = i.added_build WHERE i.status = 'ok'"
        " GROUP BY b.update_name, i.kind").fetchall()
    order = {r[0]: r[1] for r in c.execute("SELECT update_name, max(vkey) FROM builds GROUP BY update_name")}
    groups: dict[str, dict] = {}
    for r in rows:
        g = groups.setdefault(r["update_name"] or "—", {"name": r["update_name"], "date": r["date"], "kinds": {}, "total": 0,
                                                        "order": order.get(r["update_name"], "")})
        g["kinds"][r["kind"]] = r["n"]
        g["total"] += r["n"]
        g["date"] = min(g["date"], r["date"])
    first = c.execute("SELECT version, date FROM builds ORDER BY vkey LIMIT 1").fetchone()
    return page(request, "updates.html", groups=sorted(groups.values(), key=lambda g: g["order"], reverse=True), first=first)


# ---------- API ----------

_items_cache: dict = {}


@router.get("/api/items")
def api_items():
    c = con()
    key = (autotags.ensure(c),)
    if _items_cache.get("key") != key:
        atags = autotags.by_formid(c)
        rows = c.execute(
            "SELECT printf('%08X', i.formid) AS id, i.name_ru, i.name_en, i.kind, i.subkind, i.weight, i.value, i.status, i.edid,"
            " json_extract(i.stats, '$.craftable') AS craftable, json_extract(i.stats, '$.in_lvli') AS in_lvli,"
            " ba.version AS added, ba.update_name AS added_update, br.version AS removed,"
            " (SELECT 1 FROM wishlist w WHERE w.formid = i.formid) AS wish,"
            # схемы, которые учат этому предмету (у самой схемы — она сама): по ним фронт показывает «изучено»
            " CASE WHEN i.kind IN ('plan', 'recipe') AND json_extract(i.stats, '$.teaches') = 1 THEN printf('%08X', i.formid)"
            " ELSE (SELECT group_concat(DISTINCT printf('%08X', r.plan)) FROM recipes r JOIN items p ON p.formid = r.plan"
            " WHERE r.product = i.formid AND p.kind IN ('plan', 'recipe')) END AS plans"
            " , i.formid FROM items i LEFT JOIN builds ba ON ba.tag = i.added_build LEFT JOIN builds br ON br.tag = i.removed_build").fetchall()
        data = []
        for r in rows:
            d = dict(r)
            d["atags"] = atags.get(d.pop("formid"), [])
            data.append(d)
        _items_cache.update(key=key, data=json.dumps(data, ensure_ascii=False))
    return Response(_items_cache["data"], media_type="application/json")


@router.get("/api/autotags")
def api_autotags():
    """Все автотеги с подписями, цветами и числом предметов, по группам."""
    c = con()
    autotags.ensure(c)
    counts = dict(c.execute("SELECT tag, count(*) FROM item_auto_tags GROUP BY tag").fetchall())
    return [{**d, "used": counts[d["code"]]} for d in autotags.ordered(counts)]


@router.get("/api/tags")
def api_tags():
    return [dict(r) for r in con().execute(
        "SELECT t.*, (SELECT count(*) FROM item_tags it WHERE it.tag_id = t.id) AS used FROM tags t ORDER BY t.name")]


@router.post("/api/tags")
def api_tag_save(name: str = Body(...), color: str | None = Body(None), icon: str | None = Body(None), id: int | None = Body(None)):
    c = con()
    name = name.strip()
    if not name:
        raise HTTPException(400, "Пустое название тега")
    dup = c.execute("SELECT id FROM tags WHERE name = ? AND id IS NOT ?", (name, id)).fetchone()
    if dup:
        raise HTTPException(400, f"Тег «{name}» уже есть")
    if id:
        c.execute("UPDATE tags SET name = ?, color = ?, icon = ? WHERE id = ?", (name, _color(color), icon or None, id))
    else:
        id = c.execute("INSERT INTO tags(name, color, icon) VALUES (?, ?, ?)", (name, _color(color), icon or None)).lastrowid
    c.commit()
    return {"ok": True, "id": id}


@router.delete("/api/tags/{tag_id}")
def api_tag_delete(tag_id: int):
    c = con()
    c.execute("DELETE FROM tags WHERE id = ?", (tag_id,))
    c.commit()
    return {"ok": True}


@router.post("/api/tags/apply")
def api_tag_apply(tag_id: int = Body(...), keys: list[str] = Body(...), on: bool = Body(...)):
    c = con()
    sql = ("INSERT INTO item_tags(tag_id, key) VALUES (?, ?) ON CONFLICT DO NOTHING" if on
           else "DELETE FROM item_tags WHERE tag_id = ? AND key = ?")
    c.executemany(sql, [(tag_id, k) for k in keys])
    c.commit()
    return {"ok": True}


@router.post("/api/display_name")
def api_display_name(key: str = Body(...), name: str | None = Body(None)):
    c = con()
    if (name or "").strip():
        c.execute("INSERT INTO display_names(key, name) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET name = excluded.name", (key, name.strip()))
    else:
        c.execute("DELETE FROM display_names WHERE key = ?", (key,))
    c.commit()
    return {"ok": True}


@router.post("/api/wishlist")
def api_wishlist(formid: str = Body(...), wish: bool = Body(...), note: str | None = Body(None)):
    c = con()
    fid = int(formid, 16)
    if wish:
        c.execute("INSERT INTO wishlist(formid, note) VALUES (?, ?) ON CONFLICT(formid) DO UPDATE SET note = excluded.note", (fid, note))
    else:
        c.execute("DELETE FROM wishlist WHERE formid = ?", (fid,))
    c.commit()
    _items_cache.clear()
    return {"ok": True}


@router.get("/api/saved")
def api_saved(page: str):
    return [dict(r) for r in con().execute("SELECT id, name, params FROM saved_searches WHERE page = ? ORDER BY name", (page,))]


@router.post("/api/saved")
def api_saved_add(page: str = Body(...), name: str = Body(...), params: str = Body(...)):
    c = con()
    c.execute("INSERT INTO saved_searches(page, name, params) VALUES (?, ?, ?)"
              " ON CONFLICT(page, name) DO UPDATE SET params = excluded.params", (page, name.strip(), params))
    c.commit()
    return {"ok": True}


@router.delete("/api/saved/{sid}")
def api_saved_delete(sid: int):
    c = con()
    c.execute("DELETE FROM saved_searches WHERE id = ?", (sid,))
    c.commit()
    return {"ok": True}


WIKI_TTL_DAYS = 14       # найденная страница


WIKI_MISS_TTL_DAYS = 1   # «не нашлась»: новые предметы появляются на вики не сразу


def _wiki_row(r) -> dict:
    ru = {"title": r["ru_title"], "url": r["ru_url"], "html": r["ru_html"]} if r["ru_title"] else None
    return {"wiki": r["wiki"], "title": r["title"], "url": r["url"], "html": r["html"], "ru": ru}


@router.get("/api/item/{formid}/wiki")
def api_item_wiki(formid: str, refresh: bool = False):
    """Описание и «где взять» со страниц предмета: русская fandom, английская fandom или fallout.wiki. Кэш в `wiki_obtain`."""
    fid = int(formid, 16)
    key = f"{fid:08X}"
    c = con()
    # найденное живёт WIKI_TTL_DAYS, «не нашлось» — WIKI_MISS_TTL_DAYS; записи без поиска русской страницы перечитываются
    row = c.execute(
        "SELECT * FROM wiki_obtain WHERE key = ? AND ru_checked = 1 AND fetched >= datetime('now', '-' ||"
        " CASE WHEN title IS NULL AND ru_title IS NULL THEN ? ELSE ? END || ' days')",
        (key, WIKI_MISS_TTL_DAYS, WIKI_TTL_DAYS)).fetchone()
    if row and not refresh:
        return {**_wiki_row(row), "cached": True}
    item = c.execute("SELECT name_en, name_ru, kind FROM items WHERE formid = ?", (fid,)).fetchone()
    if not item:
        raise HTTPException(404, "Нет такого предмета")
    names = [item["name_en"]]
    if item["kind"] in ("plan", "recipe"):
        names.append(re.sub(r"^(Plans?|Recipe): ", "", item["name_en"]))
    try:
        r = fo76wiki.obtain(names, fid, item["name_ru"]) or {}
    except Exception as e:
        raise HTTPException(502, f"Вики не ответили: {e}")
    ru = r.get("ru") or {}
    c.execute("INSERT OR REPLACE INTO wiki_obtain(key, wiki, title, url, html, ru_title, ru_url, ru_html, ru_checked, fetched)"
              " VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, datetime('now'))",
              (key, r.get("wiki"), r.get("title"), r.get("url"), r.get("html"), ru.get("title"), ru.get("url"), ru.get("html")))
    c.commit()
    return {**_wiki_row(c.execute("SELECT * FROM wiki_obtain WHERE key = ?", (key,)).fetchone()), "cached": False}
