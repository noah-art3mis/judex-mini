"""Seed the gold/ directory with Mistral baseline texts as starting points
for hand-correction.

For every PDF tagged ``gold_corrected: true`` in manifest.jsonl, copies
``texts/<sha1>.mistral.txt`` to ``gold/<sha1>.txt``. Skips files that
already exist in gold/ (so re-runs don't clobber edits in progress).

Also writes ``gold/_index.md`` — a checklist with the PDF link, page
count, and stratum so you can work through them in order.

Run after the Mistral baseline pass:

    uv run python scripts/ocr_bakeoff_gold_init.py
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT_DIR = REPO_ROOT / "runs" / "active" / "2026-04-30-ocr-bakeoff"


def main() -> int:
    out_dir = DEFAULT_OUT_DIR
    manifest_path = out_dir / "manifest.jsonl"
    texts_dir = out_dir / "texts"
    gold_dir = out_dir / "gold"
    gold_dir.mkdir(exist_ok=True)

    rows = [json.loads(l) for l in manifest_path.read_text().splitlines() if l.strip()]
    gold_rows = [r for r in rows if r.get("gold_corrected")]

    n_seeded = n_skipped = n_missing = 0
    index_lines: list[str] = ["# Hand-correction checklist\n"]
    index_lines.append(
        f"{len(gold_rows)} PDFs to correct ({sum(1 for r in gold_rows if r['stratum']=='born_digital')} "
        f"born-digital + {sum(1 for r in gold_rows if r['stratum']=='scanned')} scanned)\n"
    )
    index_lines.append("Workflow: open the PDF, compare against `gold/<sha1>.txt`, fix Mistral errors.\n")
    index_lines.append("")
    index_lines.append("| sha1 (8) | stratum | pages | doc_type | url |")
    index_lines.append("|---|---|---:|---|---|")

    for row in gold_rows:
        sha = row["sha1"]
        src = texts_dir / f"{sha}.mistral.txt"
        dst = gold_dir / f"{sha}.txt"
        if not src.exists():
            n_missing += 1
            print(f"  MISSING mistral text for {sha[:8]} — run mistral pass first")
            continue
        if dst.exists():
            n_skipped += 1
        else:
            shutil.copy2(src, dst)
            n_seeded += 1
        index_lines.append(
            f"| `{sha[:8]}` | {row['stratum']} | {row['n_pages']} | "
            f"{(row.get('doc_type') or '—')[:24]} | <{row['url']}> |"
        )

    (gold_dir / "_index.md").write_text("\n".join(index_lines), encoding="utf-8")
    print(f"\nseeded {n_seeded} new gold files, skipped {n_skipped} existing, "
          f"{n_missing} missing source")
    print(f"checklist: {gold_dir}/_index.md")
    print(f"\nedit each file in {gold_dir}/ — they become the ground truth for CER scoring.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
