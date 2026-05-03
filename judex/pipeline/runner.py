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

from judex.pipeline.handlers import HandlerFn, make_handlers
from judex.pipeline.models import Counters, PoolConfig
from judex.pipeline.scheduler import (
    RunResult,
    SchedulerConfig,
    run_scheduler,
    seeds_from_targets,
)
from judex.pipeline.state import PipelineState

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
) -> str:
    """One-page Markdown summary of the run. Written to
    ``<saida>/report.md`` on clean exit.
    """
    # Per-pool counters
    pool_lines = []
    for pool_name, c in result.counters.items():
        util = c.busy_seconds / max(result.wall_seconds, 1e-6)
        pool_lines.append(
            f"| {pool_name} | {c.started} | {c.finished} | {c.failed} | "
            f"{c.busy_seconds:.1f} | {util:.0%} |"
        )

    # State-side breakdown by status
    meta_status: _Counter = _Counter()
    bytes_status: _Counter = _Counter()
    text_status: _Counter = _Counter()
    for case in targets:
        s = state.meta_status(case) or "missing"
        meta_status[s] += 1
        for url in state.known_bytes_urls(case):
            bytes_status[state.bytes_status(case, url=url) or "missing"] += 1
            text_status[state.text_status(case, url=url) or "missing"] += 1

    def _fmt_counter(c: _Counter) -> str:
        if not c:
            return "(none)"
        return ", ".join(f"{k}={v}" for k, v in sorted(c.items()))

    md = []
    md.append("# Unified pipeline run\n")
    md.append(f"- targets: {len(targets)}")
    md.append(f"- provedor: `{provedor}`")
    md.append(f"- wall: {result.wall_seconds:.1f}s")
    md.append(f"- shutdown_requested: {result.shutdown_requested}")
    md.append("")
    md.append("## Per-pool")
    md.append("")
    md.append("| pool | started | finished | failed | busy_s | utilisation |")
    md.append("|---|---|---|---|---|---|")
    md.extend(pool_lines)
    md.append("")
    md.append("## Per-stage status (state-side)")
    md.append("")
    md.append(f"- meta:  {_fmt_counter(meta_status)}")
    md.append(f"- bytes: {_fmt_counter(bytes_status)}")
    md.append(f"- text:  {_fmt_counter(text_status)}")
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
    handlers_factory=None,  # type: ignore[no-untyped-def]
) -> int:
    """Run the unified pipeline against ``targets`` to completion.

    ``handlers_factory`` is an injection point for tests: pass a
    callable taking ``(state, **kwargs)`` and returning a
    ``dict[TaskKind, HandlerFn]``. Defaults to the real
    ``make_handlers`` wired against the scrape + cache + OCR stack.
    Real-call signature: ``factory(state, provedor=provedor,
    fetch_dje=fetch_dje)``; test factories can ignore those kwargs.
    """
    saida = Path(saida)
    saida.mkdir(parents=True, exist_ok=True)

    state_path = saida / "executar.state.json"
    state = PipelineState.load(state_path)

    factory = handlers_factory or make_handlers
    handlers = factory(state, provedor=provedor, fetch_dje=fetch_dje)

    pools = [
        PoolConfig(name="portal", concurrency=portal_concurrencia),
        PoolConfig(name="sistemas", concurrency=sistemas_concurrencia),
        PoolConfig(name="ocr", concurrency=ocr_concurrencia),
    ]
    config = SchedulerConfig(pools=pools, handlers=handlers)

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

    report = render_report_md(targets=targets, state=state, result=result, provedor=provedor)
    (saida / "report.md").write_text(report, encoding="utf-8")
    log.info("executar: done. wall=%.1fs · report=%s", result.wall_seconds, saida / "report.md")

    return 1 if result.shutdown_requested else 0
