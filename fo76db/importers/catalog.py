"""Каталог предметов.

Базовый список, EditorID, ключевые слова и названия EN/RU берутся из установленной игры
(SeventySix.esm + Localization.ba2). Вес, цена, эффекты, разбор, крафт и списки добычи
берутся из последнего не-PTS релиза fo76-dumps.
"""
from __future__ import annotations

import json
import re
import sqlite3
from collections import Counter

from ..db import set_meta
from ..sources import dumps
from ..sources.esm import Record, esm_stamp, read_records
from ..sources.strings import load_strings

DUMP_FILES = (
    "tabular.WEAP.csv", "tabular.ARMO.csv", "tabular.ALCH.csv", "tabular.MISC.csv",
    "tabular.COBJ.csv", "tabular.LVLI.csv", "tabular.ENTM.csv",
)
# Где стоит в мире: в разных релизах файл бывает и .csv, и .csv.7z
LOC_FILES = ("tabular.LVLI_LOC.csv", "tabular.WEAP_LOC.csv", "tabular.ARMO_LOC.csv", "tabular.MISC_LOC.csv", "tabular.FLOR_LOC.csv")

UNUSED_RE = re.compile(
    r"(?i)^zz|^cut_|_cut\b|cut$|deprecated|^test|_test|debug|dummy|backup|unused|donotuse|dontuse|^dn_|placeholder|_old$|^nw_"
)


def classify(rec: Record, kw: set[str], name_en: str) -> tuple[str, str | None]:
    s = rec.sig
    if s == "WEAP":
        if "WeaponTypeGrenade" in kw or "ObjectTypeOrdnance" in kw or "UI_WeaponTypeThrown" in kw:
            return "weapon", "explosive"
        if "WeaponTypeMeleeGeneral" in kw or "QuickkeyMelee" in kw or "AnimsUnarmed" in kw:
            return "weapon", "melee"
        return "weapon", "ranged"
    if s == "ARMO":
        if "ArmorTypePower" in kw:
            return "armor", "power_armor"
        if "ObjectTypeUnderarmor" in kw:
            return "apparel", "underarmor"
        if "ObjectTypeArmor" in kw or any(k.startswith("ObjectTypeArmor") for k in kw):
            return "armor", "armor"
        if "HatTypeFasnachtMask" in kw:
            return "apparel", "fasnacht_mask"
        if any(k.startswith(("ClothingTypeHeadwear", "HatType", "ClothingTypeFormalHat")) for k in kw):
            return "apparel", "headwear"
        return "apparel", None
    if s == "ALCH":
        for k, sub in (("MagazineKeyword", "magazine"), ("BobbleheadKeyword", "bobblehead")):
            if k in kw:
                return sub, None
        for k, sub in (("ObjectTypeSerum", "serum"), ("ObjectTypeChem", "chem"),
                       ("ObjectTypeDrink", "drink"), ("ObjectTypeFood", "food")):
            if k in kw:
                return "consumable", sub
        return "consumable", "aid"
    if s == "BOOK":
        low = name_en.lower()
        if low.startswith("recipe"):
            return "recipe", None
        if low.startswith("plan"):
            return "plan", None
        return "book", None
    if s == "OMOD":
        return ("legendary_mod", None) if rec.edid.lower().startswith("mod_legendary") else ("mod", None)
    return {
        "MISC": ("misc", None), "AMMO": ("ammo", None), "NOTE": ("holotape", None),
        "KEYM": ("key", None), "CMPO": ("component", None), "ENTM": ("atom", None),
    }[s]


def _num(s: str, cast=float):
    try:
        return cast(float(s))
    except (TypeError, ValueError):
        return None


CELL_RE = re.compile(r'^(?P<edid>[^\s"\[]+)?\s*(?:"(?P<name>[^"]*)")?\s*\[CELL:[0-9A-Fa-f]{8}\](?:\s*\(in (?P<wedid>\S+) "(?P<world>[^"]*)")?')
TEST_CELL_RE = re.compile(r"(?i)^(76QA|QA|zz|zCUT|cut|test|debug|warehouse|dev|aaa)")


def parse_cell(raw: str) -> tuple[str, str | None] | None:
    """`TheRustyPick01 "The Rusty Pick" [CELL:…] (in APPALACHIA "Appalachia" …)` -> ("The Rusty Pick", "Appalachia").
    Безымянная внешняя ячейка — по EditorID (`POITrainStationBerkeleySpringsExt` -> «Train Station Berkeley Springs»).
    Тестовые и служебные ячейки — None."""
    m = CELL_RE.match(raw.strip())
    if not m or (m["edid"] and TEST_CELL_RE.match(m["edid"])):
        return None
    name = m["name"]
    if not name and m["edid"]:
        e = re.sub(r"\d+$", "", re.sub(r"^(POI|LC\d+|Burn\d*)(?=[A-Z])|(Ext|Int)?\d*$", "", m["edid"]))
        name = re.sub(r"(?<=[a-z])(?=[A-Z0-9])|(?<=[A-Z])(?=[A-Z][a-z])", " ", e).replace("_", " ").strip()
    if not name:
        return None
    return name, m["world"]


def latest_release(releases: list[dict]) -> dict:
    stable = [r for r in releases if not dumps.is_pts(r["version"]) and "tabular.WEAP.csv" in r["assets"]]
    return max(stable, key=lambda r: dumps.version_key(r["version"]))


def _ref_list(raw: str, key: str) -> list[dict]:
    out = []
    for c in dumps.parse_json_list(raw):
        ref = dumps.parse_ref(c.get(key, ""))
        if ref:
            out.append({"formid": ref["formid"], "name": ref["name"] or ref["edid"], "count": _num(c.get("Count"), int)})
    return out


