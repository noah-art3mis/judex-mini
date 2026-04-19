"""
Run the HTTP scraper against every fixture in tests/ground_truth/ and
diff each top-level field.

Run:
    PYTHONPATH=. uv run python scripts/validate_ground_truth.py

Hits the live STF portal on first run (once per fixture, tabs
parallelized). Cached thereafter — iterate freely.

Ground truths were captured at some earlier date, so a process's
reverse-chronological lists may have grown since. The harness reports
additions separately from mismatches so genuine drift doesn't get
flagged as breakage.
"""

from __future__ import annotations

import json
import re
import sys
import time
import urllib3
from pathlib import Path
from typing import Any

from judex.sweeps.diff_harness import diff_item
from judex.scraping.http_session import new_session
from judex.scraping.scraper import scrape_processo_http

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def _load_fixture(path: Path) -> dict[str, Any]:
    return json.load(path.open())


def _split_filename(path: Path) -> tuple[str, int]:
    m = re.match(r"([A-Z]+)_(\d+)", path.stem)
    assert m, f"unexpected fixture name: {path.name}"
    return m.group(1), int(m.group(2))


def main() -> int:
    fixtures = sorted(Path("tests/ground_truth").glob("*.json"))
    if not fixtures:
        print("no fixtures found under tests/ground_truth/")
        return 2

    results: list[tuple[Path, int, float]] = []
    with new_session() as session:
        for path in fixtures:
            classe, processo = _split_filename(path)
            print(f"\n=== {path.name} ({classe} {processo}) ===")

            t0 = time.perf_counter()
            try:
                http_item = scrape_processo_http(
                    classe, processo, use_cache=True, session=session
                )
            except Exception as e:
                print(f"  ERROR: {e}")
                results.append((path, 1, 0.0))
                continue
            elapsed = time.perf_counter() - t0

            gt = _load_fixture(path)
            diffs = diff_item(dict(http_item), gt, allow_growth=True)
            print(f"  wall: {elapsed:.2f}s")
            if not diffs:
                print("  MATCH (all non-skipped fields equal ground truth)")
            else:
                print(f"  {len(diffs)} diff(s):")
                for d in diffs:
                    print(d)
            results.append((path, len(diffs), elapsed))

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    total = 0
    for path, n_diffs, elapsed in results:
        status = "OK" if n_diffs == 0 else f"{n_diffs} diff(s)"
        print(f"  {path.name:<30s} {elapsed:>5.2f}s  {status}")
        total += n_diffs
    print(f"\nTotal diffs across fixtures: {total}")
    return 0 if total == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
