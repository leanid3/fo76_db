"""Минимальный проход по SeventySix.esm: EditorID, ID строки FULL и ключевые слова записей.

Читаются только верхние группы нужных типов, остальные пропускаются по размеру,
поэтому проход по 900-мегабайтному файлу занимает доли секунды.
Заголовок записи и группы — 24 байта. Флаг 0x00040000 — данные записи сжаты (u32 размер + zlib).
"""
from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass, field
from pathlib import Path


ESM = "SeventySix.esm"  # в папке Data игры (config: game_data)


def _esm(path: Path | None) -> Path:
    if path is not None:
        return path
    from ..config import game_data
    return game_data() / ESM

ITEM_TYPES = ("WEAP", "ARMO", "ALCH", "BOOK", "MISC", "AMMO", "NOTE", "KEYM", "CMPO", "OMOD", "ENTM")
COMPRESSED = 0x00040000


@dataclass
class Record:
    sig: str
    formid: int
    edid: str = ""
    full: int | None = None          # ID локализованной строки
    keywords: list[int] = field(default_factory=list)


def _parse(sig: str, formid: int, data: bytes) -> Record:
    rec = Record(sig, formid)
    pos, big = 0, None
    while pos + 6 <= len(data):
        sub = data[pos : pos + 4]
        (size,) = struct.unpack_from("<H", data, pos + 4)
        pos += 6
        if sub == b"XXXX":
            (big,) = struct.unpack_from("<I", data, pos)
            pos += size
            continue
        if big is not None:
            size, big = big, None
        body = data[pos : pos + size]
        pos += size
        if sub == b"EDID":
            rec.edid = body.rstrip(b"\0").decode("utf-8", "replace")
        elif sub == b"FULL" and size == 4 and rec.full is None:
            rec.full = struct.unpack("<I", body)[0]
        elif sub == b"KWDA":
            rec.keywords = list(struct.unpack(f"<{size // 4}I", body))
    return rec


def _walk(f, end: int, sig_name: str, out: dict[int, Record]) -> None:
    sig_bytes = sig_name.encode()
    while f.tell() < end:
        hdr = f.read(24)
        (size,) = struct.unpack_from("<I", hdr, 4)
        if hdr[:4] == b"GRUP":
            _walk(f, f.tell() - 24 + size, sig_name, out)
            continue
        data = f.read(size)
        if hdr[:4] != sig_bytes:
            continue
        flags, formid = struct.unpack_from("<II", hdr, 8)
        if flags & COMPRESSED:
            data = zlib.decompress(data[4:])
        out[formid] = _parse(sig_name, formid, data)


def read_records(types=ITEM_TYPES + ("KYWD",), esm: Path | None = None) -> dict[int, Record]:
    """FormID -> Record для записей указанных типов (только верхние группы этих типов)."""
    out: dict[int, Record] = {}
    wanted = {t.encode() for t in types}
    with open(_esm(esm), "rb") as f:
        total = f.seek(0, 2)
        f.seek(0)
        hdr = f.read(24)
        f.seek(struct.unpack_from("<I", hdr, 4)[0], 1)  # пропуск TES4
        while f.tell() < total:
            ghdr = f.read(24)
            (gsize,) = struct.unpack_from("<I", ghdr, 4)
            gend = f.tell() - 24 + gsize
            if ghdr[:4] == b"GRUP" and ghdr[8:12] in wanted:
                _walk(f, gend, ghdr[8:12].decode(), out)
            f.seek(gend)
    return out


def esm_stamp(esm: Path | None = None) -> str:
    """Отпечаток установленной версии: размер и mtime файла."""
    st = _esm(esm).stat()
    return f"{st.st_size}:{int(st.st_mtime)}"
