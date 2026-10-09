"""Лаунчер: состояние, диагностика, сборка и установка форка мода, юниты systemd, перенос данных.

Игру трогают только `mod_install` и `mod_rollback` (замена InventOmaticStash-UO.ba2) — с бэкапом в
`<backup_root>/_backup_<ГГГГММДД>/Data/` и только по подтверждению вызывающего."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import shutil
import socket
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

from . import config, db, iomconfig

BA2 = "InventOmaticStash-UO.ba2"
SWC_URL = "https://fpdownload.macromedia.com/get/flashplayer/updaters/32/playerglobal32_0.swc"
# Изменённые скрипты форка (BUILD.md): swf в архиве → скрипты относительно каталога swf в форке
SCRIPTS = {
    "interface/InventOmaticStash.swf": ("InventOmaticStash/scripts", ["ItemWorker.as", "InventOmaticStash.as", "Version.as", "utils/ItemProtection.as"]),
    "interface/securetrade.swf": ("securetrade/scripts", ["SecureTrade.as", "ItemListEntry.as"]),
}
UNITS = {"fo76db-serve": "serve", "fo76db-watch": "watch"}


class LauncherError(RuntimeError):
    pass


def sha1(p: Path) -> str | None:
    return hashlib.sha1(p.read_bytes()).hexdigest() if p.is_file() else None


def fork_dir() -> Path:
    """Исходники форка: `mod_fork_dir`, иначе `mod-fork/` рядом с приложением (так в сборке для развёртывания),
    иначе ~/src/Invent-O-Matic-Stash-modificaed."""
    cfg = config.load().get("mod_fork_dir")
    if cfg:
        return Path(cfg).expanduser()
    for p in (db.ROOT / "mod-fork", Path("~/src/Invent-O-Matic-Stash-modificaed").expanduser()):
        if (p / "tools/ba2.py").is_file():
            return p
    return db.ROOT / "mod-fork"


def _backup_root() -> Path:
    return iomconfig._paths()[1]


def built_path() -> Path:
    return db.DATA / "launcher" / BA2


def _run(cmd: list[str], timeout: int = 600) -> str:
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if r.returncode:
        raise LauncherError(f"{' '.join(cmd[:2])}: {(r.stderr or r.stdout).strip()[-600:]}")
    return r.stdout


def _pgrep(pat: str) -> bool:
    return subprocess.run(["pgrep", "-f", pat], capture_output=True).returncode == 0


def _port_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            return True
    except OSError:
        return False


def ba2_version(path: Path) -> dict | None:
    """Версия мода в архиве: {version, fork} (fork — FORK_VERSION или None у оригинала). Читается из класса Version внутри
    InventOmaticStash.swf через ffdec; результат кэшируется по sha1 в data/launcher/versions.json."""
    h = sha1(path)
    if not h:
        return None
    cache_file = db.DATA / "launcher" / "versions.json"
    try:
        cache = json.loads(cache_file.read_text())
    except (OSError, ValueError):
        cache = {}
    if h in cache:
        return cache[h]
    if not shutil.which("ffdec"):
        return None
    try:
        with tempfile.TemporaryDirectory(prefix="fo76db-ver-") as tmp:
            tmp = Path(tmp)
            _run([sys.executable, str(_ba2tool(fork_dir())), "unpack", str(path), str(tmp / "ba2")], 120)
            _run(["ffdec", "-selectclass", "Version", "-export", "script", str(tmp / "out"), str(tmp / "ba2/interface/InventOmaticStash.swf")], 180)
            src = next((tmp / "out").rglob("Version.as")).read_text()
    except (LauncherError, StopIteration, OSError, subprocess.TimeoutExpired):
        return None
    info = _parse_version(src)
    if info:
        cache[h] = info
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps(cache))
    return info


def _parse_version(src: str) -> dict | None:
    import re
    m = re.search(r"VERSION:Number\s*=\s*([\d.]+)", src)
    if not m:
        return None
    f = re.search(r"FORK_VERSION:int\s*=\s*(\d+)", src)
    return {"version": float(m.group(1)), "fork": int(f.group(1)) if f else None}


def source_version() -> dict | None:
    """Версия мода, под которую написан форк (из его исходников): {version, fork}."""
    try:
        return _parse_version((fork_dir() / "InventOmaticStash/scripts/Version.as").read_text())
    except OSError:
        return None


def original_ba2() -> Path | None:
    """Оригинал архива мода: самый свежий бэкап без пометки форка (в старых бэкапах версию не читаем без ffdec — берём первый)."""
    found = sorted(_backup_root().glob(f"_backup_*/Data/{BA2}"))
    clean = [p for p in found if (ba2_version(p) or {}).get("fork") is None]
    return (clean or found or [None])[-1] if shutil.which("ffdec") else (found[0] if found else None)


def ensure_original() -> Path:
    """Оригинал архива для сборки и отката. В Data лежит чистый (не форк) архив, которого нет в бэкапах — например, после
    обновления мода с Nexus, — он копируется в бэкап и становится новым оригиналом."""
    cur = config.game_data() / BA2
    o = original_ba2()
    if cur.is_file() and sha1(cur) != sha1(built_path()):
        v = ba2_version(cur)
        known = {sha1(p) for p in _backup_root().glob(f"_backup_*/Data/{BA2}")}
        if (v is None or v.get("fork") is None) and sha1(cur) not in known and (o is None or v is not None):
            dst = _game_backup_dir() / BA2
            if dst.exists():
                dst = dst.with_name(f"{BA2}.{dt.datetime.now():%H%M%S}")
            shutil.copy2(cur, dst)
            return dst
    if o:
        return o
    raise LauncherError(f"в Data нет {BA2}: установите мод Invent-O-Matic Stash (Nexus Mods → «Invent-O-Matic Stash») и повторите")


def mod_versions() -> dict:
    """Версии: мод в Data, оригинал в бэкапе, исходники форка; `compatible` — совпадает ли база форка с оригиналом."""
    data = config.game_data() / BA2
    orig = original_ba2()
    src = source_version()
    o = ba2_version(orig) if orig else None
    return {"installed": ba2_version(data) if data.is_file() else None, "original": o, "source": src,
            "compatible": None if not (o and src) else o["version"] == src["version"]}


def fork_version(fd: Path) -> int | None:
    try:
        m = [ln for ln in (fd / "InventOmaticStash/scripts/Version.as").read_text().splitlines() if "FORK_VERSION" in ln]
        return int(m[0].split("=")[1].strip(" ;")) if m else None
    except (OSError, ValueError, IndexError):
        return None


def status() -> dict:
    cfg = config.load()
    data = config.game_data()
    ba2 = data / BA2
    out = {"game_data": str(data), "ba2": {"path": str(ba2), "sha1": sha1(ba2)}, "original": str(original_ba2() or ""),
           "fork_dir": str(fork_dir()), "fork_version_src": fork_version(fork_dir())}
    built = built_path()
    out["built"] = {"path": str(built.resolve()), "sha1": sha1(built)}
    try:
        conf = iomconfig.load()["data"]
    except Exception as e:  # noqa: BLE001 — статус не должен падать из-за конфига
        conf, out["config_error"] = {}, str(e)
    mf = conf.get("modFork") if isinstance(conf, dict) else None
    out["config"] = {"modFork": mf, "markConfig": isinstance(conf.get("markConfig"), dict), "godrolls": bool((conf.get("protectionConfig") or {}).get("scrapProtection", {}).get("godrolls"))}
    plan = data / "inventOmaticPlan.json"
    out["plan"] = {"exists": plan.exists(), "mtime": dt.datetime.fromtimestamp(plan.stat().st_mtime).isoformat(timespec="seconds") if plan.exists() else None}
    out["tools"] = {"java": bool(shutil.which("java")), "ffdec": bool(shutil.which("ffdec")),
                    "swc": any((Path.home() / d / "flashlib/playerglobal32_0.swc").exists() for d in (".config/FFDec", ".config/JPEXS/FFDec"))}
    out["versions"] = mod_versions()
    out["running"] = {"game": _pgrep("Fallout76.exe"), "serve": _port_open(int(cfg.get("port", 7676))), "watch": _pgrep("fo76db.* watch|cli.py watch")}
    out["ba2_mtime"] = dt.datetime.fromtimestamp(ba2.stat().st_mtime).isoformat(timespec="seconds") if ba2.exists() else None
    return out


def diagnose(st: dict | None = None) -> list[dict]:
    """Проверки «почему мод не работает»: [{ok, name, detail, hint}]; ok None — предупреждение."""
    st = st or status()
    rows: list[dict] = []

    def add(ok, name, detail, hint=""):
        rows.append({"ok": ok, "name": name, "detail": detail, "hint": hint})

    ba, bt = st["ba2"]["sha1"], st["built"]["sha1"]
    add(bool(ba), "Архив мода в Data", st["ba2"]["path"] if ba else "нет файла", "Положите InventOmaticStash-UO.ba2 в Data")
    v = st.get("versions") or {}
    if v.get("compatible") is False:
        add(False, "Версия мода и форка", f"установлен мод v{v['original']['version']}, форк написан под v{v['source']['version']}",
            "Перенесите правки форка на новую версию мода (mod-fork/BUILD.md); до этого сборка отключена")
    elif v.get("original"):
        add(True, "Версия мода и форка", f"мод v{v['original']['version']}, форк v{(v['source'] or {}).get('fork')}")
    add(None if not bt else (ba == bt), "Установлен собранный форк", "совпадает со сборкой" if bt and ba == bt else ("сборки нет" if not bt else "в игре другой архив"),
        "fo76db launcher build && fo76db launcher install --yes")
    mf = st["config"]["modFork"]
    add(bool(mf), "Конфиг знает форк (modFork)", json.dumps(mf, ensure_ascii=False) if mf else "поля modFork нет — метки и chain* не работают",
        "Страница «Действия»: «Установлен форк мода» → «Предпросмотр» → «Записать»")
    add(st["config"]["markConfig"], "Метки (markConfig)", "есть" if st["config"]["markConfig"] else "нет", "Запись конфига с включённым форком")
    add(st["plan"]["exists"], "План цепочки", st["plan"]["mtime"] or "нет файла", "Страница «Действия» → «План цепочки…»")
    t = st["tools"]
    add(all(t.values()) or None, "Инструменты сборки", ", ".join(f"{k}={'да' if v else 'нет'}" for k, v in t.items()),
        "yay -S --needed jdk-openjdk ffdec-bin; playerglobal32_0.swc — `fo76db launcher build` скачает сам")
    if st["running"]["game"] and st["ba2_mtime"]:
        add(None, "Игра запущена", "новый архив подхватится после перезапуска игры")
    add(st["running"]["serve"], "serve", "работает" if st["running"]["serve"] else "не запущен", "fo76db launcher start")
    return rows


# --- сборка форка -----------------------------------------------------------------------------------------

def _ba2tool(fd: Path) -> Path:
    p = fd / "tools/ba2.py"
    if not p.exists():
        raise LauncherError(f"нет {p}")
    return p


def ensure_swc() -> None:
    dst = Path.home() / ".config/FFDec/flashlib/playerglobal32_0.swc"
    if dst.exists():
        return
    import urllib.request
    dst.parent.mkdir(parents=True, exist_ok=True)
    urllib.request.urlretrieve(SWC_URL, dst)  # noqa: S310 — фиксированный https-адрес Adobe


def mod_build(out_dir: Path | None = None, force: bool = False) -> dict:
    """Собрать новый архив из форка и оригинала (ffdec + ba2.py). Игру не трогает: результат — `data/launcher/<ba2>`."""
    fd = fork_dir()
    if not (fd / "InventOmaticStash/scripts").is_dir():
        raise LauncherError(f"нет исходников форка в {fd} (параметр mod_fork_dir)")
    orig = ensure_original()
    ov, sv = ba2_version(orig), source_version()
    if ov and sv and ov["version"] != sv["version"] and not force:
        raise LauncherError(f"форк написан под мод v{sv['version']}, а установлен v{ov['version']}: правки форка надо перенести на новую версию "
                            "(mod-fork/BUILD.md); сборка поверх чужих скриптов затрёт изменения мода. Принудительно — `build --force`")
    for tool in ("java", "ffdec"):
        if not shutil.which(tool):
            raise LauncherError(f"не найден {tool}: yay -S --needed jdk-openjdk ffdec-bin")
    ensure_swc()
    tool = _ba2tool(fd)
    dest = Path(out_dir) if out_dir else built_path().parent
    dest.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="fo76db-mod-") as tmp:
        tmp = Path(tmp)
        unpacked = tmp / "ba2"
        _run([sys.executable, str(tool), "unpack", str(orig), str(unpacked)])
        for swf, (src, files) in SCRIPTS.items():
            imp = tmp / ("imp_" + Path(swf).stem)
            for f in files:
                (imp / f).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(fd / src / f, imp / f)
            new = tmp / (Path(swf).stem + "_new.swf")
            _run(["ffdec", "-importScript", str(unpacked / swf), str(new), str(imp)])
            shutil.copy2(new, unpacked / swf)
        target = dest / BA2
        _run([sys.executable, str(tool), "pack", str(unpacked), str(target), "--like", str(orig)])
    return {"path": str(target), "sha1": sha1(target), "size": target.stat().st_size, "fork_version": fork_version(fd)}


def _game_backup_dir() -> Path:
    d = _backup_root() / f"_backup_{dt.datetime.now():%Y%m%d}" / "Data"
    d.mkdir(parents=True, exist_ok=True)
    return d


def mod_install(src: Path | None = None) -> dict:
    """Заменить архив мода в Data собранным (после подтверждения). Прежний — в бэкап. Перезапустите игру."""
    src = src or built_path()
    if not src.is_file():
        raise LauncherError("сначала `launcher build`")
    dst = config.game_data() / BA2
    bk = None
    if dst.exists():
        if sha1(dst) == sha1(src):
            return {"changed": False, "path": str(dst)}
        bk = _game_backup_dir() / f"{BA2}.{dt.datetime.now():%H%M%S}"
        shutil.copy2(dst, bk)
    shutil.copyfile(src, dst)  # тот же inode, права и владелец сохраняются
    return {"changed": True, "path": str(dst), "backup": str(bk) if bk else None, "sha1": sha1(dst)}


def mod_rollback(which: Path | None = None) -> dict:
    """Вернуть архив из бэкапа (по умолчанию — оригинал). Текущий сначала копируется в бэкап."""
    src = which or original_ba2()
    if not src or not Path(src).is_file():
        raise LauncherError("бэкап архива не найден")
    dst = config.game_data() / BA2
    bk = None
    if dst.exists() and sha1(dst) != sha1(src):
        bk = _game_backup_dir() / f"{BA2}.{dt.datetime.now():%H%M%S}"
        shutil.copy2(dst, bk)
    shutil.copyfile(src, dst)
    return {"restored": str(src), "backup": str(bk) if bk else None, "path": str(dst)}


# --- развёртывание одной кнопкой --------------------------------------------------------------------------

def deploy(confirm: bool = False, force: bool = False) -> dict:
    """Всё сразу: собрать форк, поставить архив в Data, включить форк, записать конфиг IOM и план цепочки.
    Каждый шаг пишется в `steps`; при ошибке остановка на этом шаге (прежнее состояние сохраняется бэкапами)."""
    from . import actions, chainplan
    if not confirm:
        raise LauncherError("развёртывание пишет в папку игры: нужно подтверждение")
    steps: list[dict] = []

    def step(name, fn):
        try:
            res = fn()
        except Exception as e:  # noqa: BLE001 — шаг отчитывается и прерывает цепочку
            steps.append({"step": name, "ok": False, "error": str(e)})
            raise LauncherError(f"{name}: {e}") from e
        steps.append({"step": name, "ok": True, **(res if isinstance(res, dict) else {})})

    try:
        step("Сборка форка", lambda: mod_build(force=force))
        step("Архив мода в Data", mod_install)
        c = db.connect()
        step("Включить форк", lambda: (chainplan.set_fork(c, True), {})[1])

        def cfg():
            cur = iomconfig.load()
            r = actions.build_config(c, cur["data"])
            out = iomconfig.save(r["data"], cur["sha1"])
            return {**out, "written": r["written"], "warnings": r["warnings"]}
        step("Конфиг IOM", cfg)
        step("План цепочки", lambda: iomconfig.save_aux(chainplan.PLAN_FILE, chainplan.plan_text(c), config.game_data()))
    except LauncherError as e:
        return {"ok": False, "error": str(e), "steps": steps}
    return {"ok": True, "steps": steps, "restart_game": True}


# --- запуск/остановка -------------------------------------------------------------------------------------

def unit_text(kind: str) -> str:
    root = db.ROOT
    py = root / ".venv/bin/python"
    return (f"[Unit]\nDescription=fo76db {kind}\n\n[Service]\nWorkingDirectory={root}\n"
            f"ExecStart={py if py.exists() else sys.executable} -m fo76db {kind}\nRestart=on-failure\n\n[Install]\nWantedBy=default.target\n")


def units_install() -> list[str]:
    d = Path.home() / ".config/systemd/user"
    d.mkdir(parents=True, exist_ok=True)
    out = []
    for name, kind in UNITS.items():
        p = d / f"{name}.service"
        p.write_text(unit_text(kind), encoding="utf-8")
        out.append(str(p))
    _run(["systemctl", "--user", "daemon-reload"])
    return out


def service(action: str) -> str:
    if action not in ("start", "stop", "restart", "status"):
        raise LauncherError("действие: start|stop|restart|status")
    r = subprocess.run(["systemctl", "--user", action, *[f"{n}.service" for n in UNITS]], capture_output=True, text=True)
    if r.returncode and action != "status":
        raise LauncherError((r.stderr or r.stdout).strip() or "systemctl: ошибка (юниты установлены? `launcher units`)")
    return (r.stdout or r.stderr).strip()


# --- перенос ----------------------------------------------------------------------------------------------

def export_bundle(dest: Path) -> dict:
    """Архив для переноса: config.toml, data/paths.json и копия базы (sqlite .backup, база в WAL)."""
    root = db.ROOT
    with tempfile.TemporaryDirectory(prefix="fo76db-exp-") as tmp:
        snap = Path(tmp) / "fo76.sqlite"
        src = db.connect()
        dstc = __import__("sqlite3").connect(snap)
        src.backup(dstc)
        dstc.close()
        with tarfile.open(dest, "w:gz") as t:
            t.add(snap, "data/fo76.sqlite")
            for rel in ("config.toml", "data/paths.json", "data/network.json"):
                if (root / rel).is_file():
                    t.add(root / rel, rel)
    return {"path": str(dest), "size": Path(dest).stat().st_size}


def import_bundle(src: Path, target: Path | None = None) -> dict:
    """Развернуть архив в каталог приложения. Существующая база сначала копируется рядом (`.before-import`)."""
    root = target or db.ROOT
    done = []
    with tarfile.open(src) as t:
        for m in t.getmembers():
            if not m.isfile() or m.name.startswith(("/", "..")) or ".." in Path(m.name).parts:
                raise LauncherError(f"недопустимое имя в архиве: {m.name}")
            p = root / m.name
            p.parent.mkdir(parents=True, exist_ok=True)
            if p.exists():
                shutil.copy2(p, p.with_name(p.name + ".before-import"))
            for ext in ("-wal", "-shm"):  # старый журнал WAL не должен примениться к чужой базе
                p.with_name(p.name + ext).unlink(missing_ok=True)
            p.write_bytes(t.extractfile(m).read())
            done.append(m.name)
    return {"files": done, "root": str(root)}
