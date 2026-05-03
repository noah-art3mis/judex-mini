"""Top-level runner for the unified pipeline.

Glues the slices together into one ``run_pipeline()`` library function
that the Typer command in ``judex/cli.py`` calls. The runner is also
the natural integration point for tests that want to exercise the
whole stack with mocked handlers.

Layout under ``--saida``:

    runs/active/<label>/
        executar.state.json     # PipelineState snapshot (atomic)
        executar.log.jsonl       # one line per task outcome (post-v1)
        report.md                # final summary written on clean exit

Returns 0 on a clean run (every target reached terminal state), 1 on
shutdown-requested mid-run, 2 on configuration error.
"""

from __future__ import annotations

import asyncio
import csv as _csv
import logging
from collections import Counter as _Counter
from pathlib import Path
from typing import Optional

import urllib3

from judex.pipeline.handlers import HandlerFn, make_handlers
from judex.pipeline.models import Counters, PoolConfig
from judex.pipeline.scheduler import (
    RunResult,
    SchedulerConfig,
    run_scheduler,
    seeds_from_targets,
)
from judex.pipeline.state import PipelineState

# Mirror legacy ``run_sweep.py``: STF serves valid certs but our tests use
# direct-IP HTTPS with verify=False in some paths. Suppress the urllib3
# "InsecureRequestWarning" flood so launcher.log stays scannable. The
# legacy `varrer-processos` / `baixar-pecas` commands do this at module
# import; the unified pipeline was missing it (the noise drowned out
# every progress line, surfaced on the first real HC 2020 launch).
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

HandlersFactory = "Callable[..., dict[str, HandlerFn]]"


log = logging.getLogger(__name__)


def read_targets_csv(path: Path) -> list[tuple[str, int]]:
    """Read a CSV of ``(classe, processo)`` rows.

    Accepts ``processo`` or ``processo_id`` for the integer column —
    same lenience the existing ``targets_from_csv`` resolvers use.
    Raises ``ValueError`` on a malformed file (clear error message
    > silent partial read).
    """
    out: list[tuple[str, int]] = []
    with path.open(newline="") as fh:
        reader = _csv.DictReader(fh)
        if reader.fieldnames is None:
            raise ValueError(f"empty CSV: {path}")
        if "classe" not in reader.fieldnames:
            raise ValueError(f"CSV missing 'classe' column: {path}")
        proc_col = next(
            (c for c in ("processo", "processo_id") if c in reader.fieldnames),
            None,
        )
        if proc_col is None:
            raise ValueError(f"CSV missing 'processo' or 'processo_id' column: {path}")

        for i, row in enumerate(reader, start=2):  # row 1 is header
            classe = (row.get("classe") or "").strip()
            raw = (row.get(proc_col) or "").strip()
            if not classe or not raw:
                continue
            try:
                processo = int(raw)
            except ValueError as exc:
                raise ValueError(f"row {i}: bad {proc_col}={raw!r}: {exc}") from exc
            out.append((classe, processo))
    return out


def targets_from_range(classe: str, inicio: int, fim: int) -> list[tuple[str, int]]:
    """Synthesise the inclusive ``[inicio..fim]`` range as ``(classe, n)`` tuples.

    Cheaper symmetric of legacy ``varrer-processos -c -i -f``: no CSV
    materialisation, no on-disk roots probe — the unified pipeline
    discovers each case at runtime via ``handle_fetch_meta``, so we
    can hand the bare range straight to the scheduler.
    """
    return [(classe.upper(), n) for n in range(inicio, fim + 1)]


def targets_from_errors_jsonl(errors_path: Path) -> list[tuple[str, int]]:
    """Read ``executar.errors.jsonl`` → unique ``(classe, processo)`` cases
    with at least one retryable failure.

    Uses :func:`judex.pipeline.log.classify_unified_error` to decide
    per row — the unified-vocabulary sibling of legacy
    ``judex.sweeps.error_triage.classify_error``. Terminal rows
    (``unallocated_pid``, ``empty``, ``no_bytes``) are dropped: they
    can't recover via re-run, so re-seeding them just burns a
    portal/sistemas slot on a known-dead target.
    """
    from judex.pipeline.log import classify_unified_error, read_errors_file

    seen: set[tuple[str, int]] = set()
    out: list[tuple[str, int]] = []
    for row in read_errors_file(errors_path):
        if classify_unified_error(row) != "transient":
            continue
        classe = row.get("classe")
        processo = row.get("processo")
        if classe is None or processo is None:
            continue
        key = (str(classe), int(processo))
        if key in seen:
            continue
        seen.add(key)
        out.append(key)
    return out


