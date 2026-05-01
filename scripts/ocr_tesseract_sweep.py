"""Tesseract hyperparameter sweep — workers, DPI, PSM, OEM.

Reuses the 2026-04-30 OCR bakeoff manifest + gold subset:
- ``runs/active/2026-04-30-ocr-bakeoff/manifest.jsonl`` — sampled PDFs
- ``runs/active/2026-04-30-ocr-bakeoff/gold/<sha1>.txt`` — references

Sweeps each axis independently (one-axis-at-a-time; other axes held at
default). Defaults match the bakeoff anchor: workers=auto, dpi=200,
psm=3, oem=3.

Default axes:
- workers: 1, 2, 4, <auto>
- dpi:     150, 200, 300
- psm:     3, 4, 6, 11
- oem:     1, 3

Output:
- ``<out>/sweep_results.jsonl`` — one row per (sha1, axis, value) cell
- ``<out>/sweep_report.md``     — per-axis summary table

Run after `ocr_bakeoff_sample.py` has populated the manifest:

    uv run python scripts/ocr_tesseract_sweep.py --smoke    # 2 PDFs, all axes
    uv run python scripts/ocr_tesseract_sweep.py            # 5 PDFs, all axes
    uv run python scripts/ocr_tesseract_sweep.py --pdfs 20  # full gold subset
"""

from __future__ import annotations

import argparse
import gzip
import json
import re
import statistics
import time
from collections import defaultdict
from dataclasses import replace
from pathlib import Path

from jiwer import cer

from judex.scraping.ocr.base import OCRConfig
from judex.scraping.ocr.tesseract_local import (
    _resolve_workers as _tesseract_resolve_workers,
    extract,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
PECAS_ROOT = REPO_ROOT / "data" / "raw" / "pecas"
DEFAULT_BAKEOFF = REPO_ROOT / "runs" / "active" / "2026-04-30-ocr-bakeoff"
DEFAULT_OUT = REPO_ROOT / "runs" / "active" / "2026-05-01-tesseract-sweep"

_WS_RE = re.compile(r"\s+")
# Markdown markers Chandra emits — stripped before CER so Tesseract's
# plain-text output isn't penalized for "missing" Markdown syntax.
_MD_RE = re.compile(r"(\*\*|\*|_|`|^#+\s*)", re.MULTILINE)


def _normalize(text: str) -> str:
    return _WS_RE.sub(" ", (text or "")).strip()


def _normalize_for_cer(text: str) -> str:
    """Whitespace-fold AND strip Markdown markers (for Chandra comparison)."""
    return _WS_RE.sub(" ", _MD_RE.sub("", text or "")).strip()


def _resolve_auto_workers() -> int:
    """Mirror what tesseract_local picks when ``tesseract_workers=None``.

    Routes through ``tesseract_local._resolve_workers`` so the "auto"
    label in the sweep is the same number the provider would pick on
    this box: RAM-capped on memory-tight hosts (3 on a 3 GiB WSL),
    cpu-bound on workstations.
    """
    return _tesseract_resolve_workers(None, n_pages=10**6)


def load_manifest(bakeoff_dir: Path) -> list[dict]:
    path = bakeoff_dir / "manifest.jsonl"
    if not path.exists():
        raise SystemExit(
            f"manifest not found: {path}\n"
            "run `uv run python scripts/ocr_bakeoff_sample.py` first."
        )
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]


def pick_pdfs(manifest: list[dict], n: int, gold_only: bool) -> list[dict]:
    """Pick a representative subset, prioritizing gold-tagged PDFs.

    Stratified across (gold_corrected, stratum) so a small N still covers
    the variance the full bakeoff revealed (born-digital fast path vs
    scanned-DESPACHO scribbles).
    """
    rows = [m for m in manifest if m.get("gold_corrected")] if gold_only else manifest
    by_stratum: dict[str, list[dict]] = defaultdict(list)
    for m in rows:
        by_stratum[m.get("stratum") or "?"].append(m)
    # Round-robin across strata so we never get all-born-digital on small N.
    out: list[dict] = []
    keys = list(by_stratum.keys())
    while len(out) < n and any(by_stratum[k] for k in keys):
        for k in keys:
            if by_stratum[k] and len(out) < n:
                out.append(by_stratum[k].pop(0))
    return out


def load_gold(bakeoff_dir: Path, sha: str) -> str | None:
    p = bakeoff_dir / "gold" / f"{sha}.txt"
    if not p.exists():
        return None
    return p.read_text(encoding="utf-8")


def load_chandra(bakeoff_dir: Path, sha: str) -> str | None:
    """Chandra-extracted text from the 2026-04-30 bakeoff — used as
    'golden by proxy' since the bakeoff ranked it as the cleanest body
    text of any provider (no char errors, accents intact, correct order).
    Caveat: aggressive boilerplate stripping + rare Markdown hallucination
    on short docs."""
    p = bakeoff_dir / "texts" / f"{sha}.chandra.txt"
    if not p.exists():
        return None
    return p.read_text(encoding="utf-8")


