"""Проверка новой версии FO76 DB: последний релиз на GitHub против `__version__`. Ничего не скачивает и не ставит — только предлагает.

Запрос — раз в 6 часов (после ошибки — раз в час), результат лежит в `meta`. Отключается в «Настройки → Разделы и сервисы» или `update_check = false` в config.toml.
Для приватного репозитория без `GITHUB_TOKEN` GitHub отвечает 404: это не ошибка, обновлений просто не видно.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time

from . import __version__, features
from .db import get_meta, set_meta
from .sources import net

log = logging.getLogger(__name__)
REPO = "leanid3/fo76_db"
API = f"https://api.github.com/repos/{REPO}/releases/latest"
TTL, TTL_ERROR = 6 * 3600, 3600


def parse(version: str) -> tuple[int, ...] | None:
    """`v2026.10.5.3` → (2026, 10, 5, 3); не версия — None. Кортежи сравниваются как есть: 2026.10.5 < 2026.10.5.3."""
    m = re.fullmatch(r"v?(\d+(?:\.\d+)*)", (version or "").strip())
    return tuple(int(p) for p in m[1].split(".")) if m else None


def enabled() -> bool:
    return features.service_on("updates")


def _fetch() -> dict | None:
    headers = {"User-Agent": "fo76db", "Accept": "application/vnd.github+json"}
    if os.environ.get("GITHUB_TOKEN"):
        headers["Authorization"] = f"Bearer {os.environ['GITHUB_TOKEN']}"
    r = json.loads(net.get(API, headers, timeout=8))
    return {"tag": r["tag_name"], "name": r.get("name") or r["tag_name"], "url": r["html_url"],
            "date": (r.get("published_at") or "")[:10]}


def refresh(con, force: bool = False) -> None:
    """Спросить GitHub, если данные устарели (или force). Сбой пишется в meta, наружу не бросается."""
    if not enabled():
        return
    checked = float(get_meta(con, "update_checked") or 0)
    ttl = TTL_ERROR if get_meta(con, "update_error") else TTL
    if not force and time.time() - checked < ttl:
        return
    try:
        latest = _fetch()
        set_meta(con, "update_latest", json.dumps(latest))
        set_meta(con, "update_error", "")
    except Exception as e:  # noqa: BLE001 — сеть, лимит, 404 приватного репозитория
        code = getattr(e, "code", None)
        set_meta(con, "update_error", "нет доступа к релизам (репозиторий приватный?)" if code == 404 else str(e)[:200])
        log.info("проверка обновлений: %s", e)
    set_meta(con, "update_checked", str(time.time()))
    con.commit()


def info(con) -> dict:
    """Для баннера и «Настроек»: current, latest (или None), newer — вышла версия новее, available — newer и не скрыта."""
    latest = json.loads(get_meta(con, "update_latest") or "null")
    cur, new = parse(__version__), parse(latest["tag"]) if latest else None
    newer = bool(cur and new and new > cur)
    return {"enabled": enabled(), "current": __version__, "latest": latest, "newer": newer,
            "available": newer and get_meta(con, "update_dismissed") != latest["tag"],
            "checked": get_meta(con, "update_checked"), "error": get_meta(con, "update_error") or None}


def dismiss(con, tag: str) -> None:
    set_meta(con, "update_dismissed", tag)
    con.commit()
