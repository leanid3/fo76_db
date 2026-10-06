"""Фоновые задачи из веб-интерфейса: каталог, история, события, импорт — то же, что команды CLI.

Нужны там, где командной строки нет или она неудобна: десктоп-версия, PWA на телефоне, exe двойным кликом.
Одновременно идёт одна задача (все пишут в одну базу). Журнал последних строк хранится в памяти процесса.
"""
from __future__ import annotations

import logging
import collections
import datetime as dt
import threading

from . import config, db

TITLES = {
    "catalog": "Каталог: игра + последний релиз fo76-dumps (~1 мин)",
    "history": "История: «добавлено в обновлении» по всем версиям (первый раз ~15 мин и ~1 ГБ)",
    "events": "События, Минерва, сезоны",
    "steam": "Steam: Update Notes, онлайн, сборка игры",
    "import": "Импорт выгрузок инвентаря и легендарных модов",
}

logger = logging.getLogger(__name__)
_lock = threading.Lock()
_state: dict[str, dict] = {name: {"status": "idle", "started": None, "finished": None, "error": None,
                                  "log": collections.deque(maxlen=200)} for name in TITLES}


def _catalog(log) -> None:
    from .importers import catalog
    from .sources import dumps
    rel = catalog.latest_release(dumps.list_releases())
    log(f"Каталог из релиза {rel['tag']}")
    catalog.build(db.connect(), rel, log=log)


def _history(log) -> None:
    from .importers import history
    history.build(db.connect(), log=log)


def _events(log) -> None:
    from . import events
    r = events.refresh(db.connect())
    log(f"Календарь: {r.get('calendar', 0)}, схем Минервы: {r.get('minerva_plans', 0)}, сезонов: {r.get('seasons', 0)}"
        + (f"; ошибки: {'; '.join(r['errors'])}" if r.get("errors") else ""))


def _steam(log) -> None:
    from . import steam
    r = steam.refresh(db.connect())
    log(f"Новостей: {r.get('total', '—')}, новых патчей: {r.get('new_patches', '—')}, онлайн: {r.get('online', '—')}, сборка: {r.get('build') or '—'}"
        + (f"; ошибки: {'; '.join(r['errors'])}" if r["errors"] else ""))


def _import(log) -> None:
    from . import notify
    from .importers import inventory
    cfg = config.load()
    con = db.connect()
    found = False
    for path in config.expand(cfg["inventory"]):
        found = True
        log(f"Инвентарь: {path}")
        inventory.import_file(con, path)
    for path in config.expand(cfg["legendary_mods"]):
        found = True
        log(f"Легендарные моды: {path}")
        inventory.import_legendary_mods(con, path)
    if not found:
        log("Выгрузок не найдено: проверьте game_data и пути inventory / legendary_mods в config.toml")
    notify.check_rolls(con)


RUN = {"catalog": _catalog, "history": _history, "events": _events, "steam": _steam, "import": _import}


def _now() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def start(name: str) -> bool:
    """Запустить задачу в фоне. False — уже идёт какая-то задача."""
    with _lock:
        if any(s["status"] == "running" for s in _state.values()):
            return False
        st = _state[name]
        st.update(status="running", started=_now(), finished=None, error=None)
        st["log"].clear()

    def log(msg: str) -> None:
        logger.info("%s", msg.strip())
        st["log"].append(f"{dt.datetime.now():%H:%M:%S} {msg.strip()}")

    def work() -> None:
        try:
            RUN[name](log)
            st["status"] = "done"
            log("Готово")
        except Exception as e:  # noqa: BLE001 — показать в интерфейсе любую ошибку
            st.update(status="error", error=f"{type(e).__name__}: {e}")
            log(f"Ошибка: {e}")
        finally:
            st["finished"] = _now()

    threading.Thread(target=work, name=f"fo76db-{name}", daemon=True).start()
    return True


def status() -> dict:
    con = db.connect()
    data = {
        "items": con.execute("SELECT COUNT(*) FROM items").fetchone()[0],
        "builds": con.execute("SELECT COUNT(*) FROM builds WHERE processed = 1").fetchone()[0],
        "catalog_release": db.get_meta(con, "catalog_release"),
        "events_fetched": db.get_meta(con, "events_fetched"),
        "steam_fetched": db.get_meta(con, "steam_fetched"),
        "snapshots": con.execute("SELECT COUNT(*) FROM inv_snapshots").fetchone()[0],
        "game_data": str(config.game_data()),
        "game_found": (config.game_data() / "SeventySix.esm").is_file(),
        "home": str(db.ROOT),
    }
    tasks = {name: {k: (list(v) if k == "log" else v) for k, v in st.items()} | {"title": TITLES[name]}
             for name, st in _state.items()}
    return {"tasks": tasks, "data": data}
