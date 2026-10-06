"""Командная строка: python -m fo76db <команда>."""
from __future__ import annotations

import argparse
import logging
import os
import sys

from . import db


def cmd_catalog(args) -> None:
    from .importers import catalog
    from .sources import dumps

    con = db.connect()
    releases = dumps.list_releases()
    rel = next(r for r in releases if r["tag"] == args.tag) if args.tag else catalog.latest_release(releases)
    print(f"Каталог из релиза {rel['tag']}")
    catalog.build(con, rel)


def cmd_history(args) -> None:
    from .importers import history

    if args.relabel:
        print("Названия обновлений по таблице патчей Fallout Wiki")
        history.relabel(db.connect())
        return
    print("История версий (fo76-dumps, все стабильные релизы)")
    history.build(db.connect(), workers=args.workers)


def cmd_import(args) -> None:
    from . import config
    from .importers import inventory

    cfg = config.load()
    con = db.connect()
    files = [config.Path(p) for p in args.files] if args.files else config.expand(cfg["inventory"])
    for path in files:
        print(f"Инвентарь: {path}")
        inventory.import_file(con, path)
    for path in config.expand(cfg["legendary_mods"]):
        print(f"Легендарные моды: {path}")
        inventory.import_legendary_mods(con, path)
    from . import notify
    notify.check_rolls(con)


def _running(url: str) -> bool:
    """На этом адресе уже отвечает FO76 DB (проверка по /static/app.css)."""
    import urllib.request
    try:
        with urllib.request.urlopen(url.removesuffix("/home") + "/static/app.css", timeout=1) as r:
            return r.status == 200
    except OSError:
        return False


def cmd_serve(args) -> None:
    import uvicorn

    from . import config

    cfg = config.load()
    host, port = args.host or cfg["host"], args.port or cfg["port"]
    url = f"http://{'127.0.0.1' if host in ('0.0.0.0', '::') else host}:{port}/home"
    if _running(url):
        # второй запуск из меню или двойной клик по exe: сервер уже работает — только открыть страницу
        print(f"FO76 DB уже запущен: {url}")
        if args.open:
            import webbrowser
            webbrowser.open(url)
        return
    if host not in ("127.0.0.1", "::1", "localhost") and not cfg.get("token") and not os.environ.get("FO76DB_ALLOW_OPEN"):
        sys.exit("Отказ: сервер на внешнем адресе без токена открыт всем в сети (запись конфига IOM, запуск загрузок)."
                 " Задайте token в config.toml или FO76DB_TOKEN (см. docs/pwa.md), например: python -c "
                 "\"import secrets; print(secrets.token_urlsafe(24))\" (FO76DB_ALLOW_OPEN=1 — снять проверку, если порт закрыт снаружи)")
    ssl = {k: cfg[k] for k in ("ssl_certfile", "ssl_keyfile") if cfg.get(k)}
    if (args.watch or cfg.get("serve_watch")) and not args.reload:
        import threading

        from . import watch
        threading.Thread(target=watch.run, name="fo76db-watch", daemon=True).start()
    if args.open:
        import threading
        import webbrowser
        threading.Timer(1.5, webbrowser.open, (url,)).start()
    if args.reload:
        uvicorn.run("fo76db.web.app:app", host=host, port=port, reload=True, **ssl)
    else:
        # объект приложения, а не строка: так модуль виден сборщику (PyInstaller)
        from .web.app import app
        app.state.bind_host = host
        uvicorn.run(app, host=host, port=port, proxy_headers=True, forwarded_allow_ips="127.0.0.1", **ssl)


def cmd_openapi(args) -> None:
    import json

    from .web.app import app
    text = json.dumps(app.openapi(), ensure_ascii=False, indent=2) + "\n"
    if args.output == "-":
        sys.stdout.write(text)
    else:
        from pathlib import Path
        Path(args.output).write_text(text, encoding="utf-8")
        print(f"Схема OpenAPI: {args.output}")


def cmd_desktop(args) -> None:
    try:
        import webview  # noqa: F401
    except ImportError:
        sys.exit('Нужен pywebview: pip install "fo76db[desktop]" (на Linux ставит и PySide6 с QtWebEngine)')
    from . import desktop
    desktop.run(watch=args.watch)


def cmd_watch(args) -> None:
    from . import watch

    watch.run(args.interval)


def cmd_events(args) -> None:
    from . import events

    r = events.refresh(db.connect())
    print(f"Календарь: {r.get('calendar', '—')} событий, схем Минервы: {r.get('minerva_plans', '—')}, сезонов: {r.get('seasons', '—')}")
    for e in r["errors"]:
        print(f"  ошибка: {e}")


def cmd_steam(args) -> None:
    from . import steam

    r = steam.refresh(db.connect())
    print(f"Новостей: {r.get('total', '—')}, новых патчей: {r.get('new_patches', '—')}, онлайн: {r.get('online', '—')}, сборка: {r.get('build') or '—'}")
    for e in r["errors"]:
        print(f"  ошибка: {e}")


def cmd_backup(args) -> None:
    from . import maintenance

    print(f"Копия базы: {maintenance.backup(args.out, args.keep)}")


