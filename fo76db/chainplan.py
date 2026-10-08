"""Данные для форка мода: план цепочки легендарок (inventOmaticPlan.json), годролы и уникальные для защиты, цвета меток.

Форк (docs/mod-fork.md, BUILD.md в репозитории форка) читает план при старте и сам решает по предмету: оставить, передать
назначенному или разобрать. Здесь план только строится из тех же данных, что и советы «Вес» (legscrap.Chain)."""
from __future__ import annotations

import json
import sqlite3

from . import legscrap, rolls
from .db import get_meta, set_meta

FORK_VERSION = 1
PLAN_FILE = "inventOmaticPlan.json"
MARK_KINDS = ("godroll", "unique", "give")
DEFAULT_MARKS = {
    "enabled": True,
    "godroll": {"enabled": True, "color": 0xFFD700, "label": "GOLD"},
    "unique": {"enabled": True, "color": 0x4CAF50, "label": "UNIQUE"},
    "give": {"enabled": True, "color": 0xF44336, "label": ""},
}


def char_key(ch: dict) -> str:
    return f"{ch['account']}/{ch['name']}"


def build_plan(c: sqlite3.Connection) -> dict:
    """{version, characters[{key, account, name, priority}], effects[{names, stars, to}]}; to — назначенный или None."""
    chain = legscrap.Chain(c)
    chars = [{"key": char_key(ch), "account": ch["account"], "name": ch["name"], "priority": ch["priority"]} for ch in chain.chars]
    effects = []
    for (en, stars), cid in sorted(chain.designated.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        effects.append({"names": sorted(chain.local[(en, stars)], key=lambda x: (x != en, x)), "stars": stars,
                        "to": char_key(chain.by_id[cid]) if cid in chain.by_id else None})
    return {"version": 1, "characters": chars, "effects": effects}


def godrolls(c: sqlite3.Connection) -> list[dict]:
    """Годролы для protectionConfig.*.godrolls: шаблоны звёзд 1–3 раскрыты в точные названия эффектов (EN и локальные).
    Пустой список слота — любой эффект."""
    chain = legscrap.Chain(c)
    by_star: dict[int, dict[tuple[str, int], set[str]]] = {1: {}, 2: {}, 3: {}}
    for key, names in chain.local.items():
        if key[1] in by_star:
            by_star[key[1]][key] = names
    out = []
    for r in c.execute("SELECT * FROM protected_items WHERE kind = 'godroll'"):
        slots = []
        for star in (1, 2, 3):
            m = rolls.matcher(r[f"s{star}"])
            if m is None:
                slots.append([])
                continue
            names: list[str] = []
            for (en, _), loc in by_star[star].items():
                ru = next((x for x in loc if x != en), "")
                if any(m({"text": n, "en": en, "ru": ru}) for n in loc):
                    names += [n for n in sorted(loc) if n not in names]
            slots.append(names)
        if r["scope"] in ("any", "weapon", "armor"):
            out.append({"scope": r["scope"], "slots": slots, "name": r["name_en"] or ""})
    return out


def unique_names(c: sqlite3.Connection) -> list[str]:
    seen: dict[str, None] = {}
    for r in c.execute("SELECT name_en, name_ru FROM protected_items WHERE kind = 'unique'"):
        for n in (r["name_en"], r["name_ru"]):
            if n:
                seen.setdefault(n)
    return list(seen)


def fork_on(c: sqlite3.Connection) -> bool:
    return get_meta(c, "fork_enabled") == "1"


def set_fork(c: sqlite3.Connection, on: bool) -> None:
    set_meta(c, "fork_enabled", "1" if on else "0")
    c.commit()


def get_marks(c: sqlite3.Connection) -> dict:
    out = json.loads(json.dumps(DEFAULT_MARKS))
    try:
        saved = json.loads(get_meta(c, "mark_config") or "{}")
    except ValueError:
        saved = {}
    if isinstance(saved.get("enabled"), bool):
        out["enabled"] = saved["enabled"]
    for k in MARK_KINDS:
        s = saved.get(k)
        if isinstance(s, dict):
            out[k].update({f: s[f] for f in ("enabled", "color", "label") if f in s})
    return out


def set_marks(c: sqlite3.Connection, data: dict) -> dict:
    """Проверить и сохранить настройки меток; ValueError с понятным текстом."""
    out = get_marks(c)
    if "enabled" in data:
        out["enabled"] = bool(data["enabled"])
    for k in MARK_KINDS:
        s = data.get(k)
        if not isinstance(s, dict):
            continue
        if "color" in s:
            try:
                col = int(s["color"]) if not isinstance(s["color"], str) else int(s["color"].lstrip("#"), 16)
            except ValueError:
                raise ValueError(f"{k}: цвет должен быть числом или #RRGGBB")
            if not 0 <= col <= 0xFFFFFF:
                raise ValueError(f"{k}: цвет вне диапазона RRGGBB")
            out[k]["color"] = col
        if "enabled" in s:
            out[k]["enabled"] = bool(s["enabled"])
        if "label" in s:
            if len(str(s["label"])) > 20:
                raise ValueError(f"{k}: подпись длиннее 20 символов")
            out[k]["label"] = str(s["label"])
    set_meta(c, "mark_config", json.dumps(out, ensure_ascii=False))
    c.commit()
    return out


def apply_fork(c: sqlite3.Connection, data: dict) -> list[str]:
    """Дописать в конфиг поля форка: modFork, markConfig, godrolls и uniqueNames в защите. Возвращает предупреждения."""
    warns = []
    data["modFork"] = {"name": "fo76db", "version": FORK_VERSION}
    data["markConfig"] = get_marks(c)
    gods, uniq = godrolls(c), unique_names(c)
    prot = data.get("protectionConfig")
    if not isinstance(prot, dict):
        return ["В конфиге нет protectionConfig: годролы и уникальные не записаны"]
    for sec in ("scrapProtection", "transferProtection"):
        s = prot.get(sec)
        if not isinstance(s, dict):
            warns.append(f"В конфиге нет protectionConfig.{sec}: годролы и уникальные не записаны")
            continue
        s["godrolls"] = gods
        s["uniqueNames"] = uniq
        if not s.get("enabled"):
            warns.append(f"protectionConfig.{sec}.enabled выключен — защита годролов и уникальных не будет работать в этой секции")
    return warns


def plan_text(c: sqlite3.Connection) -> str:
    return json.dumps(build_plan(c), ensure_ascii=False, indent="\t") + "\n"


__all__ = ["build_plan", "godrolls", "unique_names", "get_marks", "set_marks", "apply_fork", "plan_text", "fork_on", "set_fork"]
