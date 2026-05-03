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

    # State-side breakdown by status + cost-relevant counts
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
            if bs == "ok":
                bytes_ok += 1
            if ts == "ok":
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

    md = []
    md.append("# Unified pipeline run\n")
    md.append(f"- targets: {len(targets)}")
    md.append(f"- provedor: `{provedor}`")
    md.append(f"- wall: {result.wall_seconds:.1f}s")
    md.append(f"- shutdown_requested: {result.shutdown_requested}")
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
    )

    pools = [
        PoolConfig(name="portal", concurrency=portal_concurrencia),
        PoolConfig(name="sistemas", concurrency=sistemas_concurrencia),
        PoolConfig(name="ocr", concurrency=ocr_concurrencia),
    ]
    config = SchedulerConfig(
        pools=pools, handlers=handlers, n_targets=len(targets),
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
    log.info("executar: done. wall=%.1fs · report=%s", result.wall_seconds, saida / "report.md")

    return 1 if result.shutdown_requested else 0
