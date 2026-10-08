"""Таблица действий персонажа: правила мода IOM как строки БД (fo76db/actions.py)."""
from __future__ import annotations

import difflib
import json

from fastapi import APIRouter, Body, HTTPException, Request
from fastapi.responses import HTMLResponse

from ... import actions, iomconfig
from ..common import _need_local, con, page

router = APIRouter()

FIELDS = ("name", "account", "character", "type", "hotkey", "ord", "after_id", "test_run", "enabled")


def _out(r) -> dict:
    d = dict(r)
    d["filter"] = d["filter"] or "{}"
    d["last_result"] = json.loads(d["last_result"]) if d["last_result"] else None
    d["fork_only"] = d["type"] in actions.FORK_ONLY
    d.pop("raw", None)
    return d


def _clean(body: dict) -> dict:
    out = {k: body[k] for k in FIELDS if k in body}
    if "type" in out and out["type"] not in actions.TYPES:
        raise HTTPException(400, "Неизвестный тип действия: " + str(out["type"]))
    for k in ("test_run", "enabled"):
        if k in out:
            out[k] = 1 if out[k] else 0
    for k in ("account", "character", "hotkey"):
        if k in out:
            out[k] = (str(out[k]).strip() or None) if out[k] is not None else None
    if "filter" in body:
        try:
            f = json.loads(body["filter"]) if isinstance(body["filter"], str) else body["filter"]
        except ValueError:
            raise HTTPException(400, "filter: некорректный JSON")
        if not isinstance(f, dict):
            raise HTTPException(400, "filter должен быть объектом")
        out["filter"] = json.dumps(f, ensure_ascii=False)
    return out


@router.get("/actions", response_class=HTMLResponse, include_in_schema=False)
def actions_page(request: Request):
    return page(request, "actions.html", TYPES=actions.TYPES, FORK_ONLY=actions.FORK_ONLY)


@router.get("/api/actions")
def api_actions():
    c = con()
    rows = list(c.execute("SELECT * FROM actions ORDER BY ord, id"))
    return {"items": [_out(r) for r in rows], "conflicts": actions.key_conflicts(rows)}


@router.post("/api/actions")
def api_action_add(body: dict = Body(...)):
    d = _clean(body)
    d.setdefault("name", "Новое действие")
    d.setdefault("type", "scrap")
    c = con()
    d.setdefault("ord", c.execute("SELECT COALESCE(MAX(ord), -1) + 1 FROM actions").fetchone()[0])
    d["source"] = "manual"
    cur = c.execute(f"INSERT INTO actions ({', '.join(d)}) VALUES ({', '.join('?' * len(d))})", list(d.values()))
    c.commit()
    return {"id": cur.lastrowid}


@router.patch("/api/actions/{aid}")
def api_action_patch(aid: int, body: dict = Body(...)):
    d = _clean(body)
    if d:
        c = con()
        if not c.execute("UPDATE actions SET " + ", ".join(f"{k} = ?" for k in d) + " WHERE id = ?", [*d.values(), aid]).rowcount:
            raise HTTPException(404, "Нет такого действия")
        c.commit()
    return {"ok": True}


@router.post("/api/actions/bulk")
def api_action_bulk(ids: list[int] = Body(...), values: dict = Body(...)):
    """Массовое изменение: enabled / test_run."""
    d = {k: (1 if v else 0) for k, v in values.items() if k in ("enabled", "test_run")}
    if not d or not ids:
        raise HTTPException(400, "Нечего менять")
    c = con()
    c.execute(f"UPDATE actions SET {', '.join(f'{k} = ?' for k in d)} WHERE id IN ({','.join('?' * len(ids))})", [*d.values(), *ids])
    c.commit()
    return {"ok": True}


@router.delete("/api/actions/{aid}")
def api_action_delete(aid: int):
    c = con()
    c.execute("UPDATE actions SET after_id = NULL WHERE after_id = ?", (aid,))
    c.execute("DELETE FROM actions WHERE id = ?", (aid,))
    c.commit()
    return {"ok": True}


@router.post("/api/actions/order")
def api_action_order(ids: list[int] = Body(..., embed=True)):
    """Порядок выполнения: id в нужной последовательности."""
    c = con()
    c.executemany("UPDATE actions SET ord = ? WHERE id = ?", [(i, a) for i, a in enumerate(ids)])
    c.commit()
    return {"ok": True}


@router.post("/api/actions/import")
def api_action_import():
    """Добавить правила из конфига игры, которых ещё нет в таблице (в конфиг ничего не пишется)."""
    try:
        cur = iomconfig.load()
    except iomconfig.IomError as e:
        raise HTTPException(400, str(e))
    return actions.import_rules(con(), cur["data"])


def _plan():
    try:
        cur = iomconfig.load()
    except iomconfig.IomError as e:
        raise HTTPException(400, str(e))
    return cur, actions.build_config(con(), cur["data"])


@router.get("/api/actions/preview")
def api_action_preview():
    """Что изменится в конфиге игры (diff, предупреждения, пропущенные действия) — без записи."""
    cur, plan = _plan()
    old = iomconfig.dumps(cur["data"], cur["indent"]).splitlines()
    new = iomconfig.dumps(plan["data"], cur["indent"]).splitlines()
    diff = list(difflib.unified_diff(old, new, "было", "станет", n=2, lineterm=""))
    return {"diff": diff, "written": plan["written"], "skipped": plan["skipped"], "warnings": plan["warnings"],
            "issues": iomconfig.validate(plan["data"]), "sha1": cur["sha1"], "path": cur["path"]}


@router.post("/api/actions/apply")
def api_action_apply(request: Request, sha1: str = Body(..., embed=True), confirm: bool = Body(False)):
    """Записать правила в конфиг IOM (бэкап и сохранение inode — в iomconfig.save). Только по явной кнопке."""
    _need_local(request)
    if not confirm:
        raise HTTPException(400, "Запись в файл игры требует подтверждения")
    try:
        _, plan = _plan()
        return iomconfig.save(plan["data"], sha1)
    except iomconfig.IomError as e:
        raise HTTPException(400, str(e))
