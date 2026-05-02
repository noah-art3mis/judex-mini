"""`judex coletar` — total-run orchestrator (per ADR-0004).

Owns the six-stage interleaved chain for a (classe, range) backfill:

    varrer → varrer-retry → baixar → baixar-retry → extrair → extrair-retry

Each retry stage replays only the prior stage's transient residual,
classified by `judex.sweeps.error_triage`. Cap of 2 retry cycles per
stage with early-exit when residual=0 OR didn't shrink between cycles.
Per-stage transient-rate gate (default 2%) aborts the chain rather
than firing retries against a systemic break.

This module is deliberately runner-agnostic — `run_stage_with_retries`
takes `forward_fn` / `retry_fn` callables so the cycle loop is testable
without invoking real sweeps. The Typer command in `judex/cli.py`
wires the production runners (subprocess-based: shells out to the
existing per-stage commands so all CLI plumbing — CSV gen, signal
handlers, preview, retomar — is reused).

REPORT.md is rendered post-run; run-quality classification (clean /
acceptable / degraded / broken) grades the residual independently of
the gate trip — the gate aborts chains mid-flight; quality grades
chains that finished.
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Literal, Optional


Quality = Literal["clean", "acceptable", "degraded", "broken"]
StageName = Literal["varrer", "baixar", "extrair"]


# Errors-file name per stage. varrer's store writes `sweep.errors.jsonl`;
# baixar/extrair both use `pdfs.errors.jsonl` (PecaStore).
_ERRORS_FILENAME: dict[str, str] = {
    "varrer": "sweep.errors.jsonl",
    "baixar": "pdfs.errors.jsonl",
    "extrair": "pdfs.errors.jsonl",
}


@dataclass(frozen=True)
class ColetaConfig:
    """Inputs for one coleta run."""

    classe: str
    inicio: int
    fim: int
    saida: Path
    rotulo: str
    max_retry_cycles: int = 2
    transient_gates: dict[str, float] = field(
        default_factory=lambda: {"varrer": 0.02, "baixar": 0.02, "extrair": 0.02}
    )


@dataclass(frozen=True)
class StageMetrics:
    """One forward or retry pass's outcome.

    `transient_residual` is the count of rows in the produced
    errors.jsonl that classify `transient` per `error_triage`. Other
    classifications (terminal, cross_stage, ok) are not counted here
    — they're reported separately in the per-stage outcome.

    `total_processed` is the count of rows the stage attempted in
    this pass — for forward, the input target count; for retry, the
    transient residual it was scoped to.
    """

    transient_residual: int
    total_processed: int

    @property
    def transient_rate(self) -> float:
        if self.total_processed == 0:
            return 0.0
        return self.transient_residual / self.total_processed


@dataclass(frozen=True)
class StageOutcome:
    """Aggregated forward + retry cycles for one stage."""

    forward: StageMetrics
    retries: list[StageMetrics]
    aborted_at: Optional[str]   # None | "forward" | "retry-1" | "retry-2"
    final_transient: int

    @property
    def total_processed(self) -> int:
        return self.forward.total_processed


@dataclass(frozen=True)
class ColetaResult:
    config: ColetaConfig
    stages: dict[str, StageOutcome]
    quality: Quality
    aborted_at_stage: Optional[str]


# ----- cycle loop -----------------------------------------------------------


ForwardFn = Callable[[Path], StageMetrics]
RetryFn = Callable[[Path, Path], StageMetrics]


def run_stage_with_retries(
    *,
    stage_name: str,
    base_dir: Path,
    forward_fn: ForwardFn,
    retry_fn: RetryFn,
    transient_gate: float,
    max_cycles: int,
) -> StageOutcome:
    """Run one stage's forward pass + up to `max_cycles` retry cycles.

    Sequence:
      1. Call ``forward_fn(base_dir)``.
      2. If forward transient rate > ``transient_gate``: abort the
         stage with ``aborted_at="forward"``. Caller checks this and
         halts the chain.
      3. Else iterate up to ``max_cycles`` retry cycles. Each cycle:
         - reads errors.jsonl from the previous pass's directory,
         - calls ``retry_fn(retry_dir, errors_path)``,
         - early-exits when residual=0 OR didn't shrink vs the prior
           cycle's residual.

    Returns a ``StageOutcome``.
    """
    forward = forward_fn(base_dir)

    if forward.transient_rate > transient_gate:
        return StageOutcome(
            forward=forward,
            retries=[],
            aborted_at="forward",
            final_transient=forward.transient_residual,
        )

    retries: list[StageMetrics] = []
    prev_residual = forward.transient_residual
    prev_dir = base_dir

    for cycle in range(1, max_cycles + 1):
        if prev_residual == 0:
            break  # nothing to retry — early-exit on residual=0
        retry_dir = base_dir.parent / f"{base_dir.name}-retry-{cycle}"
        errors_path = prev_dir / _ERRORS_FILENAME[stage_name]
        result = retry_fn(retry_dir, errors_path)
        retries.append(result)
        if result.transient_residual >= prev_residual:
            break  # no shrink — early-exit per ADR-0004
        prev_residual = result.transient_residual
        prev_dir = retry_dir

    return StageOutcome(
        forward=forward,
        retries=retries,
        aborted_at=None,
        final_transient=prev_residual,
    )


# ----- run quality ----------------------------------------------------------


def compute_run_quality(stages: dict[str, StageMetrics]) -> Quality:
    """Grade a finished coleta by per-stage transient rate.

    Tiers (per ADR-0004 / CONTEXT.md § Run quality):
      - ``clean``      : all stages residual = 0
      - ``acceptable`` : all stages residual ≤ 1%
      - ``degraded``   : any stage in 1–5%
      - ``broken``     : any stage > 5%

    Caller passes the *final* per-stage metrics (after all retry cycles).
    """
    rates = [m.transient_rate for m in stages.values()]
    if all(r == 0 for r in rates):
        return "clean"
    if all(r <= 0.01 for r in rates):
        return "acceptable"
    if any(r > 0.05 for r in rates):
        return "broken"
    return "degraded"


# ----- REPORT.md render -----------------------------------------------------


def render_report_md(
    config: ColetaConfig,
    stage_outcomes: dict[str, StageOutcome],
    quality: Quality,
) -> str:
    """Render the human-readable summary of a finished coleta.

    Stable shape — analysis tooling and operators read this so the
    section headers and column names should not drift without thought.
    """
    lines: list[str] = []
    lines.append(f"# Coleta — {config.rotulo}")
    lines.append("")
    lines.append(
        f"- classe: `{config.classe}` · range: "
        f"`{config.inicio}..{config.fim}` ({config.fim - config.inicio + 1} ids)"
    )
    lines.append(f"- saída: `{config.saida}`")
    lines.append(f"- max-retry-cycles: {config.max_retry_cycles}")
    lines.append(f"- run quality: **{quality}**")
    lines.append("")
    lines.append("## Stages")
    lines.append("")
    lines.append(
        "| stage    | total | forward residual | retry-1 residual | "
        "retry-2 residual | final residual | rate   | status |"
    )
    lines.append(
        "|----------|------:|-----------------:|-----------------:|"
        "-----------------:|---------------:|-------:|--------|"
    )
    for stage_name in ("varrer", "baixar", "extrair"):
        if stage_name not in stage_outcomes:
            continue
        out = stage_outcomes[stage_name]
        r1 = out.retries[0].transient_residual if len(out.retries) >= 1 else "—"
        r2 = out.retries[1].transient_residual if len(out.retries) >= 2 else "—"
        rate = out.final_transient / out.total_processed if out.total_processed else 0.0
        status = "aborted" if out.aborted_at else "done"
        lines.append(
            f"| {stage_name:<8s} | {out.total_processed:>5d} | "
            f"{out.forward.transient_residual:>16d} | {str(r1):>16s} | "
            f"{str(r2):>16s} | {out.final_transient:>14d} | "
            f"{rate * 100:>5.2f}% | {status} |"
        )
    lines.append("")
    return "\n".join(lines)


# ----- chain composition ----------------------------------------------------


@dataclass(frozen=True)
class StageRunner:
    """Forward + retry pair for one stage. Production wiring lives
    in `judex/cli.py`'s `coletar` command; tests inject fakes.
    """

    forward: ForwardFn
    retry: RetryFn


# Order is load-bearing: baixar consumes case JSONs from varrer, and
# extrair consumes bytes from baixar. Per ADR-0004 the chain halts on
# the first stage abort because downstream artifacts would otherwise
# be silently incomplete.
_STAGE_ORDER: list[str] = ["varrer", "baixar", "extrair"]


def run_coleta(
    config: ColetaConfig,
    runners: dict[str, StageRunner],
) -> ColetaResult:
    """Run the full coleta chain — varrer → baixar → extrair, each
    with its own retry cycle, halting on the first gate abort.

    Writes ``<saida>/REPORT.md`` summarising per-stage residuals + run
    quality.
    """
    config.saida.mkdir(parents=True, exist_ok=True)

    stages: dict[str, StageOutcome] = {}
    aborted_at: Optional[str] = None

    for stage_name in _STAGE_ORDER:
        runner = runners[stage_name]
        base_dir = config.saida / stage_name
        outcome = run_stage_with_retries(
            stage_name=stage_name,
            base_dir=base_dir,
            forward_fn=runner.forward,
            retry_fn=runner.retry,
            transient_gate=config.transient_gates[stage_name],
            max_cycles=config.max_retry_cycles,
        )
        stages[stage_name] = outcome
        if outcome.aborted_at is not None:
            aborted_at = stage_name
            break

    if aborted_at is not None:
        # An aborted chain failed mid-flight; its run quality is not
        # measurable in the same units as a finished chain. Use
        # `broken` deliberately — it is the only quality grade
        # consistent with "operator must investigate before
        # re-running" per ADR-0004.
        quality: Quality = "broken"
    else:
        # Compute quality from each stage's *final* metrics: the
        # transient residual after retry exhaustion, divided by the
        # forward pass's total processed.
        final_metrics = {
            name: StageMetrics(
                transient_residual=outcome.final_transient,
                total_processed=outcome.total_processed,
            )
            for name, outcome in stages.items()
        }
        quality = compute_run_quality(final_metrics)

    md = render_report_md(config, stages, quality)
    (config.saida / "REPORT.md").write_text(md)

    return ColetaResult(
        config=config,
        stages=stages,
        quality=quality,
        aborted_at_stage=aborted_at,
    )


# ----- post-run scanning ----------------------------------------------------


# state.json file name per stage. Mirrors the constants in
# process_store / peca_store; duplicated here only so the helper
# below can be a pure function (no store import).
_STATE_FILENAME: dict[str, str] = {
    "varrer": "sweep.state.json",
    "baixar": "pdfs.state.json",
    "extrair": "pdfs.state.json",
}


def count_transient_residual(errors_path: Path, stage: str) -> int:
    """Count rows in ``errors.jsonl`` that classify ``transient`` for the
    stage, via ``error_triage.classify_error``.

    Missing file returns 0 (the stage produced no errors).
    """
    from judex.sweeps.error_triage import classify_error

    if not errors_path.exists():
        return 0
    n = 0
    with errors_path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            if classify_error(stage, rec) == "transient":
                n += 1
    return n


def count_total_processed(state_path: Path) -> int:
    """Count entries in a ``state.json`` file. Returns 0 if missing."""
    if not state_path.exists():
        return 0
    with state_path.open() as f:
        data = json.load(f)
    if isinstance(data, dict):
        # Both process_store and peca_store wrap in {"items": {...}}
        # or similar. Inspect for known shapes.
        for key in ("items", "entries"):
            if key in data and isinstance(data[key], dict):
                return len(data[key])
        # Fallback: assume the whole dict is keyed by primary key.
        return sum(
            1 for v in data.values() if isinstance(v, dict)
        )
    return 0


def stage_metrics_from_dir(out_dir: Path, stage: str) -> StageMetrics:
    """Build a ``StageMetrics`` by scanning a finished sweep's output dir."""
    return StageMetrics(
        transient_residual=count_transient_residual(
            out_dir / _ERRORS_FILENAME[stage], stage,
        ),
        total_processed=count_total_processed(
            out_dir / _STATE_FILENAME[stage],
        ),
    )


