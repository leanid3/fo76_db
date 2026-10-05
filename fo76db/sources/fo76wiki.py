"""Сезоны, варианты Daily Ops и раздел «как получить» предмета с fallout.wiki.

- `Fallout_76_Seasons`: таблица собирается шаблоном, поэтому разбирается готовый HTML страницы.
  Строка: номер, картинка, название сезона, обновление, дата начала. Конца в таблице нет — сезон идёт до начала следующего.
- `Daily_Ops/Variables` (вики-разметка, `?action=raw`): режимы (Uplink, Decryption) с закреплённой мутацией, мутации (`; '''Имя'''`), места, фракции.
"""
from __future__ import annotations

import html
import json
import re
import urllib.parse

from . import net
from .dates import english_date

PAGE = "https://fallout.wiki/wiki/"
UA = {"User-Agent": "fo76db/0.1"}

ROW_RE = re.compile(r"<tr>\s*<td>(\d+)\s*</td>(.*?)</tr>", re.S)
CELL_RE = re.compile(r"<td[^>]*>(.*?)</td>", re.S)
DATE_RE = re.compile(r"(January|February|March|April|May|June|July|August|September|October|November|December) (\d{1,2}), (\d{4})")
LINK_RE = re.compile(r"\[\[(?:[^|\]]*\|)?([^\]]*)\]\]")

# Если вики недоступна: списки на сентябрь 2026
DAILYOPS_FALLBACK = {
    "modes": {"Uplink": "Piercing Gaze", "Decryption": "Savage Strike"},
    "locations": ["Arktos Pharma Biome Labs", "Charleston Capitol Building", "Garrahan Mining Headquarters", "Morgantown High School",
                  "The Burning Mine", "The Burrows", "Uncanny Caverns", "Valley Galleria", "Vault 94", "Vault 96",
                  "Watoga Civic Center", "Watoga High School", "West Tek Research Center"],
    "factions": ["Aliens", "Blood Eagles", "Communists", "Mothman cultists", "Mole Miners", "Robots", "Scorched", "Super Mutants"],
    "mutations": ["Active Camouflage", "Freezing Touch", "Group Regeneration", "Piercing Gaze", "Reflective Skin", "Resilient",
                  "Savage Strike"],
}


def _get(url: str, timeout: float = 30) -> str:
    # обычные адреса страниц: `api.php?action=parse` без кэша на сервере отвечает до минуты
    return net.get(url, UA, timeout)


