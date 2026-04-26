"""Per-case tar.gz HTML cache.

Cache lives at `data/raw/html/{classe}_{processo}.tar.gz` — one
archive per process containing every tab as a plain `.html` member
plus `incidente.txt`. The outer gzip layer compresses across tabs
(STF HTML shares a lot of boilerplate, and one case's ~30 KB of
fragments fits inside gzip's 32 KB sliding window), so the total
footprint is close to the previous per-file-gz layout at ~10× fewer
inodes.

Writes are atomic at the case granularity: `write_case` renders the
whole archive in a tempfile and `os.replace`s it over the target, so
a crash mid-scrape either leaves the archive absent (never scraped)
or replaces a prior-complete archive — never partial.
"""

from __future__ import annotations

import io
import os
import tarfile
from pathlib import Path

CACHE_ROOT = Path("data/raw/html")
_INCIDENTE_MEMBER = "incidente.txt"


def _archive_path(classe: str, processo: int) -> Path:
    return CACHE_ROOT / f"{classe}_{processo}.tar.gz"


def has_case(classe: str, processo: int) -> bool:
    return _archive_path(classe, processo).exists()


def read(classe: str, processo: int, tab: str) -> str | None:
    archive = _archive_path(classe, processo)
    if not archive.exists():
        return None
    member = f"{tab}.html"
    with tarfile.open(archive, "r:gz") as tf:
        try:
            fp = tf.extractfile(member)
        except KeyError:
            return None
        if fp is None:
            return None
        return fp.read().decode("utf-8")


def read_incidente(classe: str, processo: int) -> int | None:
    archive = _archive_path(classe, processo)
    if not archive.exists():
        return None
    with tarfile.open(archive, "r:gz") as tf:
        try:
            fp = tf.extractfile(_INCIDENTE_MEMBER)
        except KeyError:
            return None
        if fp is None:
            return None
        text = fp.read().decode("utf-8").strip()
    return int(text) if text.isdigit() else None


def write_case(
    classe: str,
    processo: int,
    *,
    tabs: dict[str, str],
    incidente: int,
) -> None:
    archive = _archive_path(classe, processo)
    archive.parent.mkdir(parents=True, exist_ok=True)
    tmp = archive.with_name(archive.name + ".tmp")

    with tarfile.open(tmp, "w:gz") as tf:
        for tab, html in tabs.items():
            payload = html.encode("utf-8")
            info = tarfile.TarInfo(name=f"{tab}.html")
            info.size = len(payload)
            tf.addfile(info, io.BytesIO(payload))

        inc_payload = str(incidente).encode("utf-8")
        info = tarfile.TarInfo(name=_INCIDENTE_MEMBER)
        info.size = len(inc_payload)
        tf.addfile(info, io.BytesIO(inc_payload))

    os.replace(tmp, archive)
