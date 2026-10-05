"""Легендарные эффекты предмета по звёздам: для поиска «★1 = Bloodied, ★3 = …».

В выгрузке Invent-O-Matic эффекты лежат одной строкой через « / » в порядке звёзд. Перед ними может стоять блок
«SET BONUS» (сетовые бонусы брони), после них — встроенные свойства оружия («+65% Damage to Scorched», проклятые
эффекты и т. п.). Поэтому берём первые `stars` частей после сетового блока; в части бывает несколько строк, эффект
звезды — первая.

Название эффекта (Bloodied / Кровожадный) находим по описанию из LegendaryMods.ini (`known_legendary_mods`). У
описаний вида «… Currently +2» хвост с текущим значением отбрасывается.
"""
from __future__ import annotations

import json
import re
import sqlite3

TAIL_RE = re.compile(r"\s*currently\b.*$|[\s§½¹²³]+$", re.I | re.S)


def _norm(s: str) -> str:
    s = s.strip().split("\n")[0].lower()
    return re.sub(r"\s+", " ", TAIL_RE.sub("", s)).strip(" .")


def names(c: sqlite3.Connection) -> dict[tuple[str, int], dict]:
    """{(нормализованное описание, звёзды): {en, ru}}."""
    ru: dict[str, str] = {}
    for en, r in c.execute("SELECT name_en, name_ru FROM items WHERE kind = 'legendary_mod' AND name_ru IS NOT NULL ORDER BY formid"):
        ru.setdefault(en, r)
    out: dict[tuple[str, int], dict] = {}
    for name, st, desc in c.execute("SELECT DISTINCT name, stars, description FROM known_legendary_mods WHERE name_local IS NULL"):
        for d in json.loads(desc or "{}").values():
            if d:
                out.setdefault((_norm(d), st), {"en": name, "ru": ru.get(name)})
    return out


def slots(legendary: str | None, stars: int, lookup: dict) -> tuple[list[dict], str]:
    """([{star, text, en, ru}] — по записи на звезду, остальное: сетовый бонус и встроенные свойства)."""
    if not legendary or not stars:
        return [], legendary or ""
    parts = legendary.split(" / ")
    extra = [p for p in parts if p.startswith("SET BONUS")]
    parts = [p for p in parts if not p.startswith("SET BONUS")]
    out = []
    for i, p in enumerate(parts[:stars], 1):
        text, *rest = p.strip().split("\n")
        n = lookup.get((_norm(text), i)) or {}
        out.append({"star": i, "text": text, "en": n.get("en"), "ru": n.get("ru")})
        extra += rest
    extra += parts[stars:]
    return out, "\n".join(x.strip() for x in extra if x.strip())


def catalog(c: sqlite3.Connection) -> dict[int, list[dict]]:
    """Все известные легендарные эффекты по звёздам: {звезда: [{en, ru, desc}]} — подсказки для полей поиска."""
    ru: dict[str, str] = {}
    for en, r in c.execute("SELECT name_en, name_ru FROM items WHERE kind = 'legendary_mod' AND name_ru IS NOT NULL ORDER BY formid"):
        ru.setdefault(en, r)
    out: dict[int, dict[str, dict]] = {1: {}, 2: {}, 3: {}, 4: {}}
    for name, st, desc in c.execute(
            "SELECT DISTINCT name, stars, description FROM known_legendary_mods WHERE name_local IS NULL ORDER BY name"):
        if st in out:
            d = json.loads(desc or "{}")
            out[st].setdefault(name, {"en": name, "ru": ru.get(name), "desc": " | ".join(dict.fromkeys(v for v in d.values() if v))})
    return {k: list(v.values()) for k, v in out.items()}
