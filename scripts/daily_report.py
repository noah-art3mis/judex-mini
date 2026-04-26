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

from judex.config import ScraperConfig
from judex.reports.daily import WatchedCaseChange, render_daily_markdown
from judex.reports.state import DailyState
from judex.reports.watch_diff import diff_watched
from judex.reports.watchlist import load_snapshot, parse_watchlist, save_snapshot
from judex.scraping.http_session import new_session
from judex.scraping.proxy_pool import ProxyPool
from judex.scraping.scraper import (
    NoIncidenteError,
    resolve_incidente,
    scrape_processo_http,
)
from judex.sweeps.discovery import discover_new_numeros


_WAREHOUSE_PATH = Path("data/derived/warehouse/judex.duckdb")


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


def run_daily_report(
    *,
    classe: str = "HC",
    state_file: Path = Path("state/daily_report.json"),
    out_dir: Path = Path("docs/reports/daily"),
    proxy_pool: Path | None = None,
    stop_after_misses: int = 20,
    max_probes: int = 1000,
    seed_from_warehouse: bool = False,
    watchlist: Path | None = None,
    snapshot_root: Path = Path("state/watchlist"),
) -> int:
    args = argparse.Namespace(
        classe=classe, state_file=state_file, out_dir=out_dir,
        proxy_pool=proxy_pool, stop_after_misses=stop_after_misses,
        max_probes=max_probes, seed_from_warehouse=seed_from_warehouse,
        watchlist=watchlist, snapshot_root=snapshot_root,
    )

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

    watched_changes: list[WatchedCaseChange] | None = None
    if args.watchlist is not None:
        watchlist = parse_watchlist(args.watchlist)
        logging.info("watchlist: %d cases to check", len(watchlist))
        watched_changes = []
        for w_classe, w_numero in watchlist:
            old = load_snapshot(w_classe, w_numero, root=args.snapshot_root)
            try:
                item = scrape_processo_http(
                    w_classe, w_numero,
                    session=session, config=config,
                    fetch_pdfs=True, fetch_dje=True,
                )
            except Exception as e:
                logging.exception("watched %s %d: scrape failed: %s", w_classe, w_numero, e)
                continue
            change = diff_watched(old, item)
            save_snapshot(w_classe, w_numero, item, root=args.snapshot_root)
            watched_changes.append(
                WatchedCaseChange(classe=w_classe, numero=w_numero, item=item, change=change)
            )
        n_actionable = sum(1 for wc in watched_changes if wc.change.has_changes)
        logging.info("watched: %d of %d changed", n_actionable, len(watched_changes))

    duration_s = round(time.time() - t0, 1)
    today = datetime.now(timezone.utc).date().isoformat()
    stats: dict = {
        "n_probed": len(new) + args.stop_after_misses,
        "duration_s": duration_s,
    }
    if watched_changes is not None:
        stats["watched_total"] = len(watched_changes)

    md = render_daily_markdown(
        cases,
        date=today,
        classe=args.classe,
        stats=stats,
        watched_changes=watched_changes,
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
    parser.add_argument("--watchlist", type=Path, default=None,
                        help="Text file with one 'CLASSE NUMERO' per line; re-scrape and diff.")
    parser.add_argument("--snapshot-root", type=Path,
                        default=Path("state/watchlist"),
                        help="Where per-case watch snapshots are read/written.")
    args = parser.parse_args(argv)
    return run_daily_report(**vars(args))


if __name__ == "__main__":
    sys.exit(main())
