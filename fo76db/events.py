"""События на сегодня: автообновление календаря, Минерва, сезоны, Daily Ops, чек-лист ежедневок.

Время в таблице `events` — местное, без пояса (`ГГГГ-ММ-ДДTЧЧ:ММ`), как у событий, внесённых вручную.
У внешних источников есть только даты: событие начинается и заканчивается в момент дневного сброса.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import sqlite3
from zoneinfo import ZoneInfo

from .db import get_meta, set_meta
from .sources import falloutbuilds, fo76wiki

# Сброс дня и недели в игре: 12:00 по Нью-Йорку, неделя — со вторника. Допущение по данным сообщества.
RESET_TZ = ZoneInfo("America/New_York")
RESET_HOUR = 12
WEEKLY_RESET_WEEKDAY = 1  # вторник
REFRESH_EVERY = 6 * 3600   # секунд между автообновлениями в `watch`
RETRY_AFTER_ERROR = 900  # секунд: после неудачного обновления (нет сети, правка страницы) повтор раньше, чем через REFRESH_EVERY

EVENT_TITLE_RU = {
    "Double XP": "Двойной опыт", "Double Score": "Двойные очки сезона", "Double Mutations": "Двойные мутации",
    "Legendary Sale": "Легендарная распродажа", "Caps-A-Plenty": "Крышки в изобилии", "Mischief Night": "Ночь проказ",
    "Spooky Scorched": "Жуткие Выжженные", "Holiday Scorched": "Праздничные Выжженные", "Fasnacht Day": "Фаснахт",
    "Meat Week": "Мясная неделя", "The Big Bloom": "Большое цветение", "The Mothman Equinox": "Равноденствие Мотылька",
    "Mothman Equinox": "Равноденствие Мотылька", "Invaders from Beyond": "Пришельцы извне",
    "Mutated Public Events": "Мутировавшие публичные события", "Anniversary Events": "Годовщина игры",
    "Slasher C.A.M.P. Contest": "Конкурс лагерей «Слэшер»", "Treasure Hunter": "Охотник за сокровищами",
    "Gold Rush": "Золотая лихорадка", "Purveyor Sale": "Распродажа у Мурмрга",
}
BONUS = ("double", "legendary sale", "caps-a-plenty", "gold rush", "purveyor", "sale")
SEASONAL = ("scorched", "fasnacht", "meat week", "bloom", "mothman", "invaders", "treasure", "mischief", "mutated",
            "anniversary", "contest")


def kind_of(title: str) -> str:
    t = title.lower()
    if t.startswith("minerva"):
        return "minerva"
    if any(k in t for k in SEASONAL):
        return "seasonal_event"
    if any(k in t for k in BONUS):
        return "doublexp"
    return "other"


def title_ru(title: str) -> str | None:
    if title in EVENT_TITLE_RU:
        return EVENT_TITLE_RU[title]
    if m := re.match(r"Minerva (Super )?Sale #(\d+)", title):
        return f"Минерва — {'супер-распродажа' if m[1] else 'распродажа'} #{m[2]}"
    if m := re.match(r"Season (\d+): (.*)", title):
        return f"Сезон {m[1]}: {m[2]}"
    return None


# ---------- время ----------

def _now(now: dt.datetime | None) -> dt.datetime:
    return (now or dt.datetime.now().astimezone()).astimezone(RESET_TZ)


def day_bounds(now: dt.datetime | None = None) -> tuple[dt.datetime, dt.datetime]:
    """Начало и конец текущего игрового дня (с поясом)."""
    n = _now(now)
    start = n.replace(hour=RESET_HOUR, minute=0, second=0, microsecond=0)
    if n < start:
        start -= dt.timedelta(days=1)
    return start, start + dt.timedelta(days=1)


def week_bounds(now: dt.datetime | None = None) -> tuple[dt.datetime, dt.datetime]:
    start, _ = day_bounds(now)
    start -= dt.timedelta(days=(start.weekday() - WEEKLY_RESET_WEEKDAY) % 7)
    return start, start + dt.timedelta(days=7)


def period(reset: str, now: dt.datetime | None = None) -> str:
    """Ключ периода для отметок чек-листа: дата начала игрового дня или недели."""
    return (week_bounds(now) if reset == "weekly" else day_bounds(now))[0].date().isoformat()


def local(t: dt.datetime) -> str:
    return t.astimezone().strftime("%Y-%m-%dT%H:%M")


def at_reset(d: dt.date) -> str:
    """Дата из внешнего источника → момент сброса в этот день, в местном времени."""
    return local(dt.datetime.combine(d, dt.time(RESET_HOUR), RESET_TZ))


# ---------- обновление из сети ----------

def _plan_index(con: sqlite3.Connection) -> dict[str, int]:
    idx: dict[str, int] = {}
    for fid, name in con.execute(
            "SELECT formid, name_en FROM items WHERE kind IN ('plan', 'recipe') AND name_en IS NOT NULL ORDER BY status, formid"):
        idx.setdefault(name.replace("’", "'").lower(), fid)
    return idx


def _replace(con: sqlite3.Connection, source: str, rows: list[dict], since: str | None) -> None:
    """Заменить автособытия источника, которые ещё не закончились к `since` (прошедшие остаются историей)."""
    if since is None:
        con.execute("DELETE FROM events WHERE source = ?", (source,))
    else:
        con.execute("DELETE FROM events WHERE source = ? AND (end IS NULL OR end >= ?)", (source, since))
    con.executemany(
        "INSERT INTO events(kind, title, start, end, source, ext_key, data, note, source_url)"
        " VALUES (:kind, :title, :start, :end, :source, :ext_key, :data, :note, :url)",
        [{"note": None, "data": None, "url": None, "source": source, **r} for r in rows])


def refresh(con: sqlite3.Connection) -> dict:
    """Скачать календарь, Минерву, сезоны и варианты Daily Ops. Ошибка одного источника не мешает остальным."""
    result: dict = {"errors": []}

    try:
        cal = falloutbuilds.fetch_calendar()
        minerva = falloutbuilds.fetch_minerva()
        rows = [{"kind": kind_of(e["title"]), "title": e["title"], "start": at_reset(e["start"]), "end": at_reset(e["end"]),
                 "ext_key": f"falloutbuilds:{e['title']}:{e['start']}", "url": f"{falloutbuilds.BASE}/events/"}
                for e in cal if not e["title"].startswith("Minerva")]  # Минерва — из её таблицы, там точные даты
        for s in minerva["sales"]:
            rows.append({"kind": "minerva", "title": f"Minerva Sale #{s['sale']}", "start": at_reset(s["start"]),
                         "end": at_reset(s["end"]), "ext_key": f"minerva:{s['sale']}:{s['start']}",
                         "data": json.dumps({"sale": s["sale"], "location": s["location"]}),
                         "note": s["location"], "url": f"{falloutbuilds.BASE}/minerva/#sale-{s['sale']}"})
        idx = _plan_index(con)
        with con:
            _replace(con, "falloutbuilds", rows, min((r["start"] for r in rows), default=None))
            con.execute("DELETE FROM minerva_plans")
            con.executemany("INSERT OR IGNORE INTO minerva_plans(sale, name_en, formid) VALUES (?, ?, ?)",
                            [(sale, n, idx.get(n.lower())) for sale, names in minerva["plans"].items() for n in names])
        result["calendar"] = len(rows)
        result["minerva_plans"] = sum(len(v) for v in minerva["plans"].values())
    except Exception as e:
        result["errors"].append(f"falloutbuilds.com: {e}")

    try:
        seasons = fo76wiki.fetch_seasons()
        rows = [{"kind": "season", "title": f"Season {s['number']}: {s['name']}", "start": at_reset(s["start"]),
                 "end": at_reset(seasons[i + 1]["start"]) if i + 1 < len(seasons) else None,
                 "ext_key": f"season:{s['number']}", "note": f"Обновление «{s['update']}»",
                 "data": json.dumps({"number": s["number"], "name": s["name"], "update": s["update"]}),
                 "url": "https://fallout.wiki/wiki/Fallout_76_Seasons"} for i, s in enumerate(seasons)]
        with con:
            _replace(con, "wiki", rows, None)
        result["seasons"] = len(rows)
    except Exception as e:
        result["errors"].append(f"fallout.wiki (сезоны): {e}")

    try:
        set_meta(con, "dailyops_vars", json.dumps(fo76wiki.fetch_dailyops()))
    except Exception as e:
        result["errors"].append(f"fallout.wiki (Daily Ops): {e}")

    set_meta(con, "events_fetched", dt.datetime.now().isoformat(timespec="seconds"))
    set_meta(con, "events_error", "; ".join(result["errors"]))
    con.commit()
    return result


def refresh_if_stale(con: sqlite3.Connection) -> dict | None:
    last = get_meta(con, "events_fetched")
    limit = RETRY_AFTER_ERROR if get_meta(con, "events_error") else REFRESH_EVERY
    if last and (dt.datetime.now() - dt.datetime.fromisoformat(last)).total_seconds() < limit:
        return None
    return refresh(con)


# ---------- Daily Ops и чек-лист ----------

def dailyops_vars(con: sqlite3.Connection) -> dict:
    v = get_meta(con, "dailyops_vars")
    return json.loads(v) if v else fo76wiki.DAILYOPS_FALLBACK


def save_dailyops(con: sqlite3.Connection, mode: str, location: str, faction: str, mutations: list[str],
                  note: str | None = None, now: dt.datetime | None = None) -> None:
    """Daily Ops текущего игрового дня (вносится вручную: открытого источника ротации нет)."""
    start, end = day_bounds(now)
    key = f"dailyops:{start.date()}"
    data = {"mode": mode, "location": location, "faction": faction, "mutations": [m for m in mutations if m]}
    title = " · ".join(filter(None, [mode, location, faction]))
    with con:
        con.execute("DELETE FROM events WHERE ext_key = ?", (key,))
        con.execute("INSERT INTO events(kind, title, start, end, source, ext_key, data, note) VALUES ('dailyops', ?, ?, ?, 'dailyops', ?, ?, ?)",
                    (title, local(start), local(end), key, json.dumps(data, ensure_ascii=False), note or None))


def checklist(con: sqlite3.Connection, now: dt.datetime | None = None) -> list[dict]:
    tasks = [dict(r) for r in con.execute("SELECT * FROM daily_tasks ORDER BY reset = 'weekly', sort, id")]
    for t in tasks:
        t["period"] = period(t["reset"], now)
        t["done"] = [r[0] for r in con.execute(
            "SELECT character_id FROM daily_done WHERE task_id = ? AND period = ?", (t["id"], t["period"]))]
    return tasks


def toggle(con: sqlite3.Connection, task_id: int, character_id: int, done: bool, now: dt.datetime | None = None) -> None:
    row = con.execute("SELECT reset FROM daily_tasks WHERE id = ?", (task_id,)).fetchone()
    if not row:
        raise KeyError(task_id)
    p = period(row["reset"], now)
    with con:
        if done:
            con.execute("INSERT OR IGNORE INTO daily_done(task_id, character_id, period) VALUES (?, ?, ?)", (task_id, character_id, p))
        else:
            con.execute("DELETE FROM daily_done WHERE task_id = ? AND character_id = ? AND period = ?", (task_id, character_id, p))
        # старые отметки больше не нужны
        con.execute("DELETE FROM daily_done WHERE period < ?", ((dt.date.fromisoformat(p) - dt.timedelta(days=30)).isoformat(),))


# ---------- сводка «Сегодня» ----------

def _event(r: sqlite3.Row) -> dict:
    d = dict(r)
    d["data"] = json.loads(d["data"]) if d.get("data") else None
    d["title_ru"] = title_ru(d["title"])
    return d


def minerva_plans(con: sqlite3.Connection, sale: int, character_id: int | None) -> list[dict]:
    return [dict(r) for r in con.execute(
        "SELECT m.name_en, CASE WHEN m.formid IS NOT NULL THEN printf('%08X', m.formid) END AS id, i.name_ru,"
        " (SELECT source FROM known_recipes k WHERE k.formid = m.formid AND k.character_id = ?) AS known,"
        " (SELECT 1 FROM wishlist w WHERE w.formid = m.formid) AS wish"
        " FROM minerva_plans m LEFT JOIN items i ON i.formid = m.formid WHERE m.sale = ? ORDER BY m.name_en",
        (character_id or 0, sale))]


def today(con: sqlite3.Connection, character_id: int | None = None, now: dt.datetime | None = None) -> dict:
    day_start, day_end = day_bounds(now)
    week_start, week_end = week_bounds(now)
    now_s = local(_now(now))
    soon_s = local(_now(now) + dt.timedelta(days=14))
    rows = [_event(r) for r in con.execute(
        "SELECT * FROM events WHERE start <= ? AND (end IS NULL OR end >= ?) ORDER BY start", (soon_s, now_s))]
    season = next((e for e in rows if e["kind"] == "season" and e["start"] <= now_s), None)
    dailyops = next((e for e in rows if e["kind"] == "dailyops" and e["start"] <= now_s), None)
    others = [e for e in rows if e["kind"] not in ("season", "dailyops")]

    minerva = None
    m = con.execute("SELECT * FROM events WHERE kind = 'minerva' AND source IS NOT NULL AND end >= ? ORDER BY start LIMIT 1",
                    (now_s,)).fetchone()
    if m:
        minerva = _event(m)
        minerva["active"] = minerva["start"] <= now_s
        plans = minerva_plans(con, minerva["data"]["sale"], character_id)
        minerva["total"] = len(plans)
        minerva["unknown"] = sum(1 for p in plans if p["id"] and not p["known"]) if character_id else None
        minerva["wish"] = [p["name_ru"] or p["name_en"] for p in plans if p["wish"]]

    return {
        "now": local(_now(now)),
        "day": {"start": day_start.isoformat(), "end": day_end.isoformat(), "period": day_start.date().isoformat()},
        "week": {"start": week_start.isoformat(), "end": week_end.isoformat()},
        "season": season,
        "dailyops": dailyops,
        "dailyops_vars": dailyops_vars(con),
        "active": [e for e in others if e["start"] <= now_s],
        "upcoming": [e for e in others if e["start"] > now_s],
        "minerva": minerva,
        "fetched": get_meta(con, "events_fetched"),
        "error": get_meta(con, "events_error") or None,
    }
