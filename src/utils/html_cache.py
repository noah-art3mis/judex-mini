"""
On-disk HTML cache keyed by (classe, processo, tab).

Cache lives under `.cache/html/{classe}_{processo}/{tab}.html.gz`.
STF tab HTML compresses 8-10x so gzip costs almost nothing in CPU and
keeps the cache practical for mass scrapes. Reads transparently fall
back to legacy plain .html files if a gzip version is absent.
"""

import gzip
from pathlib import Path

CACHE_ROOT = Path(".cache/html")


def _dir(classe: str, processo: int) -> Path:
    return CACHE_ROOT / f"{classe}_{processo}"


def _path(classe: str, processo: int, tab: str) -> Path:
    return _dir(classe, processo) / f"{tab}.html.gz"


def read(classe: str, processo: int, tab: str) -> str | None:
    gz = _path(classe, processo, tab)
    if gz.exists():
        return gzip.decompress(gz.read_bytes()).decode("utf-8")
    plain = _dir(classe, processo) / f"{tab}.html"
    if plain.exists():
        return plain.read_text(encoding="utf-8")
    return None


def write(classe: str, processo: int, tab: str, html: str) -> None:
    p = _path(classe, processo, tab)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(gzip.compress(html.encode("utf-8")))


def read_incidente(classe: str, processo: int) -> int | None:
    p = _dir(classe, processo) / "incidente.txt"
    if p.exists():
        text = p.read_text().strip()
        if text.isdigit():
            return int(text)
    return None


def write_incidente(classe: str, processo: int, incidente: int) -> None:
    p = _dir(classe, processo) / "incidente.txt"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(str(incidente))