def build(con: sqlite3.Connection, release: dict, log=print) -> None:
    files = {}
    for name in DUMP_FILES:
        log(f"  dumps {release['tag']}: {name}")
        files[name] = dumps.fetch(release, name)

    for name in LOC_FILES:
        log(f"  dumps {release['tag']}: {name}")
        files[name] = dumps.fetch(release, name) or dumps.fetch(release, name + ".7z")

    log("  чтение SeventySix.esm и строк EN/RU")
    recs = read_records()
    en, ru = load_strings("en"), load_strings("ru")
    kw_names = {fid: r.edid for fid, r in recs.items() if r.sig == "KYWD"}

    # Статы из dumps по formid
    stats: dict[int, dict] = {}
    for name in ("tabular.WEAP.csv", "tabular.ARMO.csv", "tabular.ALCH.csv", "tabular.MISC.csv"):
        for row in dumps.read_csv(files[name]):
            fid = int(row["Form ID"], 16)
            st = {"weight": _num(row.get("Weight")), "value": _num(row.get("Value"), int)}
            if row.get("Effects"):
                st["effects"] = [
                    (dumps.parse_ref(e.get("Base Effect", "")) or {}).get("name") or ""
                    for e in dumps.parse_json_list(row["Effects"])
                ]
            if row.get("Components"):
                st["scrap"] = _ref_list(row["Components"], "Component")
            if row.get("Levels"):
                st["levels"] = dumps.parse_json_list(row["Levels"])
            stats[fid] = st
    for row in dumps.read_csv(files["tabular.ENTM.csv"]):
        fid = int(row["Form ID"], 16)
        stats[fid] = {
            "description": row.get("Description", "").replace("\\n", "\n").strip(),
            "store": [r["name"] for r in (dumps.parse_ref(k) for k in dumps.parse_json_list(row.get("Keywords"))) if r and r["name"]],
        }

    log("  рецепты (COBJ)")
    con.execute("DELETE FROM recipes")
    craftable, plans_used = set(), set()
    for row in dumps.read_csv(files["tabular.COBJ.csv"]):
        product = dumps.parse_ref(row["Product"])
        plan = dumps.parse_ref(row["Recipe"])
        con.execute(
            "INSERT OR REPLACE INTO recipes(cobj, edid, product, plan, components) VALUES (?, ?, ?, ?, ?)",
            (int(row["Form ID"], 16), row["Editor ID"], product and product["formid"], plan and plan["formid"],
             json.dumps(_ref_list(row["Components"], "Component"), ensure_ascii=False)),
        )
        if product:
            craftable.add(product["formid"])
        if plan:
            plans_used.add(plan["formid"])

    log("  списки добычи (LVLI)")
    for t in ("lvli_refs", "lvli", "lvli_edges", "placements"):
        con.execute(f"DELETE FROM {t}")
    in_lvli = set()
    for row in dumps.read_csv(files["tabular.LVLI.csv"]):
        lid = int(row["Form ID"], 16)
        con.execute("INSERT OR IGNORE INTO lvli(formid, edid) VALUES (?, ?)", (lid, row["Editor ID"]))
        for e in dumps.parse_json_list(row["Leveled List"]):
            ref = dumps.parse_ref(e.get("Reference", ""))
            if not ref:
                continue
            con.execute("INSERT OR IGNORE INTO lvli_edges(child, parent) VALUES (?, ?)", (ref["formid"], lid))
            if ref["sig"] != "LVLI":
                in_lvli.add(ref["formid"])
                con.execute("INSERT OR IGNORE INTO lvli_refs(formid, lvli) VALUES (?, ?)", (ref["formid"], row["Editor ID"]))

    log("  где стоит в мире (*_LOC)")
    placed: Counter = Counter()
    for name in LOC_FILES:
        if not files.get(name):
            continue
        for row in dumps.read_csv(files[name]):
            cell = parse_cell(row.get("Cell", ""))
            if cell:
                placed[(int(row["Form ID"], 16), *cell)] += 1
    con.executemany("INSERT OR REPLACE INTO placements(formid, cell, world, n) VALUES (?, ?, ?, ?)",
                    [(fid, cell, world, n) for (fid, cell, world), n in placed.items()])

    log("  предметы")
    old = {r[0]: (r[1], r[2]) for r in con.execute("SELECT formid, added_build, removed_build FROM items")}
    con.execute("DELETE FROM items")
    n = 0
    for fid, rec in recs.items():
        if rec.sig == "KYWD" or rec.full is None:
            continue
        name_en, name_ru = en.get(rec.full, ""), ru.get(rec.full, "")
        if not name_en.strip():
            continue
        kw = {kw_names.get(k, "") for k in rec.keywords}
        kind, sub = classify(rec, kw, name_en)
        st = stats.get(fid, {})
        st["craftable"] = fid in craftable
        st["in_lvli"] = fid in in_lvli
        if rec.sig == "BOOK":
            st["teaches"] = fid in plans_used
        status = "unused" if UNUSED_RE.search(rec.edid) or "playerCannotEquip" in kw else "ok"
        added, removed = old.get(fid, (None, None))
        con.execute(
            "INSERT INTO items(formid, sig, edid, name_en, name_ru, kind, subkind, weight, value, keywords, stats, status, added_build, removed_build)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (fid, rec.sig, rec.edid, name_en, name_ru or None, kind, sub, st.pop("weight", None), st.pop("value", None),
             " ".join(sorted(k for k in kw if k)), json.dumps(st, ensure_ascii=False), status, added, removed),
        )
        n += 1
    set_meta(con, "catalog_release", release["tag"])
    set_meta(con, "catalog_esm", esm_stamp())
    con.commit()
    log(f"  готово: {n} предметов")
