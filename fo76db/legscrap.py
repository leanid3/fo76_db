"""Разбор легендарок по приоритету персонажей и защита ценных предметов.

Цепочка игрока: эффект (мод + звезда), который не выучил кто-то из персонажей, нужен. Его разбирает персонаж с
наименьшим `profiles.priority` среди тех, кто мод не выучил (назначенный), остальные оставляют предмет и передают
назначенному. Если эффект выучен всеми, предмет разбирается или идёт на скрип.

Участвуют персонажи с данными в `known_legendary_mods` (LegendaryMods.ini) и не отмеченные складом. Эффект предмета
определяется как в `legendary.slots`; если название эффекта не сопоставилось, предмет не трогаем.

Защищённые предметы (таблица `protected_items`) не разбираются никогда: уникальные именные (по formid или названию)
и годролы (шаблоны звёзд как у хотелок, `rolls.matcher`).

`build_rules` строит правила LegeScrap для мода Invent-O-Matic Stash: по правилу на персонажа (одна клавиша,
`checkCharacterName`), в `excluded` — эффекты, назначенные другому персонажу. Мод сравнивает исключения подстрокой,
поэтому предметы с эффектами для разных персонажей правило оставляет всем (разбирать вручную у назначенного).
"""
from __future__ import annotations

import copy
import json
import re
import sqlite3
from collections import defaultdict

from . import legendary, rolls
from .db import get_meta, set_meta

KINDS = {"unique": "Уникальный", "godroll": "Годролл"}


def participants(c: sqlite3.Connection) -> list[dict]:
    """Персонажи с данными о выученных модах: [{id, name, label, priority}] по возрастанию приоритета."""
    rows = c.execute(
        "SELECT c.id, c.name, c.account, coalesce(p.label, c.name) AS label, coalesce(p.priority, 100) AS priority"
        " FROM characters c LEFT JOIN profiles p ON p.character_id = c.id"
        " WHERE coalesce(p.mule, 0) = 0 AND EXISTS (SELECT 1 FROM known_legendary_mods k WHERE k.character_id = c.id)"
        " ORDER BY 5, c.id")
    return [dict(r) for r in rows]


class Chain:
    """Выученные моды и назначенные персонажи. Эффект — (английское название мода, звезда)."""

    def __init__(self, c: sqlite3.Connection):
        self.chars = participants(c)
        self.by_id = {ch["id"]: ch for ch in self.chars}
        ids = {ch["id"] for ch in self.chars}
        self.effects: set[tuple[str, int]] = set()
        self.learned: dict[int, set[tuple[str, int]]] = defaultdict(set)
        self.local: dict[tuple[str, int], set[str]] = defaultdict(set)  # названия в клиентах: en + локальные
        for r in c.execute("SELECT character_id, name, stars, learned, name_local FROM known_legendary_mods"):
            if r["character_id"] not in ids or not r["stars"]:
                continue
            key = (r["name"], r["stars"])
            self.effects.add(key)
            self.local[key].add(r["name"])
            if r["name_local"]:
                self.local[key].add(r["name_local"])
            if r["learned"]:
                self.learned[r["character_id"]].add(key)
        # назначенный: первый по приоритету среди не выучивших (chars уже отсортированы)
        self.designated: dict[tuple[str, int], int | None] = {}
        for e in self.effects:
            self.designated[e] = next((ch["id"] for ch in self.chars if e not in self.learned[ch["id"]]), None)
        self.lookup = legendary.names(c)
        self.protected = _load_protected(c)

    def label(self, cid: int | None) -> str:
        return self.by_id[cid]["label"] if cid in self.by_id else "?"

    def item_effects(self, legendary_text: str | None, stars: int) -> list[tuple[str, int] | None]:
        """Эффекты предмета по звёздам; None — название не сопоставилось."""
        slots, _ = legendary.slots(legendary_text, stars, self.lookup)
        return [(s["en"], s["star"]) if s["en"] else None for s in slots]


def _norm_name(s: str) -> str:
    """Название без регистра, пробелов и знаков: «-EXP holyfire» находит «Holy Fire»."""
    return re.sub(r"[\W_]+", "", s.lower())


def _load_protected(c: sqlite3.Connection) -> dict:
    rows = [dict(r) for r in c.execute("SELECT * FROM protected_items")]
    gods = []
    for r in rows:
        if r["kind"] == "godroll":
            gods.append({**r, "s4": None, "name": r["name_en"] or r["name_ru"] or "годролл", "notify": 0})
    return {"unique_ids": {r["formid"] for r in rows if r["kind"] == "unique" and r["formid"] is not None},
            "unique_names": {_norm_name(r[f]) for r in rows if r["kind"] == "unique" for f in ("name_en", "name_ru") if r[f]},
            "godrolls": rolls.compile_wants(gods)}


