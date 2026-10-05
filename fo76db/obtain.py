"""«Как получить» для карточки предмета.

Источники в игре почти всегда — списки добычи (LVLI): торговцы, награды квестов и событий, Daily Ops, выпадение
из существ, контейнеры. Предмет входит в список, тот — в другие списки и так далее. Поднимаемся по графу
`lvli_edges` до верха и раскладываем все встреченные списки по категориям по их EditorID (`RULES`).
Классификация эвристическая: EditorID — внутренние имена разработчиков, поэтому в интерфейсе рядом с понятной
подписью всегда доступен исходный EditorID.

Плюс то, что известно без списков: где предмет или его список стоит в мире (`placements`), крафт по схеме,
распродажи Минервы.
"""
from __future__ import annotations

import re
import sqlite3
from collections import defaultdict

MAX_DEPTH = 15

# Порядок категорий в карточке и их заголовки
CATEGORIES = {
    "gold": "Торговцы за золото",
    "scrip": "За легендарный скрип",
    "event": "События",
    "activity": "Daily Ops, экспедиции, рейды, рыбалка",
    "quest": "Квесты и награды",
    "season": "Сезон и Atom Shop",
    "creature": "Выпадает из врагов",
    "vendor": "Торговцы за крышки",
    "container": "Контейнеры и тайники",
    "other": "Прочие списки",
}

GOLD_VENDORS = {"Mortimer": "Мортимер (Кратер, рейдеры)", "Samuel": "Сэмюэл (Фонд, поселенцы)",
                "Reginald": "Реджинальд (Убежище 79)", "Regs": "Реджинальд (Убежище 79)"}
EVENTS = {"Fasnacht": "Фаснахт", "MeatWeek": "Мясная неделя", "Mothman": "Равноденствие Мотылька", "Encryptid": "Encryptid",
          "Festive": "Праздничные Выжженные", "Holiday": "Праздничные Выжженные", "Spooky": "Жуткие Выжженные",
          "TreasureHunt": "Охотник за сокровищами", "MutatedEvents": "Мутировавшие публичные события",
          "PowerPlantEvent": "События электростанций", "Bloom": "Большое цветение", "Invaders": "Пришельцы извне",
          "MSilo": "Ракетные шахты", "Scorchbeast": "Королева Скорчзверей", "Herd": "Eviction Notice / стадо"}


def _words(s: str) -> str:
    s = re.sub(r"(?<=[a-z])(?=[A-Z0-9])|(?<=[A-Z])(?=[A-Z][a-z])", " ", s.replace("_", " "))
    return re.sub(r"\s+", " ", s).strip()


def _event(edid: str) -> str | None:
    for key, ru in EVENTS.items():
        if key.lower() in edid.lower():
            return ru
    for word in re.findall(r"[A-Za-z]+", re.sub(r"^E\d+[A-Z]?_", "", edid)):
        if word not in ("LL", "LLD", "LLS", "LLI", "LLV", "LLE", "LPI"):
            return _words(word)
    return None


def _creature(edid: str) -> str:
    m = re.search(r"(?:Creature|LLD|LLE)_(?:Creature_)?([A-Za-z]+)", edid)
    return _words(m[1]) if m else _words(edid)


# (категория, регулярное выражение по EditorID, подпись). Первое совпадение выигрывает; категория None — пропустить.
RULES: list[tuple[str | None, re.Pattern, object]] = [
    (None, re.compile(r"(?i)^zz|deprecated|^cut_|debug|imgui|_pts\b|^llc_pts|loadout|chargen|^test"), None),
    ("gold", re.compile(r"Minerva"), "Минерва"),
    ("gold", re.compile(r"GoldVendor_(?:[A-Za-z]+_)?(" + "|".join(GOLD_VENDORS) + ")"), lambda m: GOLD_VENDORS[m[1]]),
    ("gold", re.compile(r"GoldVendor"), "Общий список торговцев за золото"),
    ("scrip", re.compile(r"(?i)purveyor|scrip"), "Мурмрг"),
    ("activity", re.compile(r"DailyOps"), "Daily Ops"),
    ("activity", re.compile(r"^XPD|_XPD_"), "Экспедиции"),
    ("activity", re.compile(r"^AC_|_AC_"), "Атлантик-Сити"),
    ("activity", re.compile(r"^V9[46]_|VaultSystem|Raid(?!er)"), "Рейды"),
    ("activity", re.compile(r"Fishing"), "Рыбалка"),
    ("activity", re.compile(r"TreasureMap"), "Карты сокровищ"),
    ("activity", re.compile(r"Bounty"), "Награды за головы"),
    ("season", re.compile(r"SCORE_S(\d+)"), lambda m: f"Сезон {int(m[1])}"),
    ("season", re.compile(r"^ATX_"), "Atom Shop (коллектроны, наборы)"),
    ("event", re.compile(r"^E\d+[A-Z]?_|Festive|Spooky|TreasureHunt|MutatedEvents|PowerPlantEvent|MSilo|Scorchbeast|Holiday"),
     lambda m: _event(m.string)),
    ("quest", re.compile(r"(?i)quest|reward|_mq|mqr|mqs|_sq\d|^rq|givetoplayer"), lambda m: _words(m.string)),
    ("creature", re.compile(r"(?i)^legendaryitems|^lgnd_"), "Легендарные враги"),
    ("container", re.compile(r"^LL[DE]_(?!Creature)(?:Safe|Tool|Footlocker|Medkit|Container|Crate|Ammo|Chest)"), lambda m: _words(m.string)),
    ("creature", re.compile(r"^LL[DE]_|Creature"), lambda m: _creature(m.string)),
    ("vendor", re.compile(r"(?i)vendor|vending"), lambda m: _words(m.string)),
    ("container", re.compile(r"(?i)container|^llc_|loot|crate|safe|toolbox|duffle|suitcase|trunk|chest|bag|cache"),
     lambda m: _words(m.string)),
]


