"""Конфиг Invent-O-Matic Stash: чтение, проверка и безопасная запись.

Единственное место, где утилита пишет в файлы игры. Файл — жёсткая ссылка (modconfig/ ↔ Data/), поэтому:
- запись только поверх существующего inode (open "r+" + truncate), без переименований и пересоздания;
- перед записью — копия в <backup_root>/_backup_<ГГГГММДД>/;
- если файл изменился с момента открытия в редакторе — отказ (sha1);
- после записи проверяется, что ссылок на файл столько же, сколько было.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
from pathlib import Path

from . import config

BACKUP_PREFIX = "inventOmaticStashConfig."


class IomError(Exception):
    pass


def _paths(path: str | Path | None = None, backup_root: str | Path | None = None) -> tuple[Path, Path]:
    cfg = config.load()
    return Path(path or cfg["iom_config"]), Path(backup_root or cfg["backup_root"])


def _sha1(raw: bytes) -> str:
    return hashlib.sha1(raw).hexdigest()


def _indent(text: str) -> str:
    """Отступ оригинала: табуляция или N пробелов (по первой строке с отступом)."""
    for line in text.splitlines()[1:]:
        stripped = line.lstrip()
        if stripped and line != stripped:
            pad = line[: len(line) - len(stripped)]
            return "\t" if pad.startswith("\t") else " " * len(pad)
    return "\t"


def dumps(data, indent: str = "\t") -> str:
    return json.dumps(data, indent=indent, ensure_ascii=False) + "\n"


def load(path=None) -> dict:
    p, _ = _paths(path)
    raw = p.read_bytes()
    text = raw.decode("utf-8-sig")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        # Дефолтный конфиг мода содержит комментарии // — такой файл редактор не перепишет без потерь
        raise IomError(f"{p}: не строгий JSON ({e}). Скорее всего, в файле комментарии — редактор не может сохранить его без потерь.")
    indent = _indent(text)
    return {
        "path": str(p), "data": data, "sha1": _sha1(raw), "mtime": p.stat().st_mtime, "links": p.stat().st_nlink,
        # совпадёт ли файл байт-в-байт после сохранения без изменений (иначе изменится только форматирование)
        "exact": dumps(data, indent) == text, "indent": indent,
    }


def validate(data) -> list[dict]:
    """Проблемы конфига: [{level: error|warn|info, path, message}]."""
    out: list[dict] = []

    def add(level, path, msg):
        out.append({"level": level, "path": path, "message": msg})

    if not isinstance(data, dict):
        add("error", "", "Корень конфига должен быть объектом")
        return out
    ex = data.get("extractConfig")
    if isinstance(ex, dict):
        if not ex.get("enabled"):
            add("warn", "extractConfig.enabled", "Выгрузка (Extract) выключена — fo76db не получит инвентарь")
        if ex.get("useCustomFormat"):
            add("error", "extractConfig.useCustomFormat", "Свой формат выгрузки (CSV) — fo76db читает только стандартный JSON")
    hotkeys: dict[str, list[str]] = {}

    def rules(section, items):
        for i, r in enumerate(items):
            if not isinstance(r, dict):
                continue
            where = f"{section}[{i}]"
            name = r.get("name") or where
            if r.get("enabled") and r.get("hotkey") and r.get("showButton", True) is not None:
                hotkeys.setdefault(str(r["hotkey"]).upper(), []).append(f"{section}: {name}")
            if r.get("enabled") and r.get("matchMode") == "ALL" and section in ("npcSellConfig", "scrapConfig") and not r.get("types"):
                add("error", where, f"«{name}»: matchMode ALL без types — правило затронет все предметы")
            names = r.get("itemNames")
            if isinstance(names, list) and len(names) != len(set(map(str, names))):
                add("warn", where + ".itemNames", f"«{name}»: в itemNames есть повторы")
            for k in ("types", "itemNames", "excluded", "legendaryEffects", "transferLegendaries", "scrapByLegendaryStar", "armorGrades"):
                if k in r and not isinstance(r[k], list):
                    add("error", f"{where}.{k}", f"«{name}»: {k} должен быть списком")
            for k in ("amount", "delay", "maxItems", "maxPrice", "price"):
                if k in r and not isinstance(r[k], (int, float)):
                    add("error", f"{where}.{k}", f"«{name}»: {k} должен быть числом")

    tc = data.get("transferConfig")
    if isinstance(tc, list):
        rules("transferConfig", tc)
        seen: dict[tuple, str] = {}
        for i, r in enumerate(tc):
            if isinstance(r, dict) and r.get("enabled"):
                # одинаковые по сути правила: всё, кроме названия, клавиши и служебных флагов
                key = json.dumps({k: v for k, v in r.items() if k not in ("name", "hotkey", "enabled", "debug", "showButton", "testRun")},
                                 sort_keys=True, ensure_ascii=False)
                if key in seen:
                    add("warn", f"transferConfig[{i}]", f"«{r.get('name')}» повторяет «{seen[key]}»")
                seen[key] = r.get("name") or str(i)
    for sec in ("npcSellConfig", "buyConfig", "lootConfig", "scrapConfig"):
        s = data.get(sec)
        if not isinstance(s, dict):
            continue
        if isinstance(s.get("configs"), list):
            rules(sec, s["configs"])
        if s.get("enabled") and sec in ("npcSellConfig", "scrapConfig", "buyConfig") and s.get("testRun") is False:
            live = [c for c in s.get("configs") or [] if isinstance(c, dict) and c.get("enabled") and not c.get("testRun")]
            if live:
                add("info", sec, f"{sec}: {len(live)} правил работают по-настоящему (testRun выключен) — проверьте их перед игрой")
    camp = data.get("campAssignConfig")
    if isinstance(camp, dict) and isinstance(camp.get("configs"), list):
        rules("campAssignConfig", camp["configs"])
    for key, users in hotkeys.items():
        if len(users) > 1:
            add("info", "hotkey", f"Клавиша {key} назначена нескольким включённым правилам: " + "; ".join(users)
                + " (допустимо, если правила работают в разных меню)")
    return out


def _backup(p: Path, raw: bytes, backup_root: Path) -> Path:
    now = dt.datetime.now()
    d = backup_root / f"_backup_{now:%Y%m%d}"
    d.mkdir(parents=True, exist_ok=True)
    out = d / f"{BACKUP_PREFIX}{now:%H%M%S}.json"
    n = 1
    while out.exists():
        out = d / f"{BACKUP_PREFIX}{now:%H%M%S}-{n}.json"
        n += 1
    with open(out, "wb") as f:
        f.write(raw)
        f.flush()
        os.fsync(f.fileno())
    return out


def _write_in_place(p: Path, text: str, links_before: int, original: bytes | None = None) -> None:
    """Запись поверх файла (inode и жёсткие ссылки сохраняются). Сбой посреди записи — вернуть исходное содержимое:
    запись неатомарна, и обрыв оставил бы в конфиге игры половину файла."""
    ino = p.stat().st_ino
    try:
        with open(p, "r+", encoding="utf-8", newline="") as f:
            f.write(text)
            f.truncate()
            f.flush()
            os.fsync(f.fileno())
    except BaseException:
        if original is not None:
            with open(p, "r+b") as f:
                f.write(original)
                f.truncate()
                f.flush()
                os.fsync(f.fileno())
        raise
    st = p.stat()
    if st.st_ino != ino or st.st_nlink < links_before:
        raise IomError(f"После записи у {p} изменился inode или число ссылок ({links_before} → {st.st_nlink}). Проверьте modconfig/ и Data/!")


def save(data, expected_sha1: str, path=None, backup_root=None) -> dict:
    p, root = _paths(path, backup_root)
    problems = [x for x in validate(data) if x["level"] == "error"]
    if problems:
        raise IomError("Ошибки в конфиге: " + "; ".join(x["message"] for x in problems))
    raw = p.read_bytes()
    if _sha1(raw) != expected_sha1:
        raise IomError("Файл изменился после открытия в редакторе (игра, другой редактор или вторая вкладка). Откройте его заново.")
    links = p.stat().st_nlink
    text = dumps(data, _indent(raw.decode("utf-8-sig")))
    if text.encode() == raw:
        return {"ok": True, "changed": False, "sha1": expected_sha1}
    backup = _backup(p, raw, root)
    _write_in_place(p, text, links, raw)
    return {"ok": True, "changed": True, "backup": str(backup), "sha1": _sha1(p.read_bytes()), "links": p.stat().st_nlink}


def backups(path=None, backup_root=None) -> list[Path]:
    _, root = _paths(path, backup_root)
    return sorted(root.glob(f"_backup_*/{BACKUP_PREFIX}*.json"), key=lambda x: x.stat().st_mtime, reverse=True)


def restore_latest(expected_sha1: str, path=None, backup_root=None, backup: str | None = None) -> dict:
    """Вернуть бэкап: последний или выбранный (`backup` — путь из списка `backups()`; чужие пути не принимаются).
    Текущая версия перед этим тоже сохраняется в бэкап."""
    p, root = _paths(path, backup_root)
    found = backups(path, backup_root)
    if not found:
        raise IomError("Бэкапов конфига нет")
    if backup is None:
        src = found[0]
    else:
        src = next((b for b in found if str(b) == backup), None)
        if src is None:
            raise IomError("Такого бэкапа нет в списке")
    raw = p.read_bytes()
    if _sha1(raw) != expected_sha1:
        raise IomError("Файл изменился после открытия в редакторе. Откройте его заново.")
    text = src.read_bytes().decode("utf-8-sig")
    json.loads(text)  # бэкап должен быть корректным JSON
    links = p.stat().st_nlink
    backup = _backup(p, raw, root)
    _write_in_place(p, text, links, raw)
    return {"ok": True, "restored": str(src), "backup": str(backup), "sha1": _sha1(p.read_bytes())}
