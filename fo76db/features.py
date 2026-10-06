"""Что включено в интерфейсе: вкладки (страницы), блоки внутри страниц и обращения к внешним сервисам.

Переключатели хранятся в `data/features.json` — словарь `{ключ: true|false}`; чего в нём нет, включено по умолчанию
(кроме проверки обновлений: её исходное значение — `update_check` из config.toml). Ключи: `page:<id>`, `section:<id>`, `service:<id>`, `notify:<id>`.
Файл читают и `serve`, и `watch` (по времени изменения), поэтому перезапуск не нужен.

- страница выключена → пропадает из меню, адрес показывает «Раздел отключён» (API остаются: ими пользуются соседние страницы);
- блок выключен → его нет на странице; блок, которому нужен сервис, скрывается и при выключенном сервисе;
- сервис выключен → программа не обращается к его адресам (`require` в источниках, пропуск в `watch`, кнопки обновления отвечают отказом).
"""
from __future__ import annotations

import json

from . import config
from .db import DATA

FILE = DATA / "features.json"


class ServiceOff(RuntimeError):
    """Обращение к внешнему сервису, который выключен в «Настройки → Разделы и сервисы»."""


# id → (подпись, адреса для сопоставления с путём, пояснение). Главная и настройки не отключаются.
PAGES = {
    "events": ("События", ("/events",), "Календарь событий, Daily Ops, ежедневки, Минерва, онлайн Steam"),
    "updates": ("Обновления", ("/updates",), "Что добавляли в обновлениях и Update Notes из Steam"),
    "achievements": ("Достижения", ("/achievements",), "Редкость достижений Steam"),
    "inventory": ("Инвентарь", ("/inventory",), "Таблица предметов по персонажам и тайникам"),
    "optimize": ("Вес", ("/optimize",), "Куда уходит вес и что можно убрать"),
    "rolls": ("Роллы", ("/rolls",), "Нужные роллы легендарок: оценка и уведомления"),
    "iom": ("IOM", ("/iom",), "Редактор правил Invent-O-Matic"),
    "catalog": ("Каталог", ("/", "/item"), "Каталог предметов и страницы предметов"),
    "plans": ("Схемы", ("/plans",), "Схемы и рецепты: что изучено, что передать"),
    "legendary": ("Легендарные моды", ("/legendary",), "Список легендарных модов"),
    "history": ("История", ("/history",), "Выгрузки инвентаря и изменения между ними"),
    "glossary": ("Глоссарий", ("/glossary",), "Пояснения терминов"),
}

# id → (страница, подпись, сервис или None, пояснение)
SECTIONS = {
    "home.categories": ("home", "По категориям", None, "Сводная таблица предметов по категориям"),
    "events.dailyops": ("events", "Daily Ops", "wiki", "Режим дня и места из списков fallout.wiki"),
    "events.checklist": ("events", "Ежедневки", None, "Чек-лист ежедневных и еженедельных дел по персонажам"),
    "events.minerva": ("events", "Минерва", "falloutbuilds", "Где торгует Минерва и какие схемы"),
    "events.online": ("events", "Онлайн в Steam", "steam", "График числа игроков"),
    "events.heatmap": ("events", "Когда играют", "steam", "Средний онлайн по дням недели и часам"),
    "updates.steam": ("updates", "Update Notes из Steam", "steam", "Заметки к патчам и ваша сборка"),
    "item.obtain": ("item", "Как получить", "wiki", "Откуда берётся предмет (по данным вики)"),
    "shell.nukes": ("*", "Коды ракет в строке состояния", "nukacrypt", "Коды запуска на всех страницах"),
}

# id → (название, адреса, зачем, что перестанет работать, включён по умолчанию)
SERVICES = {
    "steam": ("Steam", ("api.steampowered.com", "steamcommunity.com"),
              "Update Notes, число игроков онлайн, редкость достижений",
              "Update Notes, график и карта онлайна, страница достижений перестанут обновляться"),
    "falloutbuilds": ("falloutbuilds.com", ("www.falloutbuilds.com",),
                      "Календарь событий и распродажи Минервы", "календарь событий и Минерва не обновятся"),
    "wiki": ("Fallout Wiki (fallout.wiki, Fandom)", ("fallout.wiki", "fallout.fandom.com"),
             "Сезоны, Daily Ops, список патчей, «Как получить»", "сезоны, Daily Ops, патчи и «Как получить» не обновятся"),
    "nukacrypt": ("NukaCrypt", ("api.nukacrypt.com",), "Коды запуска ракет", "коды ракет пропадут из строки состояния"),
    "dumps": ("GitHub: fo76-dumps", ("api.github.com", "github.com"),
              "Каталог предметов и история версий (релизы выгрузок игры)", "каталог и история не обновятся — останутся прежние данные"),
    "updates": ("GitHub: новые версии FO76 DB", ("api.github.com",),
                "Раз в 6 часов спрашивает, не вышла ли новая версия утилиты", "баннер «вышла новая версия» не появится"),
}

