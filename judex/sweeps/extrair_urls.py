"""URL-scoped re-extraction — the missing third targeting mode.

``judex executar`` targets cases (range / CSV / errors.jsonl), then
walks every peça in those cases. For URL-scoped recovery (e.g. re-OCR
just the 8 outlier PDFs in HC 2020 cap-recovery) the case-walker
over-extracts: forcing through the 8 cases would hit ~140 peças, with
quality regression on the ~132 that already had clean pypdf text.

This module is the URL-scoped alternative. Reads bytes from
``peca_cache`` (no fetch logic — exits cleanly on missing bytes),
runs the chosen provider, writes text + ``<sha1>.extractor`` sidecar
back to peca_cache. No state file, no portal/sistemas pools, no
fetch_meta — the unified pipeline does all of those.

Spec: ``.scratch/per-url-extract/PRD.md``.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from judex.scraping.ocr import OCRConfig, extract_pdf
from judex.utils import peca_cache


@dataclass(frozen=True)
class UrlExtractResult:
    """Counts from a single ``run_extrair_urls`` invocation.

    The four counts partition the URL list — every URL falls into
    exactly one bucket. Operators can sanity-check ``ok + skipped +
    missing_bytes + fail == len(urls)`` against the input file.
    """

    n_ok: int
    n_skipped: int          # extractor sidecar already matches provedor
    n_missing_bytes: int    # peça not in cache; needs `executar` first
    n_fail: int             # provider raised — wall isn't lost on the rest
    wall_s: float


def parse_urls_file(path: Path) -> list[str]:
    """One URL per line. Blank lines and ``#``-comments are dropped."""
    out: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        out.append(line)
    return out


def run_extrair_urls(
    urls_path: Path,
    *,
    provedor: str,
    forcar: bool = False,
) -> UrlExtractResult:
    """Re-extract text for each URL in ``urls_path`` using ``provedor``.

    Idempotent on the ``<sha1>.extractor`` sidecar: skips URLs whose
    existing extractor already matches ``provedor`` unless ``forcar``.
    """
    urls = parse_urls_file(Path(urls_path))
    config = OCRConfig(provider=provedor)

    n_ok = n_skipped = n_missing = n_fail = 0
    t0 = time.time()

    for url in urls:
        if not forcar and peca_cache.read_extractor(url) == provedor:
            n_skipped += 1
            continue
        pdf_bytes = peca_cache.read_bytes(url)
        if pdf_bytes is None:
            n_missing += 1
            continue
        try:
            result = extract_pdf(pdf_bytes, config=config)
        except Exception:
            n_fail += 1
            continue
        peca_cache.write(url, result.text, extractor=provedor)
        n_ok += 1

    return UrlExtractResult(
        n_ok=n_ok,
        n_skipped=n_skipped,
        n_missing_bytes=n_missing,
        n_fail=n_fail,
        wall_s=time.time() - t0,
    )
