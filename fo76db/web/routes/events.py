"""События, Минерва, ежедневные задачи, коды ракет."""
from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request

from fastapi import APIRouter, Body, HTTPException, Request
from fastapi.responses import HTMLResponse

from ... import events, features, gamepaths, steam
from ...db import get_meta
from ..common import EVENT_KINDS, con, page

router = APIRouter()


@router.get("/events", response_class=HTMLResponse, include_in_schema=False)
def events_page(request: Request):
    return page(request, "events.html")


@router.get("/api/events")
def api_events():
    return [events._event(r) for r in con().execute("SELECT * FROM events ORDER BY start DESC")]


@router.post("/api/events")
def api_event_add(kind: str = Body(...), title: str = Body(...), start: str = Body(...), end: str | None = Body(None),
                  source_url: str | None = Body(None), note: str | None = Body(None)):
    if kind not in EVENT_KINDS:
        raise HTTPException(400, "Неизвестный тип события")
    c = con()
    c.execute("INSERT INTO events(kind, title, start, end, source_url, note) VALUES (?, ?, ?, ?, ?, ?)",
              (kind, title, start, end or None, source_url or None, note or None))
    c.commit()
    return {"ok": True}


@router.delete("/api/events/{event_id}")
def api_event_delete(event_id: int):
    c = con()
    # автособытия при следующем обновлении вернутся — удалять можно только внесённые вручную и Daily Ops
    if not c.execute("DELETE FROM events WHERE id = ? AND (source IS NULL OR source = 'dailyops')", (event_id,)).rowcount:
        raise HTTPException(400, "Событие из внешнего источника не удаляется: оно вернётся при обновлении")
    c.commit()
    return {"ok": True}


@router.post("/api/events/refresh")
def api_events_refresh():
    return events.refresh(con())


@router.get("/api/steam/news")
def api_steam_news(limit: int = 10, all: bool = False):
    return steam.news(con(), max(1, min(limit, 100)), patches_only=not all)


@router.get("/api/steam/online")
def api_steam_online(days: int = 7):
    return steam.online(con(), days)


@router.get("/achievements", response_class=HTMLResponse, include_in_schema=False)
def achievements_page(request: Request):
    return page(request, "achievements.html", rows=steam.achievements(con()), fetched=get_meta(con(), "steam_ach_fetched"))


@router.get("/api/steam/achievements")
def api_steam_achievements():
    return steam.achievements(con())


@router.get("/api/steam/heatmap")
def api_steam_heatmap():
    return steam.heatmap(con())


@router.get("/api/steam/build")
def api_steam_build():
    return gamepaths.steam_build()


@router.post("/api/steam/refresh")
def api_steam_refresh():
    return steam.refresh(con())


@router.get("/api/today")
def api_today(character_id: int | None = None):
    return events.today(con(), character_id)


@router.get("/api/minerva")
def api_minerva(sale: int, character_id: int | None = None):
    return events.minerva_plans(con(), sale, character_id)


@router.post("/api/dailyops")
def api_dailyops(mode: str = Body(""), location: str = Body(""), faction: str = Body(""), mutations: list[str] = Body([]),
                 note: str | None = Body(None)):
    if not (mode or location or faction):
        raise HTTPException(400, "Укажите хотя бы режим, место или врагов")
    events.save_dailyops(con(), mode.strip(), location.strip(), faction.strip(), [m.strip() for m in mutations], note)
    return {"ok": True}


@router.get("/api/daily")
def api_daily():
    return events.checklist(con())


@router.post("/api/daily/toggle")
def api_daily_toggle(task_id: int = Body(...), character_id: int = Body(0), done: bool = Body(...)):
    try:
        events.toggle(con(), task_id, character_id, done)
    except KeyError:
        raise HTTPException(404, "Нет такого пункта")
    return {"ok": True}


@router.post("/api/daily/tasks")
def api_daily_task_add(title: str = Body(...), reset: str = Body("daily"), per_char: bool = Body(True)):
    if reset not in ("daily", "weekly") or not title.strip():
        raise HTTPException(400, "Нужно название и сброс daily или weekly")
    c = con()
    c.execute("INSERT INTO daily_tasks(title, reset, per_char, sort) VALUES (?, ?, ?, (SELECT coalesce(max(sort), 0) + 10 FROM daily_tasks))",
              (title.strip(), reset, int(per_char)))
    c.commit()
    return {"ok": True}


@router.delete("/api/daily/tasks/{task_id}")
def api_daily_task_delete(task_id: int):
    c = con()
    c.execute("DELETE FROM daily_tasks WHERE id = ?", (task_id,))
    c.commit()
    return {"ok": True}


_nukes: dict = {}


@router.get("/api/nukes")
def api_nukes():
    """Коды ракет с NukaCrypt, кэш 10 минут."""
    if not features.service_on("nukacrypt"):
        return {"disabled": True}
    if time.time() - _nukes.get("t", 0) > 600:
        try:
            req = urllib.request.Request("https://api.nukacrypt.com/api/codes", headers={"User-Agent": "fo76db"})
            with urllib.request.urlopen(req, timeout=10) as r:
                _nukes.update(t=time.time(), data=json.loads(r.read()))
        except Exception as e:  # сеть недоступна — вернуть последнее известное
            return {"error": str(e), **_nukes.get("data", {})}
    return _nukes["data"]
