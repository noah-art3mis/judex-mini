"""
Compare the HTTP prototype vs. the already-captured Selenium output.

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

from src.scraper_http import extract_andamentos_http, fetch_process

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def main(classe: str, processo: int) -> int:
    selenium_path = Path(f"output/bench/judex-mini_{classe}_{processo}-{processo}.json")
    if not selenium_path.exists():
        print(f"ERROR: missing Selenium output at {selenium_path}")
        print("Run: uv run python main.py -c {classe} -i {processo} -f {processo} -o json -d output/bench --overwrite")
        return 2

    with selenium_path.open() as f:
        sel_items = json.load(f)
    sel_item = sel_items[0] if isinstance(sel_items, list) else sel_items
    sel_andamentos = sel_item.get("andamentos") or []

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
    print("== extract_andamentos_http ==")
    t0 = time.perf_counter()
    http_andamentos = extract_andamentos_http(fetched.tabs["abaAndamentos"])
    t_extract = time.perf_counter() - t0
    print(f"  count:    {len(http_andamentos)}")
    print(f"  parse:    {t_extract * 1000:.1f}ms")

    print()
    print(f"== diff vs Selenium ({len(sel_andamentos)} items) ==")
    if len(http_andamentos) != len(sel_andamentos):
        print(f"  COUNT MISMATCH: http={len(http_andamentos)} selenium={len(sel_andamentos)}")

    diffs = 0
    for i, (a, b) in enumerate(zip(http_andamentos, sel_andamentos)):
        for k in ("index_num", "data", "nome", "complemento", "julgador", "link_descricao", "link"):
            if a.get(k) != b.get(k):
                diffs += 1
                print(f"  [{i}] field={k!r}: http={a.get(k)!r} selenium={b.get(k)!r}")
    if diffs == 0 and len(http_andamentos) == len(sel_andamentos):
        print("  MATCH")

    print()
    print("== cached re-run ==")
    t0 = time.perf_counter()
    fetch_process(classe, processo, use_cache=True)
    t_cached = time.perf_counter() - t0
    print(f"  total wall (cached): {t_cached * 1000:.1f}ms")

    print()
    print("== summary ==")
    print(f"  selenium per-process (measured earlier): 4.98s + 13s driver = 18s total")
    print(f"  http fresh:   {t_fetch:.2f}s")
    print(f"  http cached:  {t_cached * 1000:.1f}ms")

    return 0


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("usage: bench_http_vs_selenium.py <classe> <processo>")
        sys.exit(2)
    sys.exit(main(sys.argv[1], int(sys.argv[2])))
