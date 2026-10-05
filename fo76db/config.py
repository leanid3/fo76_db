"""Настройки: config.toml в корне репозитория (если нет — значения по умолчанию)."""
from __future__ import annotations

import copy
import glob
import json
import logging
import os
import tempfile
import tomllib
from pathlib import Path

from . import gamepaths
from .db import DATA, ROOT

CONFIG = ROOT / "config.toml"
log = logging.getLogger(__name__)

PATH_KEYS = ("game_data", "ini_dir", "iom_config", "backup_root", "mods_dir")
NETWORK_FILE = DATA / "network.json"  # режим доступа из «Настройки → Доступ по сети»; перекрывает host/token из config.toml
PATHS_FILE = DATA / "paths.json"  # пути, заданные в «Настройки → Пути игры»; перекрывают config.toml

DEFAULTS = {
    # Пути игры. Пустое значение — определить автоматически (Steam, Proton, Xbox, Bethesda.net), см. gamepaths.py.
    # Меняются в «Настройки → Пути игры» (хранятся в data/paths.json) или здесь. FO76DB_GAME_DATA перекрывает game_data.
    "game_data": "",     # папка Data: SeventySix.esm, Localization.ba2, выгрузки модов
    "ini_dir": "",       # Documents/My Games/Fallout 76 (Fallout76Prefs.ini, Fallout76Custom.ini)
    "mods_dir": "",      # папка модов; пока не используется
    # Конфиг Invent-O-Matic Stash для редактора правил. Это жёсткая ссылка на Data/inventOmaticStashConfig.json:
    # пишется только с сохранением inode, перед записью — копия в <backup_root>/_backup_<ГГГГММДД>/.
    "iom_config": "",    # пусто — {game_data}/inventOmaticStashConfig.json
    "backup_root": "",   # пусто — <data>/backups
    # Файлы выгрузки Invent-O-Matic Extractor (мод пишет JSON в itemsmod.ini). Допустимы шаблоны glob.
    # {game_data} подставляется из настройки game_data.
    "inventory": [
        "{game_data}/itemsmod.ini",
        "{game_data}/itemsmod.json",
    ],
    # Файлы Improved Workbench со списком легендарных модов.
    "legendary_mods": [
        "{game_data}/LegendaryMods.ini",
    ],
    # true — `serve` сам следит за выгрузками и обновляет события (не нужен отдельный `watch`); то же делает `serve --watch`
    "serve_watch": False,
    "host": "127.0.0.1",
    "port": 7676,
    # Доступ не с этого компьютера (телефон/PWA, сеть, обратный прокси): токен обязателен. Пусто — без проверки.
    # FO76DB_TOKEN перекрывает. Локальные запросы (127.0.0.1 без прокси) токен не спрашивают.
    "token": "",
    # HTTPS прямо из uvicorn (PWA на телефоне требует HTTPS с доверенным сертификатом, см. docs/pwa.md)
    # Адреса сторонних фронтендов (браузер на другом origin), например ["http://localhost:5173"]; нужен перезапуск serve.
    "cors_origins": [],
    "ssl_certfile": "",
    "ssl_keyfile": "",
}


def write_atomic(path: Path, text: str) -> None:
    """Записать файл целиком или никак: временный файл рядом + os.replace (параллельные процессы не увидят половину файла)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _read_json(path: Path) -> dict:
    """JSON-объект из файла; нет файла — {}, порча — {} с записью в журнал (раньше пути молча сбрасывались)."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        log.warning("не прочитан %s: %s", path, e)
        return {}
    return raw if isinstance(raw, dict) else {}


def saved_paths() -> dict:
    """Пути из data/paths.json (только непустые известные ключи)."""
    raw = _read_json(PATHS_FILE)
    return {k: str(raw[k]) for k in PATH_KEYS if isinstance(raw.get(k), str) and raw[k].strip()}


def save_paths(values: dict) -> None:
    """Сохранить пути в data/paths.json; пустое значение — вернуть автоопределение / config.toml."""
    cur = saved_paths()
    for k in PATH_KEYS:
        if k in values:
            v = str(values[k] or "").strip()
            if v:
                cur[k] = v
            else:
                cur.pop(k, None)
    write_atomic(PATHS_FILE, json.dumps(cur, ensure_ascii=False, indent=2))


LOOPBACK_HOSTS = ("127.0.0.1", "::1", "localhost")


