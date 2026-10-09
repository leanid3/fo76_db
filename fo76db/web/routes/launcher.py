"""Лаунчер: статус и диагностика, сборка/установка форка мода, юниты (fo76db/launcher.py). Всё, что пишет, — только локально."""
from __future__ import annotations

from fastapi import APIRouter, Body, HTTPException, Request
from fastapi.responses import HTMLResponse

from ... import launcher
from ..common import _need_local, page

router = APIRouter()


def _guard(fn, *a):
    try:
        return fn(*a)
    except (launcher.LauncherError, OSError) as e:
        raise HTTPException(500, str(e))


@router.get("/launcher", response_class=HTMLResponse, include_in_schema=False)
def launcher_page(request: Request):
    return page(request, "launcher.html")


@router.get("/api/launcher/status")
def api_status():
    st = launcher.status()
    return {"status": st, "checks": launcher.diagnose(st)}


@router.post("/api/launcher/build")
def api_build(request: Request, force: bool = Body(False, embed=True)):
    """Собрать форк в data/launcher (ffdec, до минуты). Игру не трогает."""
    _need_local(request)
    return _guard(launcher.mod_build, None, force)


@router.post("/api/launcher/install")
def api_install(request: Request, confirm: bool = Body(False, embed=True)):
    _need_local(request)
    if not confirm:
        raise HTTPException(400, "Запись в папку игры требует подтверждения")
    return _guard(launcher.mod_install)


@router.post("/api/launcher/rollback")
def api_rollback(request: Request, confirm: bool = Body(False, embed=True)):
    _need_local(request)
    if not confirm:
        raise HTTPException(400, "Запись в папку игры требует подтверждения")
    return _guard(launcher.mod_rollback)


@router.post("/api/launcher/deploy")
def api_deploy(request: Request, confirm: bool = Body(False, embed=True), force: bool = Body(False)):
    """Развернуть всё одной кнопкой: сборка, архив в Data, включение форка, конфиг IOM, план цепочки."""
    _need_local(request)
    if not confirm:
        raise HTTPException(400, "Запись в папку игры требует подтверждения")
    return _guard(launcher.deploy, True, force)


@router.post("/api/launcher/units")
def api_units(request: Request):
    _need_local(request)
    return {"files": _guard(launcher.units_install)}


@router.post("/api/launcher/service/{action}")
def api_service(request: Request, action: str):
    _need_local(request)
    return {"output": _guard(launcher.service, action)}
