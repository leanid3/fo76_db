"""Обслуживание: копия базы, проверка окружения (`fo76db backup`, `fo76db doctor`, «Настройки → Диагностика»)."""
from __future__ import annotations

import datetime as dt
import os
import shutil
import sqlite3
import sys
from pathlib import Path

from . import __version__, config, db, gamepaths

BACKUP_DIR = db.DATA / "db-backups"
PREFIX = "fo76-"


def backup(dest: Path | str | None = None, keep: int = 10) -> Path:
    """Согласованная копия базы через API бэкапа SQLite (база в режиме WAL — обычное копирование файла не годится).
    В папке остаётся не больше `keep` копий, созданных этой функцией (чужие файлы не трогаются); keep=0 — не удалять."""
    folder = Path(dest) if dest else BACKUP_DIR
    folder.mkdir(parents=True, exist_ok=True)
    out = folder / f"{PREFIX}{dt.datetime.now():%Y%m%d-%H%M%S}.sqlite"
    src = db.connect()
    try:
        tmp = out.with_suffix(".sqlite.part")
        dst = sqlite3.connect(tmp)
        try:
            src.backup(dst)
        finally:
            dst.close()
        os.replace(tmp, out)
    finally:
        src.close()
    if keep > 0:
        old = sorted(folder.glob(f"{PREFIX}*.sqlite"), key=lambda p: p.stat().st_mtime, reverse=True)[keep:]
        for p in old:
            p.unlink(missing_ok=True)
    return out


def health() -> dict:
    """Для /healthz: база отвечает, версия приложения и каталога."""
    con = db.connect()
    try:
        con.execute("SELECT 1").fetchone()
        return {"ok": True, "version": __version__, "items": con.execute("SELECT COUNT(*) FROM items").fetchone()[0],
                "catalog_release": db.get_meta(con, "catalog_release"), "events_fetched": db.get_meta(con, "events_fetched")}
    finally:
        con.close()


def _row(name: str, ok: bool | None, detail: str, hint: str = "") -> dict:
    """ok: True — хорошо, False — проблема, None — предупреждение/к сведению."""
    return {"name": name, "ok": ok, "detail": detail, "hint": hint}


def doctor() -> list[dict]:
    """Проверки окружения: что нужно утилите и чего не хватает. Ничего не меняет."""
    from . import mods
    from .sources import dumps

    cfg = config.load()
    out = [_row("Версия", True, f"fo76db {__version__}, Python {sys.version.split()[0]}, данные: {db.ROOT}")]

    try:
        h = health()
        out.append(_row("База данных", True, f"{db.DB_PATH} · предметов: {h['items']}"))
        if not h["items"]:
            out.append(_row("Каталог", False, "каталог пуст", "Главная → «Каталог» (или `fo76db catalog`)"))
        else:
            out.append(_row("Каталог", True, f"релиз fo76-dumps: {h['catalog_release'] or '—'}"))
        out.append(_row("События", True if h["events_fetched"] else None, f"обновлены: {h['events_fetched'] or 'ещё не загружались'}",
                        "" if h["events_fetched"] else "Главная → «События»"))
    except Exception as e:  # noqa: BLE001 — диагностика не должна падать
        out.append(_row("База данных", False, f"{type(e).__name__}: {e}", "проверьте права на папку data/"))

    gd = Path(cfg["game_data"])
    out.append(_row("Папка Data игры", gd.is_dir(), str(gd),
                    "" if gd.is_dir() else "Настройки → Пути игры (автоопределение или «Обзор…»)"))
    esm = gd / gamepaths.ESM
    out.append(_row(gamepaths.ESM, esm.is_file(), str(esm) if esm.is_file() else "не найден — каталог игры не прочитать",
                    "" if esm.is_file() else "укажите папку Data, где лежит SeventySix.esm"))
    for m in mods.status():
        state = m["state"]
        out.append(_row(f"Мод: {m['name']}", {"ok": True, "empty": None}.get(state, False),
                        {"ok": "файл найден", "empty": "файл пуст — мод ещё ничего не выгрузил"}.get(state, "файл не найден"),
                        "" if state != "missing" else "Настройки → Моды → «Проверить / найти»"))

    try:
        out.append(_row("7-Zip", True, dumps.sevenzip()))
    except RuntimeError as e:
        out.append(_row("7-Zip", False, "не найден", str(e)))

    for key, label in (("backup_root", "Папка бэкапов IOM"), ("iom_config", "Конфиг IOM")):
        p = Path(cfg[key])
        out.append(_row(label, True if p.exists() else None, str(p) + ("" if p.exists() else " — пока нет")))

    from .sources import steam as steam_src
    try:
        out.append(_row("Steam API", True, f"api.steampowered.com отвечает, онлайн сейчас: {steam_src.fetch_players()}"))
    except Exception as e:  # noqa: BLE001
        out.append(_row("Steam API", None, f"не отвечает: {e}", "Update Notes и график онлайна не обновятся"))

    host, token = cfg["host"], cfg.get("token")
    if host not in config.LOOPBACK_HOSTS:
        out.append(_row("Доступ из сети", True if token else False, f"сервер слушает {host}" + (", токен задан" if token else ", токена НЕТ"),
                        "" if token else "задайте token в config.toml или FO76DB_TOKEN"))
    try:
        total, used, free = shutil.disk_usage(db.DATA)
        out.append(_row("Место на диске", True if free > 2 << 30 else None, f"свободно {free / 1e9:.1f} ГБ в {db.DATA}",
                        "" if free > 2 << 30 else "для истории версий нужно около 1 ГБ"))
    except OSError:
        pass
    return out