def protected_reason(chain: Chain, *, formid: int | None, name: str, category: str | None, slots: list[dict]) -> str | None:
    """Почему предмет нельзя разбирать: «уникальный» / «годролл: <название>» / None."""
    p = chain.protected
    if formid is not None and formid in p["unique_ids"]:
        return "уникальный"
    low = _norm_name(name or "")
    if any(n and n in low for n in p["unique_names"]):
        return "уникальный"
    if len(slots) >= 3 and p["godrolls"]:  # минимум 3★; 4★ в оценку не входит
        g = rolls.grade(slots[:3], category, p["godrolls"])
        if g and g["grade"] == "god":
            return "годролл: " + " + ".join(s["en"] or s["text"] for s in slots[:3])
    return None


def item_advice(chain: Chain, character_id: int, effects: list) -> dict | None:
    """{type: 'give'|'self'|'learned', target, targets, need} для легендарного предмета; None — не определить.

    give — предмет нужен другому персонажу; self — персонаж выучит моды, разобрав сам; learned — всё выучено всеми.
    """
    if not effects or any(e is None or e not in chain.designated for e in effects):
        return None
    need = [(e, chain.designated[e]) for e in effects if chain.designated[e] is not None]
    if not need:
        return {"type": "learned", "target": None, "targets": [], "need": []}
    targets = {t for _, t in need}
    target = min(targets, key=lambda t: (chain.by_id[t]["priority"], t))
    kind = "self" if target == character_id else "give"  # эффекты разных персонажей: сначала тому, кто выше
    return {"type": kind, "target": target, "targets": sorted(targets), "need": need}


def need_text(chain: Chain, adv: dict) -> str:
    """«Vampire's ★1 (Skrom_TV), …» — какие эффекты предмета ещё нужны и кому."""
    return ", ".join(f"{e[0]} ★{e[1]} ({chain.label(t)})" for e, t in adv["need"])


# ---------- правила LegeScrap ----------

def _token(name: str) -> str:
    """Подстрока для исключения: «Vampire's» → «vampire»; русские формы — как есть."""
    return re.sub(r"['’]s$", "", name.strip()).lower() if name.isascii() else name.strip()


def excluded_for(chain: Chain, character_id: int) -> list[str]:
    """Названия (EN и локальные) эффектов, которые персонаж не должен разбирать: они нужны другому."""
    out: dict[str, None] = {}
    for e, d in sorted(chain.designated.items()):
        if d is not None and d != character_id:
            for n in sorted(chain.local[e]):
                out.setdefault(_token(n))
    return list(out)


def collisions(chain: Chain, character_id: int, excluded: list[str]) -> list[str]:
    """Предупреждения: исключение-подстрока задевает и эффекты, которые персонаж разбирать как раз должен."""
    keep = set(excluded)
    warns = []
    for e, d in sorted(chain.designated.items()):
        if d is not None and d != character_id:
            continue
        for n in chain.local[e]:
            t = _token(n)
            hits = [x for x in excluded if x and x != t and x in t.lower()]
            if hits and t not in keep:
                warns.append(f"«{n}» (★{e[1]}) содержит исключение «{hits[0]}» — предмет с ним тоже останется")
    return warns


def build_rules(c: sqlite3.Connection, base: dict, keep_manual: bool = False, protect: list[str] | None = None) -> dict:
    """По правилу LegeScrap на каждого участника: {rules: [...], characters: [{id, name, excluded, warnings}]}.

    `base` — текущее правило LegeScrap из конфига (из него берутся клавиша, звёзды и прочие настройки);
    исключения заменяются сгенерированными (при keep_manual прежний ручной список добавляется), добавляются `checkCharacterName`/`characterName`.
    `protect` — названия защищённых предметов: правило scrap не учитывает `scrapProtection.itemNames` (проверено тестовым
    прогоном в игре), поэтому они дописываются в `excluded` каждого правила.
    """
    chain = Chain(c)
    rules, chars = [], []
    for ch in chain.chars:
        gen = excluded_for(chain, ch["id"])
        # прежний ручной список исключений сохраняется только по просьбе: он защищает любой предмет с «хорошим» эффектом
        seen = {x.lower() for x in gen}
        manual = [x for x in dict.fromkeys(base.get("excluded") or []) if x.lower() not in seen] if keep_manual else []
        have = {x.lower() for x in gen + manual}
        ex = gen + manual + [n for n in dict.fromkeys(protect or []) if n.lower() not in have]
        rule = copy.deepcopy(base)
        rule["name"] = f"LegeScrap {ch['name']}"
        rule["excluded"] = ex
        rule["checkCharacterName"] = True
        rule["characterName"] = ch["name"]
        if ch["account"] and ch["account"] != "?":  # имя «main» бывает у нескольких аккаунтов
            rule["checkAccountName"] = True
            rule["accountName"] = ch["account"]
        rules.append(rule)
        mine = sum(1 for d in chain.designated.values() if d == ch["id"])
        chars.append({"id": ch["id"], "name": ch["name"], "label": ch["label"], "priority": ch["priority"],
                      "excluded": ex, "generated": len(gen), "manual": len(manual), "protected": len(ex) - len(gen) - len(manual), "scrap_effects": mine, "warnings": collisions(chain, ch["id"], ex)})
    return {"rules": rules, "characters": chars}


