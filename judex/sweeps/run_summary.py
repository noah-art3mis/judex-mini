"""Cluster-wide rollup of an ``executar`` run — finished or in-flight.

Powers two operator-facing surfaces:

- ``judex relatar <run_dir>`` (post-hoc summary command)
- ``judex acompanhar <run_dir>`` (the ``--until-done`` end-detection +
  rendered-summary path that fires when every shard's driver.log
  shows ``executar: done``)

Both call :func:`summarize_run` to build the same :class:`RunSummary`
dataclass; the only difference is when they call it (post-hoc vs at
the end-of-tail moment).

Inputs (per run dir):

- ``shard-*/driver.log`` (or top-level ``driver.log`` for mono runs) —
  contains the canonical ``executar: done. wall=… · report=… ·
  errors=…`` line emitted by ``judex/pipeline/runner.py:417``. Anchor
  for end-detection and wall extraction. A re-resumed shard appends a
  *second* done line with ``wall=0.0`` (the no-op resume); we pick
  the max wall across all done lines in a shard, which is the wall of
  the original productive run.
- ``shard-*/executar.state.json`` — per-stage status mix, case count.
  Same atomic-snapshot file the live aggregator polls. We re-use the
  same shape but compute cluster-wide totals not status-line totals.
- ``shard-*/executar.errors.jsonl`` — one row per non-ok task derived
  at clean exit by ``judex/pipeline/log.py:derive_errors_file``. Schema
  ``{kind, classe, processo, status, url, doc_type, extractor, error}``.
  Source of truth for the residuals classification.
- ``shard-*/report.md`` — per-shard report; we parse the OCR cost line.

The recovery-mapping (``STATUS_TO_RECOVERY``) maps every observed
``(kind, status)`` to a :class:`RecoveryAction` that knows whether the
class is terminal (no retry possible) or retryable, and what command
the operator should run for retryables. Adding a new failure class is
one new entry there + one row in
``tests/unit/test_run_summary.py::test_recovery_mapping_covers_every_observed_status``.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional


class RunState(str, Enum):
    DONE = "DONE"
    RUNNING = "RUNNING"
    EMPTY = "EMPTY"


@dataclass(frozen=True)
class RecoveryAction:
    """Describes how to recover from one (kind, status) failure class.

    ``template`` is a ``str.format``-able command with optional keys
    ``{errors_path}`` and ``{shard_dir}``. Static templates (no keys)
    are returned verbatim — see the local-tesseract escape hatch.
    """

    label: str
    is_terminal: bool
    template: Optional[str]


# Canonical retry path: re-run executar with --retentar-de pointing at the
# per-shard errors file. Resets the retry budget for those targets per
# ADR-0005 and re-fetches/re-extracts in the same sweep dir, so corpus-
# shared cache wins compound.
_RETENTAR_TEMPLATE = (
    "uv run judex executar --retentar-de {errors_path} "
    "--saida {shard_dir} --provedor auto --nao-perguntar"
)

# Local-OCR escape hatch for >1 MB compressed PDFs. Fly's tesseract server
# refuses these (OutlierPdfError, fly/server.py:_MAX_PDF_BYTES); local
# tesseract has no size cap. Operator fills in <subset> with the URL list.
_FORCAR_LOCAL_TEMPLATE = (
    "uv run judex extrair-pecas --csv <subset> "
    "--provedor tesseract --forcar"
)


STATUS_TO_RECOVERY: dict[tuple[str, str], RecoveryAction] = {
    ("fetch_meta", "unallocated_pid"): RecoveryAction(
        label="STF gap (terminal)", is_terminal=True, template=None,
    ),
    ("fetch_meta", "http_error"): RecoveryAction(
        label="transient HTTP", is_terminal=False, template=_RETENTAR_TEMPLATE,
    ),
    ("fetch_bytes", "empty"): RecoveryAction(
        label="0-byte STF response (terminal)", is_terminal=True, template=None,
    ),
    ("fetch_bytes", "http_error"): RecoveryAction(
        label="transient HTTP", is_terminal=False, template=_RETENTAR_TEMPLATE,
    ),
    ("extract_text", "provider_error"): RecoveryAction(
        label="OCR transient", is_terminal=False, template=_RETENTAR_TEMPLATE,
    ),
    ("extract_text", "outlier_skipped"): RecoveryAction(
        label=">1 MB Fly outlier", is_terminal=False,
        template=_FORCAR_LOCAL_TEMPLATE,
    ),
}


@dataclass
class StatusBreakdown:
    """Per-stage status mix across a run."""

    processos: dict[str, int] = field(default_factory=dict)
    pecas: dict[str, int] = field(default_factory=dict)
    text: dict[str, int] = field(default_factory=dict)


@dataclass
class Residual:
    """One (kind, status) class of failure with its count and recovery."""

    kind: str
    status: str
    count: int
    label: str
    is_terminal: bool
    suggested_command: Optional[str]


@dataclass
class RunSummary:
    """Cluster-wide rollup of a run."""

    run_dir: Path
    layout: str
    n_shards: int
    n_done_shards: int
    state: RunState
    longest_wall_s: Optional[float]
    total_wall_s: Optional[float]
    breakdown: StatusBreakdown
    cases_total: int
    ocr_cost_usd: float
    residuals: list[Residual]


# --- layout + log helpers -------------------------------------------------


_LOG_NAMES = ("driver.log", "launcher.log", "executar.log", "executar.log.jsonl")


def _list_shard_dirs(run_dir: Path) -> list[Path]:
    return sorted(d for d in run_dir.glob("shard-*") if d.is_dir())


def _detect_layout(run_dir: Path) -> tuple[str, list[Path]]:
    """Return ``("sharded", [shard_dirs])`` or ``("mono", [run_dir])``
    or ``("empty", [])``. Sharded wins over mono if shard-* dirs exist."""
    sharded = _list_shard_dirs(run_dir)
    if sharded:
        return ("sharded", sharded)
    for name in _LOG_NAMES:
        if (run_dir / name).is_file():
            return ("mono", [run_dir])
    return ("empty", [])


def _shard_log(shard_dir: Path) -> Optional[Path]:
    for name in _LOG_NAMES:
        p = shard_dir / name
        if p.is_file():
            return p
    return None


def _has_done_line(log_path: Optional[Path]) -> bool:
    if log_path is None or not log_path.is_file():
        return False
    try:
        for line in log_path.read_text(errors="ignore").splitlines():
            if line.startswith("executar: done"):
                return True
    except OSError:
        return False
    return False


def _is_dir_done(d: Path) -> bool:
    """A run directory marks itself done via either:

    1. A ``report.md`` (the unified pipeline writes this on successful
       ``run_pipeline`` return — matches monolithic ``judex executar``
       and ``judex atualizar`` runs whose JSONL log carries no
       ``"executar: done"`` text marker), or
    2. A ``"executar: done"`` line in any driver/launcher log file
       (legacy chain + sharded children).

    Either signal is sufficient. The order matters only for cost —
    a stat is cheaper than a full log scan.
    """
    if (d / "report.md").is_file():
        return True
    return _has_done_line(_shard_log(d))


_WALL_RE = re.compile(r"executar: done\. wall=([\d.]+)s")


def _max_wall(log_path: Optional[Path]) -> Optional[float]:
    """Max ``wall=`` across every done line in one log.

    A re-resumed shard logs a second done line with ``wall=0.0``;
    picking the max ignores the no-op resume."""
    if log_path is None or not log_path.is_file():
        return None
    walls: list[float] = []
    try:
        for line in log_path.read_text(errors="ignore").splitlines():
            m = _WALL_RE.search(line)
            if m:
                walls.append(float(m.group(1)))
    except OSError:
        return None
    return max(walls) if walls else None


def _fmt_wall(seconds: float) -> str:
    """Render seconds as ``Xh Ym`` / ``Xm Ys`` / ``Xs`` depending on
    magnitude. Operators read wall-clock in human units (a 13983 s
    shard is "3h 53m" before it's "13983 seconds")."""
    s = int(round(seconds))
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m {s % 60}s"
    h, rem = divmod(s, 3600)
    m = rem // 60
    return f"{h}h {m}m"


_COST_RE = re.compile(r"^\|\s*OCR cost.*?\|\s*\$([\d.]+)")


def _read_ocr_cost(report_path: Path) -> float:
    if not report_path.is_file():
        return 0.0
    try:
        for line in report_path.read_text(errors="ignore").splitlines():
            m = _COST_RE.match(line)
            if m:
                return float(m.group(1))
    except OSError:
        pass
    return 0.0


# --- aggregation ----------------------------------------------------------


def _aggregate_state_breakdown(
    state_files: list[Path],
) -> tuple[StatusBreakdown, int]:
    breakdown = StatusBreakdown()
    cases_total = 0
    for sf in state_files:
        if not sf.is_file():
            continue
        try:
            d = json.loads(sf.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        cases = d.get("cases") or {}
        cases_total += len(cases)
        for case in cases.values():
            if not isinstance(case, dict):
                continue
            meta = case.get("fetch_meta") or {}
            s = meta.get("status")
            if s:
                breakdown.processos[s] = breakdown.processos.get(s, 0) + 1
            for entry in (case.get("fetch_bytes") or {}).values():
                s = (entry or {}).get("status")
                if s:
                    breakdown.pecas[s] = breakdown.pecas.get(s, 0) + 1
            for entry in (case.get("extract_text") or {}).values():
                s = (entry or {}).get("status")
                if s:
                    breakdown.text[s] = breakdown.text.get(s, 0) + 1
    return breakdown, cases_total


def _render_command(action: RecoveryAction, dirs: list[Path]) -> Optional[str]:
    """Build the operator-facing command for one recovery action.

    Single-shard runs: emit one bare command pointing at that shard's
    errors file. Multi-shard runs: emit a ``for d in <run>/shard-*``
    loop so the operator can paste-and-run without dispatching to N
    shells. Templates without ``{errors_path}`` (e.g. local-tesseract
    escape hatch) are returned verbatim."""
    if action.template is None:
        return None
    if "{errors_path}" not in action.template:
        return action.template
    if len(dirs) == 1:
        sd = dirs[0]
        return action.template.format(
            errors_path=sd / "executar.errors.jsonl",
            shard_dir=sd,
        )
    parent = dirs[0].parent
    cmd = action.template.format(
        errors_path='"$d/executar.errors.jsonl"',
        shard_dir='"$d"',
    )
    return (
        f"for d in {parent}/shard-*; do\n"
        f"    test -s \"$d/executar.errors.jsonl\" || continue\n"
        f"    nohup {cmd} > \"$d/retry.log\" 2>&1 &\n"
        f"done"
    )


def _collect_residuals(dirs: list[Path]) -> list[Residual]:
    """Aggregate ``executar.errors.jsonl`` rows by ``(kind, status)``."""
    counts: dict[tuple[str, str], int] = {}
    for sd in dirs:
        ej = sd / "executar.errors.jsonl"
        if not ej.is_file():
            continue
        try:
            for line in ej.read_text(errors="ignore").splitlines():
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                k, s = row.get("kind"), row.get("status")
                if k and s:
                    counts[(k, s)] = counts.get((k, s), 0) + 1
        except OSError:
            continue

    residuals: list[Residual] = []
    for (kind, status), n in sorted(counts.items()):
        action = STATUS_TO_RECOVERY.get(
            (kind, status),
            RecoveryAction(label="(unmapped)", is_terminal=False, template=None),
        )
        cmd = _render_command(action, dirs) if not action.is_terminal else None
        residuals.append(Residual(
            kind=kind, status=status, count=n,
            label=action.label,
            is_terminal=action.is_terminal,
            suggested_command=cmd,
        ))
    return residuals


# --- public API -----------------------------------------------------------


def is_run_done(run_dir: Path) -> tuple[bool, int, int]:
    """End-detection: does every shard have at least one ``executar: done`` line?

    Returns ``(all_done, n_done, n_shards)``. Used by
    ``acompanhar --until-done`` to break out of the multitail loop and
    by ``relatar`` to decide whether to render the residual block."""
    layout, dirs = _detect_layout(run_dir)
    if layout == "empty":
        return (False, 0, 0)
    n_done = sum(1 for d in dirs if _is_dir_done(d))
    return (n_done == len(dirs), n_done, len(dirs))


def summarize_run(run_dir: Path) -> RunSummary:
    """Walk ``run_dir`` and return a cluster-wide :class:`RunSummary`."""
    layout, dirs = _detect_layout(run_dir)
    if layout == "empty":
        return RunSummary(
            run_dir=run_dir, layout="empty", n_shards=0, n_done_shards=0,
            state=RunState.EMPTY, longest_wall_s=None, total_wall_s=None,
            breakdown=StatusBreakdown(), cases_total=0,
            ocr_cost_usd=0.0, residuals=[],
        )

    n_done = sum(1 for d in dirs if _is_dir_done(d))
    state = RunState.DONE if n_done == len(dirs) else RunState.RUNNING

    breakdown, cases_total = _aggregate_state_breakdown(
        [d / "executar.state.json" for d in dirs]
    )

    walls = [w for w in (_max_wall(_shard_log(d)) for d in dirs) if w is not None]
    longest = max(walls) if walls else None
    total = sum(walls) if walls else None

    cost_total = sum(_read_ocr_cost(d / "report.md") for d in dirs)

    # Residuals only meaningful at DONE; while RUNNING the scheduler
    # can still convert non-ok → ok and the suggested commands would
    # mis-target work the run is actively doing.
    residuals = _collect_residuals(dirs) if state == RunState.DONE else []

    return RunSummary(
        run_dir=run_dir, layout=layout, n_shards=len(dirs), n_done_shards=n_done,
        state=state, longest_wall_s=longest, total_wall_s=total,
        breakdown=breakdown, cases_total=cases_total,
        ocr_cost_usd=cost_total, residuals=residuals,
    )


def render_summary(summary: RunSummary) -> str:
    """Format a :class:`RunSummary` as operator-readable text."""
    lines: list[str] = []
    lines.append(
        f"Run: {summary.run_dir}/  ({summary.layout}, "
        f"{summary.n_shards} shard{'s' if summary.n_shards != 1 else ''})"
    )

    if summary.state == RunState.DONE:
        lines.append(
            f"Status: ✓ DONE  ({summary.n_done_shards}/{summary.n_shards} shards)"
        )
    elif summary.state == RunState.RUNNING:
        lines.append(
            f"Status: ⋯ RUNNING  "
            f"({summary.n_done_shards}/{summary.n_shards} shards done)"
        )
    else:
        lines.append("Status: ∅ EMPTY  (no logs found at this path)")
        return "\n".join(lines) + "\n"

    lines.append("")
    lines.append("Per-stage rollup (cluster-wide):")
    bd = summary.breakdown
    if bd.processos or bd.pecas or bd.text:
        for label, mix in (
            ("processos", bd.processos),
            ("pecas    ", bd.pecas),
            ("text     ", bd.text),
        ):
            if mix:
                parts = " · ".join(f"{k}={v}" for k, v in sorted(mix.items()))
                lines.append(f"  {label}  {parts}")
    else:
        lines.append("  (no state file present yet)")

    if summary.longest_wall_s is not None:
        lines.append("")
        longest_h = _fmt_wall(summary.longest_wall_s)
        total_h = _fmt_wall(summary.total_wall_s or 0.0)
        lines.append(
            f"Wall: longest shard {longest_h} ({summary.longest_wall_s:.0f}s) · "
            f"sum across shards {total_h} ({summary.total_wall_s:.0f}s)"
        )
    if summary.ocr_cost_usd > 0:
        lines.append(f"OCR cost: ${summary.ocr_cost_usd:.4f}")

    if summary.state == RunState.DONE:
        lines.append("")
        if not summary.residuals:
            lines.append("Residuals: (none — all clean)")
        else:
            lines.append("Residuals:")
            for r in summary.residuals:
                tag = "terminal" if r.is_terminal else "retryable"
                lines.append(
                    f"  {r.kind:<13} {r.status:<20} {r.count:>5}  "
                    f"[{tag}: {r.label}]"
                )

            retryable = [r for r in summary.residuals if not r.is_terminal]
            if retryable:
                lines.append("")
                lines.append("Next steps (copy-paste ready):")
                seen: set[str] = set()
                for r in retryable:
                    if not r.suggested_command or r.suggested_command in seen:
                        continue
                    seen.add(r.suggested_command)
                    lines.append("")
                    lines.append(f"# {r.label} ({r.count} {r.kind}/{r.status})")
                    lines.append(r.suggested_command)

    return "\n".join(lines) + "\n"