def _text(s: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", s)).strip()


def parse_seasons(page: str) -> list[dict]:
    """[{number, name, update, start: date}] по возрастанию номера."""
    out = []
    for num, rest in ROW_RE.findall(page.split('id="Legacy_Seasons"', 1)[0]):
        texts = [t for t in map(_text, CELL_RE.findall(rest)) if t]
        date = next((DATE_RE.search(c) for c in texts if DATE_RE.search(c)), None)
        if not date or len(texts) < 3:
            continue
        start = english_date(*date.groups())
        out.append({"number": int(num), "name": texts[0], "update": texts[1], "start": start})
    return sorted(out, key=lambda s: s["number"])


def fetch_seasons() -> list[dict]:
    return parse_seasons(_get(PAGE + "Fallout_76_Seasons"))


def parse_dailyops(text: str) -> dict:
    def section(name: str) -> str:
        return text.split(f"=={name}==", 1)[-1].split("\n==", 1)[0] if f"=={name}==" in text else ""

    modes = dict(re.findall(r"\[\[(\w+)\]\]\s*\n\|[^\n']*'''([^'\n]+)'''", section("Game modes")))
    mutations = re.findall(r"^;\s*'''([^']+)'''", section("Mutations"), re.M)
    locations = [LINK_RE.sub(r"\1", c).strip() for c in re.findall(r"\|style=[^|]*\|(\[\[[^\n]*)", section("Locations"))]
    factions = [LINK_RE.sub(r"\1", f).strip() for f in re.findall(r"^;\s*'''(.*?)'''\s*$", section("Factions"), re.M)]
    got = {"modes": modes, "locations": locations, "factions": factions, "mutations": mutations}
    return {k: v or DAILYOPS_FALLBACK[k] for k, v in got.items()}


def fetch_dailyops() -> dict:
    return parse_dailyops(_get(PAGE + "Daily_Ops/Variables?action=raw"))


# ---------- «Как получить» со страницы предмета ----------

OBTAIN_SECTIONS = re.compile(r"(?i)^(locations?|obtaining|acquisition|how to obtain|vendors?|rewards?)$")
# Русская вики: описание и где взять
OBTAIN_SECTIONS_RU = re.compile(r"(?i)^(описание|местонахождени\w*|получени\w*|где найти|торговц\w*|продавц\w*|награды?)$")
RU_BASE = "https://fallout.fandom.com/ru"
HEAD_RE = re.compile(r"^(=+)\s*(.*?)\s*\1\s*$", re.M)


# Где искать страницу предмета, по порядку: fandom полнее и быстрее получает новые предметы, fallout.wiki — запасной.
# `?action=raw` fandom закрывает (403), поэтому везде через api.php: `query` по нескольким названиям сразу и `opensearch`.
WIKIS = (("fallout.fandom.com", "https://fallout.fandom.com"), ("fallout.wiki", "https://fallout.wiki"))


def page_url(title: str, base: str = "https://fallout.wiki") -> str:
    return f"{base}/wiki/" + urllib.parse.quote(title.replace(" ", "_"))


def _api(base: str, **params) -> dict:
    return json.loads(_get(f"{base}/api.php?" + urllib.parse.urlencode({"format": "json", **params}), timeout=15))


def _pages(base: str, titles: list[str]) -> list[tuple[str, str]]:
    """[(название, вики-разметка)] существующих страниц, по перенаправлениям, в порядке запроса."""
    d = _api(base, action="query", prop="revisions", rvprop="content", rvslots="main", redirects=1, titles="|".join(titles))
    q = d.get("query", {})
    alias = {x["from"]: x["to"] for x in q.get("normalized", []) + q.get("redirects", [])}
    found = {p["title"]: p["revisions"][0]["slots"]["main"]["*"] for p in q.get("pages", {}).values() if "revisions" in p}
    out = []
    for t in titles:
        while t in alias:
            t = alias[t]
        if t in found and all(t != x for x, _ in out):
            out.append((t, found[t]))
    return out


def _search(base: str, name: str) -> list[str]:
    """Поиск без учёта регистра: «Phantom Outfit» найдёт страницу «Phantom outfit»."""
    titles = _api(base, action="opensearch", search=name, limit=8, redirects="resolve")[1]
    want = (name.lower(), f"{name} (fallout 76)".lower())
    return sorted((t for t in titles if t.lower() in want), key=lambda t: "(fallout 76)" not in t.lower())


def _plain(s: str) -> str:
    s = re.sub(r"<ref[^>]*/>|<ref[^>]*>.*?</ref>|<!--.*?-->", "", s, flags=re.S)
    s = re.sub(r"\{\{ID\|([0-9A-Fa-f]{8})\}\}", r"\1", s)
    s = re.sub(r"\{\{dot\}\}", "·", s)
    s = re.sub(r"\{\{#var:[^{}]*\}\}", "?", s)  # переменная, заданная на другой странице вики
    while re.search(r"\{\{[^{}]*\}\}", s):
        s = re.sub(r"\{\{[^{}]*\}\}", "", s)
    s = re.sub(r"\[\[(?:File|Image|Category):[^\]]*\]\]", "", s)
    s = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]*)\]\]", r"\1", s)
    s = re.sub(r"\[https?://\S+ ([^\]]+)\]", r"\1", s)
    s = re.sub(r"'{2,}", "", s)
    return re.sub(r"<[^>]+>", "", s)


def _to_html(text: str) -> str:
    """Вики-разметка раздела -> простой безопасный HTML (весь текст экранируется)."""
    out, in_list = [], False
    for line in _plain(text).splitlines():
        line = line.rstrip()
        if not line.strip() or line.startswith(("{|", "|", "!")):
            continue
        m = re.match(r"^(\*+)\s*(.*)", line)
        if m and not in_list:
            out.append("<ul>")
        elif not m and in_list:
            out.append("</ul>")
        in_list = bool(m)
        if m:
            out.append(f'<li style="margin-left:{(len(m[1]) - 1) * 16}px">{html.escape(m[2])}</li>')
        elif m := re.match(r"^;\s*(.*)", line):
            out.append(f"<div><b>{html.escape(m[1])}</b></div>")
        elif m := HEAD_RE.match(line):
            out.append(f"<h4>{html.escape(m[2])}</h4>")
        else:
            out.append(f"<p>{html.escape(line.lstrip(':'))}</p>")
    if in_list:
        out.append("</ul>")
    return "\n".join(out)


def sections(text: str, wanted: re.Pattern = OBTAIN_SECTIONS) -> list[tuple[str, str]]:
    """[(заголовок, разметка)] разделов о том, где взять предмет."""
    heads = list(HEAD_RE.finditer(text))
    out = []
    for i, h in enumerate(heads):
        if not wanted.match(h[2]):
            continue
        level = len(h[1])
        end = next((x.start() for x in heads[i + 1:] if len(x[1]) <= level), len(text))
        body = text[h.end():end].strip()
        if body:
            out.append((h[2], body))
    return out


