"""On-disk caches for PDF-derived content, keyed by URL sha1.

Two parallel caches, both under `data/pdf/`, both sha1(url)-keyed:

- **Text cache** (`<sha1>.txt.gz`): flat extracted text. Written by
  every extractor path (pypdf, Unstructured OCR, RTF fallback). This
  is what downstream notebooks read via `pdf_cache.read(url)`.
- **Elements cache** (`<sha1>.elements.json.gz`): structured element
  list from Unstructured (each element has `type`,
  `text`, `metadata`, `element_id`, …). Written only by
  `scripts/reextract_unstructured.py` when an OCR pass succeeds.
  Absent for pypdf-sourced entries (pypdf has no element structure
  to capture).

The two caches are independent — writing to one doesn't populate the
other. Consumers that need boilerplate-free or section-aware text
read the elements cache and filter; consumers that just want a blob
keep using `read(url)` and get whatever the most-recent extractor
produced.
"""

from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path
from typing import Any, Optional

CACHE_ROOT: Path = Path("data/pdf")


def _hash(url: str) -> str:
    return hashlib.sha1(url.encode("utf-8")).hexdigest()


def _text_path(url: str) -> Path:
    return CACHE_ROOT / f"{_hash(url)}.txt.gz"


def _elements_path(url: str) -> Path:
    return CACHE_ROOT / f"{_hash(url)}.elements.json.gz"


def read(url: str) -> Optional[str]:
    p = _text_path(url)
    if not p.exists():
        return None
    return gzip.decompress(p.read_bytes()).decode("utf-8")


def write(url: str, text: str) -> None:
    p = _text_path(url)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(gzip.compress(text.encode("utf-8")))


def read_elements(url: str) -> Optional[list[dict[str, Any]]]:
    """Return the Unstructured element list for `url`, or None on miss.

    Elements preserve `type` / `metadata.page_number` / etc., which
    the flat text cache throws away. Only OCR-sourced entries have
    this; pypdf-sourced URLs return None even when `read(url)` hits.
    """
    p = _elements_path(url)
    if not p.exists():
        return None
    return json.loads(gzip.decompress(p.read_bytes()).decode("utf-8"))


def write_elements(url: str, elements: list[dict[str, Any]]) -> None:
    """Store the Unstructured element list for `url`.

    Callers should pass the raw API response rows (each row is a
    dict with `type`, `text`, `metadata`, etc.). Storing them as-is
    keeps downstream consumers free to re-derive flat text, strip
    Header/Footer, group by page, etc.
    """
    p = _elements_path(url)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(elements, ensure_ascii=False).encode("utf-8")
    p.write_bytes(gzip.compress(payload))
