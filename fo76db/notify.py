"""Уведомления на рабочий стол (notify-send): новый патч, скорые события, Минерва, вишлист в событиях, нужные роллы."""
from __future__ import annotations

import logging
import datetime as dt
import json
import shutil
import sqlite3
import subprocess

from . import rolls
from .db import get_meta, set_meta
from .events import title_ru
from .sources import dumps

log = logging.getLogger(__name__)


def send(title: str, body: str) -> None:
    log.info("🔔 %s: %s", title, body)
    if shutil.which("notify-send"):
        subprocess.run(["notify-send", "-a", "FO76 DB", title, body], check=False)
    elif shutil.which("gdbus"):  # Flatpak: notify-send в среде нет, gdbus есть (из GLib)
        # аргументы gdbus разбираются как текст GVariant: строки — в кавычках JSON (экранирование совместимо)
        subprocess.run(["gdbus", "call", "--session", "--dest", "org.freedesktop.Notifications",
                        "--object-path", "/org/freedesktop/Notifications",
                        "--method", "org.freedesktop.Notifications.Notify",
                        '"FO76 DB"', "0", '""', json.dumps(title, ensure_ascii=False),
                        json.dumps(body, ensure_ascii=False), "[]", "{}", "5000"],
                       check=False, stdout=subprocess.DEVNULL)


def _sent(con: sqlite3.Connection) -> set[str]:
    return set(json.loads(get_meta(con, "notified") or "[]"))


def _mark(con: sqlite3.Connection, keys: set[str]) -> None:
    set_meta(con, "notified", json.dumps(sorted(keys)[-500:]))
    con.commit()


def check(con: sqlite3.Connection) -> None:
    sent = _sent(con)
    new = set()

    # 1. Новый релиз fo76-dumps = вышел патч игры
    try:
        stable = [r for r in dumps.list_releases() if not dumps.is_pts(r["version"])]
        latest = max(stable, key=lambda r: dumps.version_key(r["version"]))
        have = get_meta(con, "catalog_release")
        key = f"release:{latest['tag']}"
        if have and latest["tag"] != have and key not in sent:
            send("Новый патч Fallout 76", f"Вышли данные версии {latest['version']}. Обновите базу: fo76db catalog && fo76db history")
            new.add(key)
    except Exception as e:
        log.warning("проверка релизов: %s", e)

    # 2. События, которые начинаются в ближайшие сутки или уже идут
    now = dt.datetime.now()
    soon = (now + dt.timedelta(days=1)).isoformat(timespec="minutes")
    now_s = now.isoformat(timespec="minutes")
    events = con.execute(
        "SELECT * FROM events WHERE start <= ? AND (end IS NULL OR end >= ?)", (soon, now_s)).fetchall()
    wish = con.execute(
        "SELECT i.name_en, i.name_ru FROM wishlist w JOIN items i ON i.formid = w.formid").fetchall()
    for e in events:
        if e["kind"] == "season":
            continue
        # у автособытий id меняется при каждом обновлении, ключ берём стабильный
        key = f"event:{e['ext_key'] or e['id']}"
        if key not in sent:
            when = "идёт сейчас" if e["start"] <= now_s else f"начнётся {e['start'].replace('T', ' ')}"
            send(title_ru(e["title"]) or e["title"], when + (f"\n{e['note']}" if e["note"] else "") + _minerva_text(con, e))
            new.add(key)
        # 3. Вишлист: название предмета упомянуто в событии (например, в списке товаров Минервы)
        text = f"{e['title']} {e['note'] or ''}".lower()
        for w in wish:
            for name in filter(None, (w["name_en"], w["name_ru"])):
                wkey = f"wish:{e['id']}:{name}"
                if name.lower() in text and wkey not in sent:
                    send("Предмет из вишлиста", f"{name} — {e['title']}")
                    new.add(wkey)
        # 4. Вишлист: схема продаётся у Минервы
        if e["kind"] == "minerva" and e["data"]:
            sale = json.loads(e["data"])["sale"]
            for (name,) in con.execute(
                    "SELECT coalesce(i.name_ru, m.name_en) FROM minerva_plans m JOIN wishlist w ON w.formid = m.formid"
                    " LEFT JOIN items i ON i.formid = m.formid WHERE m.sale = ?", (sale,)):
                wkey = f"wish:{e['ext_key']}:{name}"
                if wkey not in sent:
                    send("Предмет из вишлиста у Минервы", f"{name} — {e['note'] or ''}")
                    new.add(wkey)

    if new:
        _mark(con, sent | new)
    check_rolls(con)


def check_rolls(con: sqlite3.Connection) -> int:
    """Новые предметы, подошедшие под хотелку целиком (после импорта инвентаря и в общей проверке)."""
    found = rolls.new_matches(con)
    names = {r[0]: r[1] for r in con.execute("SELECT c.id, coalesce(p.label, c.name) FROM characters c"
                                             " LEFT JOIN profiles p ON p.character_id = c.id")}
    for w, m in found:
        effects = " / ".join(s["en"] or s["text"] for s in m["slots"])
        where = "тайник" if m["container"] == "stash" else "инвентарь"
        send(f"Нужный ролл: {w['name']}", f"{m['name']} — {names.get(m['character_id'], '?')}, {where}\n{effects}")
    return len(found)


def _minerva_text(con: sqlite3.Connection, e: sqlite3.Row) -> str:
    """Сколько схем распродажи Минервы не изучено у каждого персонажа, о котором есть данные."""
    if e["kind"] != "minerva" or not e["data"]:
        return ""
    sale = json.loads(e["data"])["sale"]
    rows = con.execute(
        "SELECT coalesce(p.label, c.name), (SELECT count(*) FROM minerva_plans m WHERE m.sale = ? AND m.formid IS NOT NULL"
        " AND m.formid NOT IN (SELECT formid FROM known_recipes k WHERE k.character_id = c.id))"
        " FROM characters c LEFT JOIN profiles p ON p.character_id = c.id"
        " WHERE c.id IN (SELECT character_id FROM inv_snapshots UNION SELECT character_id FROM known_recipes)", (sale,)).fetchall()
    parts = [f"{name} — {n}" for name, n in rows if n]
    return ("\nНе изучено: " + ", ".join(parts)) if parts else ""