def _accept(text: str, formid: int | None) -> bool:
    if "FO76" not in text and "Fallout 76" not in text:
        return False
    # в русской вики FormID короткий: {{ID|8E0691}}
    ids = {int(x, 16) for x in re.findall(r"\{\{ID\|([0-9A-Fa-f]{1,8})\}\}", text.split("}}\n", 1)[0])}
    return formid is None or not ids or formid in ids


SPLIT = "\n\n@@FO76DB-SECTION@@\n\n"


def _expand(base: str, title: str, bodies: list[str]) -> list[str]:
    """Раскрыть шаблоны в разделах (одним запросом на страницу). Например, в русской вики «Местонахождение» бывает
    одним шаблоном `{{LL DailyOps Rewards HighLVL Chase Rare}}` — без раскрытия раздел был бы пустым."""
    if not any("{{" in b for b in bodies):
        return bodies
    # переменные (#var) заданы в другом месте страницы и вне её пусты — оставляем «?»
    text = SPLIT.join(re.sub(r"\{\{#var:[^{}]*\}\}", "?", b) for b in bodies)
    try:
        out = _api(base, action="expandtemplates", prop="wikitext", title=title, text=text)["expandtemplates"]["wikitext"]
    except Exception:
        return bodies  # без раскрытия: шаблоны просто выпадут из текста
    parts = out.split(SPLIT.strip())
    return [p.strip() for p in parts] if len(parts) == len(bodies) else bodies


def _render(base: str, title: str, text: str, wanted: re.Pattern) -> str | None:
    secs = sections(text, wanted)
    bodies = _expand(base, title, [b for _, b in secs])
    html_parts = [(h, _to_html(b)) for (h, _), b in zip(secs, bodies)]
    return "\n".join(f"<h4>{html.escape(h)}</h4>\n{b}" for h, b in html_parts if b.strip()) or None


def _ru_page(en_title: str | None, name_ru: str | None, formid: int | None) -> dict | None:
    """Русская страница: по межъязыковой ссылке с английской страницы fandom, иначе по русскому названию из игры."""
    titles = []
    if en_title:
        q = _api(WIKIS[0][1], action="query", prop="langlinks", lllang="ru", redirects=1, titles=en_title).get("query", {})
        titles += [ll["*"] for p in q.get("pages", {}).values() for ll in p.get("langlinks", [])]
    if name_ru:
        # в игре кавычки прямые, на вики — «ёлочки»: «Схема: окраска "Свист в темноте"» -> «…«Свист в темноте»»
        for n in dict.fromkeys([name_ru, re.sub(r'"([^"]*)"', r"«\1»", name_ru)]):
            titles += [f"{n} (Fallout 76)", n]
    pages = _pages(RU_BASE, titles) if titles else []
    if not any(_accept(t, formid) for _, t in pages) and name_ru:
        found = _search(RU_BASE, re.sub(r'"([^"]*)"', r"«\1»", name_ru)) or _search(RU_BASE, name_ru)
        pages = _pages(RU_BASE, found) if found else []
    for title, text in pages:
        if _accept(text, formid):
            return {"title": title, "url": page_url(title, RU_BASE), "html": _render(RU_BASE, title, text, OBTAIN_SECTIONS_RU)}
    return None


def obtain(names: list[str], formid: int | None = None, name_ru: str | None = None) -> dict | None:
    """Найти страницу Fallout 76 и вернуть {wiki, title, url, html, ru} с разделами «Locations», «Vendors» и т.п.;
    `ru` — {title, url, html} русской страницы fandom («Описание», «Местонахождение»), если она есть.
    Если в инфобоксе указан другой FormID — это не наш предмет. Ошибка одной вики не мешает искать в другой."""
    errors = []
    en = None
    for wiki, base in WIKIS:
        try:
            exact = [t for n in names for t in (f"{n} (Fallout 76)", n)]
            pages = _pages(base, exact)
            if not any(_accept(text, formid) for _, text in pages):
                found = [t for n in names for t in _search(base, n)]
                pages = _pages(base, list(dict.fromkeys(found))) if found else []
        except Exception as e:
            errors.append(f"{wiki}: {e}")
            continue
        for title, text in pages:
            if _accept(text, formid):
                en = {"wiki": wiki, "title": title, "url": page_url(title, base), "html": _render(base, title, text, OBTAIN_SECTIONS)}
                break
        if en:
            break
    try:
        ru = _ru_page(en["title"] if en and en["wiki"] == WIKIS[0][0] else None, name_ru, formid)
    except Exception as e:
        errors.append(f"fallout.fandom.com/ru: {e}")
        ru = None
    if not en and not ru and len(errors) == len(WIKIS) + 1:
        raise OSError("; ".join(errors))
    if not en and not ru:
        return None
    return {**(en or {"wiki": None, "title": None, "url": None, "html": None}), "ru": ru}
