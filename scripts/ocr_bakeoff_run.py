"""Per-provider runner for the OCR bakeoff.

Reads ``manifest.jsonl`` from the bakeoff dir, runs one OCR provider
across every sampled PDF, and writes:

- ``texts/<sha1>.<provider>.txt`` — the extracted text
- ``results.jsonl`` — appended one row per (sha1, provider) with timing
  + cost + char/page counts
- ``failures.jsonl`` — appended on extract errors with traceback

Resumable: if ``texts/<sha1>.<provider>.txt`` already exists the row is
skipped. Run once per provider:

    uv run python scripts/ocr_bakeoff_run.py --provedor mistral
    uv run python scripts/ocr_bakeoff_run.py --provedor gemini --batch
    uv run python scripts/ocr_bakeoff_run.py --provedor surya  # via Modal
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import time
import traceback
from pathlib import Path

from dotenv import load_dotenv

from judex.scraping.ocr.base import OCRConfig
from judex.scraping.ocr.dispatch import estimate_cost, extract_pdf

# Load .env from repo root so MISTRAL_API_KEY / GEMINI_API_KEY are
# available without requiring `uv run --env-file .env`.
load_dotenv(Path(__file__).resolve().parents[1] / ".env")


REPO_ROOT = Path(__file__).resolve().parents[1]
PECAS_ROOT = REPO_ROOT / "data" / "raw" / "pecas"
DEFAULT_OUT_DIR = REPO_ROOT / "runs" / "active" / "2026-04-30-ocr-bakeoff"


# Env-var name per provider — keeps API keys out of argv / shell history.
_API_KEY_ENV = {
    "mistral": "MISTRAL_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "chandra": "DATALAB_API_KEY",
    "unstructured": "UNSTRUCTURED_API_KEY",
    # Local + Modal-served providers don't need a service key. The Modal
    # endpoints are auth'd via Modal's own token in ~/.modal.toml.
    "pypdf": "",
    "surya": "",
    "paddle": "",
    "tesseract": "",
}


def load_manifest(out_dir: Path) -> list[dict]:
    path = out_dir / "manifest.jsonl"
    if not path.exists():
        raise SystemExit(
            f"manifest not found: {path}\n"
            "run `uv run python scripts/ocr_bakeoff_sample.py` first."
        )
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def append_jsonl(path: Path, row: dict) -> None:
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--provedor", required=True,
                        choices=list(_API_KEY_ENV.keys()))
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--batch", action="store_true",
                        help="provider batch mode (mistral, gemini)")
    parser.add_argument("--limit", type=int, default=None,
                        help="cap number of PDFs (smoke test)")
    parser.add_argument("--forcar", action="store_true",
                        help="re-run even if text file exists")
    args = parser.parse_args(argv)

    out_dir: Path = args.out_dir
    texts_dir = out_dir / "texts"
    texts_dir.mkdir(parents=True, exist_ok=True)
    results_path = out_dir / "results.jsonl"
    failures_path = out_dir / "failures.jsonl"

    env_key = _API_KEY_ENV[args.provedor]
    api_key = os.environ.get(env_key, "") if env_key else ""
    if env_key and not api_key:
        raise SystemExit(f"missing env var {env_key} for provider {args.provedor}")

    config = OCRConfig(
        provider=args.provedor,
        api_key=api_key,
        batch=args.batch,
    )

    manifest = load_manifest(out_dir)
    if args.limit:
        manifest = manifest[: args.limit]

    print(f"running {args.provedor} (batch={args.batch}) on {len(manifest)} PDFs")
    print(f"  out: {out_dir}")

    n_ok = n_skip = n_fail = 0
    total_wall = 0.0
    total_pages = 0

    for i, row in enumerate(manifest, 1):
        sha = row["sha1"]
        text_path = texts_dir / f"{sha}.{args.provedor}.txt"
        if text_path.exists() and not args.forcar:
            n_skip += 1
            continue

        pdf_path = PECAS_ROOT / f"{sha}.pdf.gz"
        if not pdf_path.exists():
            print(f"[{i:3d}/{len(manifest)}] {sha[:8]} MISSING PDF — skipping")
            n_fail += 1
            continue

        with gzip.open(pdf_path, "rb") as f:
            pdf_bytes = f.read()

        t0 = time.monotonic()
        try:
            result = extract_pdf(pdf_bytes, config)
            wall = time.monotonic() - t0
        except Exception as exc:
            wall = time.monotonic() - t0
            n_fail += 1
            print(f"[{i:3d}/{len(manifest)}] {sha[:8]}  FAIL  {wall:5.1f}s  {type(exc).__name__}: {exc}")
            append_jsonl(failures_path, {
                "sha1": sha,
                "provider": args.provedor,
                "wall_seconds": round(wall, 3),
                "error_type": type(exc).__name__,
                "error": str(exc),
                "traceback": traceback.format_exc(),
            })
            continue

        text = result.text or ""
        text_path.write_text(text, encoding="utf-8")

        n_pages = result.pages_processed or row.get("n_pages") or 0
        # Prefer real cost from the provider (Gemini reports it via
        # usageMetadata); fall back to the per-page estimate from PRICING.
        if result.usd_cost is not None:
            dollars = result.usd_cost
        elif n_pages:
            dollars = estimate_cost(args.provedor, n_pages, batch=args.batch)
        else:
            dollars = 0.0

        n_ok += 1
        total_wall += wall
        total_pages += n_pages

        append_jsonl(results_path, {
            "sha1": sha,
            "provider": args.provedor,
            "batch": args.batch,
            "ok": True,
            "n_chars": len(text),
            "n_pages": n_pages,
            "wall_seconds": round(wall, 3),
            "dollars": round(dollars, 4),
            "input_tokens": result.input_tokens,
            "output_tokens": result.output_tokens,
            "stratum": row.get("stratum"),
            "doc_type": row.get("doc_type"),
        })
        print(
            f"[{i:3d}/{len(manifest)}] {sha[:8]}  ok  "
            f"{len(text):>6d}c {n_pages:>2d}pg {wall:5.1f}s ${dollars:.4f}"
        )

    print()
    print(f"done: ok={n_ok} skip={n_skip} fail={n_fail}")
    print(f"  total wall: {total_wall:.1f}s  total pages: {total_pages}  "
          f"avg pps: {total_pages / total_wall if total_wall else 0:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