def classify(edid: str) -> tuple[str, str] | None:
    for cat, rx, label in RULES:
        if m := rx.search(edid):
            if cat is None:
                return None
            return cat, (label(m) if callable(label) else label) or _words(edid)
    return "other", _words(edid)


def ancestors(c: sqlite3.Connection, fids: list[int]) -> dict[int, str]:
    """Все списки добычи, в которые предметы входят прямо или через другие списки: {formid: EditorID}."""
    if not fids:
        return {}
    q = ",".join("?" * len(fids))
    return dict(c.execute(
        f"WITH RECURSIVE up(id, d) AS (SELECT parent, 1 FROM lvli_edges WHERE child IN ({q})"
        f" UNION SELECT e.parent, up.d + 1 FROM lvli_edges e JOIN up ON e.child = up.id WHERE up.d < {MAX_DEPTH})"
        " SELECT l.formid, l.edid FROM (SELECT DISTINCT id FROM up) JOIN lvli l ON l.formid = id", fids).fetchall())


def sources(c: sqlite3.Connection, fids: list[int]) -> list[dict]:
    """[{cat, title, labels: [{label, edids}], lists}] в порядке CATEGORIES."""
    groups: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for edid in sorted(ancestors(c, fids).values()):
        if r := classify(edid):
            groups[r[0]][r[1]].append(edid)
    out = []
    for cat, title in CATEGORIES.items():
        if cat in groups:
            labels = sorted(({"label": k, "edids": v} for k, v in groups[cat].items()), key=lambda x: (-len(x["edids"]), x["label"]))
            out.append({"cat": cat, "title": title, "labels": labels, "lists": sum(len(x["edids"]) for x in labels)})
    return out


def world(c: sqlite3.Connection, fids: list[int], limit: int = 40) -> list[dict]:
    """Где стоит в мире сам предмет или список добычи с ним: [{cell, world, n}], больше всего — сверху."""
    ids = list(fids) + list(ancestors(c, fids))
    if not ids:
        return []
    q = ",".join("?" * len(ids))
    return [dict(r) for r in c.execute(
        f"SELECT cell, world, sum(n) AS n FROM placements WHERE formid IN ({q}) GROUP BY cell, world ORDER BY n DESC, cell LIMIT {limit}", ids)]


def how_to_get(c: sqlite3.Connection, fid: int) -> dict:
    """Всё для блока «Как получить»: источники предмета, схем, по которым он крафтится, место в мире, Минерва."""
    plans = [r[0] for r in c.execute(
        "SELECT DISTINCT r.plan FROM recipes r JOIN items p ON p.formid = r.plan"
        " WHERE r.product = ? AND p.kind IN ('plan', 'recipe') AND p.status = 'ok'", (fid,))]
    plan_rows = []
    for p in plans:
        it = c.execute("SELECT printf('%08X', formid) AS id, name_en, name_ru FROM items WHERE formid = ?", (p,)).fetchone()
        plan_rows.append({**dict(it), "sources": sources(c, [p]), "world": world(c, [p], 15)})
    minerva = [dict(r) for r in c.execute(
        "SELECT DISTINCT m.sale, (SELECT e.start FROM events e WHERE e.kind = 'minerva' AND e.source IS NOT NULL"
        "   AND json_extract(e.data, '$.sale') = m.sale AND e.end >= strftime('%Y-%m-%dT%H:%M', 'now', 'localtime') ORDER BY e.start LIMIT 1) AS next,"
        " (SELECT json_extract(e.data, '$.location') FROM events e WHERE e.kind = 'minerva' AND json_extract(e.data, '$.sale') = m.sale"
        "   ORDER BY e.start DESC LIMIT 1) AS location"
        f" FROM minerva_plans m WHERE m.formid IN ({','.join('?' * (1 + len(plans)))}) ORDER BY m.sale", [fid, *plans])]
    return {"sources": sources(c, [fid]), "world": world(c, [fid]), "plans": plan_rows, "minerva": minerva}
