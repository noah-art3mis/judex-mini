"""CER + cost aggregator for the OCR bakeoff.

Reads:
- ``manifest.jsonl`` — sampled PDFs (`gold_corrected` flag)
- ``gold/<sha1>.txt`` — hand-corrected reference (only for gold-tagged PDFs)
- ``texts/<sha1>.<provider>.txt`` — provider outputs (from the runner)
- ``results.jsonl`` — timing + cost rows (from the runner)

Computes per (PDF, provider):
- CER vs gold (gold subset only) — via ``jiwer.cer`` on whitespace-normalized text
- Pairwise diff vs Mistral baseline (full set) — char-level Levenshtein ratio

Writes ``report.md`` with:
- Per-provider headline: median CER (gold), realized $/1k pages, mean pps
- Stratum breakdown (born_digital vs scanned)
- Per-PDF detail table (top 30 by absolute CER gap)

Run after the runner has produced texts for ≥2 providers (Mistral + at
least one challenger):

    uv run python scripts/ocr_bakeoff_score.py
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
from collections import defaultdict
from pathlib import Path

from jiwer import cer
from rapidfuzz.distance import Levenshtein


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT_DIR = REPO_ROOT / "runs" / "active" / "2026-04-30-ocr-bakeoff"

BASELINE_PROVIDER = "mistral"


_WS_RE = re.compile(r"\s+")


def normalize(text: str) -> str:
    """Whitespace-fold + strip — keeps case/diacritics (matters for legal text)."""
    return _WS_RE.sub(" ", text or "").strip()


def load_manifest(out_dir: Path) -> list[dict]:
    return [json.loads(l) for l in (out_dir / "manifest.jsonl").read_text().splitlines() if l.strip()]


def load_results(out_dir: Path) -> list[dict]:
    path = out_dir / "results.jsonl"
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]


def discover_providers(out_dir: Path) -> list[str]:
    seen: set[str] = set()
    for p in (out_dir / "texts").glob("*.txt"):
        # filename: <sha1>.<provider>.txt
        parts = p.stem.split(".")
        if len(parts) >= 2:
            seen.add(parts[-1])
    return sorted(seen)


def read_text(path: Path) -> str | None:
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8")


def diff_ratio(a: str, b: str) -> float:
    """1.0 == identical; 0.0 == fully different. Levenshtein normalized similarity."""
    a, b = normalize(a), normalize(b)
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return Levenshtein.normalized_similarity(a, b)


def build_report(out_dir: Path) -> str:
    manifest = load_manifest(out_dir)
    by_sha = {r["sha1"]: r for r in manifest}
    results = load_results(out_dir)
    providers = discover_providers(out_dir)
    texts_dir = out_dir / "texts"
    gold_dir = out_dir / "gold"

    # Index results by (sha, provider) — last write wins.
    res_idx: dict[tuple[str, str], dict] = {
        (r["sha1"], r["provider"]): r for r in results
    }

    # Collect per-(sha, provider) text + gold reference + baseline text.
    rows: list[dict] = []
    for m in manifest:
        sha = m["sha1"]
        gold_text = read_text(gold_dir / f"{sha}.txt") if m.get("gold_corrected") else None
        baseline_text = read_text(texts_dir / f"{sha}.{BASELINE_PROVIDER}.txt")
        for prov in providers:
            ptext = read_text(texts_dir / f"{sha}.{prov}.txt")
            if ptext is None:
                continue
            r = res_idx.get((sha, prov), {})
            cer_score = None
            if gold_text is not None:
                try:
                    cer_score = cer(normalize(gold_text), normalize(ptext))
                except Exception:
                    cer_score = None
            sim_to_baseline = None
            if baseline_text is not None and prov != BASELINE_PROVIDER:
                sim_to_baseline = diff_ratio(baseline_text, ptext)
            rows.append({
                "sha1": sha,
                "provider": prov,
                "stratum": m.get("stratum"),
                "doc_type": m.get("doc_type"),
                "n_pages": r.get("n_pages") or m.get("n_pages") or 0,
                "n_chars": len(ptext),
                "wall_seconds": r.get("wall_seconds"),
                "dollars": r.get("dollars"),
                "cer": cer_score,
                "sim_to_baseline": sim_to_baseline,
                "is_gold": gold_text is not None,
            })

    # ---------- Headline per provider ----------
    by_prov: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_prov[r["provider"]].append(r)

    lines: list[str] = []
    lines.append("# OCR provider bakeoff (2026-04-30)\n")
    lines.append(f"- providers: {', '.join(providers) if providers else '(none yet)'}")
    lines.append(f"- manifest: {len(manifest)} PDFs ({sum(1 for m in manifest if m.get('gold_corrected'))} gold)")
    lines.append("")

    lines.append("## Per-provider headline\n")
    lines.append("| provider | n_run | n_gold | median CER | mean pps | total $ | $/1k pages |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|")
    for prov in providers:
        prov_rows = by_prov[prov]
        n_run = len(prov_rows)
        gold_rows = [r for r in prov_rows if r["cer"] is not None]
        n_gold = len(gold_rows)
        med_cer = statistics.median(r["cer"] for r in gold_rows) if gold_rows else None
        total_pages = sum(r["n_pages"] or 0 for r in prov_rows)
        total_wall = sum(r["wall_seconds"] or 0 for r in prov_rows if r["wall_seconds"])
        total_dollars = sum(r["dollars"] or 0 for r in prov_rows if r["dollars"])
        pps = (total_pages / total_wall) if total_wall else 0
        per_1k = (total_dollars / total_pages * 1000) if total_pages else 0
        cer_cell = f"{med_cer*100:.2f}%" if med_cer is not None else "—"
        lines.append(
            f"| {prov} | {n_run} | {n_gold} | {cer_cell} | "
            f"{pps:.2f} | ${total_dollars:.4f} | ${per_1k:.4f} |"
        )
    lines.append("")

    # ---------- Stratum breakdown ----------
    lines.append("## CER by stratum (gold only)\n")
    lines.append("| provider | born_digital median | scanned median |")
    lines.append("|---|---:|---:|")
    for prov in providers:
        prov_rows = [r for r in by_prov[prov] if r["cer"] is not None]
        bd = [r["cer"] for r in prov_rows if r["stratum"] == "born_digital"]
        sc = [r["cer"] for r in prov_rows if r["stratum"] == "scanned"]
        bd_cell = f"{statistics.median(bd)*100:.2f}%" if bd else "—"
        sc_cell = f"{statistics.median(sc)*100:.2f}%" if sc else "—"
        lines.append(f"| {prov} | {bd_cell} | {sc_cell} |")
    lines.append("")

    # ---------- Pairwise similarity to Mistral baseline ----------
    if BASELINE_PROVIDER in providers:
        lines.append(f"## Similarity to {BASELINE_PROVIDER} baseline (all PDFs)\n")
        lines.append("| provider | median sim | p10 | p90 |")
        lines.append("|---|---:|---:|---:|")
        for prov in providers:
            if prov == BASELINE_PROVIDER:
                continue
            sims = [r["sim_to_baseline"] for r in by_prov[prov] if r["sim_to_baseline"] is not None]
            if not sims:
                continue
            sims_sorted = sorted(sims)
            med = statistics.median(sims_sorted)
            p10 = sims_sorted[max(0, int(0.10 * len(sims_sorted)) - 1)]
            p90 = sims_sorted[min(len(sims_sorted) - 1, int(0.90 * len(sims_sorted)))]
            lines.append(f"| {prov} | {med:.3f} | {p10:.3f} | {p90:.3f} |")
        lines.append("")

    # ---------- Worst gold disagreements ----------
    lines.append("## Worst CER (gold subset, top 20)\n")
    gold_only = [r for r in rows if r["cer"] is not None]
    gold_only.sort(key=lambda r: -r["cer"])
    if gold_only:
        lines.append("| sha | provider | stratum | doc_type | pages | CER |")
        lines.append("|---|---|---|---|---:|---:|")
        for r in gold_only[:20]:
            lines.append(
                f"| {r['sha1'][:8]} | {r['provider']} | {r['stratum']} | "
                f"{(r['doc_type'] or '—')[:24]} | {r['n_pages']} | "
                f"{r['cer']*100:.2f}% |"
            )
        lines.append("")
    else:
        lines.append("_(no gold-corrected references found yet)_\n")

    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    args = parser.parse_args(argv)

    report = build_report(args.out_dir)
    report_path = args.out_dir / "report.md"
    report_path.write_text(report, encoding="utf-8")
    print(f"wrote {report_path}  ({len(report.splitlines())} lines)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
