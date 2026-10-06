"""Публичные Steam API Fallout 76 (appid 1151340), ключ не нужен: новости (Update Notes) и число игроков онлайн.

steamdb.info закрыт Cloudflare, поэтому берутся сами API Steam. Истории онлайна у них нет — её копит `fo76db.steam`.
"""
from __future__ import annotations

import datetime as dt
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
