"""Импорт инвентаря из выгрузки Invent-O-Matic Extractor и легендарных модов из Improved Workbench.

itemsmod.json: {"characterInventories": {<персонаж>: {playerInventory, stashInventory, AccountInfoData, CharacterInfoData}}}.
FormID в выгрузке нет, поэтому предметы сопоставляются с каталогом по названию (EN или RU).
Каждый импорт — снимок. Одинаковые снимки (тот же хэш содержимого) повторно не сохраняются.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import sqlite3
from pathlib import Path

# filterFlag (битовая маска Pip-Boy) -> категория. Порядок важен: проверяется сверху вниз.
FILTER_BITS = (
    (0x80000, "junk"), (0x20000, "holotape"), (0x10000, "ammo"), (0x800, "plan"), (0x400, "note"),
    (0x4000, "junk"), (0x1000, "key"), (0x2000, "misc"), (0x40, "aid"), (0x20, "food"),
    (0x10, "apparel"), (0x8, "armor"), (0x4, "weapon"),
)

# Категория инвентаря -> подходящие kind каталога (для выбора среди одноимённых записей)
CATEGORY_KINDS = {
    "weapon": {"weapon"}, "armor": {"armor", "apparel"}, "apparel": {"apparel", "armor"},
    "aid": {"consumable", "magazine", "bobblehead"}, "food": {"consumable"},
    "plan": {"plan", "recipe"}, "note": {"book", "plan", "recipe"}, "ammo": {"ammo"},
    "holotape": {"holotape"}, "key": {"key", "book", "holotape", "misc"}, "misc": {"misc", "component"},
    "junk": {"misc", "component"},
}

LEGENDARY_SEP = "¬"


def category(item: dict) -> str:
    flag = int(item.get("filterFlag") or 0)
    for bit, name in FILTER_BITS:
        if flag & bit:
            return name
    # filterFlag = 0 бывает у надетых вещей и предметов в витринах: смотрим на карточку
    card = {e.get("text") for e in item.get("ItemCardEntries") or []}
    if "$ROF" in card or "$dmg" in card:
        return "weapon"
    if "$dr" in card:
        return "armor"
    return "other"


def clean_name(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("¢", "").replace(LEGENDARY_SEP, "")).strip()


class Matcher:
    """Название из инвентаря -> formid каталога."""

    def __init__(self, con: sqlite3.Connection):
        self.by_name: dict[str, list[sqlite3.Row]] = {}
        self.gear: list[tuple[str, sqlite3.Row]] = []
        rows = con.execute(
            "SELECT formid, kind, status, name_en, name_ru, json_extract(stats, '$.craftable') AS craftable,"
            " json_extract(stats, '$.in_lvli') AS in_lvli FROM items WHERE kind NOT IN ('atom', 'mod', 'legendary_mod')"
        ).fetchall()
        for r in rows:
            for n in {r["name_en"], r["name_ru"]}:
                if n:
                    self.by_name.setdefault(n.lower(), []).append(r)
                    if r["kind"] in ("weapon", "armor", "apparel") and r["status"] == "ok":
                        self.gear.append((n.lower(), r))
        # длинные названия первыми: «Gatling Plasma» должно победить «Plasma»
        self.gear.sort(key=lambda x: -len(x[0]))

    @staticmethod
    def _score(r: sqlite3.Row, kinds: set[str]) -> tuple:
        return (r["kind"] in kinds, r["status"] == "ok", bool(r["craftable"]) or bool(r["in_lvli"]), -r["formid"])

    def match(self, text: str, cat: str) -> int | None:
        name = clean_name(text).lower()
        kinds = CATEGORY_KINDS.get(cat, set())
        cands = self.by_name.get(name)
        if cands:
            return max(cands, key=lambda r: self._score(r, kinds))["formid"]
        if cat in ("weapon", "armor", "apparel"):
            # легендарные префиксы («Bloodied Sigma Squad Maximum Capacity Tesla Cannon»): ищем базовое название в конце
            for n, r in self.gear:
                if name.endswith(" " + n) and r["kind"] in kinds:
                    return r["formid"]
        return None


def _legendary(item: dict) -> str | None:
    for e in item.get("ItemCardEntries") or []:
        if e.get("text") == "DESC" and e.get("value"):
            parts = [p.strip() for p in e["value"].split(LEGENDARY_SEP) if p.strip()]
            return " / ".join(parts) or None
    return None


def character_id(con: sqlite3.Connection, account: str | None, name: str, info: dict | None = None) -> int:
    """Найти или создать персонажа. Персонаж из LegendaryMods.ini приходит без аккаунта («?»)
    и получает его при первом импорте инвентаря."""
    rows = con.execute("SELECT id, account FROM characters WHERE name = ? ORDER BY id", (name,)).fetchall()
    row = next((r for r in rows if r["account"] == account), None) if account else (rows[0] if rows else None)
    if row is None and account:
        row = next((r for r in rows if r["account"] == "?"), None)
    if row is None:
        cid = con.execute("INSERT INTO characters(account, name) VALUES (?, ?)", (account or "?", name)).lastrowid
    else:
        cid = row["id"]
        if account and row["account"] != account:
            con.execute("UPDATE characters SET account = ? WHERE id = ?", (account, cid))
    if info is not None:
        con.execute("UPDATE characters SET info = ? WHERE id = ?", (json.dumps(info, ensure_ascii=False), cid))
    return cid


def _digest(data: dict) -> str:
    return hashlib.sha1(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def import_file(con: sqlite3.Connection, path: Path, log=print) -> int:
    """Импорт одного itemsmod.json. Возвращает число новых снимков."""
    data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    taken = dt.datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds")
    matcher = Matcher(con)
    new = 0
    for char_name, inv in (data.get("characterInventories") or {}).items():
        account = (inv.get("AccountInfoData") or {}).get("name") or "?"
        info = {"account": inv.get("AccountInfoData"), "character": inv.get("CharacterInfoData")}
        cid = character_id(con, account, char_name, info)
        digest = _digest({"p": inv.get("playerInventory"), "s": inv.get("stashInventory")})
        if con.execute("SELECT 1 FROM inv_snapshots WHERE character_id = ? AND digest = ?", (cid, digest)).fetchone():
            log(f"  {account}/{char_name}: без изменений")
            continue
        sid = con.execute(
            "INSERT INTO inv_snapshots(character_id, taken_at, source, digest) VALUES (?, ?, ?, ?)",
            (cid, taken, str(path), digest),
        ).lastrowid
        rows, matched = [], 0
        for container, key in (("player", "playerInventory"), ("stash", "stashInventory")):
            for it in inv.get(key) or []:
                cat = category(it)
                fid = matcher.match(it.get("text", ""), cat)
                matched += fid is not None
                rows.append((
                    sid, container, it.get("text", ""), cat, fid, int(it.get("count") or 0),
                    # тайник игра считает без перков на вес: weightInStash
                    (it.get("weightInStash") if container == "stash" and it.get("weightInStash") is not None else it.get("weight")),
                    it.get("itemValue"), it.get("itemLevel"), int(it.get("numLegendaryStars") or 0),
                    _legendary(it) if it.get("isLegendary") else None,
                    int(bool(it.get("isLearnedRecipe"))) if cat == "plan" else None,
                    int(bool(it.get("equipState"))), json.dumps(it, ensure_ascii=False),
                ))
        con.executemany(
            "INSERT INTO inv_items(snapshot_id, container, name, category, formid, count, weight, value, level, stars,"
            " legendary, learned, equipped, raw) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        # Изученные схемы, увиденные в инвентаре
        con.executemany(
            "INSERT INTO known_recipes(character_id, formid, source) VALUES (?, ?, 'auto') ON CONFLICT DO NOTHING",
            [(cid, r[4]) for r in rows if r[4] is not None and r[11]],
        )
        new += 1
        log(f"  {account}/{char_name}: {len(rows)} записей, сопоставлено {matched} ({matched * 100 // max(len(rows), 1)}%)")
    con.commit()
    return new


def _common_prefix(a: str, b: str) -> int:
    n = 0
    for x, y in zip(a, b):
        if x != y:
            break
        n += 1
    return n


def _numbers(desc: dict) -> tuple:
    return tuple((k, tuple(re.findall(r"\d+(?:\.\d+)?", v.replace(",", ".")))) for k, v in sorted(desc.items()))


def _words(text: str) -> str:
    """Описание без чисел: «+50% Критический урон» -> «критический урон»."""
    return " ".join(re.sub(r"[+-]?\d+(?:[.,]\d+)?%?", " ", text).split()).lower()


class LegendaryNames:
    """Локализованное название легендарного мода -> английское.

    Improved Workbench в русском клиенте пишет названия, которых нет в таблицах строк игры
    («Окровавленное», а у OMOD — «Кровавость»). Поэтому для каждого русского мода подбирается
    английский с тем же числом звёзд по сумме признаков:
    - текст описания переводится через таблицы строк игры (ID строки RU -> EN) и совпадает с английским;
    - совпадают числа в описании и набор его ключей (weapons/armor/all);
    - название похоже на русское название OMOD или легендарного префикса («[Ночная]» -> Nocturnal).
    Английские описания берутся из выгрузок персонажей с английским клиентом (этот файл и база).
    Пары назначаются жадно по убыванию веса, каждое английское название — одному моду.
    """

    def __init__(self, con: sqlite3.Connection):
        self.en: set[str] = set()
        self.local: list[tuple[int | None, str, str]] = []
        for edid, en, ru in con.execute("SELECT edid, name_en, name_ru FROM items WHERE kind = 'legendary_mod'"):
            m = re.search(r"(\d)", edid or "")
            self.en.add(en)
            if ru:
                self.local.append((int(m.group(1)) if m else None, ru.lower(), en))
        self.ref: dict[tuple[str, int], dict] = {}
        for name, stars, desc in con.execute(
                "SELECT DISTINCT name, stars, description FROM known_legendary_mods WHERE name_local IS NULL"):
            if name.isascii():
                self.ref[(name, stars)] = json.loads(desc or "{}")
        self.tr: dict[str, str] = {}
        try:
            from ..sources.strings import load_strings
            ru, en = load_strings("ru"), load_strings("en")
        except Exception:
            return
        for sid, text in ru.items():
            t = en.get(sid)
            if not t:
                continue
            if text.startswith("[") and text.endswith("]"):  # легендарный префикс: «[Ночная]» -> Nocturnal
                self.local.append((None, text[1:-1].lower(), t[1:-1] if t.startswith("[") else t))
            elif len(text) < 300:
                self.tr.setdefault(text.strip(), t.strip())
                self.tr.setdefault(_words(text), _words(t))

    def _name_score(self, name: str, stars: int | None, en: str) -> int:
        n, best = name.lower(), 0
        for st, local, e in self.local:
            if e != en or (st is not None and stars is not None and st != stars):
                continue
            for word in [local, *local.split()]:
                k = _common_prefix(n, word)
                if n == word:
                    best = max(best, 10)  # короткие точные совпадения: «Сила» -> Strength
                elif k >= max(5, min(len(n), len(word)) - 3):
                    best = max(best, k)
        return best

    def resolve(self, mods: list[dict]) -> dict[tuple[str, int], str]:
        """{(локальное название, звёзды): английское} для неанглийских модов из списка."""
        ref = dict(self.ref)
        for m in mods:
            if (m.get("name") or "").isascii():
                ref[(m["name"], m.get("stars"))] = m.get("description") or {}
        taken = {k for k in ref if any(k == (m.get("name"), m.get("stars")) for m in mods)}
        local = [m for m in mods if m.get("name") and not m["name"].isascii() and m["name"] not in self.en]
        scored = []
        for m in local:
            st, desc = m.get("stars"), m.get("description") or {}
            sig = _numbers(desc)
            for (en, est), edesc in ref.items():
                if est != st or (en, est) in taken:
                    continue
                score = 0
                etexts = {v.strip() for v in edesc.values()}
                ewords = {_words(v) for v in edesc.values()} - {""}
                for v in desc.values():
                    if self.tr.get(v.strip()) in etexts:
                        score += 100
                    elif self.tr.get(_words(v)) in ewords:
                        score += 60
                if edesc and _numbers(edesc) == sig:
                    score += 20
                score += 3 * self._name_score(m["name"], st, en)
                if score >= 30:
                    scored.append((score, m["name"], st, en))
        out: dict[tuple[str, int], str] = {}
        used = set()
        for score, name, st, en in sorted(scored, reverse=True):
            if (name, st) in out or (en, st) in used:
                continue
            out[(name, st)] = en
            used.add((en, st))
        # Остальное — методом исключения: ровно один свободный английский мод с теми же звёздами и числами
        changed = True
        while changed:
            changed = False
            for m in local:
                key = (m["name"], m.get("stars"))
                if key in out:
                    continue
                sig = _numbers(m.get("description") or {})
                if not any(nums for _, nums in sig):
                    continue  # без чисел совпадение ничего не говорит
                cand = [en for (en, est), edesc in ref.items() if est == key[1] and (en, est) not in used
                        and (en, est) not in taken and edesc and _numbers(edesc) == sig]
                if len(cand) == 1:
                    out[key] = cand[0]
                    used.add((cand[0], key[1]))
                    changed = True
        return out


def import_legendary_mods(con: sqlite3.Connection, path: Path, log=print) -> None:
    """LegendaryMods.ini (Improved Workbench): {"characterInventories": {<персонаж>: {"legendaryMods": [...]}}}."""
    data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    taken = dt.datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds")
    chars = data.get("characterInventories") or {}
    names = LegendaryNames(con)
    for char_name, inv in chars.items():
        cid = character_id(con, None, char_name)
        mods = inv.get("legendaryMods") or []
        # Персонаж может быть в нескольких файлах (общий Data/ и выгрузки контейнеров): старый файл не затирает новые данные
        have = con.execute("SELECT max(taken_at) FROM known_legendary_mods WHERE character_id = ?", (cid,)).fetchone()[0]
        if have and have > taken:
            log(f"  {char_name}: в базе данные новее ({have}), файл от {taken} пропущен")
            continue
        con.execute("DELETE FROM known_legendary_mods WHERE character_id = ?", (cid,))
        rows, unmapped = {}, 0
        mapped = names.resolve(mods)
        for m in mods:
            if not m.get("name"):
                continue
            en = m["name"] if m["name"].isascii() or m["name"] in names.en else mapped.get((m["name"], m.get("stars")))
            unmapped += en is None
            key = (en or m["name"], m.get("stars"))
            rows[key] = (cid, key[0], key[1], m.get("count"), int(bool(m.get("isLearned"))),
                         json.dumps(m.get("description") or {}, ensure_ascii=False), m["name"] if en != m["name"] else None, taken)
        con.executemany(
            "INSERT INTO known_legendary_mods(character_id, name, stars, count, learned, description, name_local, taken_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows.values())
        note = f", не сопоставлено с английскими названиями: {unmapped}" if unmapped else ""
        log(f"  {char_name}: легендарных модов {len(mods)}, изучено {sum(1 for m in mods if m.get('isLearned'))}{note}")
    con.commit()


def item_key(name: str, stars: int | None, legendary: str | None) -> str:
    """Ключ предмета для тегов, отображаемых имён и хотелок: не зависит от снимка."""
    return f"{name}|{stars or 0}|{legendary or ''}"


def current_items_sql() -> str:
    """Последний снимок каждого персонажа."""
    return (
        "SELECT ii.*, c.account, c.name AS character, c.id AS character_id, s.taken_at FROM inv_items ii"
        " JOIN inv_snapshots s ON s.id = ii.snapshot_id JOIN characters c ON c.id = s.character_id"
        " WHERE s.id = (SELECT id FROM inv_snapshots s2 WHERE s2.character_id = s.character_id ORDER BY taken_at DESC, id DESC LIMIT 1)"
    )
