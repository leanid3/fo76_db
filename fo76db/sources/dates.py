"""Английские даты с вики и сайтов без strptime: %b и %B зависят от локали процесса, а Qt (десктоп-версия) при запуске
выставляет её из окружения, и при русской локали «Nov 12» уже не разбирается."""
from __future__ import annotations

import datetime as dt

_MONTHS = {m: i for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), 1)}


def month_number(name: str) -> int:
    """«Oct», «October», «oct.» → 10."""
    return _MONTHS[name.strip().lower()[:3]]


def english_date(month: str, day: str | int, year: str | int) -> dt.date:
    return dt.date(int(year), month_number(month), int(day))


def nearest_year(month: str, day: str | int, today: dt.date) -> dt.date:
    """Дата без года: год (в пределах ±4 лет, чтобы нашёлся и високосный для 29 февраля), при котором она ближе всего к today."""
    m, d = month_number(month), int(day)
    cands = []
    for year in range(today.year - 4, today.year + 5):
        try:
            cands.append(dt.date(year, m, d))
        except ValueError:  # 29 февраля в невисокосном году
            continue
    return min(cands, key=lambda x: abs((x - today).days))
