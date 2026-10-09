"""Общее для маршрутов: шаблоны, справочники подписей, соединение с БД, тема/раскладка, проверка «запрос с этого компьютера»."""
from __future__ import annotations

import hmac
import re
from pathlib import Path

from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from .. import db, features, mods

HERE = Path(__file__).parent


templates = Jinja2Templates(directory=HERE / "templates")
templates.env.globals["feat"] = features.on                        # {% if feat('events.online') %}
templates.env.globals["hid"] = lambda k: "" if features.on(k) else "hidden"  # <div {{ hid('events.online') }}>
templates.env.tests["navlink"] = lambda link: features.path_on(link[0])      # пункты меню отключённых страниц


LOOPBACK = ("127.0.0.1", "::1", "localhost")


def _local(request: Request) -> bool:
    """Запрос с этого компьютера напрямую: адрес клиента — loopback, в Host — localhost/127.0.0.1 (прокси вроде
    tailscale serve передают внешнее имя), заголовков прокси нет. Заодно защита от DNS rebinding."""
    client = request.client.host if request.client else ""
    host = (request.headers.get("host") or "").rsplit(":", 1)[0].strip("[]")
    proxied = any(h in request.headers for h in ("x-forwarded-for", "forwarded", "x-forwarded-host", "x-real-ip"))
    return client in LOOPBACK and host in LOOPBACK and not proxied


def _need_local(request: Request) -> None:
    """Запись путей и файла игры, очистка журнала — только с этого компьютера, даже если токен задан."""
    if not _local(request):
        raise HTTPException(403, "доступно только на этом компьютере")


def _eq(a: str, b: str) -> bool:
    """Сравнение секретов по байтам: не-ASCII в cookie не должен давать 500."""
    return hmac.compare_digest(a.encode(), b.encode())


KIND_RU = {
    "weapon": "Оружие", "armor": "Броня", "apparel": "Одежда", "consumable": "Расходники", "plan": "Схемы",
    "recipe": "Рецепты", "magazine": "Журналы", "bobblehead": "Пупсы", "book": "Записки и книги", "misc": "Разное",
    "ammo": "Патроны", "holotape": "Голодиски", "key": "Ключи", "component": "Компоненты", "mod": "Модификации",
    "legendary_mod": "Легендарные моды", "atom": "Atom Shop",
}


SUBKIND_RU = {
    "ranged": "дальнобойное", "melee": "ближний бой", "explosive": "взрывчатка", "armor": "броня",
    "power_armor": "силовая броня", "underarmor": "поддоспешник", "headwear": "головной убор",
    "fasnacht_mask": "маска Фаснахта", "food": "еда", "drink": "напиток", "chem": "препарат", "serum": "сыворотка", "aid": "помощь",
}


CATEGORY_RU = {
    "weapon": "оружие", "armor": "броня", "apparel": "одежда", "aid": "помощь", "food": "еда/напитки", "plan": "схемы",
    "note": "записки", "ammo": "патроны", "holotape": "голодиски", "key": "ключи и пароли", "misc": "разное",
    "junk": "хлам", "other": "прочее",
}


EVENT_KINDS = {
    "season": "Сезон (табло)", "seasonal_event": "Сезонное событие", "minerva": "Минерва", "dailyops": "Daily Ops",
    "doublexp": "Двойной опыт / бонус", "other": "Другое",
}


def con():
    return db.connect()


# Персонажи с понятными именами и цветами из профилей
CHARS_SQL = (
    "SELECT c.id, c.account, c.name, coalesce(p.label, c.name) AS label, p.color, coalesce(p.mule, 0) AS mule, coalesce(p.priority, 100) AS priority,"
    " coalesce(a.label, c.account) AS account_label, a.color AS account_color FROM characters c"
    " LEFT JOIN profiles p ON p.character_id = c.id LEFT JOIN account_labels a ON a.account = c.account"
)


THEMES = ("vault", "amber", "classic")  # vault — по умолчанию; названия и подписи — в settings.html


def theme_of(request: Request) -> str:
    """Стиль оформления из cookie fo76_theme (ставит страница настроек); чужое значение — по умолчанию."""
    t = request.cookies.get("fo76_theme")
    return t if t in THEMES else THEMES[0]


LAYOUTS = ("pipboy", "classic")  # pipboy — по умолчанию: вкладки в духе Pip-Boy и строка состояния внизу


def layout_of(request: Request) -> str:
    t = request.cookies.get("fo76_layout")
    return t if t in LAYOUTS else LAYOUTS[0]


def page(request: Request, name: str, **ctx) -> HTMLResponse:
    pid = features.page_for_path(request.url.path)
    if not features.page_on(pid):  # вкладка выключена в «Настройки → Разделы и сервисы»
        name, ctx = "disabled.html", {"page_label": features.PAGES[pid][0]}
    c = con()
    ctx.update(
        meta={r[0]: r[1] for r in c.execute("SELECT key, value FROM meta")},
        all_chars=[dict(r) for r in c.execute(CHARS_SQL + " ORDER BY c.account, label")],
        KIND_RU=KIND_RU, SUBKIND_RU=SUBKIND_RU, CATEGORY_RU=CATEGORY_RU, EVENT_KINDS=EVENT_KINDS,
        theme=theme_of(request), layout=layout_of(request), csp_nonce=getattr(request.state, "nonce", ""),
        mod_warn=mods.missing_for(request.url.path),
    )
    return templates.TemplateResponse(request, name, ctx)


def _color(v: str | None) -> str | None:
    if v and not re.fullmatch(r"#[0-9a-fA-F]{6}", v):
        raise HTTPException(400, "Цвет должен быть в виде #rrggbb")
    return v or None
