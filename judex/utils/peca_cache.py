"""On-disk caches for PDF-derived content, keyed by URL sha1.

Four parallel caches, all under `data/cache/pdf/`, all sha1(url)-keyed:

- **Bytes cache** (`<sha1>.pdf.gz`): raw PDF bytes, gzip-wrapped.
  Written by `baixar-pecas`; read by `extrair-pecas`. Splitting download
  from extraction lets us switch OCR providers without re-hitting
  STF's WAF.
- **Text cache** (`<sha1>.txt.gz`): flat extracted text. Written by
  every extractor path (pypdf, Unstructured OCR, RTF fallback). This
  is what downstream notebooks read via `peca_cache.read(url)`.
- **Elements cache** (`<sha1>.elements.json.gz`): structured element
  list from OCR providers (each element has `type`, `text`, `metadata`,
  `element_id`, …). Written by `extrair-pecas` when the provider
  returns an element list. Absent for pypdf-sourced entries.
- **Extractor sidecar** (`<sha1>.extractor`, plain text, no gzip):
  the label of the extractor that produced the text. Values come from
  the schema v4 open set ("rtf", "pypdf_plain", "pypdf_layout", "pypdf",
  "unstructured", "mistral", "chandra"); the file is 5-20 bytes so
  the storage overhead is noise. Read via `peca_cache.read_extractor`;
  `None` when the sidecar is absent (pre-v4 cache entries) or the
  extractor wasn't recorded.

The caches are independent — writing to one doesn't populate the
others. Consumers that need boilerplate-free or section-aware text
read the elements cache and filter; consumers that just want a blob
keep using `read(url)` and get whatever the most-recent extractor
produced.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Optional


def _atomic_write(path: Path, payload: bytes) -> None:
    # Writes must be atomic because concurrent sharded sweeps can race on
    # the same sha1(url) key when PDFs are cross-referenced between cases.
    # tempfile-then-os.replace avoids half-written gzip bytes; the pid
    # suffix keeps racers from stomping each other's tmp file.
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    tmp.write_bytes(payload)
    os.replace(tmp, path)

CACHE_ROOT: Path = Path("data/cache/pdf")


def _hash(url: str) -> str:
    return hashlib.sha1(url.encode("utf-8")).hexdigest()


def _text_path(url: str) -> Path:
    return CACHE_ROOT / f"{_hash(url)}.txt.gz"


def _elements_path(url: str) -> Path:
    return CACHE_ROOT / f"{_hash(url)}.elements.json.gz"


def _extractor_path(url: str) -> Path:
    return CACHE_ROOT / f"{_hash(url)}.extractor"


def _bytes_path(url: str) -> Path:
    return CACHE_ROOT / f"{_hash(url)}.pdf.gz"


def has_text(url: str) -> bool:
    """Cheap "was this URL extracted?" — O(1) file stat, no decompress.

    Under v8 the case JSON no longer carries inline text, so callers
    that just need a boolean should reach for this instead of
    `read(url) is not None` (which reads + gzip-decompresses the
    whole body only to discard it). Independent of `has_bytes` —
    `baixar-pecas` writes bytes first, `extrair-pecas` writes text
    later, so a URL can have bytes without text (and vice versa
    for pre-split legacy entries).
    """
    return _text_path(url).exists()


def read(url: str) -> Optional[str]:
    p = _text_path(url)
    if not p.exists():
        return None
    return gzip.decompress(p.read_bytes()).decode("utf-8")


def write(url: str, text: str, *, extractor: Optional[str] = None) -> None:
    """Write extracted text and, optionally, the extractor sidecar.

    When `extractor` is provided, also writes `<sha1>.extractor` as a
    plain-text sidecar. Pre-v4 callers that pass `extractor=None` leave
    the sidecar untouched (never overwritten with null), so prior
    provenance survives a text-only rewrite.
    """
    _atomic_write(_text_path(url), gzip.compress(text.encode("utf-8")))
    if extractor is not None:
        _atomic_write(_extractor_path(url), extractor.encode("utf-8"))


def read_extractor(url: str) -> Optional[str]:
    """Return the extractor label for `url`, or None on miss.

    Miss means either the PDF has no cache entry at all, or the entry
    predates the v4 sidecar contract. Callers should treat both as
    "extractor unknown" and not infer which case applies.
    """
    p = _extractor_path(url)
    if not p.exists():
        return None
    return p.read_bytes().decode("utf-8").strip() or None


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
    payload = json.dumps(elements, ensure_ascii=False).encode("utf-8")
    _atomic_write(_elements_path(url), gzip.compress(payload))


def has_bytes(url: str) -> bool:
    return _bytes_path(url).exists()


def read_bytes(url: str) -> Optional[bytes]:
    p = _bytes_path(url)
    if not p.exists():
        return None
    return gzip.decompress(p.read_bytes())


def write_bytes(url: str, body: bytes) -> None:
    """Store raw PDF bytes for `url`, gzip-wrapped and atomically written.

    Paired with `baixar-pecas` → `extrair-pecas`: the download command
    writes bytes once, then every extractor run reads them locally via
    `read_bytes`. No quality guard on overwrite — `--forcar` is the
    only knob that re-downloads.
    """
    _atomic_write(_bytes_path(url), gzip.compress(body))