def load_pypdf(bakeoff_dir: Path, sha: str, pdf_bytes: bytes) -> str | None:
    """pypdf text-layer reference. Cheap to extract (<0.1 s) so we run
    on demand and cache the result alongside the bakeoff outputs.

    Caveat: pypdf returns empty/garbage on scanned PDFs (no text layer).
    CER vs pypdf will be near 100% on scanned strata — that's expected,
    not a bug; treat the score as meaningful only on born-digital."""
    p = bakeoff_dir / "texts" / f"{sha}.pypdf.txt"
    if p.exists():
        return p.read_text(encoding="utf-8")
    from judex.scraping.ocr.pypdf import extract as pypdf_extract
    try:
        result = pypdf_extract(pdf_bytes, config=OCRConfig(provider="pypdf"))
    except Exception:
        return None
    text = result.text or ""
    p.write_text(text, encoding="utf-8")
    return text


def load_pdf_bytes(sha: str) -> bytes:
    p = PECAS_ROOT / f"{sha}.pdf.gz"
    with gzip.open(p, "rb") as f:
        return f.read()


def _safe_cer(ref: str | None, hyp: str) -> float | None:
    if ref is None:
        return None
    try:
        return cer(_normalize_for_cer(ref), _normalize_for_cer(hyp))
    except Exception:
        return None


def run_cell(
    pdf_bytes: bytes,
    base_cfg: OCRConfig,
    overrides: dict,
    gold_text: str | None,
    chandra_text: str | None,
    pypdf_text: str | None,
) -> dict:
    """Run one (PDF, hyperparameter cell) and return a result row.

    Scored against three references:
    - ``cer_gold``    — vs hand-corrected gold (gold subset only)
    - ``cer_chandra`` — vs Chandra (cleanest body fidelity, all 50 PDFs)
    - ``cer_pypdf``   — vs pypdf text layer (born-digital meaningful only)
    """
    cfg = replace(base_cfg, **overrides)
    t0 = time.monotonic()
    try:
        result = extract(pdf_bytes, config=cfg)
        wall = time.monotonic() - t0
        text = result.text or ""
        return {
            "ok": True,
            "wall_seconds": round(wall, 3),
            "n_pages": result.pages_processed or 0,
            "n_chars": len(text),
            "cer_gold": _safe_cer(gold_text, text),
            "cer_chandra": _safe_cer(chandra_text, text),
            "cer_pypdf": _safe_cer(pypdf_text, text),
            "error": None,
        }
    except Exception as exc:
        return {
            "ok": False,
            "wall_seconds": round(time.monotonic() - t0, 3),
            "n_pages": 0,
            "n_chars": 0,
            "cer_gold": None,
            "cer_chandra": None,
            "cer_pypdf": None,
            "error": f"{type(exc).__name__}: {exc}",
        }


def axis_grid(auto_workers: int) -> dict[str, list]:
    """The default sweep grid. Each axis is varied while others stay at default."""
    return {
        "tesseract_workers": [1, 2, 4, auto_workers],
        "tesseract_dpi": [150, 200, 300],
        "tesseract_psm": [3, 4, 6, 11],
        "tesseract_oem": [1, 3],
    }


