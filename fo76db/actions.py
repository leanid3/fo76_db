"""Таблица действий персонажа: правила мода IOM как строки БД (docs/mod-fork.md).

Одна строка `actions` = одно правило конфига. Импорт читает правила из секций конфига игры, запись строит новый
конфиг (данные не пишутся — запись делает iomconfig.save). Правила, созданные приложением, помечены полем
`fo76db` (id действия); правила без метки — ручные, их запись не трогает, кроме импортированных (по хэшу)."""
from __future__ import annotations

import copy
import hashlib
import json
import sqlite3

MARK = "fo76db"  # поле-метка в правиле: id действия (оригинальный мод незнакомые поля игнорирует)

# тип действия → (секция конфига, плоский список вместо {configs: [...]})
SECTIONS = {
    "scrap": ("scrapConfig", False),
    "transfer": ("transferConfig", True),
    "vend": ("campAssignConfig", False), "display": ("campAssignConfig", False), "freeze": ("campAssignConfig", False),
    "sell": ("npcSellConfig", False),
    "buy": ("buyConfig", False),
    "loot": ("lootConfig", False),
}
# цепочка легендарок: тип → (секция, mode, заготовка правила); исполняет только форк мода (utils/Plan.as)
CHAIN = {
    "chain-scrap": ("scrapConfig", "chain", {"types": ["WEAPON", "ARMOR"], "matchMode": "ALL", "onlyLegendaries": True, "excluded": []}),
    "chain-give": ("transferConfig", "chain-give", {"types": ["WEAPON", "ARMOR"], "matchMode": "ALL", "itemNames": ["*"], "direction": "TO_CONTAINER"}),
    "chain-take": ("transferConfig", "chain-take", {"types": ["WEAPON", "ARMOR"], "matchMode": "ALL", "itemNames": ["*"], "direction": "FROM_CONTAINER"}),
}
FORK_ONLY = ("consume", "drop", "lock", *CHAIN)  # нужны правки форка мода
TYPES = tuple(SECTIONS) + FORK_ONLY
# поля правила, которыми управляет таблица (остальное остаётся из raw/filter)
OWN = ("name", "hotkey", "testRun", "enabled", "checkCharacterName", "characterName", "checkAccountName", "accountName", MARK)