# ---------- наполнение защиты ----------

UNIQUE_CATEGORIES = ("Category:Fallout 76 unique weapons", "Category:Fallout 76 unique armor and clothing")


def _category(api, base: str, title: str) -> list[str]:
    out, cont = [], {}
    while True:
        r = api(base, action="query", list="categorymembers", cmtitle=title, cmlimit="500", cmnamespace="0", **cont)
        out += [m["title"] for m in r["query"]["categorymembers"]]
        if "continue" not in r:
            return out
        cont = {"cmcontinue": r["continue"]["cmcontinue"]}


def import_unique(c: sqlite3.Connection) -> dict:
    """Уникальные именные предметы Fallout 76 с вики fandom → protected_items (kind = unique). Повторный запуск
    добавляет только новые. formid ищется в каталоге по английскому названию (оружие, броня, одежда)."""
    from .sources import fo76wiki
    titles: list[str] = []
    for cat in UNIQUE_CATEGORIES:
        titles += _category(fo76wiki._api, fo76wiki.WIKIS[0][1], cat)
    have = {(r[0] or "").lower() for r in c.execute("SELECT name_en FROM protected_items WHERE kind = 'unique'")}
    added = matched = 0
    for t in dict.fromkeys(titles):
        if t.lower().startswith("fallout 76 unique"):
            continue
        name = re.sub(r"\s*\((?:Fallout 76|weapon)\)$", "", t)
        if name.lower() in have:
            continue
        row = c.execute("SELECT formid, name_ru FROM items WHERE kind IN ('weapon', 'armor', 'apparel') AND lower(name_en) = ?"
                        " ORDER BY status = 'ok' DESC, formid LIMIT 1", (name.lower(),)).fetchone()
        c.execute("INSERT INTO protected_items(kind, name_en, name_ru, formid, source, note) VALUES ('unique', ?, ?, ?, 'wiki', ?)",
                  (name, row["name_ru"] if row else None, row["formid"] if row else None, "fallout.fandom.com: " + t))
        added += 1
        matched += row is not None
    c.commit()
    return {"added": added, "with_formid": matched, "total": len(set(titles))}


# Годролл — предмет минимум с 3★, у которого каждая из звёзд 1–3 «хорошая» (две хороших — обычный предмет). Четвёртая
# звезда в оценку не входит, она важна только для изучения мода. «Хорошие» эффекты задаются по типу и звезде:
# строка protected_items (kind = godroll) на тип, s1–s3 — варианты через | (синтаксис rolls.matcher).
# Стартовый набор: консенсус игроков (единого списка нет) плюс то, что отмечено избранным и в прежнем ручном списке
# исключений LegeScrap владельца базы. Правится на странице «Защита».
GOOD = {
    "weapon": ("Bloodied|Anti-armor|Two Shot|Quad|Instigating|Furious|Vampire's", "Explosive|Rapid|Vital",
               "V.A.T.S. Optimized|Swift|Durability|Lightweight|Intelligence"),
    "armor": ("Unyielding|Overeater's|Vanguard's|Aristocrat's|Adrenal|Feral's|Lucid", "Powered|Intelligence",
              "Sentinel's|Thru-hiker's|Durability|Intelligence"),
}
GOOD_NAME = {"weapon": "Хорошие эффекты: оружие", "armor": "Хорошие эффекты: броня"}


