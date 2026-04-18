"""CSV-driven validation sweep for the HTTP backend.

Reads a list of (classe, processo) pairs from CSV, scrapes each via
`scrape_processo_http`, optionally compares against ground-truth fixtures
or a Selenium baseline CSV, and writes a Markdown report.

Every sweep run materialises three files under `--out`:

    <out>/sweep.log.jsonl      append-only attempt log, one JSON line per attempt
    <out>/sweep.state.json     compacted state, one entry per (classe, processo)
    <out>/sweep.errors.jsonl   current non-ok entries (derived from state)
    <out>/report.md            human-readable summary

`--resume` skips processes already recorded as ok. `--retry-from <errors>`
re-runs only the processes listed in a prior `sweep.errors.jsonl`.
SIGINT/SIGTERM stops cleanly after the in-flight process finishes.

See `docs/superpowers/specs/2026-04-16-validation-sweep-design.md`.

Run:
    PYTHONPATH=. uv run python scripts/run_sweep.py \\
        --csv tests/sweep/shape_coverage.csv \\
        --label shape_coverage \\
        --parity-dir tests/ground_truth \\
        --out runs/active/2026-04-16-A-shape-coverage
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import subprocess
import sys
import time
import urllib3
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, TextIO
from urllib.parse import urlparse

from scripts._diff import diff_item
from src.sweeps import shared as _shared
from src.config import ScraperConfig
from src.scraping.http_session import RetryableHTTPError, new_session
from src.scraping.proxy_pool import ProxyPool
from src.sweeps.process_store import AttemptRecord, SweepStore, load_retry_list
from src.scraping.scraper import NoIncidenteError, scrape_processo_http

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def _redact_proxy(url: Optional[str]) -> str:
    """Strip user:pass from a proxy URL before it lands in any log.

    Returns `scheme://host:port` (identifying which proxy rotated, useful
    for debugging) without the credentials (which are the secret). Returns
    `"direct"` for None/empty input — the sentinel for "no proxy". Fails
    safe: if parsing raises, returns a non-revealing placeholder.
    """
    if not url:
        return "direct"
    try:
        p = urlparse(url)
        if not p.hostname:
            return "<proxy>"
        port = f":{p.port}" if p.port else ""
        scheme = p.scheme or "?"
        return f"{scheme}://{p.hostname}{port}"
    except Exception:
        return "<proxy>"


# Columns in the Selenium baseline CSV that are JSON-encoded lists.
_JSON_LIST_COLS = {
    "badges",
    "assuntos",
    "numero_origem",
    "partes",
    "andamentos",
    "sessao_virtual",
    "deslocamentos",
    "peticoes",
    "recursos",
    "pautas",
}

_INT_COLS = {"incidente", "processo_id", "volumes", "folhas", "apensos", "status"}

# Fields we skip when diffing because they're known to differ by design
# (matches scripts/_diff.SKIP_FIELDS, plus `html` which the CSV lacks).
_CSV_SKIP_FIELDS = {"extraido", "html", "sessao_virtual", "status"}


# ----- CSV parsing ---------------------------------------------------------


def parse_sweep_csv(fp: TextIO) -> list[tuple[str, int, Optional[str]]]:
    """Parse the input sweep CSV.

    Accepts `classe,processo` minimal or `classe,processo,source` extended.
    Returns a list of (classe, processo, source) tuples; source is None if
    the column is absent or empty.
    """
    reader = csv.DictReader(fp)
    rows: list[tuple[str, int, Optional[str]]] = []
    for row in reader:
        classe = row["classe"].strip()
        processo = int(row["processo"])
        source = (row.get("source") or "").strip() or None
        rows.append((classe, processo, source))
    return rows


def parse_selenium_row(row: dict[str, str]) -> dict[str, Any]:
    """Convert one row of the Selenium output CSV into a dict shaped like StfItem.

    Empty scalar strings become None; JSON-encoded list columns are decoded;
    integer columns become int (or None if empty).
    """
    out: dict[str, Any] = {}
    for key, val in row.items():
        if key in _JSON_LIST_COLS:
            if val == "" or val is None:
                out[key] = None if key == "numero_origem" else []
            else:
                parsed = json.loads(val)
                out[key] = parsed if parsed else ([] if key != "numero_origem" else None)
            if key == "numero_origem" and out[key] == []:
                out[key] = None
        elif key in _INT_COLS:
            out[key] = int(val) if val not in ("", None) else None
        else:
            out[key] = val if val not in ("", None) else None
    return out


# ----- Retry instrumentation ----------------------------------------------


@dataclass
class RetryCounter:
    by_status: Counter = field(default_factory=Counter)

    def add(self, status_code: int) -> None:
        if status_code == 429:
            self.by_status["429"] += 1
        elif 500 <= status_code < 600:
            self.by_status["5xx"] += 1
        else:
            self.by_status[str(status_code)] += 1

    def snapshot(self) -> dict[str, int]:
        return dict(self.by_status)

    def reset(self) -> None:
        self.by_status.clear()


def install_retry_counter() -> RetryCounter:
    """Monkey-patch `RetryableHTTPError` to count every retriable failure."""
    counter = RetryCounter()
    orig_init = RetryableHTTPError.__init__

    def tracking_init(self: RetryableHTTPError, status_code: int, url: str = "") -> None:  # type: ignore[override]
        counter.add(status_code)
        orig_init(self, status_code, url)

    RetryableHTTPError.__init__ = tracking_init  # type: ignore[method-assign]
    return counter


# ----- Shape probe --------------------------------------------------------


_REQUIRED_SCALAR_FIELDS = ("classe", "processo_id", "incidente")

# Fields that should be either a populated list or an empty list (never None).
_LIST_FIELDS = (
    "badges",
    "assuntos",
    "partes",
    "andamentos",
    "deslocamentos",
    "peticoes",
    "recursos",
)


def shape_anomalies(item: dict[str, Any]) -> list[str]:
    msgs: list[str] = []
    for k in _REQUIRED_SCALAR_FIELDS:
        if item.get(k) in (None, ""):
            msgs.append(f"missing {k}")
    for k in _LIST_FIELDS:
        v = item.get(k)
        if not isinstance(v, list):
            msgs.append(f"{k} is {type(v).__name__}, expected list")
    sv = item.get("sessao_virtual")
    if sv is not None and not isinstance(sv, (dict, list)):
        msgs.append(f"sessao_virtual is {type(sv).__name__}, expected dict|list")
    docs = (sv or {}).get("documentos") if isinstance(sv, dict) else None
    if isinstance(docs, dict):
        for slot, val in docs.items():
            if val is not None and not isinstance(val, str):
                msgs.append(f"sessao_virtual.documentos[{slot}] non-str: {type(val).__name__}")
    return msgs


# ----- Parity sources -----------------------------------------------------


def load_gt_fixture(parity_dir: Path, classe: str, processo: int) -> Optional[dict[str, Any]]:
    # Ground truth filenames use underscore + number; some include a suffix
    # (e.g. ADI_2820_reread.json). Prefer exact match, fall back to prefix.
    exact = parity_dir / f"{classe}_{processo}.json"
    if exact.exists():
        return _load_fixture_file(exact)
    for candidate in parity_dir.glob(f"{classe}_{processo}_*.json"):
        return _load_fixture_file(candidate)
    return None


def _load_fixture_file(path: Path) -> dict[str, Any]:
    data = json.load(path.open())
    return data[0] if isinstance(data, list) else data


def load_parity_csv(path: Path) -> dict[tuple[str, int], dict[str, Any]]:
    csv.field_size_limit(sys.maxsize)
    out: dict[tuple[str, int], dict[str, Any]] = {}
    with path.open(newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if not row.get("classe") or not row.get("processo_id"):
                continue
            key = (row["classe"], int(row["processo_id"]))
            out[key] = parse_selenium_row(row)
    return out


# ----- Sweep execution ----------------------------------------------------


@dataclass
class ProcessResult:
    classe: str
    processo: int
    source: Optional[str]
    wall_s: float
    status: str  # ok | fail | error
    error: Optional[str]
    retries: dict[str, int]
    diffs: list[str]
    anomalies: list[str]
    error_type: Optional[str] = None
    http_status: Optional[int] = None
    error_url: Optional[str] = None
    body_head: Optional[str] = None

    @property
    def diff_count(self) -> int:
        return len(self.diffs)


def _write_item_json(items_dir: Path, classe: str, processo: int, item_dict: dict) -> None:
    """Atomic write of `[item]` to <items_dir>/judex-mini_<classe>_<n>-<n>.json.

    One-file-per-process so parallel replay tools can walk the dir
    unambiguously. Wrapped in a 1-element list to match the JSON
    format main.py -o json emits.
    """
    items_dir.mkdir(parents=True, exist_ok=True)
    path = items_dir / f"judex-mini_{classe}_{processo}-{processo}.json"
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps([item_dict], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    tmp.replace(path)


def run_one(
    classe: str,
    processo: int,
    source: Optional[str],
    session: Any,
    counter: RetryCounter,
    gt_dir: Optional[Path],
    parity_csv: Optional[dict[tuple[str, int], dict[str, Any]]],
    *,
    config: Optional[Any] = None,
    items_dir: Optional[Path] = None,
) -> ProcessResult:
    counter.reset()
    t0 = time.perf_counter()
    try:
        item = scrape_processo_http(
            classe, processo, use_cache=True, session=session, config=config
        )
    except NoIncidenteError as e:
        return ProcessResult(
            classe, processo, source,
            wall_s=time.perf_counter() - t0,
            status="fail",
            error=f"scrape returned None (incidente not resolved): {e.location!r}",
            retries=counter.snapshot(),
            diffs=[], anomalies=[],
            error_type="NoIncidente",
            http_status=e.http_status,
            body_head=e.location[:200] if e.location else "",
        )
    except Exception as e:
        etype, http_status, url = _shared.classify_exception(e)
        return ProcessResult(
            classe, processo, source,
            wall_s=time.perf_counter() - t0,
            status="error",
            error=f"{etype}: {e}",
            retries=counter.snapshot(),
            diffs=[], anomalies=[],
            error_type=etype,
            http_status=http_status,
            error_url=url,
        )
    wall = time.perf_counter() - t0

    item_dict = dict(item)
    anomalies = shape_anomalies(item_dict)

    if items_dir is not None:
        _write_item_json(items_dir, classe, processo, item_dict)

    diffs: list[str] = []
    if gt_dir is not None:
        gt = load_gt_fixture(gt_dir, classe, processo)
        if gt is not None:
            diffs = diff_item(item_dict, gt, allow_growth=True)
    elif parity_csv is not None:
        baseline = parity_csv.get((classe, processo))
        if baseline is not None:
            filtered = {k: v for k, v in baseline.items() if k not in _CSV_SKIP_FIELDS}
            diffs = diff_item(item_dict, filtered, allow_growth=True)

    return ProcessResult(
        classe, processo, source,
        wall_s=wall, status="ok", error=None,
        retries=counter.snapshot(),
        diffs=diffs, anomalies=anomalies,
    )


# ----- Reporting ----------------------------------------------------------


def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], text=True
        ).strip()
    except Exception:
        return "unknown"


def _pct_cell(key: str, results: list[ProcessResult]) -> int:
    return sum(r.retries.get(key, 0) for r in results)


def render_report(
    *,
    label: str,
    csv_path: Path,
    out_path: Path,
    started: datetime,
    finished: datetime,
    commit: str,
    parity_source: str,
    cold_results: list[ProcessResult],
    warm_results: Optional[list[ProcessResult]],
) -> None:
    def section(title: str, results: list[ProcessResult]) -> list[str]:
        lines = [f"## {title}", ""]
        header = "| classe | processo | wall_s | 429 | 5xx | diffs | anomalies | status |"
        sep = "|--------|----------|-------:|----:|----:|------:|-----------|--------|"
        lines.append(header)
        lines.append(sep)
        for r in results:
            retries_429 = r.retries.get("429", 0)
            retries_5xx = r.retries.get("5xx", 0)
            anomalies_str = "; ".join(r.anomalies) if r.anomalies else "—"
            status = r.status if r.status != "error" else f"error: {r.error}"
            lines.append(
                f"| {r.classe} | {r.processo} | {r.wall_s:.2f} | "
                f"{retries_429} | {retries_5xx} | {r.diff_count} | "
                f"{anomalies_str} | {status} |"
            )
        wall = [r.wall_s for r in results if r.status == "ok"]
        p50, p90, pmax = _shared.percentiles(wall)
        total_429 = _pct_cell("429", results)
        total_5xx = _pct_cell("5xx", results)
        ok = sum(1 for r in results if r.status == "ok")
        fail = sum(1 for r in results if r.status != "ok")
        diff_total = sum(r.diff_count for r in results)
        anomaly_total = sum(len(r.anomalies) for r in results)
        lines += [
            "",
            f"- completed: **{ok} ok / {fail} fail** of {len(results)}",
            f"- wall p50 / p90 / max: **{p50:.2f}s / {p90:.2f}s / {pmax:.2f}s**",
            f"- retries: **429×{total_429}**, **5xx×{total_5xx}**",
            f"- parity diffs (total across {len(results)} processes): **{diff_total}**",
            f"- shape anomalies (total): **{anomaly_total}**",
            "",
        ]
        return lines

    def per_process_diffs(results: list[ProcessResult]) -> list[str]:
        lines = ["## Per-process diffs", ""]
        any_shown = False
        for r in results:
            if r.diffs or r.anomalies:
                any_shown = True
                lines.append(f"### {r.classe} {r.processo}" + (f" ({r.source})" if r.source else ""))
                lines.append("")
                if r.anomalies:
                    lines.append("Shape anomalies:")
                    for a in r.anomalies:
                        lines.append(f"- {a}")
                    lines.append("")
                if r.diffs:
                    lines.append("Diffs vs parity source:")
                    lines.append("```")
                    for d in r.diffs:
                        lines.append(d.rstrip())
                    lines.append("```")
                    lines.append("")
        if not any_shown:
            lines.append("_No diffs or anomalies on any process._")
            lines.append("")
        return lines

    def recurring(results: list[ProcessResult]) -> list[str]:
        key_counts: Counter = Counter()
        for r in results:
            for d in r.diffs:
                head = d.strip().split(":", 1)[0]
                key_counts[head] += 1
        lines = ["## Recurring divergences", ""]
        recur = [(k, n) for k, n in key_counts.items() if n >= 2]
        if not recur:
            lines.append("_No field diffs in ≥2 processes._")
            lines.append("")
            return lines
        lines.append("| field | occurrences |")
        lines.append("|-------|-------------:|")
        for k, n in sorted(recur, key=lambda x: (-x[1], x[0])):
            lines.append(f"| {k} | {n} |")
        lines.append("")
        return lines

    def errors_breakdown(results: list[ProcessResult]) -> list[str]:
        buckets: Counter = Counter()
        endpoints: Counter = Counter()
        for r in results:
            if r.status == "ok":
                continue
            etype = r.error_type or "unknown"
            status = r.http_status if r.http_status is not None else "-"
            buckets[(etype, status)] += 1
            if r.error_url:
                # strip query string + base URL so we bucket by endpoint path only
                ep = r.error_url.split("?", 1)[0].rsplit("/", 1)[-1]
                endpoints[ep] += 1

        lines = ["## Errors breakdown", ""]
        if not buckets:
            lines.append("_No errors or failures._")
            lines.append("")
            return lines
        lines.append("| error_type | http_status | count |")
        lines.append("|------------|------------:|------:|")
        for (etype, status), n in sorted(buckets.items(), key=lambda x: (-x[1], x[0])):
            lines.append(f"| {etype} | {status} | {n} |")
        lines.append("")
        if endpoints:
            lines.append("| endpoint | count |")
            lines.append("|----------|------:|")
            for ep, n in sorted(endpoints.items(), key=lambda x: (-x[1], x[0])):
                lines.append(f"| `{ep}` | {n} |")
            lines.append("")
        return lines

    out_lines: list[str] = []
    out_lines.append(f"# Validation sweep — {label}")
    out_lines.append("")
    out_lines.append(
        f"- commit: `{commit}` · csv: `{csv_path}` · parity: {parity_source}"
    )
    out_lines.append(f"- started: {started.isoformat(timespec='seconds')}")
    out_lines.append(f"- finished: {finished.isoformat(timespec='seconds')}")
    out_lines.append(f"- elapsed: {(finished - started).total_seconds():.1f}s")
    out_lines.append("")

    out_lines += section("Cold pass", cold_results)
    if warm_results is not None:
        out_lines += section("Warm pass", warm_results)

    out_lines += errors_breakdown(cold_results)
    out_lines += per_process_diffs(cold_results)
    out_lines += recurring(cold_results)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(out_lines))


def _to_attempt_record(
    res: ProcessResult,
    attempt: int,
    ts: Optional[str] = None,
    regime: Optional[str] = None,
    filter_skip: Optional[bool] = None,
) -> AttemptRecord:
    return AttemptRecord(
        ts=ts or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        classe=res.classe,
        processo=res.processo,
        attempt=attempt,
        wall_s=round(res.wall_s, 3),
        status=res.status,
        error=res.error,
        error_type=res.error_type,
        http_status=res.http_status,
        error_url=res.error_url,
        retries=dict(res.retries),
        diff_count=res.diff_count,
        anomaly_count=len(res.anomalies),
        regime=regime,
        filter_skip=filter_skip,
        body_head=res.body_head,
    )


# ----- Main ---------------------------------------------------------------


def parse_args(argv: list[str]) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--csv", type=Path, help="Input CSV of (classe, processo) pairs")
    ap.add_argument("--label", required=True)
    ap.add_argument(
        "--out", required=True, type=Path,
        help="Output DIRECTORY. Holds sweep.log.jsonl, sweep.state.json, "
             "sweep.errors.jsonl, report.md.",
    )
    ap.add_argument("--parity-dir", type=Path, help="Dir of GT fixtures")
    ap.add_argument("--parity-csv", type=Path, help="Selenium baseline CSV")
    ap.add_argument(
        "--warm-pass", action="store_true",
        help="Second pass over the same list without wiping cache.",
    )
    ap.add_argument(
        "--wipe-cache", action="store_true",
        help="Remove data/cache/html entries for the processes in the sweep before starting.",
    )
    ap.add_argument(
        "--resume", action="store_true",
        help="Skip processes that already have a status=ok record in sweep.state.json.",
    )
    ap.add_argument(
        "--retry-from", type=Path,
        help="Path to an existing sweep.errors.jsonl; re-run only those processes. "
             "Takes precedence over --csv.",
    )
    ap.add_argument(
        "--progress-every", type=int, default=25,
        help="Print running totals every N processes (default: 25).",
    )
    ap.add_argument(
        "--no-retry-403", dest="retry_403", action="store_false", default=True,
        help="Disable the default retry-on-403 behavior. STF's WAF uses 403 "
             "(not 429) as its throttle signal; retry-403 rides out block cycles.",
    )
    ap.add_argument(
        "--circuit-window", type=int, default=50,
        help="Rolling window of recent processes the circuit breaker watches "
             "(default: 50). Pass 0 to disable the breaker.",
    )
    ap.add_argument(
        "--items-dir", type=Path, default=None,
        help="If set, write one judex-mini_<CLASSE>_<n>-<n>.json per ok "
             "process into this directory. Eliminates the post-sweep "
             "cache-hot replay step used to populate output/sample/*/.",
    )
    ap.add_argument(
        "--circuit-threshold", type=float, default=0.8,
        help="Non-ok fraction of the window that trips the breaker (default: "
             "0.8 — permissive, since retry-403 normally absorbs WAF blocks; "
             "only a pathological cascade should trip this). Sweep aborts "
             "with exit code 2 once exceeded.",
    )
    ap.add_argument(
        "--cliff-window", type=int, default=50,
        help="Rolling window the CliffDetector uses to classify the sweep's "
             "operating regime (default: 50). Regime is written to each "
             "record in sweep.log.jsonl and printed on transitions. See "
             "docs/rate-limits.md § Wall taxonomy and severity timeline.",
    )
    ap.add_argument(
        "--no-stop-on-collapse", action="store_true",
        help="Disable the CliffDetector's stop-on-collapse behavior. By "
             "default, regime=collapse triggers a clean SIGTERM-equivalent "
             "shutdown; pass this flag to keep scraping through collapse "
             "(e.g. for observational studies of the cliff itself).",
    )
    ap.add_argument(
        "--proxy-pool", type=Path, default=None,
        help="Path to a file with one proxy URL per line (# comments ok). "
             "Enables proactive IP rotation: swap sessions every "
             "--proxy-rotate-seconds, well under STF's WAF L1 window, so "
             "no IP ever trips a block. See docs/rate-limits.md § Wall "
             "taxonomy and severity timeline.",
    )
    ap.add_argument(
        "--proxy-rotate-seconds", type=float, default=270.0,
        help="Seconds to use each proxy before rotating to the next "
             "(default: 270 = 4.5 min, safely under STF's ~5-min WAF "
             "sliding window). Ignored when --proxy-pool is absent.",
    )
    ap.add_argument(
        "--proxy-cooldown-minutes", type=float, default=4.0,
        help="Minutes a just-used proxy stays out of rotation (default: "
             "4). Should be ≈ (pool_size - 1) × proxy-rotate-seconds / 60 "
             "so each proxy has cooled by the time its turn returns.",
    )
    args = ap.parse_args(argv)

    if args.retry_from is None and args.csv is None:
        ap.error("either --csv or --retry-from is required")
    return args


def _load_rows(args: argparse.Namespace) -> tuple[list[tuple[str, int, Optional[str]]], str]:
    if args.retry_from:
        retry_rows = load_retry_list(args.retry_from)
        rows = [(c, p, "retry") for c, p in retry_rows]
        return rows, f"retry-from `{args.retry_from}` ({len(rows)} rows)"
    with args.csv.open(newline="") as f:
        rows = parse_sweep_csv(f)
    return rows, f"csv `{args.csv}` ({len(rows)} rows)"


def _resolve_parity(
    args: argparse.Namespace,
) -> tuple[Optional[dict[tuple[str, int], dict[str, Any]]], str]:
    if args.parity_csv:
        parity_csv = load_parity_csv(args.parity_csv)
        return parity_csv, f"selenium-csv `{args.parity_csv}` ({len(parity_csv)} rows)"
    if args.parity_dir:
        return None, f"gt-dir `{args.parity_dir}`"
    return None, "none"


def _wipe_html_caches(rows: list[tuple[str, int, Optional[str]]]) -> None:
    for classe, processo, _ in rows:
        d = Path("data/cache/html") / f"{classe}_{processo}"
        if d.exists():
            shutil.rmtree(d)


def _print_row(i: int, n: int, res: ProcessResult) -> None:
    retries = ",".join(f"{k}×{v}" for k, v in res.retries.items()) or "0"
    print(
        f"  [{i:>4d}/{n}] {res.classe:<4s} {res.processo:<8d} "
        f"{res.wall_s:>6.2f}s  status={res.status:<5s}  "
        f"retries={retries}  diffs={res.diff_count}  anomalies={len(res.anomalies)}"
        + (f"  ERR: {res.error}" if res.error else ""),
        flush=True,
    )


def _print_row_warm(i: int, n: int, classe: str, processo: int, res: ProcessResult) -> None:
    retries = ",".join(f"{k}×{v}" for k, v in res.retries.items()) or "0"
    print(
        f"  [{i:>4d}/{n}] {classe:<4s} {processo:<8d} "
        f"{res.wall_s * 1000:>7.1f}ms  status={res.status}  retries={retries}",
        flush=True,
    )


@dataclass
class SweepOutcome:
    cold_results: list[ProcessResult]
    warm_results: Optional[list[ProcessResult]]
    totals: dict[str, int]
    tripped: bool


def _run_passes(
    args: argparse.Namespace,
    rows: list[tuple[str, int, Optional[str]]],
    parity_csv: Optional[dict[tuple[str, int], dict[str, Any]]],
    store: SweepStore,
    counter: RetryCounter,
    config: ScraperConfig,
    started: datetime,
    pool: Optional[ProxyPool] = None,
) -> SweepOutcome:
    cold_results: list[ProcessResult] = []
    totals = {"ok": 0, "fail": 0, "error": 0, "skipped": 0, "429": 0, "5xx": 0}
    breaker: Optional[_shared.CircuitBreaker] = (
        _shared.CircuitBreaker(args.circuit_window, args.circuit_threshold)
        if args.circuit_window > 0 else None
    )
    detector = _shared.CliffDetector(window=args.cliff_window)
    # Track prior regime so we only print on transitions, not every record.
    last_regime: dict[str, str] = {"value": "warming"}

    # Session holder — mutable so proxy rotation can swap sessions mid-loop
    # without reaching into closure cells. `on_item_cold` reads session via
    # session_holder["session"] which is resolved at call-time.
    pool_active = pool is not None and pool.size() > 0
    initial_proxy = pool.pick() if pool_active else None
    session_holder: dict[str, Any] = {
        "session": new_session(proxy=initial_proxy),
        "proxy": initial_proxy,
        "started_at": time.monotonic(),
        "rotations": 0,
    }

    def rotate_session(reason: str) -> None:
        old = session_holder["proxy"]
        elapsed = time.monotonic() - session_holder["started_at"]
        pool.mark_hot(old, minutes=args.proxy_cooldown_minutes)
        session_holder["session"].close()
        new_proxy = pool.pick()
        if new_proxy is None:
            wait_s = pool.time_until_next_available()
            print(
                f"  [rotate] all proxies hot — waiting {wait_s:.0f}s "
                f"for the next cool proxy",
                flush=True,
            )
            time.sleep(wait_s + 1.0)
            new_proxy = pool.pick()
        session_holder["session"] = new_session(proxy=new_proxy)
        session_holder["proxy"] = new_proxy
        session_holder["started_at"] = time.monotonic()
        session_holder["rotations"] += 1
        print(
            f"  [rotate] {_redact_proxy(old)} → {_redact_proxy(new_proxy)} "
            f"(elapsed={elapsed:.0f}s reason={reason})",
            flush=True,
        )

    def on_item_cold(i: int, n: int, row: tuple[str, int, Optional[str]]) -> str:
        classe, processo, source = row
        res = run_one(
            classe, processo, source, session_holder["session"], counter,
            args.parity_dir, parity_csv, config=config,
            items_dir=args.items_dir,
        )
        cold_results.append(res)
        is_bad = detector.observe(
            res.status,
            res.wall_s,
            http_status=res.http_status,
            retries=res.retries or None,
        )
        # filter_skip = non-ok attempt the WAF-shape filter chose to IGNORE
        # (fast NoIncidente). Ok attempts aren't candidates for filtering.
        filter_skip = (res.status != "ok") and not is_bad
        regime = detector.regime()
        store.record(
            _to_attempt_record(
                res,
                attempt=store.attempt_count(classe, processo) + 1,
                regime=regime,
                filter_skip=filter_skip,
            )
        )
        totals[res.status] = totals.get(res.status, 0) + 1
        totals["429"] += res.retries.get("429", 0)
        totals["5xx"] += res.retries.get("5xx", 0)
        _print_row(i, n, res)
        if regime != last_regime["value"]:
            print(
                f"  [regime] {last_regime['value']} → {regime}  "
                f"(see docs/rate-limits.md § Wall taxonomy)",
                flush=True,
            )
            last_regime["value"] = regime
        # Proactive rotation: swap IP before L1 fires at all. Reactive
        # fallback covers the case where a proxy arrived pre-warmed.
        # Reactive rotation has a 30 s floor to prevent panic-rotation
        # cascades (the regime stays in approaching_collapse for a full
        # window until the rolling buffer flushes; without the floor,
        # every subsequent record triggers another rotation and the
        # pool drains in ~30 seconds).
        if pool_active:
            elapsed_on_proxy = time.monotonic() - session_holder["started_at"]
            rotate_reason: Optional[str] = None
            if elapsed_on_proxy > args.proxy_rotate_seconds:
                rotate_reason = f"time>{args.proxy_rotate_seconds:.0f}s"
            elif regime == "approaching_collapse" and elapsed_on_proxy > 30.0:
                rotate_reason = "approaching_collapse"
            if rotate_reason is not None:
                rotate_session(reason=rotate_reason)
        if regime == "collapse" and not args.no_stop_on_collapse:
            print(
                f"\n!! cliff detector: regime=collapse at {i}/{n}. "
                f"Stopping cleanly — cool down ≥60 min before --resume. "
                f"See docs/rate-limits.md § Wall taxonomy and severity timeline.",
                flush=True,
            )
            _shared.request_shutdown()
        return res.status

    def on_skip_cold(_row: tuple[str, int, Optional[str]]) -> None:
        totals["skipped"] += 1

    def is_done_cold(row: tuple[str, int, Optional[str]]) -> bool:
        return args.resume and store.already_ok(row[0], row[1])

    def on_progress_cold(i: int, n: int) -> None:
        _, rate, eta_s = _shared.elapsed_rate_eta(started, i, n)
        print(
            f"  [progress] ok={totals['ok']} fail={totals['fail']} "
            f"error={totals['error']} skipped={totals['skipped']} "
            f"429×{totals['429']} 5xx×{totals['5xx']} · "
            f"{rate:.2f} proc/s · eta {eta_s/60:.1f} min",
            flush=True,
        )

    warm_results: Optional[list[ProcessResult]] = None
    if pool_active:
        print(
            f"  proxy pool: {pool.size()} proxies · "
            f"rotate={args.proxy_rotate_seconds:.0f}s · "
            f"cooldown={args.proxy_cooldown_minutes:.1f}min · "
            f"initial={_redact_proxy(initial_proxy)}",
            flush=True,
        )
    try:
        tripped = _shared.iterate_with_guards(
            rows,
            on_item=on_item_cold,
            should_resume_skip=is_done_cold,
            on_skip=on_skip_cold,
            breaker=breaker,
            error_statuses=("error",),
            trip_noun="processes",
            progress_every=args.progress_every,
            on_progress=on_progress_cold,
        )

        if args.warm_pass and not _shared.shutdown_requested():
            print("\n=== warm pass (cache warm) ===", flush=True)
            warm_results = []

            def on_item_warm(i: int, n: int, row: tuple[str, int, Optional[str]]) -> None:
                classe, processo, source = row
                res = run_one(
                    classe, processo, source, session_holder["session"], counter,
                    args.parity_dir, parity_csv, config=config,
                    items_dir=args.items_dir,
                )
                warm_results.append(res)
                store.record(
                    _to_attempt_record(
                        res, attempt=store.attempt_count(classe, processo) + 1
                    )
                )
                _print_row_warm(i, n, classe, processo, res)
                return None

            _shared.iterate_with_guards(
                rows,
                on_item=on_item_warm,
                progress_every=0,
            )
    finally:
        session_holder["session"].close()
        if pool_active and session_holder["rotations"] > 0:
            print(
                f"  proxy rotations during sweep: {session_holder['rotations']}",
                flush=True,
            )

    return SweepOutcome(
        cold_results=cold_results,
        warm_results=warm_results,
        totals=totals,
        tripped=tripped,
    )


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    rows, input_source = _load_rows(args)
    if args.wipe_cache:
        _wipe_html_caches(rows)
    parity_csv, parity_source = _resolve_parity(args)

    store = SweepStore(args.out)
    counter = install_retry_counter()
    _shared.install_signal_handlers()
    config = ScraperConfig(retry_403=args.retry_403)

    pool: Optional[ProxyPool] = None
    if args.proxy_pool is not None:
        pool = ProxyPool.from_file(args.proxy_pool)

    started = datetime.now(timezone.utc)
    print(
        f"=== sweep: {args.label} · {len(rows)} processes · "
        f"input: {input_source} · parity: {parity_source} ===",
        flush=True,
    )

    outcome = _run_passes(
        args, rows, parity_csv, store, counter, config, started, pool=pool
    )

    finished = datetime.now(timezone.utc)
    errors_path = store.write_errors_file()
    report_path = args.out / "report.md"
    render_report(
        label=args.label,
        csv_path=args.csv if args.csv else args.retry_from,  # type: ignore[arg-type]
        out_path=report_path,
        started=started,
        finished=finished,
        commit=_git_sha(),
        parity_source=parity_source,
        cold_results=outcome.cold_results,
        warm_results=outcome.warm_results,
    )

    totals = outcome.totals
    print(
        f"\nsummary: ok={totals['ok']} fail={totals['fail']} error={totals['error']} "
        f"skipped={totals['skipped']} 429×{totals['429']} 5xx×{totals['5xx']}",
        flush=True,
    )
    print(f"  state:  {store.state_path}")
    print(f"  log:    {store.log_path}")
    print(f"  errors: {errors_path}")
    print(f"  report: {report_path}")

    if outcome.tripped:
        return 2
    n_error = totals["error"] + totals["fail"]
    return 0 if n_error == 0 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