def rule_hash(rule: dict) -> str:
    return hashlib.sha1(json.dumps(rule, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


def is_fork(c: sqlite3.Connection, data: dict) -> bool:
    """Форк мода: в конфиге уже стоит modFork или включено в настройках страницы «Действия»."""
    from . import chainplan
    return fork_version(data) >= 1 or chainplan.fork_on(c)


def fork_version(data: dict) -> int:
    """Версия форка мода из конфига (`modFork.version`); 0 — оригинальный мод."""
    mf = data.get("modFork") if isinstance(data, dict) else None
    try:
        return int(mf.get("version", 0)) if isinstance(mf, dict) else 0
    except (TypeError, ValueError):
        return 0


def _items(data: dict, section: str, flat: bool) -> list | None:
    s = data.get(section)
    if flat:
        return s if isinstance(s, list) else None
    return s.get("configs") if isinstance(s, dict) and isinstance(s.get("configs"), list) else None


def _type_of(section: str, rule: dict) -> str:
    if section == "campAssignConfig":
        return next((t for t in ("vend", "display", "freeze") if str(rule.get("type", rule.get("mode", ""))).lower().startswith(t[:4])), "vend")
    return next(t for t, (sec, _) in SECTIONS.items() if sec == section)


def _row(rule: dict, typ: str) -> dict:
    return {
        "name": str(rule.get("name") or typ), "type": typ, "hotkey": rule.get("hotkey") or None,
        "account": rule.get("accountName") if rule.get("checkAccountName") else None,
        "character": rule.get("characterName") if rule.get("checkCharacterName") else None,
        "test_run": 1 if rule.get("testRun", True) else 0, "enabled": 1 if rule.get("enabled") else 0,
    }


def import_rules(c: sqlite3.Connection, data: dict) -> dict:
    """Добавить в таблицу правила конфига, которых там ещё нет (по хэшу). Правила приложения (с меткой) пропускаются.
    {added, skipped}. Порядок `ord` продолжает существующий."""
    known = {r[0] for r in c.execute("SELECT src_hash FROM actions WHERE src_hash IS NOT NULL")}
    ord_ = (c.execute("SELECT COALESCE(MAX(ord), -1) FROM actions").fetchone()[0]) + 1
    added = skipped = 0
    for typ0, (section, flat) in SECTIONS.items():
        if typ0 in ("display", "freeze"):
            continue  # campAssignConfig читается один раз (vend)
        for rule in _items(data, section, flat) or []:
            if not isinstance(rule, dict) or MARK in rule:
                continue
            h = rule_hash(rule)
            if h in known:
                skipped += 1
                continue
            row = _row(rule, _type_of(section, rule))
            c.execute(
                "INSERT INTO actions (name, account, character, type, filter, hotkey, ord, test_run, enabled, raw, src_hash, source) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,'import')",
                (row["name"], row["account"], row["character"], row["type"], "{}", row["hotkey"], ord_,
                 row["test_run"], row["enabled"], json.dumps(rule, ensure_ascii=False), h))
            known.add(h)
            ord_ += 1
            added += 1
    c.commit()
    return {"added": added, "skipped": skipped}


def to_rule(a: sqlite3.Row | dict) -> dict:
    """Правило конфига из строки таблицы: raw + filter поверх, затем поля, которыми управляет таблица."""
    rule = json.loads(a["raw"] or "{}")
    rule.update(json.loads(a["filter"] or "{}"))
    rule["name"] = a["name"]
    if a["hotkey"]:
        rule["hotkey"] = a["hotkey"]
    else:
        rule.pop("hotkey", None)
    rule["testRun"] = bool(a["test_run"])  # явно: по умолчанию мод считает testRun = true
    rule["enabled"] = bool(a["enabled"])
    for flag, key, val in (("checkAccountName", "accountName", a["account"]), ("checkCharacterName", "characterName", a["character"])):
        if val:
            rule[flag], rule[key] = True, val
        else:
            rule.pop(flag, None)
            rule.pop(key, None)
    rule[MARK] = a["id"]
    return rule


def ordered(c: sqlite3.Connection) -> list[sqlite3.Row]:
    """Действия в порядке выполнения: `ord`, затем id; действие с `after_id` не раньше своего предшественника."""
    rows = list(c.execute("SELECT * FROM actions ORDER BY ord, id"))
    by_id = {r["id"]: r for r in rows}
    out: list = []
    done: set[int] = set()

    def put(r, stack=()):
        if r["id"] in done or r["id"] in stack:
            return
        dep = by_id.get(r["after_id"])
        if dep is not None:
            put(dep, stack + (r["id"],))
        done.add(r["id"])
        out.append(r)

    for r in rows:
        put(r)
    return out


def key_conflicts(rows) -> list[str]:
    """Клавиши, занятые несколькими включёнными действиями разных типов (подсказка; допустимо в разных меню)."""
    by: dict[str, set[str]] = {}
    for r in rows:
        if r["enabled"] and r["hotkey"]:
            by.setdefault(str(r["hotkey"]).upper(), set()).add(r["type"])
    return [f"{k}: {', '.join(sorted(v))}" for k, v in sorted(by.items()) if len(v) > 1]


def build_config(c: sqlite3.Connection, data: dict) -> dict:
    """Новый конфиг с правилами из таблицы (данные не пишутся). {data, written, skipped, warnings}.

    Из секций удаляются правила приложения (с меткой) и импортированные (по хэшу); на их место ставятся правила таблицы
    в порядке выполнения. Остальные (ручные) правила остаются. Действия, которым нужен форк мода, пропускаются."""
    new = copy.deepcopy(data)
    rows = ordered(c)
    fork = is_fork(c, data)
    hashes = {r["src_hash"] for r in rows if r["src_hash"]}
    warnings: list[str] = []
    skipped: list[dict] = []
    per: dict[str, list[dict]] = {}
    for a in rows:
        if a["type"] in CHAIN and fork:
            section, mode, base = CHAIN[a["type"]]
            rule = {**copy.deepcopy(base), **to_rule(a), "mode": mode}
            per.setdefault(section, []).append(rule)
            continue
        if a["type"] in FORK_ONLY or a["type"] not in SECTIONS:
            skipped.append({"id": a["id"], "name": a["name"], "reason": "нужен форк мода (действие " + a["type"] + ")"})
            continue
        rule = to_rule(a)
        if not fork and any(isinstance(e, dict) for e in rule.get("legendaryEffects", [])) and a["type"] == "scrap":
            skipped.append({"id": a["id"], "name": a["name"], "reason": "эффекты по звёздам в scrap требуют форк мода"})
            continue
        per.setdefault(SECTIONS[a["type"]][0], []).append(rule)
    written = 0
    for section in {s for s, _ in SECTIONS.values()}:
        flat = next(f for s, f in SECTIONS.values() if s == section)
        items = _items(new, section, flat)
        mine = per.get(section, [])
        if items is None:
            if mine:
                warnings.append(f"В конфиге нет секции {section}: {len(mine)} действий не записано")
                skipped += [{"id": r[MARK], "name": r["name"], "reason": f"нет секции {section}"} for r in mine]
            continue
        pos = next((i for i, r in enumerate(items) if isinstance(r, dict) and (MARK in r or rule_hash(r) in hashes)), len(items))
        keep = [r for r in items if not (isinstance(r, dict) and (MARK in r or rule_hash(r) in hashes))]
        pos = min(pos, len(keep))
        items[:] = keep[:pos] + mine + keep[pos:]
        written += len(mine)
    if fork:
        from . import chainplan
        warnings += chainplan.apply_fork(c, new)
    warnings += ["Клавиша занята разными типами действий — " + k for k in key_conflicts(rows)]
    return {"data": new, "written": written, "skipped": skipped, "warnings": warnings}
