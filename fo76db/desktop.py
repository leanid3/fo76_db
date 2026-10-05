"""Десктоп-версия: веб-интерфейс в собственном окне вместо браузера (pywebview).

Движок окна: Linux — Qt (PySide6 + QtWebEngine), Windows — Microsoft Edge WebView2 (встроен в Windows 10/11).
Сервер запускается внутри процесса на 127.0.0.1 и останавливается при закрытии окна. Если FO76 DB уже запущен
(serve или другая копия), окно просто открывается на нём. По умолчанию заодно работает слежение за выгрузками (как `watch`).
Запуск: fo76db desktop (нужен extra: pip install "fo76db[desktop]"), собранные fo76db-desktop.exe / fo76db-desktop.
"""
from __future__ import annotations

import os
import socket
import sys
import threading
import time
from pathlib import Path

from . import applog, config, db


def _free(host: str, port: int) -> bool:
    with socket.socket() as s:
        try:
            s.bind((host, port))
            return True
        except OSError:
            return False


def _start_server(host: str, port: int):
    import uvicorn

    from .web.app import app
    app.state.bind_host = host
    server = uvicorn.Server(uvicorn.Config(app, host=host, port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, name="fo76db-server", daemon=True)
    thread.start()
    for _ in range(150):  # до 15 с
        if server.started:
            return server, thread
        if not thread.is_alive():
            raise RuntimeError("сервер не запустился, подробности — в журнале")
        time.sleep(0.1)
    raise RuntimeError("сервер не ответил за 15 с")


def _gui() -> str | None:
    if sys.platform.startswith("linux"):
        os.environ.setdefault("QT_API", "pyside6")
        return "qt"
    return None  # Windows: edgechromium (WebView2) — выбор pywebview по умолчанию


def run(watch: bool | None = None) -> None:
    # вывод дублируется в data/app.log; без консоли (exe Windows, запуск из меню) он только там
    applog.setup("desktop")
    import webview

    from .cli import _running

    cfg = config.load()
    host = "127.0.0.1"
    port = int(cfg["port"])
    server = None
    if not _running(f"http://{host}:{port}/home"):
        if not _free(host, port):  # порт занят чем-то другим — любой свободный
            with socket.socket() as s:
                s.bind((host, 0))
                port = s.getsockname()[1]
        server, _ = _start_server(host, port)
        if cfg.get("desktop_watch", True) if watch is None else watch:
            from . import watch as watcher
            threading.Thread(target=watcher.run, name="fo76db-watch", daemon=True).start()
    url = f"http://{host}:{port}/home"
    print(f"Окно: {url}")

    webview.settings["ALLOW_DOWNLOADS"] = True                 # экспорт CSV/JSON
    webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True  # вики, fo76-dumps — в системном браузере
    webview.create_window("FO76 DB", url, width=1440, height=900, min_size=(800, 560), text_select=True)
    icon = Path(__file__).parent / "web" / "static" / "icons" / "icon-512.png"
    webview.start(gui=_gui(), private_mode=False, storage_path=str(db.DATA / "webview"), icon=str(icon))

    if server is not None:
        server.should_exit = True
        time.sleep(0.5)


def main() -> None:
    """Точка входа собранной десктоп-версии: без аргументов — окно, с аргументами — обычные команды fo76db."""
    if len(sys.argv) > 1:
        from .cli import main as cli_main
        cli_main()
    else:
        run()