def render_report_md(
    *,
    targets: list[tuple[str, int]],
    state: PipelineState,
    result: RunResult,
    provedor: str,
    pool_concurrencies: Optional[dict[str, int]] = None,
) -> str:
    """One-page Markdown summary of the run. Written to
    ``<saida>/report.md`` on clean exit.

    ``pool_concurrencies`` lets the utilisation column divide busy
    time by concurrency, so a pool with 4-way concurrency can't
    show >100%. Defaults to 1-per-pool when not provided (back
    compat with the slice-2 callers).
    """
    pc = pool_concurrencies or {}

    # Per-pool counters
    pool_lines = []
    total_busy = 0.0
    for pool_name, c in result.counters.items():
        k = pc.get(pool_name, 1)
        denom = max(result.wall_seconds, 1e-6) * max(k, 1)
        util = c.busy_seconds / denom
        total_busy += c.busy_seconds
        pool_lines.append(
            f"| {pool_name} | {c.started} | {c.finished} | {c.failed} | "
            f"{c.busy_seconds:.1f} | {util:.0%} |"
        )

    # State-side breakdown by status + cost-relevant counts.
    # ``skipped_cached`` is a *terminal-ok* outcome (sidecar already
    # records the right provider; re-OCR was deliberately skipped) —
    # it counts toward the bytes_ok / text_ok numerator alongside "ok",
    # because the desired output exists on disk either way. Counting
    # it as a failure would mark every successful resume as F-grade.
    _terminal_ok = ("ok", "skipped_cached")
    meta_status: _Counter = _Counter()
    bytes_status: _Counter = _Counter()
    text_status: _Counter = _Counter()
    bytes_ok = 0
    text_ok = 0
    for case in targets:
        s = state.meta_status(case) or "missing"
        meta_status[s] += 1
        for url in state.known_bytes_urls(case):
            bs = state.bytes_status(case, url=url) or "missing"
            ts = state.text_status(case, url=url) or "missing"
            bytes_status[bs] += 1
            text_status[ts] += 1
            if bs in _terminal_ok:
                bytes_ok += 1
            if ts in _terminal_ok:
                text_ok += 1

    def _fmt_counter(c: _Counter) -> str:
        if not c:
            return "(none)"
        return ", ".join(f"{k}={v}" for k, v in sorted(c.items()))

    # Comparison metrics: pipelining ratio + cost
    # Legacy chain (varrer -> baixar -> extrair) runs phases serially,
    # so its wall would equal the sum of per-pool busy times. The
    # pipelining win is (1 - actual_wall / legacy_estimate).
    legacy_wall_estimate = total_busy
    if legacy_wall_estimate > 0:
        ratio = result.wall_seconds / legacy_wall_estimate
        savings_pct = (1 - ratio) * 100
    else:
        ratio = 1.0
        savings_pct = 0.0

    # OCR cost: pypdf is free; API providers carry per-PDF cost.
    # Defer to judex.utils.cost.estimate_cost via dispatch when
    # available; default to 0.0 for pypdf.
    ocr_cost_usd = 0.0
    try:
        from judex.scraping.ocr.dispatch import estimate_cost
        # Anchor at ~5 pages/peça per CLAUDE.md (HC PDFs are short).
        # Real per-PDF page count would require parsing each PDF; an
        # average is good enough for the comparison line.
        avg_pages_per_peca = 5
        ocr_cost_usd = estimate_cost(provedor, text_ok * avg_pages_per_peca) or 0.0
    except Exception:  # noqa: BLE001
        # Don't fail the report on cost-estimation hiccups; leave at 0.
        pass

    # Quality grade — A/B/C/D/F on the run's text-ok ratio. Cheap proxy
    # for "is the OCR side healthy". Denominator is text-attempted (not
    # all peças necessarily get a text task — those still in fetch_bytes
    # don't count); numerator is text-ok across all attempted URLs.
    text_attempted = sum(text_status.values())
    text_ok_ratio = text_ok / text_attempted if text_attempted else 0.0
    if text_attempted == 0:
        quality_grade = "n/a"
    elif text_ok_ratio >= 0.99:
        quality_grade = "A"
    elif text_ok_ratio >= 0.95:
        quality_grade = "B"
    elif text_ok_ratio >= 0.90:
        quality_grade = "C"
    elif text_ok_ratio >= 0.80:
        quality_grade = "D"
    else:
        quality_grade = "F"

    md = []
    md.append("# Unified pipeline run\n")
    md.append(f"- targets: {len(targets)}")
    md.append(f"- provedor: `{provedor}`")
    md.append(f"- wall: {result.wall_seconds:.1f}s")
    md.append(f"- shutdown_requested: {result.shutdown_requested}")
    md.append(
        f"- quality grade: **{quality_grade}** "
        f"(text_ok={text_ok}/{text_attempted} = {text_ok_ratio:.1%})"
    )
    md.append("")
    md.append("## Per-pool")
    md.append("")
    md.append("| pool | started | finished | failed | busy_s | utilisation* |")
    md.append("|---|---|---|---|---|---|")
    md.extend(pool_lines)
    md.append("")
    md.append("*utilisation = `busy_s / (wall_s × concurrency)` — capped at 100% by definition.")
    md.append("")
    md.append("## Per-stage status (state-side)")
    md.append("")
    md.append(f"- meta:  {_fmt_counter(meta_status)}")
    md.append(f"- bytes: {_fmt_counter(bytes_status)}")
    md.append(f"- text:  {_fmt_counter(text_status)}")
    md.append("")
    md.append("## Comparison vs. legacy chain (varrer → baixar → extrair)")
    md.append("")
    md.append("Legacy runs phases serially; its wall ≈ sum of per-pool busy time.")
    md.append("Pipelining wins by overlapping pools.")
    md.append("")
    md.append("| metric                          | this run | legacy (≈ sum-of-busy) |")
    md.append("|---|---|---|")
    md.append(f"| wall (s)                        | {result.wall_seconds:.1f} | {legacy_wall_estimate:.1f} |")
    md.append(f"| cases                           | {len(targets)} | {len(targets)} |")
    md.append(f"| peças bytes ok                  | {bytes_ok} | {bytes_ok} |")
    md.append(f"| peças text ok                   | {text_ok} | {text_ok} |")
    md.append(f"| OCR cost (USD, provedor=`{provedor}`) | ${ocr_cost_usd:.4f} | ${ocr_cost_usd:.4f} |")
    md.append(f"| pipelining ratio                | **{ratio:.2f}** (1.00 = no overlap) | n/a |")
    md.append(f"| wall savings vs sequential      | **{savings_pct:.0f}%** | n/a |")
    md.append("")
    return "\n".join(md)


