"""Daily new-filings sweep → single Markdown report.

Pipeline:
    1. load per-class high-water mark from state file (or seed from warehouse)
    2. discover_new_numeros(classe, start=mark, resolver=…)
    3. scrape_processo_http for each newly-allocated number (metadata + PDFs + DJe)
    4. render_daily_markdown → docs/reports/daily/YYYY-MM-DD.md
    5. persist new high-water mark back to state file

Usage:
    uv run python scripts/daily_report.py --class HC --seed-from-warehouse   # first run
    uv run python scripts/daily_report.py --class HC                         # subsequent
    uv run python scripts/daily_report.py --class HC --proxy-pool proxies.txt
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from src.config import ScraperConfig
from src.reports.daily import render_daily_markdown
from src.reports.state import DailyState
from src.scraping.http_session import new_session
from src.scraping.proxy_pool import ProxyPool
from src.scraping.scraper import (
    NoIncidenteError,
    resolve_incidente,
    scrape_processo_http,
)
from src.sweeps.discovery import discover_new_numeros


_WAREHOUSE_PATH = Path("data/warehouse/judex.duckdb")


def _warehouse_max(classe: str) -> int:
    """Read MAX(processo_id) for `classe` from the DuckDB warehouse."""
    import duckdb

    con = duckdb.connect(str(_WAREHOUSE_PATH), read_only=True)
    try:
        row = con.execute(
            "SELECT MAX(processo_id) FROM cases WHERE classe = ?", [classe]
        ).fetchone()
    finally:
        con.close()
    if not row or row[0] is None:
        raise SystemExit(f"warehouse has no entries for classe={classe!r}")
    return int(row[0])


def _now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--class", dest="classe", default="HC",
                        help="Class to track (e.g. HC, ADI, ADPF). Default: HC.")
    parser.add_argument("--state-file", type=Path,
                        default=Path("state/daily_report.json"))
    parser.add_argument("--out-dir", type=Path,
                        default=Path("docs/reports/daily"))
    parser.add_argument("--proxy-pool", type=Path, default=None,
                        help="File with proxy URLs, one per line.")
    parser.add_argument("--stop-after-misses", type=int, default=20)
    parser.add_argument("--max-probes", type=int, default=1000)
    parser.add_argument("--seed-from-warehouse", action="store_true",
                        help="If state has no mark for --class, seed it from the warehouse.")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    state = DailyState.load(args.state_file)
    start = state.max_numero.get(args.classe)
    if start is None:
        if args.seed_from_warehouse:
            start = _warehouse_max(args.classe)
            logging.info("seeded %s from warehouse: max_numero=%d", args.classe, start)
        else:
            logging.error(
                "no high-water mark for class %r; re-run with --seed-from-warehouse",
                args.classe,
            )
            return 2

    pool = ProxyPool.from_file(args.proxy_pool) if args.proxy_pool else None
    session = new_session(proxy=pool.pick() if pool else None)
    config = ScraperConfig()

    def resolver(classe: str, numero: int) -> int:
        return resolve_incidente(session, classe, numero, config=config)

    t0 = time.time()
    logging.info("discovering %s numbers above %d…", args.classe, start)
    new = discover_new_numeros(
        args.classe,
        start=start,
        resolver=resolver,
        stop_after_misses=args.stop_after_misses,
        max_probes=args.max_probes,
    )
    logging.info("discovery: %d new cases", len(new))

    cases: list[dict] = []
    for d in new:
        try:
            item = scrape_processo_http(
                d.classe, d.numero,
                session=session, config=config,
                fetch_pdfs=True, fetch_dje=True,
            )
            cases.append(item)
        except NoIncidenteError:
            logging.warning(
                "%s %d: unallocated between discover+scrape; skipping",
                d.classe, d.numero,
            )
        except Exception as e:
            logging.exception("%s %d: scrape failed: %s", d.classe, d.numero, e)

    duration_s = round(time.time() - t0, 1)
    today = datetime.now(timezone.utc).date().isoformat()
    md = render_daily_markdown(
        cases,
        date=today,
        classe=args.classe,
        stats={
            "n_probed": len(new) + args.stop_after_misses,
            "duration_s": duration_s,
        },
    )

    args.out_dir.mkdir(parents=True, exist_ok=True)
    out_path = args.out_dir / f"{today}.md"
    out_path.write_text(md, encoding="utf-8")
    logging.info("wrote report → %s", out_path)

    if new:
        state.max_numero[args.classe] = max(
            state.max_numero.get(args.classe, 0),
            max(d.numero for d in new),
        )
    state.last_run_utc = _now_iso()
    state.save(args.state_file)
    logging.info("updated state → %s", args.state_file)

    return 0


if __name__ == "__main__":
    sys.exit(main())
