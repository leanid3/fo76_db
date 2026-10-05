"""Настройки: пути, сеть, моды, журнал, копия базы, диагностика, задачи, редактор IOM."""
from __future__ import annotations

import os
import secrets
import shutil
from pathlib import Path

from fastapi import APIRouter, Body, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse

from ... import applog, config, filepick, gamepaths, iomconfig, maintenance, mods, tasks, updatecheck
from ..common import (_local,
                      _need_local, con, page)

router = APIRouter()


@router.get("/settings", response_class=HTMLResponse, include_in_schema=False)
def settings_page(request: Request):
    return page(request, "settings.html")


def _paths_info(refresh: bool = False) -> dict:
    cfg, src = config.load(), config.path_sources()
    values = {k: cfg[k] for k in config.PATH_KEYS}
    checks = {
        "game_data": (Path(values["game_data"]) / gamepaths.ESM).is_file(),
        "ini_dir": Path(values["ini_dir"]).is_dir() if values["ini_dir"] else False,
        "iom_config": Path(values["iom_config"]).is_file(),
        "backup_root": Path(values["backup_root"]).is_dir(),
        "mods_dir": Path(values["mods_dir"]).is_dir() if values["mods_dir"] else None,
    }
    return {"values": values, "sources": src, "checks": checks, "candidates": gamepaths.detect(refresh)}


@router.get("/api/paths")
def api_paths(refresh: bool = False):
    return _paths_info(refresh)


@router.post("/api/paths")
def api_paths_save(request: Request, body: dict = Body(...)):
    """Сохранить пути (data/paths.json). Пустое значение — вернуть автоопределение. Папки игры не создаются и не меняются."""
    _need_local(request)
    vals = {}
    for k in config.PATH_KEYS:
        if k in body:
            v = str(body[k] or "").strip()
            if v and "\n" in v:
                raise HTTPException(400, f"{k}: путь должен быть в одну строку")
            vals[k] = v
    config.save_paths(vals)
    return _paths_info()


def _network_info(request: Request) -> dict:
    cfg = config.load()
    host = cfg["host"]
    lan = host not in config.LOOPBACK_HOSTS
    running = getattr(request.app.state, "bind_host", host)  # адрес, на котором сервер реально запущен
    return {
        "mode": "lan" if lan else "local", "host": host, "port": cfg["port"], "token": cfg.get("token") or "",
        "token_env": bool(os.environ.get("FO76DB_TOKEN")), "running_lan": running not in config.LOOPBACK_HOSTS,
        "addresses": config.lan_addresses() if lan else [],
    }


@router.get("/api/network")
def api_network(request: Request):
    _need_local(request)  # в ответе токен
    return _network_info(request)


@router.post("/api/network")
def api_network_save(request: Request, body: dict = Body(...)):
    """Режим доступа: local — только этот компьютер, lan — вся сеть по токену. Адрес меняется после перезапуска serve."""
    _need_local(request)
    mode = body.get("mode")
    if mode not in ("local", "lan"):
        raise HTTPException(400, "mode: local или lan")
    token = str(body.get("token") or "").strip() or config.load().get("token") or ""
    if body.get("new_token") or (mode == "lan" and not token):
        token = secrets.token_urlsafe(24)
    config.save_network(mode, token)
    return _network_info(request)


@router.get("/api/mods")
def api_mods(refresh: bool = False):
    """Состояние модов (есть ли их файлы). refresh — заново найти установки игры и подсказать, где лежат недостающие."""
    return mods.status(refresh)


@router.post("/api/pick")
def api_pick(request: Request, body: dict = Body(...)):
    """Системное окно выбора папки/файла (kind: dir | file). Только для запросов с этого компьютера: окно открывается на нём."""
    if not _local(request):
        raise HTTPException(403, "выбор через окно доступен только на этом компьютере — введите путь вручную")
    try:
        path = filepick.pick(body.get("kind") == "dir", body.get("start") or "", body.get("title") or "")
    except filepick.PickError as e:
        raise HTTPException(501, str(e))
    return {"path": path}


@router.get("/api/log")
def api_log(lines: int = 500):
    return applog.tail(max(10, min(lines, 5000)))


