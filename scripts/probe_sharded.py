"""Unified progress probe across N sweep shards.

A sharded sweep writes one state file per shard. This script unions
them into a single rich-rendered view so you don't have to eyeball
each probe and mentally sum.

Two sharded sweep shapes are supported, auto-detected per shard dir:

- **varrer** — `<shard>/sweep.state.json`, keyed by `<CLASSE>_<pid>`,
  one entry per case. Done/target are case-counts. Regimes come from
  the CliffDetector field on each entry.
- **baixar** — `<shard>/pdfs.state.json`, keyed by URL, one entry per
  PDF download. Done = entries; target = `targets: N PDFs` line from
  the shard's `driver.log` (parsed once at first probe). No regime
  ladder (CliffDetector is varrer-side only); the regimes column shows
  status counts (ok / fail / cached) instead.

Usage:

    uv run python scripts/probe_sharded.py --out-root runs/active/<dir>

    # Auto-refresh every 30s (Ctrl-C to stop):
    uv run python scripts/probe_sharded.py --out-root runs/active/<dir> --watch 30

Also exposed via the CLI as ``judex probe --out-root <dir> [--watch N]``.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Literal, Optional

from rich.console import Console
from rich.table import Table
from rich.text import Text


SweepMode = Literal["varrer", "baixar"]


@dataclass
class ShardStat:
    """Per-shard snapshot — what probe() computes, what render() displays."""
    name: str
    records: int
    target: Optional[int]
    mode: SweepMode = "varrer"
    statuses: Counter = field(default_factory=Counter)
    regimes: Counter = field(default_factory=Counter)
    min_processo: Optional[int] = None
    earliest_ts: Optional[datetime] = None
    latest_ts: Optional[datetime] = None
    mtime: float = 0.0


# Regime taxonomy from docs/rate-limits.md § Wall taxonomy. Matches
# the six-regime ladder emitted by `judex.sweeps.shared.CliffDetector`:
#  - severity drives ordering in the display (worst first — so the
#    eye lands on cliff-adjacent regimes without scanning).
#  - label is a short form that fits a narrow column.
#  - style is the rich color.
REGIME_META = {
    # regime name:            (severity, short_label, style)
    "collapse":               (5, "cliff", "red bold"),
    "approaching_collapse":   (4, "warn",  "red"),
    "l2_engaged":             (3, "l2",    "yellow"),
    "healthy":                (2, "ok",    "cyan"),
    "under_utilising":        (1, "good",  "green"),
    "warming":                (0, "warm",  "dim"),
}

# baixar-pecas has no regime ladder; the rightmost column shows
# download status counts instead. Same (severity, label, style) shape
# as REGIME_META so _fmt_meta can render either.
STATUS_META = {
    "fail":   (3, "fail",   "red"),
    "error":  (3, "err",    "red"),
    "ok":     (1, "ok",     "green"),
    "cached": (0, "cached", "dim"),
}


def _count_csv_rows(path: Path) -> Optional[int]:
    try:
        with path.open() as f:
            return sum(1 for _ in f) - 1  # minus header
    except OSError:
        return None


def _find_target(out_root: Path, shard_name: str) -> Optional[int]:
    """Map shard-a/b/c… → <out-root>/shards/*.shard.0/1/2.csv row count."""
    letter = shard_name.rsplit("-", 1)[-1]
    if not (letter.isalpha() and len(letter) == 1):
        return None
    idx = ord(letter) - ord("a")
    shards_dir = out_root / "shards"
    if not shards_dir.is_dir():
        return None
    candidates = list(shards_dir.glob(f"*.shard.{idx}.csv"))
    return _count_csv_rows(candidates[0]) if candidates else None


_BAIXAR_TARGETS_RE = re.compile(r"^targets:\s*(\d+)\s*PDFs", re.MULTILINE)


def _detect_mode_and_state(shard_dir: Path) -> tuple[SweepMode, Optional[Path]]:
    """Decide which sharded sweep this is by looking for known state files.

    Returns ``(mode, state_path_or_None)``. State path is None when the
    shard has launched but hasn't written its first record yet.
    """
    pdfs = shard_dir / "pdfs.state.json"
    if pdfs.exists():
        return "baixar", pdfs
    sweep = shard_dir / "sweep.state.json"
    if sweep.exists():
        return "varrer", sweep
    # Indeterminate (pre-first-write). Default to varrer-shape so the
    # display still renders a 0/target row instead of disappearing.
    return "varrer", None


def _parse_baixar_target(shard_dir: Path) -> Optional[int]:
    """Extract `targets: N PDFs` from the shard's driver.log.

    The line is written once at startup, before any HTTP, so it's
    available even if no records have landed yet. Returns None if the
    log doesn't exist or the line hasn't been written.
    """
    log = shard_dir / "driver.log"
    if not log.exists():
        return None
    try:
        # The line is in the first dozen-or-so lines. Read a bounded
        # prefix to avoid scanning huge logs late in a run.
        head = log.open().read(4096)
    except OSError:
        return None
    m = _BAIXAR_TARGETS_RE.search(head)
    return int(m.group(1)) if m else None


def probe_shard(shard_dir: Path, out_root: Path) -> ShardStat:
    """Read one shard's state file and return a structured snapshot.

    Dispatches on which state file exists:
    - ``pdfs.state.json`` → baixar mode, URL-keyed, target from
      driver.log's `targets: N PDFs` line.
    - ``sweep.state.json`` → varrer mode, case-keyed, target from the
      partitioned shard CSV row count.
    """
    mode, sf = _detect_mode_and_state(shard_dir)
    if mode == "baixar":
        target = _parse_baixar_target(shard_dir)
    else:
        target = _find_target(out_root, shard_dir.name)

    if sf is None:
        return ShardStat(
            name=shard_dir.name, records=0, target=target, mode=mode,
        )

    mtime = sf.stat().st_mtime
    data = json.loads(sf.read_text())
    statuses: Counter = Counter()
    regimes: Counter = Counter()
    min_pid: Optional[int] = None
    earliest: Optional[datetime] = None
    latest: Optional[datetime] = None

    for v in data.values():
        if not isinstance(v, dict):
            continue
        s = v.get("status")
        if s:
            statuses[s] += 1
        r = v.get("regime")
        if r:
            regimes[r] += 1
        # Varrer entries use `processo`; baixar entries use `processo_id`.
        p = v.get("processo")
        if not isinstance(p, int):
            p = v.get("processo_id")
        if isinstance(p, int):
            min_pid = p if min_pid is None else min(min_pid, p)
        ts = v.get("ts")
        if ts:
            dt = datetime.fromisoformat(ts)
            earliest = dt if earliest is None else min(earliest, dt)
            latest = dt if latest is None else max(latest, dt)

    return ShardStat(
        name=shard_dir.name, records=len(data), target=target, mode=mode,
        statuses=statuses, regimes=regimes,
        min_processo=min_pid, earliest_ts=earliest, latest_ts=latest,
        mtime=mtime,
    )


def probe(out_root: Path) -> list[ShardStat]:
    """Probe every shard under out_root. Returns [] if no shard-* dirs."""
    shards = sorted(d for d in out_root.glob("shard-*") if d.is_dir())
    return [probe_shard(d, out_root) for d in shards]


def _fmt_duration(seconds: float) -> str:
    if seconds <= 0:
        return "—"
    if seconds < 60:
        return f"{seconds:.0f}s"
    if seconds < 3600:
        return f"{seconds/60:.1f}m"
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    return f"{h}h{m:02d}m"


def _fmt_meta(counts: Counter, meta: dict) -> Text:
    """Render counts worst-first with short labels + color, given a
    ``meta`` table of ``{key: (severity, short_label, style)}``."""
    if not counts:
        return Text("—", style="dim")
    ordered = sorted(
        counts.items(),
        key=lambda kv: -meta.get(kv[0], (0, kv[0], "white"))[0],
    )
    out = Text()
    for i, (key, count) in enumerate(ordered):
        m = meta.get(key, (0, key, "white"))
        if i > 0:
            out.append(" ")
        out.append(f"{m[1]}={count}", style=m[2])
    return out


def _shard_summary_cell(st: ShardStat) -> Text:
    """Pick the right counter+meta for the shard's mode."""
    if st.mode == "baixar":
        return _fmt_meta(st.statuses, STATUS_META)
    return _fmt_meta(st.regimes, REGIME_META)


def _rec_per_second(st: ShardStat) -> float:
    if st.records < 2 or st.earliest_ts is None or st.latest_ts is None:
        return 0.0
    span = (st.latest_ts - st.earliest_ts).total_seconds()
    return st.records / span if span > 0 else 0.0


def render(stats: list[ShardStat], out_root: Path) -> Table:
    """Build the rich Table. Pure function of stats + out-root label."""
    table = Table(
        title=f"Sweep probe · {out_root}",
        title_justify="left",
        title_style="bold",
        row_styles=["", "dim"],
    )
    table.add_column("shard", style="cyan", no_wrap=True)
    table.add_column("done / target", justify="right")
    table.add_column("%", justify="right")
    table.add_column("rec/s", justify="right")
    table.add_column("min pid", justify="right")
    table.add_column("regimes")  # may wrap on narrow terminals
    table.add_column("age", justify="right")

    now = time.time()
    grand_records = 0
    grand_target = 0
    all_statuses: Counter = Counter()
    all_regimes: Counter = Counter()
    cluster_earliest: Optional[datetime] = None
    cluster_latest: Optional[datetime] = None

    for st in stats:
        grand_records += st.records
        if st.target is not None:
            grand_target += st.target
        all_statuses.update(st.statuses)
        all_regimes.update(st.regimes)
        if st.earliest_ts:
            cluster_earliest = st.earliest_ts if cluster_earliest is None else min(cluster_earliest, st.earliest_ts)
        if st.latest_ts:
            cluster_latest = st.latest_ts if cluster_latest is None else max(cluster_latest, st.latest_ts)

        target_cell = f"{st.records} / {st.target}" if st.target else f"{st.records} / ?"
        pct_cell = f"{st.records/st.target*100:5.1f}%" if st.target else "—"
        rec_s = _rec_per_second(st)
        rec_s_cell = f"{rec_s:.2f}" if rec_s > 0 else "—"
        age_s = now - st.mtime if st.mtime else -1
        age_cell = (
            Text(f"{age_s:.0f}s", style="red" if age_s > 120 else "")
            if age_s >= 0 else Text("—", style="dim")
        )

        table.add_row(
            st.name,
            target_cell, pct_cell, rec_s_cell,
            str(st.min_processo) if st.min_processo else "—",
            _shard_summary_cell(st),
            age_cell,
        )

    # Cluster-mode is whichever mode the shards are in (they all share
    # one in practice; if mixed, fall back to varrer/regimes).
    cluster_mode: SweepMode = stats[0].mode if stats else "varrer"

    # Footer: cluster totals
    if cluster_earliest and cluster_latest and grand_records > 1:
        cluster_span = (cluster_latest - cluster_earliest).total_seconds()
        cluster_rps = grand_records / cluster_span if cluster_span > 0 else 0.0
        remaining = grand_target - grand_records if grand_target else 0
        eta = remaining / cluster_rps if cluster_rps > 0 and remaining > 0 else 0.0
        elapsed_cell = Text(f"elapsed {_fmt_duration(cluster_span)}", style="dim")
        eta_cell = Text(
            f"eta {_fmt_duration(eta)}",
            style="bold yellow" if eta > 0 else "dim",
        )
        rps_cell = Text(f"{cluster_rps:.2f}", style="bold")
    else:
        elapsed_cell = Text("—", style="dim")
        eta_cell = Text("—", style="dim")
        rps_cell = Text("—", style="bold")

    cluster_summary = (
        _fmt_meta(all_statuses, STATUS_META)
        if cluster_mode == "baixar"
        else _fmt_meta(all_regimes, REGIME_META)
    )

    table.add_section()
    table.add_row(
        Text("TOTAL", style="bold"),
        Text(f"{grand_records} / {grand_target}" if grand_target else f"{grand_records}", style="bold"),
        Text(f"{grand_records/grand_target*100:5.1f}%" if grand_target else "—", style="bold"),
        rps_cell,
        elapsed_cell,
        cluster_summary,
        eta_cell,
    )
    return table


def _run_once(out_root: Path, console: Console) -> int:
    stats = probe(out_root)
    if not stats:
        console.print(f"[red]no shard-* dirs under {out_root}[/red]")
        return 1
    console.print(render(stats, out_root))
    return 0


def _run_watch(out_root: Path, seconds: int, console: Console) -> int:
    try:
        while True:
            console.clear()
            stats = probe(out_root)
            if not stats:
                console.print(f"[red]no shard-* dirs under {out_root}[/red]")
                return 1
            console.print(render(stats, out_root))
            console.print(
                f"[dim]refresh every {seconds}s · "
                f"{datetime.now().strftime('%H:%M:%S')} · Ctrl-C to stop[/dim]"
            )
            time.sleep(seconds)
    except KeyboardInterrupt:
        console.print("\n[dim]stopped[/dim]")
        return 0


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-root", type=Path, required=True)
    ap.add_argument(
        "--watch", type=int, default=0,
        help="Refresh interval in seconds (0 = probe once and exit).",
    )
    args = ap.parse_args(argv)

    console = Console()
    if args.watch > 0:
        return _run_watch(args.out_root, args.watch, console)
    return _run_once(args.out_root, console)


if __name__ == "__main__":
    sys.exit(main())
