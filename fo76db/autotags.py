"""Автоматические теги предметов: редкость, сезон, откуда получить.

Считаются по каталогу целиком и хранятся в `item_auto_tags(formid, tag)`. Пересчёт ленивый (`ensure`): при первом
запросе после импорта каталога, истории версий или обновления событий (сезоны, Минерва). Код тега — строка `группа:значение`, подпись и цвет берутся из `describe()`.

- Редкость: ключевые слова `ATX_ItemRarity_*` (Atom Shop) и `ItemRarity_*` (гранаты Nuka, ядерный чемоданчик).
- Сезон добавления: дата сборки, в которой предмет появился в выгрузках (дата выхода обновления, если известна),
  попадает в даты сезона по fallout.wiki. Предметы первой выгрузки (2019) получают «До сезонов».
- Откуда: те же правила по EditorID списков добычи, что и в «Как получить» (`obtain.classify`), только надёжные
  категории (золото, скрип, Daily Ops, экспедиции, рейды, сезонные события, награды табло, Atom Shop) плюс Минерва
  и Fallout 1st. Источники схемы переходят на предмет, который по ней крафтится.
- Состояние: новое (последнее обновление), удалено из игры, не используется.
"""
from __future__ import annotations

import re
import sqlite3
import time
from collections import defaultdict

from . import obtain

# (код, подпись, цвет): цвета редкости — серый, зелёный, синий, фиолетовый, золотой
RARITY = {
    "ATX_ItemRarity_Standard": ("common", "Обычное", "#9aa3ad"),
    "ItemRarity_Low": ("common", "Обычное", "#9aa3ad"),
    "ItemRarity_Medium": ("uncommon", "Необычное", "#5ec26a"),
    "ATX_ItemRarity_Rare": ("rare", "Редкое", "#4c9dff"),
    "ItemRarity_High": ("rare", "Редкое", "#4c9dff"),
    "ATX_ItemRarity_Superior": ("epic", "Превосходное", "#b36bff"),
    "ItemRarity_Epic": ("epic", "Эпическое", "#b36bff"),
    "ATX_ItemRarity_Nuclear": ("legendary", "Ядерное", "#ffb02e"),
}
RARITY_ORDER = ["common", "uncommon", "rare", "epic", "legendary"]

# Подписи «откуда» по категории obtain.classify; для activity и event подпись берётся из правила
SOURCE = {"gold": "Золото", "scrip": "Мурмрг (скрип)"}
ACTIVITY = {"Daily Ops", "Экспедиции", "Атлантик-Сити", "Рейды", "Рыбалка", "Карты сокровищ"}
# Только сезонные события: «Королева», шахты и электростанции — обычные события, их списки смешаны с добычей врагов
SEASONAL = {"Фаснахт", "Мясная неделя", "Равноденствие Мотылька", "Encryptid", "Праздничные Выжженные", "Жуткие Выжженные",
            "Охотник за сокровищами", "Мутировавшие публичные события", "Большое цветение", "Пришельцы извне"}
GROUPS = {"rarity": "Редкость", "season": "Сезон добавления", "src": "Откуда", "event": "Сезонное событие",
          "score": "Награда табло", "state": "Состояние"}
COLORS = {"season": "#3fb5a3", "src": "#d8a24a", "event": "#e0709a", "score": "#7fb2ff", "state": "#8a8f98"}
STATE = {"new": ("Новое", "#6fd36f"), "removed": ("Удалено из игры", "#e06666"), "unused": ("Не используется", "#8a8f98")}


def describe(code: str) -> dict:
    """{code, group, group_ru, label, color, sort} для кода тега."""
    group, _, val = code.partition(":")
    color, sort = COLORS.get(group, "#9aa3ad"), val
    if group == "rarity":
        label, color = next((l, c) for k, l, c in RARITY.values() if k == val)
        sort = str(RARITY_ORDER.index(val))
    elif group == "season":
        label = "До сезонов" if val == "0" else f"Сезон {val}"
        sort = f"{int(val):03d}"
    elif group == "score":
        label, sort = f"Табло S{val}", f"{int(val):03d}"
    elif group == "state":
        label, color = STATE[val]
    else:
        label = val
    return {"code": code, "group": group, "group_ru": GROUPS.get(group, group), "label": label, "color": color, "sort": sort}


def _source_tag(edid: str) -> str | None:
    r = obtain.classify(edid)
    if not r:
        return None
    cat, label = r
    if label == "Минерва":
        return "src:Минерва"
    if cat in SOURCE:
        return "src:" + SOURCE[cat]
    if cat == "activity" and label in ACTIVITY:
        return "src:" + label
    if cat == "event" and label in SEASONAL:
        return "event:" + label
    if cat == "season":
        m = re.fullmatch(r"Сезон (\d+)", label)
        return f"score:{m[1]}" if m else "src:Atom Shop"
    return None


