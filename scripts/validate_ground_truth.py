"""
Run the HTTP scraper against every fixture in tests/ground_truth/ and
diff each top-level field.

Run:
    PYTHONPATH=. uv run python scripts/validate_ground_truth.py

This hits the live STF portal on first run (once per fixture, tabs
parallelized). Cached thereafter — so iterate freely.

Ground truths were captured at some earlier date, so a process's
movement list may have grown since. The harness reports additions
separately from mismatches so genuine drift doesn't get flagged as
breakage. Known limitations (sessao_virtual, extraido, html, status)
are skipped.
"""

from __future__ import annotations

import json
import re
import sys
import time
import urllib3
from pathlib import Path
from typing import Any

from src.scraper_http import scrape_processo_http

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


SKIP_FIELDS = {"extraido", "html", "sessao_virtual", "status"}
# Lists where drift (new items) is expected over time. We compare the
# *overlap* with ground truth (oldest N items of the current list should
# equal the ground truth's list, since items are indexed reverse-chronologically).
GROWING_LISTS = {"andamentos", "peticoes", "recursos", "deslocamentos"}


def _load_fixture(path: Path) -> dict[str, Any]:
    data = json.load(path.open())
    return data[0] if isinstance(data, list) else data


def _split_filename(path: Path) -> tuple[str, int]:
    m = re.match(r"([A-Z]+)_(\d+)", path.stem)
    assert m, f"unexpected fixture name: {path.name}"
    return m.group(1), int(m.group(2))


def _diff_growing_list(key: str, http_list: list, gt_list: list) -> list[str]:
    """
    Lists are reverse-chronological (index_num N..1 or similar). If
    http_list is longer, the extras should be at the front (newer items).
    Compare http_list[-len(gt_list):] to gt_list.
    """
    msgs: list[str] = []
    if len(http_list) < len(gt_list):
        msgs.append(f"  {key}: http has FEWER items ({len(http_list)}) than ground truth ({len(gt_list)}) — regression")
        return msgs
    tail = http_list[-len(gt_list):] if gt_list else []
    if tail != gt_list:
        # Find first mismatch
        for i, (a, b) in enumerate(zip(tail, gt_list)):
            if a != b:
                msgs.append(f"  {key}[tail idx {i}]: http={a!r} vs gt={b!r}")
                if len(msgs) >= 3:
                    msgs.append(f"  {key}: (further diffs truncated)")
                    break
    added = len(http_list) - len(gt_list)
    if added > 0:
        msgs.append(f"  {key}: +{added} new item(s) since ground truth (expected drift, not a regression)")
    return msgs


def diff_item(http: dict, gt: dict) -> list[str]:
    messages: list[str] = []
    for k in sorted(set(http) | set(gt)):
        if k in SKIP_FIELDS:
            continue
        a = http.get(k)
        b = gt.get(k)
        if a == b:
            continue
        if k in GROWING_LISTS and isinstance(a, list) and isinstance(b, list):
            messages.extend(_diff_growing_list(k, a, b))
        else:
            # Clip long string diffs
            def _clip(v: Any) -> str:
                s = repr(v)
                return s if len(s) < 200 else s[:200] + "...[truncated]"
            messages.append(f"  {k}: http={_clip(a)} vs gt={_clip(b)}")
    return messages


def main() -> int:
    fixtures = sorted(Path("tests/ground_truth").glob("*.json"))
    if not fixtures:
        print("no fixtures found under tests/ground_truth/")
        return 2

    results: list[tuple[Path, int, list[str], float]] = []
    for path in fixtures:
        classe, processo = _split_filename(path)
        print(f"\n=== {path.name} ({classe} {processo}) ===")

        t0 = time.perf_counter()
        try:
            http_item = scrape_processo_http(classe, processo, use_cache=True)
        except Exception as e:
            print(f"  ERROR: {e}")
            results.append((path, 0, [f"exception: {e!r}"], 0.0))
            continue
        elapsed = time.perf_counter() - t0

        if http_item is None:
            print("  ERROR: HTTP fetch failed (no incidente)")
            results.append((path, 0, ["fetch failed"], elapsed))
            continue

        gt = _load_fixture(path)
        diffs = diff_item(dict(http_item), gt)
        print(f"  wall: {elapsed:.2f}s")
        if not diffs:
            print("  MATCH (all non-skipped fields equal ground truth)")
        else:
            print(f"  {len(diffs)} diff(s):")
            for d in diffs:
                print(d)
        results.append((path, len(diffs), diffs, elapsed))

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    total_diffs = 0
    for path, n_diffs, _, elapsed in results:
        status = "OK" if n_diffs == 0 else f"{n_diffs} diff(s)"
        print(f"  {path.name:<30s} {elapsed:>5.2f}s  {status}")
        total_diffs += n_diffs
    print(f"\nTotal diffs across fixtures: {total_diffs}")
    return 0 if total_diffs == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
