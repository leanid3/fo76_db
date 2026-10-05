"""Собирает THIRD_PARTY_LICENSES.txt: лицензии всего, что попадает в бинарник и exe (Python, зависимости fo76db, Tabulator).

MIT, BSD и PSF требуют прикладывать текст лицензии к копиям, а PyInstaller не кладёт в файл dist-info пакетов.
Запуск из корня репозитория в том окружении, где установлен fo76db: python packaging/third_party.py [файл] [extra ...]
(десктоп-версия: ... THIRD_PARTY_LICENSES-desktop.txt desktop — добавит pywebview, PySide6/Qt, pythonnet)
"""
from __future__ import annotations

import importlib.metadata as md
import re
import sys
import sysconfig
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LICENSE_NAME = re.compile(r"(LICEN[CS]E|COPYING|NOTICE|AUTHORS)", re.I)


def _name(req: str) -> str:
    return re.split(r"[\s;\[<>=!~(]", req, maxsplit=1)[0]


def distributions(root: str = "fo76db", extras: tuple[str, ...] = ()) -> list[md.Distribution]:
    """fo76db и всё, что он тянет (плюс указанные extras), по метаданным установленных пакетов."""
    import tomllib
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    seen: dict[str, md.Distribution] = {}
    todo = [root] + [_name(r) for e in extras for r in project["optional-dependencies"][e]
                     if ";" not in r or _marker_ok(r.split(";", 1)[1])]
    try:
        md.distribution(root)
    except md.PackageNotFoundError:  # запуск из исходников без pip install: зависимости — из pyproject.toml
        todo = [_name(r) for r in project["dependencies"]] + todo[1:]
    while todo:
        name = todo.pop()
        key = name.lower().replace("_", "-")
        if key in seen:
            continue
        try:
            dist = md.distribution(name)
        except md.PackageNotFoundError:
            continue  # условная зависимость не для этой системы
        seen[key] = dist
        for req in dist.requires or []:
            if "extra ==" in req:
                continue
            marker = req.split(";", 1)[1] if ";" in req else ""
            if marker and not _marker_ok(marker):
                continue
            todo.append(_name(req))
    seen.pop("fo76db", None)
    return sorted(seen.values(), key=lambda d: d.metadata["Name"].lower())


def _marker_ok(marker: str) -> bool:
    try:
        from packaging.markers import Marker
        return Marker(marker).evaluate()
    except Exception:
        return True


def _license_texts(dist: md.Distribution) -> list[tuple[str, str]]:
    out = []
    for f in dist.files or []:
        if LICENSE_NAME.search(f.name) and not f.name.endswith((".py", ".pyc")):
            try:
                out.append((str(f), Path(dist.locate_file(f)).read_text(encoding="utf-8", errors="replace")))
            except OSError:
                pass
    return out


def build(extras: tuple[str, ...] = ()) -> str:
    parts = ["Сторонние компоненты в сборке FO76 DB (бинарник Linux, exe Windows" + (", десктоп-версия" if extras else "") + ").",
             "Сама FO76 DB — GNU AGPL v3 или новее (LICENSE), благодарности и источники — CREDITS.md.", ""]
    sep = "=" * 78

    py_license = Path(sysconfig.get_paths()["stdlib"]) / "LICENSE.txt"
    parts += [sep, f"Python {sys.version.split()[0]} — PSF License", "https://www.python.org/", sep]
    parts.append(py_license.read_text(encoding="utf-8", errors="replace") if py_license.is_file()
                 else "Python Software Foundation License Version 2: https://docs.python.org/3/license.html")

    tab = ROOT / "fo76db/web/static/tabulator.LICENSE.txt"
    parts += [sep, "Tabulator — MIT", sep, tab.read_text(encoding="utf-8")]

    parts += [sep, "PyInstaller (загрузчик) — GPL-2.0 с исключением для загрузчика: собранная программа может иметь",
              "любую лицензию. https://github.com/pyinstaller/pyinstaller/blob/develop/COPYING.txt", sep, ""]

    for dist in distributions(extras=extras):
        meta = dist.metadata
        lic = (meta.get("License-Expression") or next(iter((meta.get("License") or "").splitlines()), "")
               or ", ".join(c.rsplit(" :: ", 1)[-1] for c in meta.get_all("Classifier") or [] if c.startswith("License")))
        url = meta.get("Home-page") or next((u.split(", ", 1)[-1] for u in meta.get_all("Project-URL") or []), "")
        parts += [sep, f"{meta['Name']} {dist.version} — {lic}".rstrip(" —"), url, sep]
        texts = _license_texts(dist)
        parts += [f"--- {name}\n{text}" for name, text in texts] or ["(текст лицензии в пакете не найден)"]
    return "\n".join(parts) + "\n"


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):  # Windows (Actions): консоль в cp1252, кириллица в выводе падала
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    dest = Path(sys.argv[1] if len(sys.argv) > 1 else "THIRD_PARTY_LICENSES.txt")
    dest.write_text(build(tuple(sys.argv[2:])), encoding="utf-8")
    print(f"{dest}: {dest.stat().st_size // 1024} КБ")