def seed_godrolls(c: sqlite3.Connection) -> int:
    """Добавить наборы «хороших» эффектов, которых ещё нет (по типу). Заменяет прежние комбинации стартового набора."""
    c.execute("DELETE FROM protected_items WHERE kind = 'godroll' AND source = 'guide' AND name_en NOT IN (?, ?)",
              tuple(GOOD_NAME.values()))
    have = {r[0] for r in c.execute("SELECT name_en FROM protected_items WHERE kind = 'godroll'")}
    n = 0
    for scope, (s1, s2, s3) in GOOD.items():
        if GOOD_NAME[scope] in have:
            continue
        c.execute("INSERT INTO protected_items(kind, name_en, scope, s1, s2, s3, source, note)"
                  " VALUES ('godroll', ?, ?, ?, ?, ?, 'guide', 'стартовый набор: поправьте под свой билд')", (GOOD_NAME[scope], scope, s1, s2, s3))
        n += 1
    c.commit()
    return n


def suggest_from_inventory(c: sqlite3.Connection) -> list[dict]:
    """Эффекты избранных легендарок с 3★ и больше, которых ещё нет в «хороших»: [{scope, star, effect, count}].

    Избранное — выбор самого игрока. Блокировка передачи не учитывается: ею закрывают и обычные предметы."""
    from .importers.inventory import current_items_sql
    chain = Chain(c)
    good = {}
    for r in c.execute("SELECT scope, s1, s2, s3 FROM protected_items WHERE kind = 'godroll'"):
        for i in (1, 2, 3):
            good.setdefault((r["scope"], i), []).append(rolls.matcher(r[f"s{i}"]))
    counts: dict[tuple, int] = {}
    for r in c.execute(f"SELECT * FROM ({current_items_sql()}) WHERE stars >= 3"):
        if not json.loads(r["raw"] or "{}").get("favorite"):
            continue
        scope = "armor" if r["category"] in ("armor", "apparel") else "weapon"
        slots, _ = legendary.slots(r["legendary"], r["stars"], chain.lookup)
        for sl in slots[:3]:
            if sl["en"] and not any(m and m(sl) for m in good.get((scope, sl["star"]), [])):
                counts[(scope, sl["star"], sl["en"])] = counts.get((scope, sl["star"], sl["en"]), 0) + 1
    return sorted(({"scope": k[0], "star": k[1], "effect": k[2], "count": n} for k, n in counts.items()),
                  key=lambda x: (x["scope"], x["star"], -x["count"]))


def add_good(c: sqlite3.Connection, scope: str, star: int, effect: str) -> None:
    """Добавить эффект в «хорошие» для типа и звезды (строка kind = godroll этого типа создаётся при необходимости)."""
    if scope not in ("weapon", "armor") or star not in (1, 2, 3) or not effect.strip():
        raise ValueError("Нужны тип (weapon/armor), звезда 1–3 и эффект")
    row = c.execute("SELECT id, s1, s2, s3 FROM protected_items WHERE kind = 'godroll' AND scope = ? ORDER BY id LIMIT 1", (scope,)).fetchone()
    if row is None:
        c.execute("INSERT INTO protected_items(kind, name_en, scope, source) VALUES ('godroll', ?, ?, 'manual')", (GOOD_NAME[scope], scope))
        row = c.execute("SELECT id, s1, s2, s3 FROM protected_items WHERE kind = 'godroll' AND scope = ? ORDER BY id DESC LIMIT 1", (scope,)).fetchone()
    cur = [x for x in (row[f"s{star}"] or "").split("|") if x]
    if effect.strip().lower() not in {x.lower() for x in cur}:
        c.execute(f"UPDATE protected_items SET s{star} = ? WHERE id = ?", ("|".join(cur + [effect.strip()]), row["id"]))
    c.commit()


def add_godroll(c: sqlite3.Connection, name: str, scope: str, effects: list[str], source: str = "manual") -> int:
    pats = [(e or "").strip() or None for e in (effects + [None] * 4)[:4]]
    if not name.strip() or not any(pats) or scope not in rolls.SCOPES:
        raise ValueError("Нужны название, тип и хотя бы одна звезда")
    cur = c.execute("INSERT INTO protected_items(kind, name_en, scope, s1, s2, s3, s4, source) VALUES ('godroll', ?, ?, ?, ?, ?, ?, ?)",
                    (name.strip(), scope, *pats, source))
    c.commit()
    return cur.lastrowid


# ---------- конфиг игры ----------

RULE_NAME = "LegeScrap"


