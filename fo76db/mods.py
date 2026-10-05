"""Проверка установленных модов по их файлам (выгрузки и конфиги). Только читает файловую систему."""
from __future__ import annotations

import glob
from pathlib import Path

from . import config, gamepaths

# id → (название, ключ настройки с путями, файл в папке Data для поиска в других установках, страницы, которым мод нужен)
MODS = {
    "extractor": ("Invent-O-Matic Extractor", "inventory", "itemsmod.ini",
                  ("/inventory", "/optimize", "/rolls", "/plans", "/legendary")),
    "workbench": ("Improved Workbench (LegendaryMods.ini)", "legendary_mods", "LegendaryMods.ini", ("/legendary",)),
    "stash": ("Invent-O-Matic Stash (конфиг)", "iom_config", gamepaths.IOM_FILE, ("/iom",)),
}


def _files(patterns: list[str]) -> list[Path]:
    out: list[Path] = []
    for p in patterns:
        out += [Path(m) for m in (sorted(glob.glob(p)) if any(ch in p for ch in "*?[") else [p])]
    return [p for p in out if p.is_file()]


def check(mod_id: str, cfg: dict | None = None) -> dict:
    """{id, name, state: ok|empty|missing, files, pages}: empty — файл есть, но мод ещё ничего в него не выгрузил."""
    cfg = cfg or config.load()
    name, key, _, pages = MODS[mod_id]
    val = cfg[key]
    files = _files(val if isinstance(val, list) else [val])
    state = "missing" if not files else "ok" if any(f.stat().st_size > 0 for f in files) else "empty"
    return {"id": mod_id, "name": name, "state": state, "files": [str(f) for f in files], "pages": list(pages)}


def status(refresh: bool = False) -> list[dict]:
    """Состояние всех модов. refresh — заново определить установки игры и подсказать, где найденные моды лежат."""
    cfg = config.load()
    installs = gamepaths.detect(refresh)
    out = []
    for mod_id, (_, _, fname, _) in MODS.items():
        r = check(mod_id, cfg)
        if r["state"] == "missing":
            r["found_in"] = [c["game_data"] for c in installs if (Path(c["game_data"]) / fname).is_file()
                             and c["game_data"] != cfg["game_data"]]
        out.append(r)
    return out


def missing_for(page: str) -> list[dict]:
    """Моды, нужные странице, которых нет (файла нет вовсе). Пустой файл — мод есть, данных пока нет: не предупреждаем."""
    cfg = config.load()
    return [r for m in MODS if page in (r := check(m, cfg))["pages"] and r["state"] == "missing"]
