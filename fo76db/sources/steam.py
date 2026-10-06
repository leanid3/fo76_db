"""Публичные Steam API Fallout 76 (appid 1151340), ключ не нужен: новости (Update Notes) и число игроков онлайн.

steamdb.info закрыт Cloudflare, поэтому берутся сами API Steam. Истории онлайна у них нет — её копит `fo76db.steam`.
"""
from __future__ import annotations

import datetime as dt
import html
import json
import re

from . import net

APPID = "1151340"
API = "https://api.steampowered.com"
UA = {"User-Agent": "Mozilla/5.0 (fo76db)"}


def _get(url: str) -> dict:
    return json.loads(net.get(url, UA, timeout=30))


def parse_news(data: dict) -> list[dict]:
    """[{gid, title, date, url, feedlabel, patch}] — `date` в местном времени `ГГГГ-ММ-ДДTЧЧ:ММ`, patch — тег `patchnotes`."""
    out = []
    for n in data.get("appnews", {}).get("newsitems", []):
        out.append({
            "gid": str(n["gid"]),
            "title": n.get("title", "").strip(),
            "date": dt.datetime.fromtimestamp(n["date"]).strftime("%Y-%m-%dT%H:%M"),
            "url": n.get("url"),
            "feedlabel": n.get("feedlabel"),
            "patch": int("patchnotes" in (n.get("tags") or [])),
        })
    return out


def parse_players(data: dict) -> int:
    r = data["response"]
    if r.get("result") != 1:
        raise ValueError(f"Steam вернул result={r.get('result')}")
    return int(r["player_count"])


def fetch_news(count: int = 40) -> list[dict]:
    return parse_news(_get(f"{API}/ISteamNews/GetNewsForApp/v2/?appid={APPID}&count={count}&maxlength=0"))


def fetch_players() -> int:
    return parse_players(_get(f"{API}/ISteamUserStats/GetNumberOfCurrentPlayers/v1/?appid={APPID}"))


ROW_RE = re.compile(r'<div class="achievePercent">([\d.,]+)%</div>\s*<div class="achieveTxt">\s*<h3>(.*?)</h3>\s*<h5>(.*?)</h5>', re.S)


def parse_achievement_percents(data: dict) -> list[dict]:
    """[{api_name, percent}] — глобальный процент игроков по каждому достижению (по убыванию)."""
    return [{"api_name": a["name"], "percent": float(a["percent"])}
            for a in data.get("achievementpercentages", {}).get("achievements", [])]


def parse_achievement_page(page: str) -> list[dict]:
    """[{title, descr, percent}] со страницы steamcommunity.com/stats/<appid>/achievements (порядок — по убыванию процента)."""
    return [{"title": html.unescape(t).strip(), "descr": html.unescape(d).strip(), "percent": float(p.replace(",", "."))}
            for p, t, d in ROW_RE.findall(page)]


def merge_achievements(percents: list[dict], page: list[dict]) -> list[dict]:
    """Названия со страницы + технические имена API (нужны для личного прогресса). Обе выдачи отсортированы по проценту,
    сопоставление по позиции принимается, только если число строк совпало, а проценты различаются не больше чем на 0,25
    (два запроса идут в разное время и расходятся на 0,1), иначе api_name = None."""
    ok = len(percents) == len(page) and all(abs(a["percent"] - b["percent"]) < 0.25 for a, b in zip(percents, page))
    return [{"sort": i, "api_name": percents[i]["api_name"] if ok else None, **row} for i, row in enumerate(page)]


def fetch_achievements() -> list[dict]:
    percents = parse_achievement_percents(_get(f"{API}/ISteamUserStats/GetGlobalAchievementPercentagesForApp/v2/?gameid={APPID}"))
    page = parse_achievement_page(net.get(f"https://steamcommunity.com/stats/{APPID}/achievements/?l=russian", UA, timeout=30))
    if not page:
        raise ValueError("на странице достижений не найдено ни одной строки (вёрстка изменилась?)")
    return merge_achievements(percents, page)


def parse_appmanifest(text: str) -> dict | None:
    """Поля из appmanifest_<appid>.acf: {buildid, size, updated}. None — нет buildid."""
    def field(name: str) -> str | None:
        m = re.search(rf'"{name}"\s+"([^"]*)"', text)
        return m.group(1) if m else None

    build = field("buildid")
    if not build:
        return None
    updated = field("LastUpdated")
    return {"buildid": build,
            "size": int(field("SizeOnDisk") or 0),
            "updated": dt.datetime.fromtimestamp(int(updated)).strftime("%Y-%m-%dT%H:%M") if updated and updated != "0" else None}
