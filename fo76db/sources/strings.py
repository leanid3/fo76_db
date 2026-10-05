"""Чтение строк локализации из BA2 (GNRL).

Формат BA2 (BTDX v1): заголовок 24 байта, затем записи файлов по 36 байт,
таблица имён по смещению nameTableOffset. Данные сжаты zlib, если packedSize > 0.

Формат *.strings: count, dataSize, затем count пар (id, offset), затем данные.
В .strings строки нуль-терминированы, в .dlstrings/.ilstrings перед строкой стоит u32 длина.
"""
from __future__ import annotations

import struct
import zlib
from pathlib import Path

LOCALIZATION_BA2 = "SeventySix - Localization.ba2"  # в папке Data игры (config: game_data)


def ba2_list(path: Path) -> dict[str, tuple[int, int, int]]:
    """Имя файла (в нижнем регистре) -> (offset, packed, unpacked)."""
    with open(path, "rb") as f:
        magic, _ver, kind, count, names_off = struct.unpack("<4sI4sIQ", f.read(24))
        if magic != b"BTDX" or kind != b"GNRL":
            raise ValueError(f"{path}: не GNRL BA2 ({magic!r} {kind!r})")
        records = [struct.unpack("<I4sIIQIII", f.read(36)) for _ in range(count)]
        f.seek(names_off)
        names = []
        for _ in range(count):
            (n,) = struct.unpack("<H", f.read(2))
            names.append(f.read(n).decode("utf-8", "replace").replace("\\", "/").lower())
    return {name: (r[4], r[5], r[6]) for name, r in zip(names, records)}


def ba2_read(path: Path, name: str) -> bytes:
    offset, packed, unpacked = ba2_list(path)[name.lower()]
    with open(path, "rb") as f:
        f.seek(offset)
        if packed:
            return zlib.decompress(f.read(packed))
        return f.read(unpacked)


def parse_strings(data: bytes, prefixed: bool) -> dict[int, str]:
    count, _size = struct.unpack_from("<II", data, 0)
    base = 8 + count * 8
    out: dict[int, str] = {}
    for i in range(count):
        sid, off = struct.unpack_from("<II", data, 8 + i * 8)
        pos = base + off
        if prefixed:
            (n,) = struct.unpack_from("<I", data, pos)
            raw = data[pos + 4 : pos + 4 + n].rstrip(b"\0")
        else:
            raw = data[pos : data.index(b"\0", pos)]
        out[sid] = raw.decode("utf-8", "replace")
    return out


def load_strings(lang: str, ba2: Path | None = None) -> dict[int, str]:
    """Все строки SeventySix для языка (`en`, `ru`, ...), объединённые из трёх таблиц."""
    if ba2 is None:
        from ..config import game_data
        ba2 = game_data() / LOCALIZATION_BA2
    out: dict[int, str] = {}
    for ext, prefixed in (("strings", False), ("dlstrings", True), ("ilstrings", True)):
        out.update(parse_strings(ba2_read(ba2, f"strings/seventysix_{lang}.{ext}"), prefixed))
    return out
