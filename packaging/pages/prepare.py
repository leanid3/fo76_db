"""Готовит исходники сайта документации (GitHub Pages, MkDocs) в build/pages-src.

README.md становится главной, docs/*.md — страницами, CHANGELOG/CREDITS/LICENSE — отдельными страницами.
Относительные ссылки переписываются: на страницу сайта, если файл стал страницей, иначе — на файл в репозитории на GitHub.
Запуск из корня репозитория: python packaging/pages/prepare.py && mkdocs build
"""
from __future__ import annotations

import posixpath
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
OUT = ROOT / "build" / "pages-src"
REPO = "https://github.com/leanid3/fo76_db"

# файл репозитория → страница сайта
PAGES = {
    "README.md": "index.md",
    "docs/README.md": "documentation.md",
    "CHANGELOG.md": "changelog.md",
    "CREDITS.md": "credits.md",
    "LICENSE": "license.md",
}
PAGES |= {f"docs/{p.name}": p.name for p in sorted((ROOT / "docs").glob("*.md")) if p.name != "README.md"}

LINK = re.compile(r"(\]\()([^)\s]+)(\))")

DOWNLOAD = f"""!!! tip "Скачать"
    [Последний релиз]({REPO}/releases/latest): exe для Windows, бинарник и Flatpak для Linux, wheel, образ Docker.
    Установка и запуск описаны в разделе [Сборка и установка](packaging.md), исходники лежат на [GitHub]({REPO}).

"""


def rewrite(text: str, src: str) -> str:
    base = posixpath.dirname(src)

    def repl(m: re.Match) -> str:
        target = m.group(2)
        if re.match(r"^[a-z][a-z0-9+.-]*:|^#|^/", target, re.I):
            return m.group(0)  # внешняя ссылка, якорь или абсолютный путь
        path, _, anchor = target.partition("#")
        repo_path = posixpath.normpath(posixpath.join(base, path)) if path else src
        if repo_path in PAGES:
            new = PAGES[repo_path]
        elif (ROOT / repo_path).exists():
            kind = "tree" if (ROOT / repo_path).is_dir() else "blob"
            new = f"{REPO}/{kind}/main/{repo_path}"
        else:
            return m.group(0)
        return f"{m.group(1)}{new}{'#' + anchor if anchor else ''}{m.group(3)}"

    return LINK.sub(repl, text)


def main() -> None:
    shutil.rmtree(OUT, ignore_errors=True)
    OUT.mkdir(parents=True)
    for src, page in PAGES.items():
        text = rewrite((ROOT / src).read_text(encoding="utf-8"), src)
        if page == "index.md":
            # после заголовка и первого абзаца — блок «Скачать»
            head, sep, rest = text.partition("\n\n")
            head2, sep2, rest2 = rest.partition("\n\n")
            text = head + sep + head2 + sep2 + DOWNLOAD + rest2
        if page == "license.md":
            text = ("# Лицензия\n\nFO76 DB распространяется по GNU Affero General Public License версии 3 или новее "
                    "(`AGPL-3.0-or-later`). Кратко — в [README](index.md#лицензия), юридическую силу имеет английский текст:\n\n"
                    "```text\n" + text + "\n```\n")
        (OUT / page).write_text(text, encoding="utf-8")
    print(f"{OUT}: {len(PAGES)} страниц")


if __name__ == "__main__":
    main()
