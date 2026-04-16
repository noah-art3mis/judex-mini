"""
Compare the HTTP scraper vs. a captured Selenium output.

Run:
    uv run python scripts/bench_http_vs_selenium.py AI 772309

Assumes Selenium already produced output/bench/judex-mini_{classe}_{n}-{n}.json
(see `main.py -c AI -i 772309 -f 772309 -o json -d output/bench`).
"""

from __future__ import annotations

import json
import sys
import time
import urllib3
from pathlib import Path
from typing import Any

from src.scraper_http import fetch_process, scrape_processo_http

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


# Fields we don't expect to match (or that aren't diffable):
#   extraido — timestamp, will always differ
#   html     — giant string, we only care that it's populated
#   sessao_virtual — known limitation in HTTP path
#   status   — trivially 200 both sides
SKIP_FIELDS = {"extraido", "html", "sessao_virtual", "status"}


def diff_item(http: dict, selenium: dict) -> list[str]:
    messages: list[str] = []
    keys = set(http) | set(selenium)
    for k in sorted(keys):
        if k in SKIP_FIELDS:
            continue
        a = http.get(k)
        b = selenium.get(k)
        if a == b:
            continue
        messages.append(f"  {k!r}:\n    http:     {a!r}\n    selenium: {b!r}")
    return messages


def main(classe: str, processo: int) -> int:
    selenium_path = Path(f"output/bench/judex-mini_{classe}_{processo}-{processo}.json")
    if not selenium_path.exists():
        print(f"ERROR: missing Selenium output at {selenium_path}")
        print(
            f"Run: uv run python main.py -c {classe} -i {processo} -f {processo} "
            f"-o json -d output/bench --overwrite"
        )
        return 2

    with selenium_path.open() as f:
        sel_items = json.load(f)
    sel_item: dict[str, Any] = sel_items[0] if isinstance(sel_items, list) else sel_items

    print(f"== HTTP fetch (cache off) for {classe} {processo} ==")
    t0 = time.perf_counter()
    fetched = fetch_process(classe, processo, use_cache=False)
    t_fetch = time.perf_counter() - t0
    if fetched is None:
        print("ERROR: HTTP fetch failed to resolve incidente")
        return 3

    print(f"  incidente:     {fetched.incidente}")
    print(f"  detalhe bytes: {len(fetched.detalhe_html)}")
    for tab, html in fetched.tabs.items():
        print(f"  {tab:<20s} {len(html):>7d} bytes")
    print(f"  total wall:    {t_fetch:.2f}s")

    print()
    print("== scrape_processo_http (uses cache) ==")
    t0 = time.perf_counter()
    http_item = scrape_processo_http(classe, processo, use_cache=True)
    t_scrape = time.perf_counter() - t0
    assert http_item is not None
    print(f"  total wall: {t_scrape * 1000:.1f}ms (cache hits)")

    print()
    print(f"== field-by-field diff (skipping {sorted(SKIP_FIELDS)}) ==")
    diffs = diff_item(dict(http_item), sel_item)
    if not diffs:
        print("  ALL FIELDS MATCH")
    else:
        print(f"  {len(diffs)} field(s) differ:")
        for d in diffs:
            print(d)

    print()
    print("== summary ==")
    print(f"  selenium baseline (measured earlier): 4.98s steady, 18s including driver startup")
    print(f"  http fresh:   {t_fetch:.2f}s")
    print(f"  http cached:  {t_scrape * 1000:.1f}ms")

    return 0 if not diffs else 1


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("usage: bench_http_vs_selenium.py <classe> <processo>")
        sys.exit(2)
    sys.exit(main(sys.argv[1], int(sys.argv[2])))
