"""On-disk caches for peça-derived content, keyed by URL sha1.

Four parallel caches, all sha1(url)-keyed, split across two roots:

- **Bytes** under `data/raw/pecas/` (`<sha1>.<ext>.gz`, with `<ext>` ∈
  {`pdf`, `rtf`}): raw bytes from STF, gzip-wrapped. Written by
  `baixar-pecas`; read by `extrair-pecas`. The on-disk extension is
  picked from the payload's magic bytes (`%PDF` → `.pdf.gz`, `{\\rtf` →
  `.rtf.gz`); unknown payloads raise rather than landing in a lying
  suffix. Readers (`has_bytes` / `read_bytes`) probe both extensions
  since callers only know the URL, not what STF served. Splitting
  download from extraction lets us switch OCR providers without
  re-hitting STF's WAF.
- **Text** under `data/derived/pecas-texto/<sha1>.txt.gz`: flat
  extracted text. Written by every extractor path (pypdf, Unstructured
  OCR, RTF fallback). This is what downstream notebooks read via
  `peca_cache.read(url)`.
- **Elements** under `data/derived/pecas-texto/<sha1>.elements.json.gz`:
  structured element list from OCR providers (each element has `type`,
  `text`, `metadata`, `element_id`, …). Written by `extrair-pecas` when
  the provider returns an element list. Absent for pypdf-sourced entries.
- **Extractor sidecar** under `data/derived/pecas-texto/<sha1>.extractor`
  (plain text, no gzip): the label of the extractor that produced the
  text. Values come from the schema v4 open set ("rtf", "pypdf_plain",
  "pypdf_layout", "pypdf", "unstructured", "mistral", "chandra"); the
  file is 5-20 bytes so the storage overhead is noise. Read via
  `peca_cache.read_extractor`; `None` when the sidecar is absent
  (pre-v4 cache entries) or the extractor wasn't recorded.

The bytes-vs-text split mirrors the deletion-cost taxonomy: re-fetching
bytes from STF takes hours plus proxy budget (`raw/`); re-extracting
text from cached bytes is local and fast (`derived/`).

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

PECAS_ROOT: Path = Path("data/raw/pecas")
TEXTO_ROOT: Path = Path("data/derived/pecas-texto")


def _hash(url: str) -> str:
    return hashlib.sha1(url.encode("utf-8")).hexdigest()


def _text_path(url: str) -> Path:
    return TEXTO_ROOT / f"{_hash(url)}.txt.gz"


def _elements_path(url: str) -> Path:
    return TEXTO_ROOT / f"{_hash(url)}.elements.json.gz"


def _extractor_path(url: str) -> Path:
    return TEXTO_ROOT / f"{_hash(url)}.extractor"


def _dismissed_path(url: str) -> Path:
    """Sidecar for "operator marked this URL as known-broken, stop retrying"."""
    return TEXTO_ROOT / f"{_hash(url)}.dismissed.json"


_BYTES_EXTS: tuple[str, ...] = ("pdf", "rtf")
_MAGIC_TO_EXT: tuple[tuple[bytes, str], ...] = (
    (b"%PDF", "pdf"),
    (b"{\\rtf", "rtf"),
)


def _ext_for_payload(body: bytes) -> str:
    prefix = body[:8]
    for magic, ext in _MAGIC_TO_EXT:
        if prefix.startswith(magic):
            return ext
    raise ValueError(
        f"unrecognised peça magic bytes: {prefix!r}; "
        f"expected one of {[m for m, _ in _MAGIC_TO_EXT]}"
    )


def _bytes_path(url: str, ext: str = "pdf") -> Path:
    return PECAS_ROOT / f"{_hash(url)}.{ext}.gz"


def _find_bytes_path(url: str) -> Optional[Path]:
    h = _hash(url)
    for ext in _BYTES_EXTS:
        p = PECAS_ROOT / f"{h}.{ext}.gz"
        if p.exists():
            return p
    return None


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


def is_dismissed(url: str) -> bool:
    """True if an operator has marked this URL as known-broken.

    A dismissed URL is silently skipped by ``judex limpar`` and excluded
    from retry budgets. The dismissal sidecar persists across warehouse
    rebuilds since it lives under ``data/derived/pecas-texto/`` (which
    is preserved) rather than inside the rebuildable warehouse.
    """
    return _dismissed_path(url).exists()


def read_dismissal(url: str) -> Optional[dict]:
    """Return the dismissal payload (``{url, reason, dismissed_at}``)
    or ``None`` if the URL hasn't been dismissed."""
    p = _dismissed_path(url)
    if not p.exists():
        return None
    return json.loads(p.read_bytes().decode("utf-8"))


def write_dismissal(url: str, *, reason: str) -> None:
    """Mark a URL as dismissed with a human-readable reason.

    Idempotent: re-dismissing overwrites the timestamp + reason but
    keeps the sidecar present. The reason is operator-facing prose
    ("permanent 404", "scanned PDF, OCR maxed out", "duplicate of <X>")
    so the next operator inspecting the residual knows why this URL
    is excluded.
    """
    import datetime as dt
    payload = {
        "url": url,
        "reason": reason,
        "dismissed_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    _atomic_write(
        _dismissed_path(url),
        json.dumps(payload, ensure_ascii=False).encode("utf-8"),
    )


def clear_dismissal(url: str) -> bool:
    """Remove a URL's dismissal sidecar. Returns True if a sidecar
    existed (operator un-dismissed); False if there was nothing to
    clear (idempotent no-op)."""
    p = _dismissed_path(url)
    if not p.exists():
        return False
    p.unlink()
    return True


def has_bytes(url: str) -> bool:
    return _find_bytes_path(url) is not None


def read_bytes(url: str) -> Optional[bytes]:
    p = _find_bytes_path(url)
    if p is None:
        return None
    return gzip.decompress(p.read_bytes())


def write_bytes(url: str, body: bytes) -> None:
    """Store raw peça bytes for `url`, gzip-wrapped and atomically written.

    The on-disk extension is picked from the payload's magic bytes
    (`%PDF` → `.pdf.gz`, `{\\rtf` → `.rtf.gz`); anything else raises
    `ValueError` rather than landing in a misleading `.pdf.gz` (the
    pre-2026-05 bug that left ~4% of cache entries lying about format).
    Paired with `baixar-pecas` → `extrair-pecas`: the download command
    writes bytes once, then every extractor run reads them locally via
    `read_bytes`. No quality guard on overwrite — `--forcar` is the
    only knob that re-downloads.
    """
    ext = _ext_for_payload(body)
    _atomic_write(_bytes_path(url, ext), gzip.compress(body))