def run_pipeline(
    *,
    targets: list[tuple[str, int]],
    saida: Path,
    provedor: str = "pypdf",
    portal_concurrencia: int = 1,
    sistemas_concurrencia: int = 1,
    ocr_concurrencia: int = 4,
    fetch_dje: bool = True,
    proxy_pool: Optional[Path] = None,
    forcar: bool = False,
    impte_contains: tuple[str, ...] = (),
    doc_types: tuple[str, ...] = (),
    exclude_doc_types: tuple[str, ...] = (),
    relator_contains: tuple[str, ...] = (),
    handlers_factory=None,  # type: ignore[no-untyped-def]
) -> int:
    """Run the unified pipeline against ``targets`` to completion.

    ``handlers_factory`` is an injection point for tests: pass a
    callable taking ``(state, **kwargs)`` and returning a
    ``dict[TaskKind, HandlerFn]``. Defaults to the real
    ``make_handlers`` wired against the scrape + cache + OCR stack.
    Real-call signature: ``factory(state, provedor=provedor,
    fetch_dje=fetch_dje, portal_proxies=..., sistemas_proxies=...)``;
    test factories can ignore those kwargs.

    ``proxy_pool`` is a flat file of proxy URLs (one per line; ``#``
    comments + blank lines ignored). When provided, two independent
    :class:`ProxyPool` instances are loaded from the file — one each
    for the portal and sistemas pools — so per-pool cooldowns are
    isolated. When ``None`` (default), both pools run direct-IP.
    """
    # Configure root logger so the scheduler's [progress] heartbeat,
    # the per-task lines from ``_run_one``, and the runner's own
    # info/warning logs all surface on stderr. ``force=True`` is
    # important because ``judex executar`` may be invoked from a parent
    # process that already configured logging (e.g. tests, repl) — the
    # legacy commands do the same. Format mirrors legacy: bare message
    # (timestamps and pool labels are inside the message itself).
    logging.basicConfig(
        level=logging.INFO, format="%(message)s", force=True,
    )

    saida = Path(saida)
    saida.mkdir(parents=True, exist_ok=True)

    state_path = saida / "executar.state.json"
    log_path = saida / "executar.log.jsonl"

    # If the log file is fresher than the snapshot, the snapshot is stale
    # — the process was killed between snapshot intervals. Replay the
    # log to recover the up-to-date state, then snapshot before workers
    # start. Cheap when the log is short; the only cost when both files
    # are aligned is one stat() per file.
    if log_path.exists() and (
        not state_path.exists()
        or log_path.stat().st_mtime > state_path.stat().st_mtime
    ):
        from judex.pipeline.log import recover_state_from_log
        log.info(
            "executar: log newer than snapshot; recovering state from %s",
            log_path,
        )
        state = recover_state_from_log(log_path)
        state.snapshot()
    else:
        state = PipelineState.load(state_path)

    portal_proxies = sistemas_proxies = None
    if proxy_pool is not None:
        from judex.scraping.proxy_pool import ProxyPool

        # Same file, two independent pool instances. Different origins
        # (portal.stf vs sistemas.stf), different WAF counters at the
        # remote end, so cooldown bookkeeping must not cross-contaminate.
        portal_proxies = ProxyPool.from_file(Path(proxy_pool))
        sistemas_proxies = ProxyPool.from_file(Path(proxy_pool))
        log.info(
            "proxy pool loaded: %d entries from %s (portal + sistemas, independent counters)",
            portal_proxies.size(),
            proxy_pool,
        )

    factory = handlers_factory or make_handlers
    handlers = factory(
        state,
        provedor=provedor,
        fetch_dje=fetch_dje,
        portal_proxies=portal_proxies,
        sistemas_proxies=sistemas_proxies,
        forcar=forcar,
        impte_contains=impte_contains,
        doc_types=doc_types,
        exclude_doc_types=exclude_doc_types,
        relator_contains=relator_contains,
    )

    pools = [
        PoolConfig(name="portal", concurrency=portal_concurrencia),
        PoolConfig(name="sistemas", concurrency=sistemas_concurrencia),
        PoolConfig(name="ocr", concurrency=ocr_concurrencia),
    ]
    config = SchedulerConfig(
        pools=pools, handlers=handlers, n_targets=len(targets),
        log_path=log_path,
    )

    seeds = seeds_from_targets(targets, state)
    log.info(
        "executar: %d targets · %d seeds · provedor=%s · pools=%d/%d/%d",
        len(targets), len(seeds), provedor,
        portal_concurrencia, sistemas_concurrencia, ocr_concurrencia,
    )

    if not seeds:
        log.info("nothing to do (state already complete for every target)")
        result = RunResult(
            counters={p.name: Counters() for p in pools},
            wall_seconds=0.0,
        )
    else:
        result = asyncio.run(run_scheduler(seeds, config, state))

    pool_concurrencies = {p.name: p.concurrency for p in pools}
    report = render_report_md(
        targets=targets, state=state, result=result, provedor=provedor,
        pool_concurrencies=pool_concurrencies,
    )
    (saida / "report.md").write_text(report, encoding="utf-8")

    # Derive ``executar.errors.jsonl`` from the final state. One row per
    # non-ok target across all three task kinds — feeds the
    # ``--retentar-de`` replay path next time.
    from judex.pipeline.log import derive_errors_file
    errors_path = derive_errors_file(saida, state, targets)
    log.info(
        "executar: done. wall=%.1fs · report=%s · errors=%s",
        result.wall_seconds, saida / "report.md", errors_path,
    )

    return 1 if result.shutdown_requested else 0
