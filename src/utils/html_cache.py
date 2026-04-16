"""
On-disk HTML cache keyed by (classe, processo, tab).

The cache lives under `.cache/html/{classe}_{processo}/{tab}.html`. It is
content-agnostic: callers decide when to look it up and when to bypass it.
Intended for iterative development on parsers — refetching STF pages is
slow and rate-limit-sensitive; once a page is cached, re-extraction is
a local filesystem read.
"""

from pathlib import Path

CACHE_ROOT = Path(".cache/html")


def _cache_dir(classe: str, processo: int) -> Path:
    return CACHE_ROOT / f"{classe}_{processo}"


def cache_path(classe: str, processo: int, tab: str) -> Path:
    return _cache_dir(classe, processo) / f"{tab}.html"


def read(classe: str, processo: int, tab: str) -> str | None:
    p = cache_path(classe, processo, tab)
    if p.exists():
        return p.read_text(encoding="utf-8")
    return None


def write(classe: str, processo: int, tab: str, html: str) -> None:
    p = cache_path(classe, processo, tab)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(html, encoding="utf-8")
