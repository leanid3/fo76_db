"""История предметов: в какой версии игры FormID появился и (если так) исчез.

Для каждой стабильной версии игры берётся `tabular.IDs.csv.7z` из fo76-dumps. Из него сохраняется
только список FormID предметных типов (`data/cache/history/<версия>.txt.gz`), архив после этого удаляется.
Первый релиз dumps — 1.0.5.10 (январь 2019), всё, что было в нём, помечается как «≤ 1.0.5.10».
"""
from __future__ import annotations

import csv
import gzip
import sqlite3
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from ..db import DATA, set_meta
from ..sources import dumps
from ..sources.esm import ITEM_TYPES
from ..sources.wiki_patches import fetch_patches

HISTORY = DATA / "cache" / "history"
SIGS = set(ITEM_TYPES)


def stable_versions(releases: list[dict]) -> list[dict]:
    """По одной (самой свежей по версии скрипта) записи на каждую стабильную версию игры."""
    best: dict[str, dict] = {}
    for r in releases:
        if dumps.is_pts(r["version"]) or "tabular.IDs.csv.7z" not in r["assets"]:
            continue
        cur = best.get(r["version"])
        if cur is None or r["date"] > cur["date"]:
            best[r["version"]] = r
    return sorted(best.values(), key=lambda r: dumps.version_key(r["version"]))


def _extract_ids(release: dict) -> Path:
    out = HISTORY / f"{release['version']}.txt.gz"
    if out.exists():
        return out
    archive = dumps.fetch(release, "tabular.IDs.csv.7z")
    proc = subprocess.Popen([dumps.sevenzip(), "e", "-so", str(archive)], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            text=True, encoding="utf-8", errors="replace")
    reader = csv.reader(proc.stdout, skipinitialspace=True)
    header = next(reader)
    i_sig, i_fid = header.index("Signature"), header.index("Form ID")
    ids = set()
    for row in reader:
        if len(row) > i_fid and row[i_sig] in SIGS:
            ids.add(row[i_fid].lower())
    proc.wait()
    if proc.returncode != 0 or not ids:
        raise RuntimeError(f"{release['tag']}: не удалось прочитать IDs.csv (код {proc.returncode})")
    tmp = out.with_suffix(".part")
    with gzip.open(tmp, "wt") as f:
        f.write("\n".join(sorted(ids)))
    tmp.rename(out)
    archive.unlink()
    return out


def _load(path: Path) -> set[int]:
    with gzip.open(path, "rt") as f:
        return {int(x, 16) for x in f.read().split()}


def wiki_label(version: str, patches: list[dict]) -> dict | None:
    """Патч вики, к которому относится сборка.

    Контент попадает в файлы игры раньше официального выхода обновления, поэтому внутри ветки версий
    (первые три числа, например 1.7.25) берётся ближайший патч с версией не ниже сборки, а если такого нет —
    последний патч ветки. Без патчей в ветке — ближайший патч с меньшей версией.
    """
    key = dumps.version_key(version)
    branch = version.rsplit(".", 1)[0]
    known = []
    for p in patches:
        try:
            known.append((dumps.version_key(p["version"]), p))
        except ValueError:
            continue
    same = sorted(((k, p) for k, p in known if p["version"].rsplit(".", 1)[0] == branch), key=lambda x: x[0])
    if same:
        later = [x for x in same if x[0] >= key]
        return (later[0] if later else same[-1])[1]
    earlier = [x for x in known if x[0] <= key]
    return max(earlier, key=lambda x: x[0])[1] if earlier else None


def _patches(log) -> list[dict]:
    try:
        return fetch_patches()
    except Exception as e:  # вики недоступна — история без названий обновлений
        log(f"  вики недоступна ({e}), названия обновлений не будут заполнены")
        return []


def _label(con: sqlite3.Connection, tag: str, version: str, date: str, patches: list[dict]) -> None:
    p = wiki_label(version, patches) or {}
    upd = p.get("update") if p.get("update") != "-" else None
    name = " · ".join(x for x in (p.get("cycle"), upd) if x) or None
    con.execute(
        "INSERT INTO builds(tag, version, vkey, date, is_pts, update_name, released, processed) VALUES (?, ?, ?, ?, 0, ?, ?, 1)"
        " ON CONFLICT(tag) DO UPDATE SET update_name = excluded.update_name, released = excluded.released, processed = 1",
        (tag, version, dumps.version_key(version), date, name, p.get("date")),
    )


FIRST_BUILD_NAME = "Базовая игра (запуск — январь 2019)"


def _label_first(con: sqlite3.Connection) -> None:
    """В первую сборку dumps попало всё, что вышло до неё: это не «Update 5», а базовая игра."""
    con.execute("UPDATE builds SET update_name = ? WHERE vkey = (SELECT min(vkey) FROM builds)", (FIRST_BUILD_NAME,))


def relabel(con: sqlite3.Connection, log=print) -> None:
    """Переназначить названия обновлений уже известным сборкам (без обращения к GitHub)."""
    patches = _patches(log)
    for r in con.execute("SELECT tag, version, date FROM builds").fetchall():
        _label(con, r["tag"], r["version"], r["date"], patches)
    _label_first(con)
    con.commit()
    log(f"  названия обновлений обновлены по {len(patches)} патчам вики")


def build(con: sqlite3.Connection, workers: int = 4, log=print) -> None:
    HISTORY.mkdir(parents=True, exist_ok=True)
    releases = stable_versions(dumps.list_releases())
    patches = _patches(log)

    todo = [r for r in releases if not (HISTORY / f"{r['version']}.txt.gz").exists()]
    log(f"  версий: {len(releases)}, нужно обработать: {len(todo)}")
    with ThreadPoolExecutor(workers) as pool:
        for i, path in enumerate(pool.map(_extract_ids, todo), 1):
            log(f"  [{i}/{len(todo)}] {path.name}")

    for r in releases:
        _label(con, r["tag"], r["version"], r["date"], patches)
    _label_first(con)

    first: dict[int, str] = {}
    last: dict[int, str] = {}
    for r in releases:
        for fid in _load(HISTORY / f"{r['version']}.txt.gz"):
            first.setdefault(fid, r["tag"])
            last[fid] = r["tag"]

    latest = releases[-1]["tag"]
    next_tag = {a["tag"]: b["tag"] for a, b in zip(releases, releases[1:])}
    rows = []
    for (fid,) in con.execute("SELECT formid FROM items").fetchall():
        added = first.get(fid)
        lt = last.get(fid)
        removed = next_tag.get(lt) if lt and lt != latest else None
        rows.append((added, removed, fid))
    con.executemany("UPDATE items SET added_build = ?, removed_build = ? WHERE formid = ?", rows)
    set_meta(con, "history_first", releases[0]["tag"])
    set_meta(con, "history_latest", latest)
    con.commit()
    log(f"  готово: {sum(1 for r in rows if r[0])} предметов с версией появления")