@router.get("/api/log/download")
def api_log_download():
    if not applog.PATH.exists():
        raise HTTPException(404, "журнал пуст")
    return FileResponse(applog.PATH, media_type="text/plain; charset=utf-8", filename="fo76db-app.log")


@router.delete("/api/log")
def api_log_clear(request: Request):
    """Очистить журнал: файл усекается на месте — открытые процессы продолжают дописывать в него."""
    _need_local(request)
    if applog.PATH.exists():
        with open(applog.PATH, "r+b") as f:
            f.truncate(0)
    return {"ok": True}


# ---------- редактор конфига Invent-O-Matic ----------

@router.get("/iom", response_class=HTMLResponse, include_in_schema=False)
def iom_page(request: Request):
    return page(request, "iom.html")


def _iom_call(fn, *args):
    try:
        return fn(*args)
    except iomconfig.IomError as e:
        raise HTTPException(409, str(e))
    except OSError as e:
        raise HTTPException(500, f"Ошибка файла: {e}")


@router.get("/api/iom")
def api_iom():
    r = _iom_call(iomconfig.load)
    r["problems"] = iomconfig.validate(r["data"])
    r["backups"] = [str(p) for p in iomconfig.backups()[:30]]
    return r


@router.post("/api/iom/validate")
def api_iom_validate(data: dict = Body(..., embed=True)):
    return iomconfig.validate(data)


@router.post("/api/iom/save")
def api_iom_save(request: Request, data: dict = Body(...), sha1: str = Body(...), confirm: bool = Body(False)):
    _need_local(request)
    if not confirm:
        raise HTTPException(400, "Запись в файл игры требует подтверждения")
    return _iom_call(iomconfig.save, data, sha1)


@router.post("/api/iom/restore")
def api_iom_restore(request: Request, sha1: str = Body(...), backup: str | None = Body(None)):
    _need_local(request)
    return _iom_call(iomconfig.restore_latest, sha1, None, None, backup)


@router.get("/api/doctor")
def api_doctor():
    return maintenance.doctor()


@router.get("/api/update")
def api_update(refresh: bool = False):
    """Есть ли новая версия FO76 DB (последний релиз на GitHub). Запрос к GitHub — не чаще раза в 6 часов; refresh=true — сразу."""
    c = con()
    try:
        updatecheck.refresh(c, force=refresh)
        return updatecheck.info(c)
    finally:
        c.close()


@router.post("/api/update/dismiss")
def api_update_dismiss(request: Request, tag: str = Body(..., embed=True)):
    """Скрыть баннер для этой версии (на следующую он появится снова)."""
    _need_local(request)
    c = con()
    try:
        updatecheck.dismiss(c, tag)
        return {"ok": True}
    finally:
        c.close()


@router.get("/api/backup")
def api_backup_download(request: Request):
    """Скачать копию базы. Только с этого компьютера: в базе личные данные (инвентарь, персонажи)."""
    _need_local(request)
    import tempfile
    from starlette.background import BackgroundTask
    tmp = Path(tempfile.mkdtemp(prefix="fo76db-backup-"))
    path = maintenance.backup(tmp, keep=0)
    return FileResponse(path, media_type="application/vnd.sqlite3", filename=path.name,
                        background=BackgroundTask(shutil.rmtree, tmp, True))


@router.post("/api/backup")
def api_backup_save(request: Request):
    _need_local(request)
    return {"path": str(maintenance.backup())}


@router.get("/api/tasks")
def api_tasks():
    return tasks.status()


@router.post("/api/tasks/{name}")
def api_task_start(name: str):
    if name not in tasks.RUN:
        raise HTTPException(404, f"нет задачи {name}")
    if name in ("catalog", "history"):
        try:
            from ..sources import dumps
            dumps.sevenzip()
        except RuntimeError as e:  # архивы fo76-dumps без 7-Zip не открыть: сказать сразу, а не после загрузки
            raise HTTPException(400, str(e))
    if not tasks.start(name):
        raise HTTPException(409, "уже идёт другая задача")
    return tasks.status()
