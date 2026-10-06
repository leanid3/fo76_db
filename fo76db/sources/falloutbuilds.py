"""Календарь событий и расписание Минервы с falloutbuilds.com (страницы HTML, своего API у сайта нет).

Календарь (`/fo76/events/`) — сетка дней на ~8 недель: у каждой ячейки `data-day="ГГГГ-ММ-ДД"`, внутри по `div[title]`
на каждое событие, которое идёт в этот день. Начало и конец события — первый и последний день подряд с этим названием.
Минерва (`/fo76/minerva/`) — таблица распродаж (номер, место, даты без года) и списки схем по номерам распродаж.
"""
from __future__ import annotations

import datetime as dt
import html
import re
import urllib.request

from .. import features
from .dates import nearest_year

BASE = "https://www.falloutbuilds.com/fo76"
UA = {"User-Agent": "Mozilla/5.0 (fo76db)"}

DAY_RE = re.compile(r'data-day="(\d{4}-\d{2}-\d{2})"')
TITLE_RE = re.compile(r'title="([^"]+)"')
ROW_RE = re.compile(r"<tr[^>]*>\s*<td[^>]*>#(\d+)</td>\s*<td[^>]*>(.*?)</td>\s*<td[^>]*>(.*?)</td>\s*<td[^>]*>(.*?)</td>\s*</tr>", re.S)
SALE_RE = re.compile(r'<h3 id="sale-(\d+)">(.*?)(?=<h[23] |</article>)', re.S)
PLAN_RE = re.compile(r"<li[^>]*>\s*(Plans?: [^<]+?)\s*</li>")
SUPER_RE = re.compile(r"Super Sale.*?sales ([\d, and]+)", re.I | re.S)


def _get(url: str) -> str:
    features.require("falloutbuilds")
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def _text(s: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", s)).replace("’", "'").strip()


def parse_calendar(page: str) -> list[dict]:
    """[{title, start, end}] — даты `date`, конец включительно."""
    marks = list(DAY_RE.finditer(page))
    days: list[tuple[dt.date, set[str]]] = []
    for i, m in enumerate(marks):
        cell = page[m.end(): marks[i + 1].start() if i + 1 < len(marks) else len(page)]
        days.append((dt.date.fromisoformat(m.group(1)), {_text(t) for t in TITLE_RE.findall(cell)}))
    days.sort()
    events: list[dict] = []
    running: dict[str, dict] = {}
    for day, titles in days:
        for t in titles:
            ev = running.get(t)
            if ev and ev["end"] == day - dt.timedelta(days=1):
                ev["end"] = day
            else:
                running[t] = ev = {"title": t, "start": day, "end": day}
                events.append(ev)
    return events


def fetch_calendar() -> list[dict]:
    return parse_calendar(_get(f"{BASE}/events/"))


def _date(text: str, today: dt.date) -> dt.date:
    """«Oct 8» без года: берём год, при котором дата ближе всего к сегодняшней."""
    month, day = text.split()
    return nearest_year(month, day, today)


def parse_minerva(page: str, today: dt.date | None = None) -> dict:
    """{sales: [{sale, location, start, end}], plans: {sale: [name_en]}}."""
    today = today or dt.date.today()
    table = page.split('id="schedule"', 1)[-1]
    sales = []
    for num, loc, start, end in ROW_RE.findall(table.split("</table>", 1)[0]):
        loc = _text(re.sub(r"<sup.*?</sup>", "", loc))  # пометка «Next»/«Now» у ближайшей распродажи
        sales.append({"sale": int(num), "location": loc, "start": _date(_text(start), today), "end": _date(_text(end), today)})
    plans: dict[int, list[str]] = {}
    supers: dict[int, list[int]] = {}
    for num, body in SALE_RE.findall(page):
        names = [_text(p) for p in PLAN_RE.findall(body)]
        if names:
            plans[int(num)] = names
        elif m := SUPER_RE.search(_text(body)):
            supers[int(num)] = [int(x) for x in re.findall(r"\d+", m.group(1))]
    for num, parts in supers.items():
        plans[num] = sorted({n for p in parts for n in plans.get(p, [])})
    return {"sales": sales, "plans": plans}


def fetch_minerva() -> dict:
    return parse_minerva(_get(f"{BASE}/minerva/"))
