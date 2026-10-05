"""Автоопределение установленной Fallout 76: Steam (Windows, Linux, Flatpak, Proton), Xbox / Microsoft Store, Bethesda.net.

Только читает файловую систему (и реестр на Windows), ничего не пишет. Установка считается найденной, если в папке Data
есть SeventySix.esm. Для каждой находки подбираются папка с ini (Documents/My Games/Fallout 76), конфиг Invent-O-Matic Stash.
"""
from __future__ import annotations

import functools
import os
import re
import string
from pathlib import Path

ESM = "SeventySix.esm"
STEAM_APPID = "1151340"
IOM_FILE = "inventOmaticStashConfig.json"
STORES = {"steam": "Steam", "proton": "Steam (Proton)", "xbox": "Xbox / Microsoft Store", "bethesda": "Bethesda.net"}


def _reg(root: str, sub: str, name: str) -> str:
    """Значение из реестра Windows; пустая строка, если нет ключа или это не Windows."""
    if os.name != "nt":
        return ""
    try:
        import winreg
        with winreg.OpenKey(getattr(winreg, root), sub) as k:
            return str(winreg.QueryValueEx(k, name)[0])
    except OSError:
        return ""


def _is_data(p: Path) -> bool:
    try:
        return (p / ESM).is_file()
    except OSError:
        return False


def _steam_roots() -> list[Path]:
    home = Path.home()
    if os.name == "nt":
        roots = [_reg("HKEY_CURRENT_USER", r"Software\Valve\Steam", "SteamPath"),
                 _reg("HKEY_LOCAL_MACHINE", r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath"),
                 "C:/Program Files (x86)/Steam", "C:/Program Files/Steam"]
    else:
        roots = [home / ".local/share/Steam", home / ".steam/steam", home / ".steam/root", home / ".steam/debian-installation",
                 home / ".var/app/com.valvesoftware.Steam/.local/share/Steam"]
    seen, out = set(), []
    for r in roots:
        if r and (p := Path(r)).is_dir() and (key := p.resolve()) not in seen:
            seen.add(key)
            out.append(p)
    return out


def _steam_libraries() -> list[Path]:
    """Корни библиотек Steam (папки, внутри которых лежит steamapps), включая перечисленные в libraryfolders.vdf."""
    libs: list[Path] = []
    for root in _steam_roots():
        libs.append(root)
        try:
            text = (root / "steamapps" / "libraryfolders.vdf").read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        libs += [Path(m.replace("\\\\", "\\")) for m in re.findall(r'"path"\s+"([^"]+)"', text)]
    seen, out = set(), []
    for lib in libs:
        try:
            key = lib.resolve()
        except OSError:
            continue
        if key not in seen and (lib / "steamapps").is_dir():
            seen.add(key)
            out.append(lib)
    return out


def _documents() -> list[Path]:
    home = Path.home()
    out = []
    if os.name == "nt":
        personal = _reg("HKEY_CURRENT_USER", r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders", "Personal")
        if personal:
            out.append(Path(os.path.expandvars(personal)))
        out += [home / "Documents", home / "OneDrive" / "Documents"]
    else:
        out.append(home / "Documents")
    return out


def _ini_dir(extra: list[Path] = ()) -> str:
    """Папка с Fallout76Prefs.ini / Fallout76Custom.ini: Documents/My Games/Fallout 76 (у Proton — внутри префикса)."""
    for base in [*extra, *_documents()]:
        for sub in ("My Games/Fallout 76", "My Games/Fallout76"):
            if (p := base / sub).is_dir():
                return str(p)
    return ""


def _make(store: str, data: Path, ini_bases: list[Path] = ()) -> dict:
    iom = data / IOM_FILE
    return {"store": store, "label": STORES[store], "game_data": str(data), "ini_dir": _ini_dir(list(ini_bases)),
            "iom_config": str(iom) if iom.is_file() else ""}


@functools.lru_cache(maxsize=1)
def _detect() -> tuple[dict, ...]:
    found: list[dict] = []
    seen: set[str] = set()

    def add(store: str, data: Path, ini_bases: list[Path] = ()) -> None:
        if _is_data(data) and (key := str(data.resolve())) not in seen:
            seen.add(key)
            found.append(_make(store, data, ini_bases))

    for lib in _steam_libraries():
        game = lib / "steamapps" / "common" / "Fallout76"
        proton = lib / "steamapps" / "compatdata" / STEAM_APPID / "pfx" / "drive_c" / "users" / "steamuser" / "Documents"
        if os.name == "nt":
            add("steam", game / "Data")
        else:
            add("proton", game / "Data", [proton])
    # Xbox / Microsoft Store: <диск>:\XboxGames\Fallout 76\Content\Data
    if os.name == "nt":
        for letter in string.ascii_uppercase:
            add("xbox", Path(f"{letter}:/XboxGames/Fallout 76/Content/Data"))
        bethesda = _reg("HKEY_LOCAL_MACHINE", r"SOFTWARE\WOW6432Node\Bethesda Softworks\Fallout76", "Path")
        for root in (bethesda, "C:/Program Files (x86)/Bethesda.net Launcher/games/Fallout76"):
            if root:
                add("bethesda", Path(root) / "Data")
    return tuple(found)


def detect(refresh: bool = False) -> list[dict]:
    """Найденные установки игры: [{store, label, game_data, ini_dir, iom_config}]."""
    if refresh:
        _detect.cache_clear()
    return [dict(c) for c in _detect()]

