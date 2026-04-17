"""On-disk cache for extracted PDF/RTF text, keyed by URL sha1.

Repeated scrapes skip the network round-trip to
sistemas.stf.jus.br/repgeral for every Relatório/Voto PDF that's
already been seen. Flat layout — one `.txt.gz` per URL hash.
"""

from __future__ import annotations

import gzip
import hashlib
from pathlib import Path
from typing import Optional

CACHE_ROOT: Path = Path(".cache/pdf")


def _path(url: str) -> Path:
    h = hashlib.sha1(url.encode("utf-8")).hexdigest()
    return CACHE_ROOT / f"{h}.txt.gz"


def read(url: str) -> Optional[str]:
    p = _path(url)
    if not p.exists():
        return None
    return gzip.decompress(p.read_bytes()).decode("utf-8")


def write(url: str, text: str) -> None:
    p = _path(url)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(gzip.compress(text.encode("utf-8")))
