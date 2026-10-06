"""Steam: Update Notes игры, замеры онлайна, сборка (BuildID) из локального appmanifest.

Данные берутся из публичных API (`sources/steam.py`), историю онлайна API не отдаёт — замеры копятся с первого запуска `watch`.
"""
from __future__ import annotations

import datetime as dt
import sqlite3

from . import gamepaths
from .db import get_meta, set_meta
from .sources import steam

NEWS_EVERY = 3600          # секунд между обновлениями новостей
RETRY_AFTER_ERROR = 900
SAMPLE_EVERY = 900         # секунд между замерами онлайна в `watch`
ACH_EVERY = 86400         # достижения меняются редко
KEEP_DAYS = 400           # замеры старше удаляются


def _now() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def refresh_news(con: sqlite3.Connection) -> dict:
    """Скачать новости; {total, new_patches}. Ошибка сети — исключение (мета `steam_error` пишет вызывающий)."""
    news = steam.fetch_news()
    known = {r[0] for r in con.execute("SELECT gid FROM steam_news")}
    with con:
        con.executemany(
            "INSERT INTO steam_news(gid, title, date, url, feedlabel, patch) VALUES (:gid, :title, :date, :url, :feedlabel, :patch)"
            " ON CONFLICT(gid) DO UPDATE SET title = excluded.title, url = excluded.url, patch = excluded.patch", news)
    return {"total": len(news), "new_patches": sum(1 for n in news if n["patch"] and n["gid"] not in known)}


def refresh_achievements(con: sqlite3.Connection) -> int:
    rows = steam.fetch_achievements()
    with con:
        con.execute("DELETE FROM steam_achievements")
        con.executemany("INSERT INTO steam_achievements(sort, api_name, title, descr, percent)"
                        " VALUES (:sort, :api_name, :title, :descr, :percent)", rows)
        set_meta(con, "steam_ach_fetched", _now())
    return len(rows)


def sample_online(con: sqlite3.Connection) -> int:
    n = steam.fetch_players()
    with con:
        con.execute("INSERT OR REPLACE INTO online_samples(ts, players) VALUES (?, ?)", (_now(), n))
        cutoff = (dt.datetime.now() - dt.timedelta(days=KEEP_DAYS)).isoformat(timespec="seconds")
        con.execute("DELETE FROM online_samples WHERE ts < ?", (cutoff,))
    return n


def refresh(con: sqlite3.Connection) -> dict:
    """Новости + замер онлайна + проверка сборки. Ошибка одного источника не мешает остальным."""
    result: dict = {"errors": []}
    try:
        result |= refresh_news(con)
    except Exception as e:  # noqa: BLE001
        result["errors"].append(f"новости Steam: {e}")
    try:
        result["online"] = sample_online(con)
    except Exception as e:  # noqa: BLE001
        result["errors"].append(f"онлайн Steam: {e}")
    try:
        last = get_meta(con, "steam_ach_fetched")
        if not last or (dt.datetime.now() - dt.datetime.fromisoformat(last)).total_seconds() > ACH_EVERY:
            result["achievements"] = refresh_achievements(con)
    except Exception as e:  # noqa: BLE001
        result["errors"].append(f"достижения Steam: {e}")
    result["build"] = (b := gamepaths.steam_build()) and b["buildid"]
    set_meta(con, "steam_fetched", _now())
    set_meta(con, "steam_error", "; ".join(result["errors"]))
    con.commit()
    return result


def refresh_if_stale(con: sqlite3.Connection) -> dict | None:
    """Новости раз в час (после ошибки — через 15 мин); None — рано."""
    last = get_meta(con, "steam_fetched")
    limit = RETRY_AFTER_ERROR if get_meta(con, "steam_error") else NEWS_EVERY
    if last and (dt.datetime.now() - dt.datetime.fromisoformat(last)).total_seconds() < limit:
        return None
    return refresh(con)


def check_build(con: sqlite3.Connection) -> dict | None:
    """Сменился BuildID в appmanifest → событие «патч» в `events`; возвращает {old, new}. Первый запуск только запоминает."""
    b = gamepaths.steam_build()
    if not b:
        return None
    have = get_meta(con, "steam_buildid")
    if have == b["buildid"]:
        return None
    set_meta(con, "steam_buildid", b["buildid"])
    if not have:
        con.commit()
        return None
    when = (b["updated"] or dt.datetime.now().strftime("%Y-%m-%dT%H:%M"))
    with con:
        con.execute("DELETE FROM events WHERE ext_key = ?", (f"steambuild:{b['buildid']}",))
        con.execute("INSERT INTO events(kind, title, start, end, source, ext_key, note) VALUES ('other', ?, ?, ?, 'steam', ?, ?)",
                    (f"Игра обновилась (сборка {b['buildid']})", when, when, f"steambuild:{b['buildid']}",
                     f"Было: {have}"))
    return {"old": have, "new": b["buildid"]}


# ---------- для веб-интерфейса ----------

def achievements(con: sqlite3.Connection) -> list[dict]:
    return [dict(r) for r in con.execute("SELECT * FROM steam_achievements ORDER BY sort")]


MIN_HEATMAP_DAYS = 7


def heatmap(con: sqlite3.Connection) -> dict:
    """Средний онлайн по дням недели (0 — понедельник) и часам местного времени из собственных замеров.
    {days, ready, need, cells: [[средний онлайн или None] × 24] × 7, best: [{weekday, hour, players}] — три лучших слота}."""
    rows = con.execute(
        "SELECT CAST(strftime('%w', ts) AS INTEGER), CAST(strftime('%H', ts) AS INTEGER), avg(players)"
        " FROM online_samples GROUP BY 1, 2").fetchall()
    cells: list[list[int | None]] = [[None] * 24 for _ in range(7)]
    for w, h, avg in rows:
        cells[(w - 1) % 7][h] = round(avg)  # strftime %w: 0 — воскресенье
    span = con.execute("SELECT count(DISTINCT date(ts)) FROM online_samples").fetchone()[0]
    top = sorted(((v, w, h) for w, r in enumerate(cells) for h, v in enumerate(r) if v is not None), reverse=True)[:3]
    return {"days": span, "ready": span >= MIN_HEATMAP_DAYS, "need": MIN_HEATMAP_DAYS, "cells": cells,
            "best": [{"weekday": w, "hour": h, "players": v} for v, w, h in top]}

def news(con: sqlite3.Connection, limit: int = 10, patches_only: bool = True) -> list[dict]:
    where = "WHERE patch = 1" if patches_only else ""
    return [dict(r) for r in con.execute(f"SELECT * FROM steam_news {where} ORDER BY date DESC LIMIT ?", (limit,))]


def online(con: sqlite3.Connection, days: int = 7) -> dict:
    """{now, peak24h, since, points: [[ts, players]]} — точки из собственных замеров."""
    since = (dt.datetime.now() - dt.timedelta(days=max(1, min(days, KEEP_DAYS)))).isoformat(timespec="seconds")
    points = [[r[0], r[1]] for r in con.execute("SELECT ts, players FROM online_samples WHERE ts >= ? ORDER BY ts", (since,))]
    day = (dt.datetime.now() - dt.timedelta(days=1)).isoformat(timespec="seconds")
    last = points[-1] if points else None
    first = con.execute("SELECT min(ts) FROM online_samples").fetchone()[0]
    return {"now": last[1] if last else None, "now_ts": last[0] if last else None,
            "peak24h": max((p[1] for p in points if p[0] >= day), default=None), "collected_since": first, "points": points}
