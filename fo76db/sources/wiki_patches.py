"""Таблица патчей Fallout 76 с Fallout Wiki (MediaWiki API): версия -> номер и цикл обновления, дата.

Страница `Fallout_76_patches`, таблица «Multi-platform patches». Колонка «Update cycle» задаётся через rowspan
и переносится на следующие строки, пока не встретится новая.
"""
from __future__ import annotations

import json
import re
import urllib.request

from .dates import english_date

API = "https://fallout.fandom.com/api.php?action=parse&page=Fallout_76_patches&prop=wikitext&format=json"

DATE_RE = re.compile(r"(January|February|March|April|May|June|July|August|September|October|November|December) (\d{1,2}), (\d{4})")
PATCH_RE = re.compile(r"\[\[Fallout 76 patch ([\d.]+)\|[^\]]*\]\]\s*(\{\{[Pp]latforms\|([^}]*)\}\})?")


def _clean(cell: str) -> str:
    # `colspan="2" |text` -> `text`
    if re.match(r'^\s*(?:(?:row|col)span="\d+"\s*|style="[^"]*"\s*)+\|', cell):
        cell = cell.split("|", 1)[1]
    cell = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]*)\]\]", r"\1", cell)
    cell = re.sub(r"\{\{[^}]*\}\}", "", cell)
    return re.sub(r"''+", "", cell).replace("&ndash;", "").replace("<br />", " ").strip()


def _date(text: str) -> str | None:
    m = DATE_RE.search(text)
    if not m:
        return None
    return english_date(*m.groups()).isoformat()


def fetch_patches() -> list[dict]:
    """[{version, update, cycle, date}] для PC-версий (или общих для всех платформ)."""
    req = urllib.request.Request(API, headers={"User-Agent": "fo76db/0.1"})
    with urllib.request.urlopen(req, timeout=60) as r:
        text = json.loads(r.read())["parse"]["wikitext"]["*"]
    section = text.split("==Multi-platform patches==", 1)[1]
    section = section.split("\n|}", 1)[0]

    out, cycle = [], None
    for row in section.split("\n|-")[1:]:
        cells = [ln[1:] for ln in row.strip().split("\n") if ln.startswith("|") and not ln.startswith(("|-", "|}"))]
        if len(cells) < 3:
            continue
        versions = []
        for ver, _, plats in PATCH_RE.findall(cells[0]):
            if not plats or "pc" in plats.lower():
                versions.append(ver)
        update = _clean(cells[1]) or None
        date = None
        for i, c in enumerate(cells[2:], start=2):
            d = _date(c)
            if d:
                date = d
                if i == 3:  # перед датой есть ячейка цикла
                    cycle = _clean(cells[2]) or cycle
                break
        for v in versions:
            out.append({"version": v, "update": update, "cycle": cycle, "date": date})
    return out