def _lvli_tags(c: sqlite3.Connection) -> dict[int, set[str]]:
    """Теги для всех формидов, до которых можно дойти вниз по спискам добычи: {formid: {тег}}.

    Теги спускаются от списка ко всем его детям; повторяем проходы, пока что-то меняется (глубина графа ~15,
    циклы не мешают — множество просто перестаёт расти)."""
    edges = c.execute("SELECT parent, child FROM lvli_edges").fetchall()
    tags: dict[int, set[str]] = defaultdict(set)
    for fid, edid in c.execute("SELECT formid, edid FROM lvli"):
        if t := _source_tag(edid or ""):
            tags[fid].add(t)
    for _ in range(obtain.MAX_DEPTH + 5):
        changed = False
        for p, ch in edges:
            if (tp := tags.get(p)) and not tp <= tags[ch]:
                tags[ch] |= tp
                changed = True
        if not changed:
            break
    return tags


def _seasons(c: sqlite3.Connection) -> list[tuple[str, int]]:
    """[(дата начала YYYY-MM-DD, номер)] по возрастанию."""
    return sorted((r[0][:10], int(r[1])) for r in c.execute(
        "SELECT start, json_extract(data, '$.number') FROM events WHERE kind = 'season' AND json_extract(data, '$.number') IS NOT NULL"))


def rebuild(c: sqlite3.Connection, log=None) -> int:
    t0 = time.time()
    tags: dict[int, set[str]] = defaultdict(set)

    for fid, kw in c.execute("SELECT formid, keywords FROM items WHERE keywords LIKE '%ItemRarity_%'"):
        for w in kw.split():
            if w in RARITY:
                tags[fid].add("rarity:" + RARITY[w][0])
        if "ATX_Entitlement_Category_Store_Fallout1st" in kw.split():
            tags[fid].add("src:Fallout 1st")

    seasons = _seasons(c)
    first = c.execute("SELECT tag FROM builds ORDER BY vkey LIMIT 1").fetchone()
    latest = c.execute("SELECT update_name FROM builds WHERE is_pts = 0 AND update_name IS NOT NULL ORDER BY vkey DESC LIMIT 1").fetchone()
    for fid, build, date, upd, status, removed in c.execute(
            "SELECT i.formid, i.added_build, coalesce(b.released, b.date), b.update_name, i.status, i.removed_build"
            " FROM items i LEFT JOIN builds b ON b.tag = i.added_build"):
        if seasons and date:
            n = 0 if first and build == first[0] else max((s for d, s in seasons if d <= date[:10]), default=0)
            tags[fid].add(f"season:{n}")
        if latest and upd == latest[0] and build != (first and first[0]):
            tags[fid].add("state:new")
        if removed:
            tags[fid].add("state:removed")
        elif status != "ok":
            tags[fid].add("state:unused")

    src = _lvli_tags(c)
    for fid, t in src.items():
        tags[fid] |= t
    for (fid,) in c.execute("SELECT DISTINCT formid FROM minerva_plans WHERE formid IS NOT NULL"):
        tags[fid].add("src:Минерва")
    # схема → то, что по ней крафтится
    for product, plan in c.execute(
            "SELECT DISTINCT r.product, r.plan FROM recipes r JOIN items p ON p.formid = r.plan"
            " WHERE p.kind IN ('plan', 'recipe') AND r.product IS NOT NULL"):
        tags[product] |= {t for t in tags.get(plan, ()) if t.startswith(("src:", "event:", "score:"))}

    known = {r[0] for r in c.execute("SELECT formid FROM items")}
    rows = [(fid, t) for fid, ts in tags.items() if fid in known for t in ts]
    with c:
        c.execute("DELETE FROM item_auto_tags")
        c.executemany("INSERT INTO item_auto_tags(formid, tag) VALUES (?, ?)", rows)
        c.execute("INSERT OR REPLACE INTO meta(key, value) VALUES ('autotags_built', datetime('now'))")
    if log:
        log(f"Автотеги: {len(rows)} у {len({r[0] for r in rows})} предметов за {time.time() - t0:.1f} с")
    return len(rows)


KEY_META = ("catalog_release", "catalog_esm", "history_latest", "events_fetched")


def ensure(c: sqlite3.Connection) -> str:
    """Пересчитать, если с прошлого раза изменились каталог, история версий или события. Возвращает ключ состояния."""
    q = ",".join("?" * len(KEY_META))
    key = "|".join(f"{k}={v}" for k, v in c.execute(f"SELECT key, value FROM meta WHERE key IN ({q}) ORDER BY key", KEY_META))
    if c.execute("SELECT value FROM meta WHERE key = 'autotags_key'").fetchone() != (key,):
        rebuild(c)
        with c:
            c.execute("INSERT OR REPLACE INTO meta(key, value) VALUES ('autotags_key', ?)", (key,))
    return key


def by_formid(c: sqlite3.Connection) -> dict[int, list[str]]:
    out: dict[int, list[str]] = defaultdict(list)
    for fid, t in c.execute("SELECT formid, tag FROM item_auto_tags"):
        out[fid].append(t)
    return out


def ordered(codes) -> list[dict]:
    order = list(GROUPS)
    return sorted((describe(t) for t in codes), key=lambda d: (order.index(d["group"]) if d["group"] in order else 99, d["sort"]))
