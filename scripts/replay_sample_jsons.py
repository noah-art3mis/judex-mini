"""Heal URL-only documentos in existing sample JSONs from the PDF cache.

Background
----------
Between 2026-04-16 and 2026-04-17 the cache-hot replay step used to
populate `data/output/sample/hc_*/judex-mini_HC_<n>-<n>.json` was run
with `fetch_pdfs=False` (either explicitly or via a stale main.py
default), so many pieces of PDF text sit in `data/pdf/<sha1>.txt.gz`
but the JSONs still carry the source URLs for those documents.

This script walks each JSON, and for every documentos entry whose
value is a URL, looks up `pdf_cache.read(url)`. When there's a cache
hit, the URL is replaced by the extracted text in-place. No scraping,
no network. This is ~100× faster than re-running `scrape_processo_http`
per file because it skips HTML parsing entirely.

Entries for which the cache has no text (genuine fetch failures) are
left as URLs — those need re-scraping via `run_sweep.py`, not this
script.

Usage
-----

    PYTHONPATH=. uv run python scripts/replay_sample_jsons.py
    PYTHONPATH=. uv run python scripts/replay_sample_jsons.py \\
        --sample-dir data/output/sample/hc_230000_230999
    PYTHONPATH=. uv run python scripts/replay_sample_jsons.py --dry-run
"""

from __future__ import annotations

import argparse
import glob
import json
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from src.utils import pdf_cache


def _first_item(raw: Any) -> dict:
    if isinstance(raw, list):
        return raw[0] if raw else {}
    return raw or {}


def _heal_documentos(docs: Any, stats: dict[str, int]) -> Any:
    """Return a possibly-rewritten docs dict and mutate `stats`."""
    if not isinstance(docs, dict):
        return docs
    out: dict[str, Any] = {}
    for k, v in docs.items():
        if isinstance(v, str) and v.startswith("https://"):
            host = (urlparse(v).hostname or "?").lower()
            stats[f"before::{host}"] = stats.get(f"before::{host}", 0) + 1
            cached = pdf_cache.read(v)
            if cached:
                out[k] = cached
                stats["healed"] = stats.get("healed", 0) + 1
            else:
                out[k] = v
                stats[f"miss::{host}"] = stats.get(f"miss::{host}", 0) + 1
        else:
            out[k] = v
    return out


def heal_file(path: Path, dry_run: bool, stats: dict[str, int]) -> bool:
    """Return True if the file was rewritten."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    item = _first_item(raw)
    sv = item.get("sessao_virtual")
    if not sv:
        return False

    sessions = sv if isinstance(sv, list) else [sv]
    changed = False
    file_stats: dict[str, int] = {}
    new_sessions = []
    for session in sessions:
        if not isinstance(session, dict):
            new_sessions.append(session)
            continue
        docs = session.get("documentos")
        if not docs:
            new_sessions.append(session)
            continue
        new_docs = _heal_documentos(docs, file_stats)
        if new_docs is not docs:
            session = {**session, "documentos": new_docs}
            changed = True
        new_sessions.append(session)

    for k, v in file_stats.items():
        stats[k] = stats.get(k, 0) + v

    if not changed or file_stats.get("healed", 0) == 0:
        return False

    if dry_run:
        return False

    if isinstance(raw, list):
        raw[0] = {**item, "sessao_virtual": new_sessions if isinstance(sv, list) else new_sessions[0]}
        payload = raw
    else:
        payload = {**item, "sessao_virtual": new_sessions if isinstance(sv, list) else new_sessions[0]}

    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    tmp.replace(path)
    return True


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--sample-root", type=Path, default=Path("data/output/sample"),
        help="Directory holding hc_<lo>_<hi>/ subdirs (default: data/output/sample).",
    )
    ap.add_argument(
        "--sample-dir", type=Path, default=None,
        help="Process a single sample dir instead of walking --sample-root.",
    )
    ap.add_argument(
        "--dry-run", action="store_true",
        help="Count healable documentos without rewriting any JSON.",
    )
    ap.add_argument(
        "--progress-every", type=int, default=500,
        help="Print progress every N files (default: 500).",
    )
    args = ap.parse_args(argv)

    if args.sample_dir:
        paths = sorted(args.sample_dir.glob("judex-mini_*.json"))
    else:
        paths = sorted(
            Path(p) for p in glob.glob(
                str(args.sample_root / "hc_*" / "judex-mini_*.json")
            )
        )

    if not paths:
        print(f"No sample JSONs found under {args.sample_root}", file=sys.stderr)
        return 2

    print(f"Healing {len(paths)} files (dry_run={args.dry_run})", flush=True)
    stats: dict[str, int] = {}
    rewritten = 0
    t0 = time.perf_counter()
    for i, p in enumerate(paths, 1):
        try:
            if heal_file(p, args.dry_run, stats):
                rewritten += 1
        except Exception as e:
            print(f"  [err] {p}: {e}", flush=True)
        if i % args.progress_every == 0:
            rate = i / max(time.perf_counter() - t0, 1e-6)
            print(f"  [{i}/{len(paths)}] rewritten={rewritten} {rate:.0f} files/s", flush=True)

    wall = time.perf_counter() - t0
    print()
    print("=== heal summary ===")
    print(f"files scanned:   {len(paths)}")
    print(f"files rewritten: {rewritten}")
    print(f"urls healed:     {stats.get('healed', 0)}")
    print(f"wall:            {wall:.1f}s ({len(paths)/max(wall,1e-6):.0f} files/s)")
    print()
    print("URL counts by host:")
    before_hosts = sorted(k.split("::", 1)[1] for k in stats if k.startswith("before::"))
    for h in before_hosts:
        before = stats.get(f"before::{h}", 0)
        miss = stats.get(f"miss::{h}", 0)
        healed = before - miss
        print(f"  {h:30s}  before={before:6d}  healed={healed:6d}  still_url={miss:6d}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