def cmd_doctor(args) -> None:
    from . import maintenance

    marks = {True: "✔", False: "✘", None: "!"}
    rows = maintenance.doctor()
    for r in rows:
        print(f"{marks[r['ok']]} {r['name']}: {r['detail']}" + (f"\n    → {r['hint']}" if r["hint"] else ""))
    if any(r["ok"] is False for r in rows):
        sys.exit(1)


def cmd_notify(args) -> None:
    from . import notify

    notify.check(db.connect())


def _utf8_output() -> None:
    """Вывод в UTF-8 и там, где по умолчанию стоит cp1252: Windows, вывод в pipe или файл (CI, `> serve.log`).
    Иначе кириллица в --help, --version и журналах падает с UnicodeEncodeError."""
    for stream in (sys.stdout, sys.stderr):
        if stream and (stream.encoding or "").lower().replace("-", "") != "utf8" and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def main(argv=None) -> None:
    from . import __version__

    _utf8_output()

    p = argparse.ArgumentParser(prog="fo76db", description="База предметов, инвентаря и событий Fallout 76")
    p.add_argument("--version", action="version", version=f"fo76db {__version__} (данные: {db.ROOT})")
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("catalog", help="собрать каталог предметов (игра + последний релиз fo76-dumps)")
    c.add_argument("--tag", help="конкретный релиз fo76-dumps вместо последнего")
    c.set_defaults(func=cmd_catalog)

    c = sub.add_parser("history", help="заполнить «добавлено в версии» по всем релизам fo76-dumps (долго в первый раз)")
    c.add_argument("--workers", type=int, default=4)
    c.add_argument("--relabel", action="store_true", help="только обновить названия обновлений по вики, без скачивания")
    c.set_defaults(func=cmd_history)

    c = sub.add_parser("import", help="импорт инвентаря (itemsmod.json) и легендарных модов (LegendaryMods.ini)")
    c.add_argument("files", nargs="*", help="файлы itemsmod.json (по умолчанию — из config.toml)")
    c.set_defaults(func=cmd_import)

    c = sub.add_parser("serve", help="веб-интерфейс (по умолчанию http://127.0.0.1:7676)")
    c.add_argument("--host")
    c.add_argument("--port", type=int)
    c.add_argument("--reload", action="store_true", help="перезапуск при изменении кода")
    c.add_argument("--open", action="store_true", help="открыть страницу в браузере")
    c.add_argument("--watch", action="store_true", help="заодно следить за выгрузками (как `watch`), без второго процесса; или serve_watch = true в config.toml")
    c.set_defaults(func=cmd_serve)

    c = sub.add_parser("openapi", help="выгрузить схему OpenAPI (для генерации клиентов и сторонних фронтендов)")
    c.add_argument("-o", "--output", default="docs/openapi.json", help="файл (по умолчанию docs/openapi.json; - — в stdout)")
    c.set_defaults(func=cmd_openapi)

    c = sub.add_parser("desktop", help="веб-интерфейс в отдельном окне (Linux — Qt, Windows — WebView2); нужен extra [desktop]")
    c.add_argument("--no-watch", dest="watch", action="store_false", default=None, help="без слежения за выгрузками")
    c.set_defaults(func=cmd_desktop)

    c = sub.add_parser("watch", help="автоимпорт при изменении itemsmod.json / LegendaryMods.ini, обновление событий раз в 6 ч")
    c.add_argument("--interval", type=float, default=5.0)
    c.set_defaults(func=cmd_watch)

    c = sub.add_parser("events", help="обновить календарь событий, Минерву и сезоны (falloutbuilds.com, fallout.wiki)")
    c.set_defaults(func=cmd_events)

    c = sub.add_parser("steam", help="обновить Update Notes из Steam, замерить онлайн, проверить сборку игры")
    c.set_defaults(func=cmd_steam)

    c = sub.add_parser("backup", help="копия базы (теги, вишлист, роллы, история инвентаря) в data/db-backups")
    c.add_argument("--out", help="папка для копии (по умолчанию data/db-backups)")
    c.add_argument("--keep", type=int, default=10, help="сколько копий хранить (0 — не удалять старые)")
    c.set_defaults(func=cmd_backup)

    c = sub.add_parser("doctor", help="проверка окружения: игра, моды, 7-Zip, база, доступ из сети")
    c.set_defaults(func=cmd_doctor)

    c = sub.add_parser("notify", help="разовая проверка уведомлений (новый патч, события, вишлист)")
    c.set_defaults(func=cmd_notify)

    if argv is None:
        argv = sys.argv[1:]
    # exe/бинарник, запущенный двойным кликом: сразу веб-интерфейс в браузере
    if not argv and getattr(sys, "frozen", False):
        argv = ["serve", "--open"]
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")  # serve/watch/desktop заменят форматом с временем (applog)
    if args.cmd in ("serve", "watch"):  # desktop включает журнал сам
        from . import applog
        applog.setup(args.cmd)
    args.func(args)


if __name__ == "__main__":
    main(sys.argv[1:])
