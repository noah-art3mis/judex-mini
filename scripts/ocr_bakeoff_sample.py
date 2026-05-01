"""Stratified PDF sampler for the OCR bakeoff (2026-04-30).

Picks 50 PDFs from the cached corpus: 25 born-digital + 25 scanned.

**Stratification signal: gzipped size per page** — fast `stat()` plus a
lightweight page-count via `PdfReader` (with a hard 2-second timeout per
file to skip pathologically-slow parses). Born-digital STF PDFs cluster at
20-50 KB/page; scanned at >=100 KB/page (validated against a 30-PDF random
sample where every <50 KB/pg PDF had a clean text layer).

The cache is ~95% born-digital, so the scanned bucket comes from
oversampling the >=100 KB/pg tail. 20 of the 50 are tagged
``gold_corrected=True`` for hand-correction (10 born-digital + 10 scanned).

Writes ``manifest.jsonl`` with one row per sampled PDF:
``{sha1, url, doc_type, n_pages, size_kb, kb_per_page, stratum, gold_corrected}``.

Run with:

    uv run python scripts/ocr_bakeoff_sample.py
"""

from __future__ import annotations

import gzip
import json
import random
import signal
from io import BytesIO
from pathlib import Path

import duckdb
from pypdf import PdfReader

from judex.sweeps.peca_classification import TIER_C_DOC_TYPES


REPO_ROOT = Path(__file__).resolve().parents[1]
PECAS_ROOT = REPO_ROOT / "data" / "raw" / "pecas"
WAREHOUSE = REPO_ROOT / "data" / "derived" / "warehouse" / "judex.duckdb"
OUT_DIR = REPO_ROOT / "runs" / "active" / "2026-04-30-ocr-bakeoff"

# Stratification: KB per page threshold for "scanned" classification.
SCAN_KB_PER_PAGE_THRESHOLD = 80

# Sample sizes per stratum (gold + diff combined).
GOLD_PER_STRATUM = 10
DIFF_PER_STRATUM = 15

# Per-PDF parse timeout — pypdf can hang minutes on pathological objects.
PARSE_TIMEOUT_S = 2

SEED = 20260430


class _TimeoutErr(Exception):
    pass


def _alarm_handler(_signum, _frame):
    raise _TimeoutErr()


def page_count_with_timeout(pdf_path: Path) -> int | None:
    """Return n_pages via lightweight PDF metadata parse, or None on
    failure / RTF / timeout. No text extraction — that's the slow part."""
    try:
        with gzip.open(pdf_path, "rb") as f:
            head = f.read(20)
            if head.startswith(b"{\\rtf"):
                return None  # RTF mis-cached as .pdf.gz
            f.seek(0)
            data = f.read()
        signal.signal(signal.SIGALRM, _alarm_handler)
        signal.alarm(PARSE_TIMEOUT_S)
        try:
            reader = PdfReader(BytesIO(data))
            n = len(reader.pages)
        finally:
            signal.alarm(0)
        return n if n > 0 else None
    except Exception:
        return None


def main() -> None:
    print(f"querying warehouse: {WAREHOUSE}", flush=True)
    if not WAREHOUSE.exists():
        raise SystemExit(f"warehouse not found: {WAREHOUSE}")

    # Pull substantive HC PDFs with their precomputed sha1 — no JSON walk.
    # IN clause excludes tier-C boilerplate (CERTIDÃO, INTIMAÇÃO, etc.);
    # `link_url LIKE '%.pdf'` filters out RTF endpoints.
    tier_c = list(TIER_C_DOC_TYPES)
    placeholders = ",".join("?" * len(tier_c))
    sql = f"""
        SELECT DISTINCT link_url_sha1, link_url, link_tipo
        FROM andamentos
        WHERE classe = 'HC'
          AND link_url IS NOT NULL
          AND lower(link_url) LIKE '%.pdf'
          AND (link_tipo IS NULL OR link_tipo NOT IN ({placeholders}))
    """
    con = duckdb.connect(str(WAREHOUSE), read_only=True)
    rows = con.execute(sql, tier_c).fetchall()
    con.close()
    print(f"  {len(rows):,} substantive PDF URLs (deduped, tier-C dropped)", flush=True)

    # Stratify cached candidates by gzipped-bytes-per-page (fast: stat() +
    # lightweight PDF metadata parse). Pre-split into two pools so we can
    # sample the rare scanned tail without enumerating the whole corpus.
    rng = random.Random(SEED)
    rng.shuffle(rows)

    target_each = GOLD_PER_STRATUM + DIFF_PER_STRATUM  # 25 per stratum
    born_digital: list[dict] = []
    scanned: list[dict] = []
    probed = 0
    failed = 0

    def _record(sha: str, url: str, doc_type: str | None,
                n_pages: int, size_kb: float, kb_pg: float, stratum: str) -> dict:
        return {
            "sha1": sha,
            "url": url,
            "doc_type": doc_type,
            "n_pages": n_pages,
            "size_kb": round(size_kb, 1),
            "kb_per_page": round(kb_pg, 1),
            "stratum": stratum,
        }

    for sha, url, doc_type in rows:
        if len(born_digital) >= target_each and len(scanned) >= target_each:
            break
        pdf_path = PECAS_ROOT / f"{sha}.pdf.gz"
        if not pdf_path.exists():
            continue

        # Stat is essentially free — gates the slow parse.
        size_kb = pdf_path.stat().st_size / 1024
        if size_kb < 1.0:  # corrupt empty cache entry
            failed += 1
            continue

        n_pages = page_count_with_timeout(pdf_path)
        probed += 1
        if n_pages is None:
            failed += 1
            continue

        kb_pg = size_kb / n_pages
        stratum = "scanned" if kb_pg >= SCAN_KB_PER_PAGE_THRESHOLD else "born_digital"
        bucket = scanned if stratum == "scanned" else born_digital
        if len(bucket) >= target_each:
            continue

        bucket.append(_record(sha, url, doc_type, n_pages, size_kb, kb_pg, stratum))

        if probed % 100 == 0:
            print(
                f"  probed {probed} | born_digital={len(born_digital)}"
                f" scanned={len(scanned)} failed={failed}",
                flush=True,
            )

    print(
        f"final: probed={probed} born_digital={len(born_digital)}"
        f" scanned={len(scanned)} failed={failed}",
        flush=True,
    )

    if len(born_digital) < target_each or len(scanned) < target_each:
        print(
            f"WARNING: short of target ({target_each}/stratum). Scanned bucket "
            f"is the rare one — increase pool or lower target_each.",
            flush=True,
        )

    # Tag the first GOLD_PER_STRATUM of each stratum for hand-correction.
    rows: list[dict] = []
    for bucket in (born_digital, scanned):
        for i, row in enumerate(bucket):
            row["gold_corrected"] = i < GOLD_PER_STRATUM
            rows.append(row)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    manifest_path = OUT_DIR / "manifest.jsonl"
    with manifest_path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    gold_n = sum(1 for r in rows if r["gold_corrected"])
    diff_n = len(rows) - gold_n
    print(f"wrote {manifest_path}  ({len(rows)} rows: {gold_n} gold, {diff_n} diff-only)")


if __name__ == "__main__":
    main()