# id → (подпись, пояснение). Выключенное уведомление не показывается, но считается отправленным (при включении старое не придёт).
NOTIFY = {
    "release": ("Новый патч игры", "Вышли новые данные fo76-dumps (обновите каталог)"),
    "steamnews": ("Заметки к обновлению (Steam)", "Вышли новые Update Notes"),
    "build": ("Игра обновилась", "Сменилась сборка (BuildID) установленной игры"),
    "appupdate": ("Новая версия FO76 DB", "На GitHub вышел релиз новее установленного"),
    "events": ("События", "Событие началось или начнётся в ближайшие сутки"),
    "wishlist": ("Вишлист", "Предмет из вишлиста упомянут в событии или продаётся у Минервы"),
    "rolls": ("Нужные роллы", "В инвентаре или тайнике появился предмет, подходящий под хотелку"),
}

_cache: tuple | None = None


def _saved() -> dict[str, bool]:
    """Явные переключатели из data/features.json (кэш по времени изменения файла)."""
    global _cache
    try:
        sig = FILE.stat().st_mtime_ns
    except OSError:
        sig = None
    if _cache is None or _cache[0] != sig:
        raw = config._read_json(FILE)  # noqa: SLF001 — тот же чтец JSON, что для paths.json
        _cache = (sig, {k: v for k, v in raw.items() if isinstance(k, str) and isinstance(v, bool)})
    return _cache[1]


def _default(kind: str, key: str) -> bool:
    return bool(config.load().get("update_check", True)) if (kind, key) == ("service", "updates") else True


def _flag(kind: str, key: str) -> bool:
    return _saved().get(f"{kind}:{key}", _default(kind, key))


def service_on(key: str) -> bool:
    return _flag("service", key)


def notify_on(key: str) -> bool:
    return _flag("notify", key)


def require(key: str) -> None:
    """Вызывается перед каждым обращением к сервису: выключен — ServiceOff."""
    if not service_on(key):
        raise ServiceOff(f"сервис «{SERVICES[key][0]}» отключён в настройках")


def page_for_path(path: str) -> str | None:
    """Идентификатор страницы по адресу; None — не отключаемая (главная, настройки, служебные)."""
    for pid, (_, paths, _) in PAGES.items():
        if path in paths or (path == "/item" or path.startswith("/item/")) and "/item" in paths:
            return pid
    return None


def page_on(pid: str | None) -> bool:
    return pid is None or _flag("page", pid)


def path_on(path: str) -> bool:
    return page_on(page_for_path(path))


def on(section: str) -> bool:
    """Блок виден: включены он сам, его страница и нужный сервис."""
    page, _, service, _ = SECTIONS[section]
    return _flag("section", section) and (page == "*" or page not in PAGES or page_on(page)) and (service is None or service_on(service))


def save(values: dict) -> None:
    """Применить переключатели `{ключ: bool}`; неизвестные ключи — ValueError. Значение «по умолчанию» не хранится."""
    cur = dict(_saved())
    for k, v in values.items():
        kind, _, key = str(k).partition(":")
        known = {"page": PAGES, "section": SECTIONS, "service": SERVICES, "notify": NOTIFY}.get(kind)
        if known is None or key not in known or not isinstance(v, bool):
            raise ValueError(f"неизвестный переключатель: {k}")
        if v == _default(kind, key):
            cur.pop(f"{kind}:{key}", None)
        else:
            cur[f"{kind}:{key}"] = v
    config.write_atomic(FILE, json.dumps(cur, ensure_ascii=False, indent=2))


def describe() -> dict:
    """Для страницы настроек: все переключатели с текущим состоянием."""
    return {
        "pages": [{"key": f"page:{i}", "label": lab, "path": paths[0], "hint": hint, "on": _flag("page", i)}
                  for i, (lab, paths, hint) in PAGES.items()],
        "sections": [{"key": f"section:{i}", "label": lab, "page": page, "service": svc, "hint": hint, "on": _flag("section", i),
                      "visible": on(i)} for i, (page, lab, svc, hint) in SECTIONS.items()],
        "services": [{"key": f"service:{i}", "label": name, "hosts": list(hosts), "why": why, "off_effect": off, "on": _flag("service", i)}
                     for i, (name, hosts, why, off) in SERVICES.items()],
        "notifications": [{"key": f"notify:{i}", "label": lab, "hint": hint, "on": _flag("notify", i)} for i, (lab, hint) in NOTIFY.items()],
        "page_names": {i: v[0] for i, v in PAGES.items()} | {"home": "Главная", "item": "Страница предмета", "*": "Все страницы"},
    }
