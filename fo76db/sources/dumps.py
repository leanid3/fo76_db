"""Релизы fwdekker/fo76-dumps: список, скачивание и чтение CSV.

Каждый релиз называется `v<версия скрипта>-v<версия игры>`. Версии `0.x` — PTS.
CSV в релизах записаны с разделителем ", " и кавычками.
"""
from __future__ import annotations

import logging
import csv
import io
import json
import os
import re
import shutil
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Iterator

from .. import features
from ..db import DATA

log = logging.getLogger(__name__)

REPO = "fwdekker/fo76-dumps"
CACHE = DATA / "cache" / "dumps"
API = f"https://api.github.com/repos/{REPO}/releases"

csv.field_size_limit(2**31 - 1)  # sys.maxsize не влезает в C long на Windows


def sevenzip() -> str:
    """Путь к консольному 7-Zip: 7z, 7zz или 7za в PATH, на Windows — ещё папка установки 7-Zip."""
    for name in ("7z", "7zz", "7za"):
        if p := shutil.which(name):
            return p
    for base in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")):
        if base and (p := Path(base) / "7-Zip" / "7z.exe").is_file():
            return str(p)
    raise RuntimeError("Не найден 7-Zip (7z): он нужен для архивов fo76-dumps. Linux: пакет 7zip или p7zip; Windows: https://www.7-zip.org")


RELEASES_CACHE = CACHE / "releases.json"
RELEASES_TTL = 3600


ALLOWED_HOSTS = ("api.github.com", "github.com", ".githubusercontent.com")  # откуда качаем выгрузки и куда ведут их редиректы
RETRIES = 3


def _check_url(url: str) -> None:
    u = urllib.parse.urlsplit(url)
    host = u.hostname or ""
    if u.scheme != "https" or not any(host == h or (h.startswith(".") and host.endswith(h)) for h in ALLOWED_HOSTS):
        raise ValueError(f"адрес не из списка разрешённых: {url}")


def _open(url: str):
    """Открыть адрес с повторами (обрыв, 5xx, лимит GitHub 403/429 — ждём и пробуем снова); 4xx кроме лимита — сразу ошибка."""
    features.require("dumps")
    _check_url(url)
    headers = {"User-Agent": "fo76db", "Accept": "application/vnd.github+json"}
    if os.environ.get("GITHUB_TOKEN") and url.startswith("https://api.github.com/"):
        headers["Authorization"] = f"Bearer {os.environ['GITHUB_TOKEN']}"
    req = urllib.request.Request(url, headers=headers)
    for attempt in range(RETRIES):
        wait = 0.0
        try:
            return urllib.request.urlopen(req, timeout=120)
        except urllib.error.HTTPError as e:
            retry = e.code in (403, 429) or e.code >= 500
            if e.code in (403, 429):
                wait = float(e.headers.get("Retry-After") or 0)
                if e.headers.get("X-RateLimit-Remaining") == "0" and not wait:
                    raise RuntimeError("лимит запросов GitHub исчерпан — задайте GITHUB_TOKEN или повторите позже") from e
            if not retry or attempt == RETRIES - 1:
                raise
        except (urllib.error.URLError, TimeoutError):
            if attempt == RETRIES - 1:
                raise
        time.sleep(min(wait or 2 ** (attempt + 1), 30))
    raise RuntimeError("недостижимо")


def _get(url: str) -> bytes:
    with _open(url) as r:
        return r.read()


def game_version(tag: str) -> str:
    return tag.split("-v", 1)[1]


def version_key(version: str) -> str:
    return ".".join(f"{int(p):06d}" for p in version.split("."))


def is_pts(version: str) -> bool:
    return version.startswith("0.")


def list_releases(max_age: int = RELEASES_TTL) -> list[dict]:
    """Все релизы: tag, version, date, assets{name: url}.

    Список кэшируется на час: без токена GitHub даёт 60 запросов в час.
    Если GitHub недоступен или лимит исчерпан, используется кэш любой давности.
    """
    if RELEASES_CACHE.exists() and time.time() - RELEASES_CACHE.stat().st_mtime < max_age:
        return json.loads(RELEASES_CACHE.read_text(encoding="utf-8"))
    try:
        out = _fetch_releases()
    except (urllib.error.URLError, TimeoutError) as e:
        if RELEASES_CACHE.exists():
            log.warning("GitHub недоступен (%s), использую сохранённый список релизов", e)
            return json.loads(RELEASES_CACHE.read_text(encoding="utf-8"))
        raise
    RELEASES_CACHE.parent.mkdir(parents=True, exist_ok=True)
    RELEASES_CACHE.write_text(json.dumps(out), encoding="utf-8")
    return out


def _fetch_releases() -> list[dict]:
    out, page = [], 1
    while True:
        batch = json.loads(_get(f"{API}?per_page=100&page={page}"))
        if not batch:
            break
        for r in batch:
            if r.get("draft"):
                continue
            out.append({
                "tag": r["tag_name"],
                "version": game_version(r["tag_name"]),
                "date": (r.get("published_at") or "")[:10],
                "assets": {a["name"]: a["browser_download_url"] for a in r["assets"]},
            })
        page += 1
    return out


def fetch(release: dict, name: str) -> Path | None:
    """Скачать файл релиза в кэш (если ещё нет). None, если в релизе такого файла нет."""
    url = release["assets"].get(name)
    if not url:
        return None
    path = CACHE / release["tag"] / name
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".part")
        try:
            with _open(url) as r, open(tmp, "wb") as f:  # на диск потоком: файлы по сотням мегабайт
                size = int(r.headers.get("Content-Length") or 0)
                shutil.copyfileobj(r, f, 1 << 20)
                f.flush()
                os.fsync(f.fileno())
            if size and tmp.stat().st_size != size:
                raise OSError(f"{name}: скачано {tmp.stat().st_size} из {size} байт")
            os.replace(tmp, path)  # на Windows rename падает, если файл уже есть
        finally:
            tmp.unlink(missing_ok=True)
    return path


def open_text(path: Path) -> io.TextIOBase:
    """Открыть CSV/wiki, распаковывая .7z на лету (первый файл архива)."""
    if path.suffix == ".7z":
        # как в history.py: системный 7z (у py7zr 1.x нет чтения в память)
        data = subprocess.run([sevenzip(), "e", "-so", str(path)], capture_output=True, check=True).stdout
        return io.StringIO(data.decode("utf-8", "replace"))
    return open(path, encoding="utf-8", errors="replace", newline="")


def read_csv(path: Path) -> Iterator[dict]:
    with open_text(path) as f:
        yield from csv.DictReader(f, skipinitialspace=True)


REF_RE = re.compile(r'(?P<edid>[^\s"\[]+)(?: "(?P<name>(?:[^"\\]|\\.)*)")? \[(?P<sig>[A-Z_0-9]{4}):(?P<formid>[0-9A-Fa-f]{8})\]')


def parse_ref(s: str) -> dict | None:
    """`EditorID "Name" [SIG:0001ABCD]` -> {edid, name, sig, formid}."""
    m = REF_RE.search(s or "")
    if not m:
        return None
    d = m.groupdict()
    d["formid"] = int(d["formid"], 16)
    if d["name"] is not None:
        d["name"] = d["name"].replace('\\"', '"')
    return d


def parse_json_list(s: str) -> list:
    try:
        return json.loads(s) if s else []
    except json.JSONDecodeError:
        return []


def keywords(s: str) -> list[str]:
    return [r["edid"] for r in (parse_ref(x) for x in parse_json_list(s)) if r]
