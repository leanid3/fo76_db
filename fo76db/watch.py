"""Слежение за файлами выгрузки: при изменении itemsmod.json / LegendaryMods.ini — автоимпорт.
Раз в 6 часов — обновление календаря событий (`events.refresh_if_stale`), раз в 10 минут — уведомления; после импорта инвентаря — сразу проверка нужных роллов.

Опрос mtime раз в несколько секунд: inotify не видит изменения внутри некоторых bind-mount контейнеров.
"""
from __future__ import annotations

import logging
import time

from . import config, db, events, notify
from .importers import inventory

log = logging.getLogger(__name__)

NOTIFY_EVERY = 600  # секунд между проверками уведомлений


def _settle(path, tries: int = 10) -> None:
    """Дождаться, пока мод допишет файл: размер и время изменения не меняются секунду подряд (максимум ~10 с)."""
    def sig():
        st = path.stat()
        return st.st_size, st.st_mtime_ns
    prev = None
    for _ in range(tries):
        try:
            cur = sig()
        except OSError:
            return
        if cur == prev:
            return
        prev = cur
        time.sleep(1)


def _scan(cfg: dict) -> dict[str, float]:
    out = {}
    for kind in ("inventory", "legendary_mods"):
        for p in config.expand(cfg[kind]):
            try:
                out[str(p)] = p.stat().st_mtime
            except OSError:  # файл исчез между проверкой и чтением
                pass
    return out


def run(interval: float = 5.0) -> None:
    # Что было при старте, не импортируем (для этого есть `import`); файлы, появившиеся или
    # ставшие непустыми позже (expand пропускает пустые), — новые выгрузки.
    seen = _scan(config.load())
    last_notify = 0.0
    log.info("Слежу за выгрузками и событиями (Ctrl+C — выход)")
    while True:
        try:
            cfg = config.load()  # пути можно менять в «Настройки → Пути игры» без перезапуска
            if time.time() - last_notify > NOTIFY_EVERY:
                last_notify = time.time()
                try:
                    if (r := events.refresh_if_stale(db.connect())) is not None:
                        log.info("события обновлены%s", f": {'; '.join(r['errors'])}" if r["errors"] else "")
                except Exception as e:
                    log.warning("события: %s", e)
                try:
                    notify.check(db.connect())
                except Exception as e:
                    log.warning("уведомления: %s", e)
            for kind in ("inventory", "legendary_mods"):
                for path in config.expand(cfg[kind]):
                    try:
                        mtime = path.stat().st_mtime
                    except OSError:
                        continue
                    if seen.get(str(path)) == mtime:
                        continue
                    _settle(path)
                    try:
                        seen[str(path)] = path.stat().st_mtime
                    except OSError:
                        continue
                    try:
                        con = db.connect()
                        log.info("изменился %s", path)
                        if kind == "inventory":
                            inventory.import_file(con, path)
                            notify.check_rolls(con)
                        else:
                            inventory.import_legendary_mods(con, path)
                    except Exception as e:
                        log.error("ошибка импорта: %s", e)
        except Exception as e:  # цикл не должен умирать из-за одной ошибки (диск, права, битый конфиг)
            log.error("сбой цикла: %s", e)
        time.sleep(interval)