# ----- production wiring (subprocess) --------------------------------------


def _run_subprocess(
    argv: list[str], log_path: Path,
    *, env: Optional[dict[str, str]] = None,
) -> int:
    """Run a subcommand, tee its stdout/stderr to a log file. Returns
    the exit code. The chain log lives at ``<saida>/coletar.log`` —
    this helper writes per-stage launcher logs alongside.
    """
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a") as logf:
        proc = subprocess.run(
            argv, stdout=logf, stderr=subprocess.STDOUT, text=True, env=env,
        )
    return proc.returncode


def make_subprocess_runners(
    config: ColetaConfig,
    *,
    provedor: str = "auto",
    paralelo: int = 10,
    ocr_tesseract_provider: str = "tesseract_fly",
) -> dict[str, StageRunner]:
    """Build the three production StageRunners by shelling out to
    ``judex varrer-processos`` / ``baixar-pecas`` / ``extrair-pecas``.

    Each runner spawns the existing CLI command via ``uv run``,
    capturing stdout/stderr to ``<out_dir>/launcher-stdout.log``.
    After exit, scans the produced state/errors files for metrics.

    `ocr_tesseract_provider` controls where the auto-router sends
    ACÓRDÃO doc-types when extrair-pecas runs with `--provedor auto`:

      - ``"tesseract"``     — local CPU, free, slower (CPU-bound, no
        parallel benefit on a busy host)
      - ``"tesseract_fly"`` — Fly-hosted, billed at $0.01 / 1k pages,
        parallelizes via Modal-style fan-out (paralelo > 1 helps)
      - ``"tesseract_modal"`` — Modal-hosted, similar billing

    `coletar` defaults to ``tesseract_fly`` because the orchestrator
    is meant for production-scale backfills where wall-time dominates;
    the cost banner at the CLI startup discloses the rate so the
    operator can opt out by passing ``--ocr-tesseract-provider tesseract``.
    Direct ``extrair-pecas`` invocations keep the local default.
    """
    extrair_env: dict[str, str] = {
        **os.environ,
        "JUDEX_AUTO_TESSERACT_PROVIDER": ocr_tesseract_provider,
    }

    def varrer_forward(out_dir: Path) -> StageMetrics:
        argv = [
            "uv", "run", "judex", "varrer-processos",
            "-c", config.classe,
            "-i", str(config.inicio),
            "-f", str(config.fim),
            "--saida", str(out_dir),
            "--rotulo", config.rotulo,
            "--retomar",
        ]
        _run_subprocess(argv, out_dir / "launcher-stdout.log")
        return stage_metrics_from_dir(out_dir, "varrer")

    def varrer_retry(out_dir: Path, errors_path: Path) -> StageMetrics:
        argv = [
            "uv", "run", "judex", "varrer-processos",
            "--retentar-de", str(errors_path),
            "--saida", str(out_dir),
            "--rotulo", f"{config.rotulo}_retry",
            "--retomar",
        ]
        _run_subprocess(argv, out_dir / "launcher-stdout.log")
        return stage_metrics_from_dir(out_dir, "varrer")

    def baixar_forward(out_dir: Path) -> StageMetrics:
        argv = [
            "uv", "run", "judex", "baixar-pecas",
            "-c", config.classe,
            "-i", str(config.inicio),
            "-f", str(config.fim),
            "--saida", str(out_dir),
            "--retomar", "--nao-perguntar",
        ]
        _run_subprocess(argv, out_dir / "launcher-stdout.log")
        return stage_metrics_from_dir(out_dir, "baixar")

    def baixar_retry(out_dir: Path, errors_path: Path) -> StageMetrics:
        argv = [
            "uv", "run", "judex", "baixar-pecas",
            "--retentar-de", str(errors_path),
            "--saida", str(out_dir),
            "--retomar", "--nao-perguntar",
        ]
        _run_subprocess(argv, out_dir / "launcher-stdout.log")
        return stage_metrics_from_dir(out_dir, "baixar")

    def extrair_forward(out_dir: Path) -> StageMetrics:
        argv = [
            "uv", "run", "judex", "extrair-pecas",
            "-c", config.classe,
            "-i", str(config.inicio),
            "-f", str(config.fim),
            "--saida", str(out_dir),
            "--provedor", provedor,
            "--paralelo", str(paralelo),
            "--retomar", "--nao-perguntar",
        ]
        _run_subprocess(argv, out_dir / "launcher-stdout.log", env=extrair_env)
        return stage_metrics_from_dir(out_dir, "extrair")

    def extrair_retry(out_dir: Path, errors_path: Path) -> StageMetrics:
        # ADR-0004: extrair retry uses --provedor auto --forcar so the
        # auto-router escalates to OCR if pypdf produced garbage; the
        # sidecar match is bypassed (we want the retry to overwrite
        # any prior poisoned-cache `.txt.gz`).
        argv = [
            "uv", "run", "judex", "extrair-pecas",
            "--retentar-de", str(errors_path),
            "--saida", str(out_dir),
            "--provedor", provedor,
            "--paralelo", str(paralelo),
            "--forcar", "--retomar", "--nao-perguntar",
        ]
        _run_subprocess(argv, out_dir / "launcher-stdout.log", env=extrair_env)
        return stage_metrics_from_dir(out_dir, "extrair")

    return {
        "varrer": StageRunner(forward=varrer_forward, retry=varrer_retry),
        "baixar": StageRunner(forward=baixar_forward, retry=baixar_retry),
        "extrair": StageRunner(forward=extrair_forward, retry=extrair_retry),
    }