def lan_addresses() -> list[str]:
    """IPv4-адреса этого компьютера в локальных сетях (для ссылки с телефона)."""
    import socket
    out = []
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if not ip.startswith("127.") and ip not in out:
                out.append(ip)
    except OSError:
        pass
    try:  # адрес исходящего интерфейса (без отправки пакетов)
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 9))
            ip = s.getsockname()[0]
            if ip not in out:
                out.insert(0, ip)
    except OSError:
        pass
    return out


def saved_network() -> dict:
    """Режим доступа из data/network.json: {"mode": "local"|"lan", "token": str}; пусто — берётся config.toml."""
    raw = _read_json(NETWORK_FILE)
    out = {}
    if raw.get("mode") in ("local", "lan"):
        out["mode"] = raw["mode"]
    if isinstance(raw.get("token"), str) and raw["token"].strip():
        out["token"] = raw["token"].strip()
    return out


def save_network(mode: str, token: str) -> None:
    write_atomic(NETWORK_FILE, json.dumps({"mode": mode, "token": token}, ensure_ascii=False, indent=2))  # mkstemp даёт права 0600


def _auto() -> dict:
    found = gamepaths.detect()
    first = found[0] if found else {}
    return {"game_data": first.get("game_data", ""), "ini_dir": first.get("ini_dir", "")}


def _toml() -> dict:
    return tomllib.loads(CONFIG.read_text(encoding="utf-8")) if CONFIG.exists() else {}


def path_sources() -> dict:
    """Откуда взято значение каждого пути: env / paths / toml / auto / default."""
    toml, saved, auto = _toml(), saved_paths(), _auto()
    out = {}
    for k in PATH_KEYS:
        if k == "game_data" and os.environ.get("FO76DB_GAME_DATA"):
            out[k] = "env"
        elif k in saved:
            out[k] = "paths"
        elif toml.get(k):
            out[k] = "toml"
        elif auto.get(k):
            out[k] = "auto"
        else:
            out[k] = "default"
    return out


_cache: tuple | None = None


def _signature() -> tuple:
    """Что влияет на результат load(): время изменения файлов настроек и переменные окружения."""
    def mtime(p: Path):
        try:
            return p.stat().st_mtime_ns
        except OSError:
            return None
    return (mtime(CONFIG), mtime(PATHS_FILE), mtime(NETWORK_FILE),
            os.environ.get("FO76DB_GAME_DATA"), os.environ.get("FO76DB_TOKEN"))


def load() -> dict:
    """Настройки. Вызывается на каждый запрос веб-интерфейса, поэтому результат кэшируется до изменения файлов настроек."""
    global _cache
    sig = _signature()
    if _cache is None or _cache[0] != sig:
        _cache = (sig, _load())
    return copy.deepcopy(_cache[1])


def _load() -> dict:
    cfg = dict(DEFAULTS)
    cfg.update(_toml())
    cfg.update(saved_paths())
    net = saved_network()
    if net.get("mode"):
        cfg["host"] = "0.0.0.0" if net["mode"] == "lan" else "127.0.0.1"
    if net.get("token"):
        cfg["token"] = net["token"]
    if env := os.environ.get("FO76DB_GAME_DATA"):
        cfg["game_data"] = env
    if env := os.environ.get("FO76DB_TOKEN"):
        cfg["token"] = env
    auto = _auto()
    for k in ("game_data", "ini_dir"):
        cfg[k] = cfg.get(k) or auto[k]
    if not cfg["game_data"]:  # игра не найдена: путь-заглушка, чтобы остальной код не падал
        cfg["game_data"] = "C:/Program Files (x86)/Steam/steamapps/common/Fallout76/Data" if os.name == "nt" \
            else str(Path("~/.local/share/Steam/steamapps/common/Fallout76/Data").expanduser())
    cfg["iom_config"] = cfg.get("iom_config") or str(Path(cfg["game_data"]) / gamepaths.IOM_FILE)
    cfg["backup_root"] = cfg.get("backup_root") or str(DATA / "backups")
    for k in ("inventory", "legendary_mods"):
        cfg[k] = [p.replace("{game_data}", cfg["game_data"]) for p in cfg[k]]
    return cfg


def game_data() -> Path:
    return Path(load()["game_data"])


def expand(patterns: list[str]) -> list[Path]:
    out: list[Path] = []
    for p in patterns:
        matches = sorted(glob.glob(p)) if any(ch in p for ch in "*?[") else [p]
        # Пустой файл — заготовка, в которую мод ещё ничего не выгрузил
        out.extend(Path(m) for m in matches if Path(m).is_file() and Path(m).stat().st_size > 0)
    return out
