"""Журнал приложения: всё, что serve / watch / desktop печатают в stdout и stderr (в том числе журнал uvicorn
и трассировки), дублируется в data/app.log. Показывается в «Настройки → Журнал».

Несколько процессов (serve и watch) дописывают в один файл построчно; при старте файл больше 2 МБ обрезается до последних ~1 МБ.
"""
from __future__ import annotations

import logging
import re
import sys
import threading
import time

from . import db

PATH = db.DATA / "app.log"
MAX_BYTES = 2_000_000
KEEP_BYTES = 1_000_000
ANSI = re.compile(r"\x1b\[[0-9;]*m")
# опрос страниц и статика забивают журнал: строки доступа uvicorn к ним не пишем
NOISE = re.compile(r'"GET /(static/|api/tasks|api/log|sw\.js|manifest)')

_installed = False


def _trim() -> None:
    try:
        if PATH.stat().st_size > MAX_BYTES:
            tail = PATH.read_bytes()[-KEEP_BYTES:]
            PATH.write_bytes(tail[tail.find(b"\n") + 1:])
    except OSError:
        pass


class _Tee:
    """Файл-обёртка: пишет в исходный поток (если он есть) и построчно в журнал."""

    def __init__(self, base, file, tag: str, lock: threading.Lock):
        self._base, self._file, self._tag, self._lock, self._buf = base, file, tag, lock, ""

    def write(self, s: str) -> int:
        if self._base is not None:
            try:
                self._base.write(s)
            except Exception:
                pass
        with self._lock:
            self._buf += s
            *lines, self._buf = self._buf.split("\n")
            stamp = time.strftime("%Y-%m-%d %H:%M:%S")
            for line in lines:
                line = ANSI.sub("", line.rstrip("\r"))
                if line.strip() and not NOISE.search(line):
                    self._file.write(f"{stamp} {self._tag} {line}\n")
        return len(s)

    def flush(self) -> None:
        if self._base is not None:
            try:
                self._base.flush()
            except Exception:
                pass
        self._file.flush()

    def isatty(self) -> bool:
        return bool(self._base is not None and self._base.isatty())

    def __getattr__(self, name):  # encoding, fileno, reconfigure, ...
        if self._base is None:
            raise AttributeError(name)
        return getattr(self._base, name)


def setup(name: str) -> None:
    """Включить дублирование вывода в data/app.log. name — процесс: serve, watch, desktop."""
    global _installed
    if _installed:
        return
    _installed = True
    PATH.parent.mkdir(parents=True, exist_ok=True)
    _trim()
    f = open(PATH, "a", encoding="utf-8", buffering=1)  # noqa: SIM115 — открыт до конца процесса
    lock = threading.Lock()
    sys.stdout = _Tee(sys.stdout, f, f"[{name}]", lock)
    sys.stderr = _Tee(sys.stderr, f, f"[{name}:err]", lock)
    logging.basicConfig(level=logging.INFO, stream=sys.stderr, force=True, datefmt="%H:%M:%S",
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    print(f"--- запуск {name}")

    def hook(args):  # необработанное исключение потока (watch, фоновые задачи)
        import traceback
        print(f"поток {args.thread.name if args.thread else '?'}: ошибка", file=sys.stderr)
        traceback.print_exception(args.exc_type, args.exc_value, args.exc_traceback)
    threading.excepthook = hook


def tail(lines: int = 500) -> dict:
    """Последние строки журнала для страницы настроек."""
    try:
        size = PATH.stat().st_size
        with open(PATH, "rb") as f:
            f.seek(max(0, size - 400_000))
            text = f.read().decode("utf-8", "replace")
    except OSError:
        return {"path": str(PATH), "size": 0, "lines": []}
    return {"path": str(PATH), "size": size, "lines": text.splitlines()[-lines:]}