def protection_names(c: sqlite3.Connection) -> dict:
    """Названия защищённых предметов инвентаря для scrapProtection.itemNames (мод сравнивает подстрокой).

    {names: [...], collisions: [{name, others}]} — others: сколько НЕзащищённых предметов тоже содержат это название и
    попадут под защиту по ошибке."""
    from .importers.inventory import current_items_sql
    chain = Chain(c)
    names: dict[str, None] = {}
    plain: list[str] = []
    for r in c.execute(f"SELECT * FROM ({current_items_sql()})"):
        slots, _ = legendary.slots(r["legendary"], r["stars"], chain.lookup) if r["stars"] else ([], "")
        if r["stars"] and protected_reason(chain, formid=r["formid"], name=r["name"], category=r["category"], slots=slots):
            names.setdefault(r["name"])
        else:
            plain.append(r["name"].lower())
    out = []
    for n in names:
        k = sum(1 for x in plain if n.lower() in x)
        if k:
            out.append({"name": n, "others": k})
    return {"names": list(names), "collisions": out}


def plan_config(c: sqlite3.Connection, data: dict, keep_manual: bool = False) -> dict:
    """Новый конфиг IOM с правилами LegeScrap по персонажам (данные не пишутся). {data, characters, replaced, error}.

    Основа — первое правило с onlyLegendaries и именем LegeScrap (без привязки к персонажу); при повторном
    применении правила «LegeScrap <имя>» заменяются, остальные правила не трогаются."""
    cfgs = (data.get("scrapConfig") or {}).get("configs")
    if not isinstance(cfgs, list):
        return {"error": "В конфиге нет scrapConfig.configs"}
    generated = [r for r in cfgs if isinstance(r, dict) and str(r.get("name", "")).startswith(RULE_NAME + " ")]
    base = next((r for r in cfgs if isinstance(r, dict) and r.get("name") == RULE_NAME), None) or (generated[0] if generated else None)
    if base is None:
        return {"error": f"В конфиге нет правила «{RULE_NAME}»"}
    base = {k: v for k, v in base.items() if k not in ("checkCharacterName", "characterName", "checkAccountName", "accountName")}
    prot = protection_names(c)
    built = build_rules(c, base, keep_manual, prot["names"])
    if not built["rules"]:
        return {"error": "Нет персонажей с данными о выученных модах"}
    new = copy.deepcopy(data)
    keep = [r for r in cfgs if r not in generated and r.get("name") != RULE_NAME]
    pos = next((i for i, r in enumerate(cfgs) if r.get("name") == RULE_NAME or r in generated), len(keep))
    keep[min(pos, len(keep)):min(pos, len(keep))] = built["rules"]
    new["scrapConfig"]["configs"] = keep
    # Защита от разбора по названиям: прежние сгенерированные имена заменяются, остальные (ручные) остаются
    sp = new.setdefault("protectionConfig", {}).setdefault("scrapProtection", {})
    old_gen = set(json.loads(get_meta(c, "legscrap_names") or "[]"))
    sp["itemNames"] = [x for x in sp.get("itemNames", []) if x not in old_gen] + [x for x in prot["names"] if x not in sp.get("itemNames", [])]
    return {"data": new, "characters": built["characters"], "replaced": [r["name"] for r in cfgs if r not in keep],
            "protect_names": prot["names"], "collisions": prot["collisions"]}


def covered_names(data: dict | None) -> set[str]:
    """Названия из scrapProtection.itemNames конфига (в нижнем регистре)."""
    try:
        return {str(x).lower() for x in data["protectionConfig"]["scrapProtection"]["itemNames"]}
    except (KeyError, TypeError):
        return set()


def new_unprotected(c: sqlite3.Connection, covered: set[str]) -> list[dict]:
    """Защищённые предметы без защиты в игре (не в избранном, не заблокированы, названия нет в itemNames), о которых ещё
    не сообщали. Первый запуск только запоминает текущие. Ключ — персонаж|название|эффекты."""
    from .importers.inventory import current_items_sql
    chain = Chain(c)
    cur = {}
    for r in c.execute(f"SELECT * FROM ({current_items_sql()}) WHERE stars > 0"):
        raw = json.loads(r["raw"] or "{}")
        if raw.get("favorite") or raw.get("isTransferLocked") or any(n in r["name"].lower() for n in covered):
            continue
        slots, _ = legendary.slots(r["legendary"], r["stars"], chain.lookup)
        why = protected_reason(chain, formid=r["formid"], name=r["name"], category=r["category"], slots=slots)
        if why:
            k = f"{r['character_id']}|{r['name']}|{r['legendary']}"
            if k not in cur:
                cur[k] = {"key": k, "character": r["character"], "name": r["name"], "reason": why, "container": r["container"]}
    seen = get_meta(c, "godroll_seen")
    set_meta(c, "godroll_seen", json.dumps(sorted(cur)))
    c.commit()
    if seen is None:
        return []
    old = set(json.loads(seen))
    return [v for k, v in cur.items() if k not in old]