def append_jsonl(path: Path, row: dict) -> None:
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def build_report(
    out_dir: Path,
    grid: dict[str, list],
    auto_workers: int,
) -> str:
    rows = [
        json.loads(l)
        for l in (out_dir / "sweep_results.jsonl").read_text().splitlines()
        if l.strip()
    ]
    by_cell: dict[tuple[str, object], list[dict]] = defaultdict(list)
    for r in rows:
        by_cell[(r["axis"], r["value"])].append(r)

    lines: list[str] = []
    lines.append("# Tesseract hyperparameter sweep\n")
    lines.append(f"- machine: auto={auto_workers} workers (RAM-capped via `tesseract_local._resolve_workers`)")
    lines.append(f"- baseline: workers={auto_workers}, dpi=200, psm=3, oem=3")
    lines.append(f"- runs: {len(rows)} cells across {len({r['sha1'] for r in rows})} PDFs")
    lines.append("")

    for axis, values in grid.items():
        lines.append(f"## Axis: `{axis}`\n")
        lines.append(
            "| value | n | median wall (s) | mean pps | "
            "CER vs gold | CER vs Chandra | CER vs pypdf |"
        )
        lines.append("|---|---:|---:|---:|---:|---:|---:|")
        for v in values:
            cell_rows = [r for r in by_cell.get((axis, v), []) if r["ok"]]
            if not cell_rows:
                lines.append(f"| {v} | 0 | — | — | — | — | — |")
                continue
            walls = [r["wall_seconds"] for r in cell_rows]
            pages = [r["n_pages"] for r in cell_rows if r["n_pages"]]
            gcer = [r["cer_gold"] for r in cell_rows if r.get("cer_gold") is not None]
            ccer = [r["cer_chandra"] for r in cell_rows if r.get("cer_chandra") is not None]
            pcer = [r["cer_pypdf"] for r in cell_rows if r.get("cer_pypdf") is not None]
            med_wall = statistics.median(walls)
            mean_pps = (sum(pages) / sum(walls)) if walls and pages else 0.0

            def _cell(xs):
                return f"{statistics.median(xs)*100:.2f}% (n={len(xs)})" if xs else "—"

            lines.append(
                f"| {v} | {len(cell_rows)} | {med_wall:.2f} | {mean_pps:.2f} | "
                f"{_cell(gcer)} | {_cell(ccer)} | {_cell(pcer)} |"
            )
        lines.append("")

    # Worst failures, if any.
    failed = [r for r in rows if not r["ok"]]
    if failed:
        lines.append("## Failures\n")
        for r in failed[:20]:
            lines.append(
                f"- `{r['sha1'][:8]}` axis={r['axis']} value={r['value']}: {r['error']}"
            )
        lines.append("")

    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bakeoff-dir", type=Path, default=DEFAULT_BAKEOFF)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--pdfs", type=int, default=5,
                        help="number of PDFs to sweep across (default: 5)")
    parser.add_argument("--smoke", action="store_true",
                        help="2 PDFs, narrowed grid (workers + dpi only)")
    parser.add_argument("--axes", nargs="+",
                        choices=["tesseract_workers", "tesseract_dpi",
                                 "tesseract_psm", "tesseract_oem"],
                        default=None,
                        help="restrict to specific axes (default: all)")
    parser.add_argument("--gold-only", action="store_true", default=True,
                        help="restrict to gold-tagged PDFs (default: True)")
    args = parser.parse_args(argv)

    auto_workers = _resolve_auto_workers()
    out_dir: Path = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    results_path = out_dir / "sweep_results.jsonl"
    # Truncate so reruns are clean — sweep is fast enough that resume isn't needed.
    results_path.write_text("")

    manifest = load_manifest(args.bakeoff_dir)
    n_pdfs = 2 if args.smoke else args.pdfs
    sampled = pick_pdfs(manifest, n_pdfs, gold_only=args.gold_only)

    grid = axis_grid(auto_workers)
    if args.smoke:
        grid = {
            "tesseract_workers": [1, 2, auto_workers],
            "tesseract_dpi": [150, 200, 300],
        }
    elif args.axes:
        grid = {k: v for k, v in grid.items() if k in args.axes}

    base_cfg = OCRConfig(
        provider="tesseract_local",
        tesseract_dpi=200,
        tesseract_psm=3,
        tesseract_oem=3,
        tesseract_workers=auto_workers,
    )

    n_cells = sum(len(v) for v in grid.values()) * len(sampled)
    print(f"sweep: {len(sampled)} PDFs × {sum(len(v) for v in grid.values())} cells "
          f"= {n_cells} runs (auto_workers={auto_workers})")
    print(f"  axes: {list(grid.keys())}")
    print(f"  pdfs: {[m['sha1'][:8] for m in sampled]}")
    print(f"  out:  {out_dir}")
    print()

    i = 0
    for m in sampled:
        sha = m["sha1"]
        try:
            pdf_bytes = load_pdf_bytes(sha)
        except FileNotFoundError:
            print(f"  MISSING {sha[:8]} — skipping")
            continue
        gold = load_gold(args.bakeoff_dir, sha)
        chandra = load_chandra(args.bakeoff_dir, sha)
        pypdf_text = load_pypdf(args.bakeoff_dir, sha, pdf_bytes)

        for axis, values in grid.items():
            for v in values:
                i += 1
                overrides = {axis: v}
                outcome = run_cell(
                    pdf_bytes, base_cfg, overrides, gold, chandra, pypdf_text,
                )
                row = {
                    "sha1": sha,
                    "axis": axis,
                    "value": v,
                    "stratum": m.get("stratum"),
                    "doc_type": m.get("doc_type"),
                    "manifest_n_pages": m.get("n_pages"),
                    **outcome,
                }
                append_jsonl(results_path, row)

                def _pct(x):
                    return f"{x*100:.1f}%" if x is not None else "—"

                ok_str = "ok" if outcome["ok"] else "FAIL"
                print(
                    f"[{i:3d}/{n_cells}] {sha[:8]} {axis}={v!s:<3} "
                    f"{ok_str} {outcome['wall_seconds']:5.2f}s "
                    f"{outcome['n_pages']:>2}pg {outcome['n_chars']:>6}c "
                    f"g={_pct(outcome['cer_gold'])} "
                    f"c={_pct(outcome['cer_chandra'])} "
                    f"p={_pct(outcome['cer_pypdf'])}",
                    flush=True,
                )

    report = build_report(out_dir, grid, auto_workers)
    (out_dir / "sweep_report.md").write_text(report, encoding="utf-8")
    print()
    print(f"wrote {results_path}")
    print(f"wrote {out_dir / 'sweep_report.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
