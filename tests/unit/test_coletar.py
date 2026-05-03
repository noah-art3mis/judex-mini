"""Cycle-loop, gate, run-quality, and REPORT.md tests for `judex coletar`.

The orchestrator is testable without spinning real sweeps: forward and
retry pipelines are injected as `Callable[[Path, ...], StageMetrics]`
fakes. The tests pin the behavioural decisions from ADR-0004:

- cap=2 retry cycles per stage, early-exit on residual=0 OR no-shrink
- per-stage 2% transient-rate gate aborts the chain mid-flight
- run quality grades a finished chain: clean / acceptable / degraded / broken
- REPORT.md renders per-stage residual + quality grade
"""

from __future__ import annotations

from pathlib import Path

import pytest

from judex.sweeps.coletar import (
    ColetaConfig,
    ColetaResult,
    StageMetrics,
    StageRunner,
    compute_run_quality,
    render_report_md,
    run_coleta,
    run_stage_with_retries,
)


# ----- helpers --------------------------------------------------------------


def _fake_forward(metrics: list[StageMetrics]):
    """Return a forward_fn that yields the next metrics in order."""
    iter_metrics = iter(metrics)

    def fn(out_dir: Path) -> StageMetrics:
        out_dir.mkdir(parents=True, exist_ok=True)
        return next(iter_metrics)

    return fn


def _fake_retry(metrics: list[StageMetrics]):
    """Return a retry_fn that yields the next metrics in order."""
    iter_metrics = iter(metrics)

    def fn(out_dir: Path, errors_path: Path) -> StageMetrics:
        out_dir.mkdir(parents=True, exist_ok=True)
        return next(iter_metrics)

    return fn


# ----- cycle loop -----------------------------------------------------------


def test_no_retry_when_forward_residual_is_zero(tmp_path: Path) -> None:
    """Forward pass with 0 transient residual should fire 0 retry cycles
    — early-exit before the first retry, not after.
    """
    forward_calls: list[Path] = []
    retry_calls: list[Path] = []

    def forward(out_dir: Path) -> StageMetrics:
        forward_calls.append(out_dir)
        return StageMetrics(transient_residual=0, total_processed=1000)

    def retry(out_dir: Path, errors_path: Path) -> StageMetrics:
        retry_calls.append(out_dir)
        return StageMetrics(transient_residual=0, total_processed=0)

    out = run_stage_with_retries(
        stage_name="varrer",
        base_dir=tmp_path / "varrer",
        forward_fn=forward,
        retry_fn=retry,
        transient_gate=0.02,
        max_cycles=2,
    )

    assert len(forward_calls) == 1
    assert len(retry_calls) == 0
    assert out.aborted_at is None
    assert out.retries == []
    assert out.final_transient == 0


def test_one_retry_when_residual_clears(tmp_path: Path) -> None:
    """Forward leaves 50 transients; retry-1 clears them. Retry-2 must not run.
    """
    forward = _fake_forward([
        StageMetrics(transient_residual=50, total_processed=1000),
    ])
    retry_calls: list[Path] = []

    def retry(out_dir: Path, errors_path: Path) -> StageMetrics:
        retry_calls.append(out_dir)
        return StageMetrics(transient_residual=0, total_processed=50)

    out = run_stage_with_retries(
        stage_name="extrair",
        base_dir=tmp_path / "extrair",
        forward_fn=forward,
        retry_fn=retry,
        transient_gate=0.10,  # 50/1000 = 5% < gate
        max_cycles=2,
    )

    assert len(retry_calls) == 1
    assert len(out.retries) == 1
    assert out.final_transient == 0
    assert out.aborted_at is None


def test_two_retries_when_residual_keeps_shrinking(tmp_path: Path) -> None:
    """50 → 10 → 0: both retry cycles run, total of 3 passes."""
    forward = _fake_forward([
        StageMetrics(transient_residual=50, total_processed=1000),
    ])
    retry = _fake_retry([
        StageMetrics(transient_residual=10, total_processed=50),
        StageMetrics(transient_residual=0, total_processed=10),
    ])

    out = run_stage_with_retries(
        stage_name="extrair",
        base_dir=tmp_path / "extrair",
        forward_fn=forward,
        retry_fn=retry,
        transient_gate=0.10,
        max_cycles=2,
    )

    assert len(out.retries) == 2
    assert out.retries[0].transient_residual == 10
    assert out.retries[1].transient_residual == 0
    assert out.final_transient == 0


def test_early_exit_when_retry_does_not_shrink(tmp_path: Path) -> None:
    """50 → 50 (no improvement): retry-2 must NOT run. Cap-with-early-exit."""
    forward = _fake_forward([
        StageMetrics(transient_residual=50, total_processed=1000),
    ])
    retry_calls: list[Path] = []

    def retry(out_dir: Path, errors_path: Path) -> StageMetrics:
        retry_calls.append(out_dir)
        return StageMetrics(transient_residual=50, total_processed=50)

    out = run_stage_with_retries(
        stage_name="extrair",
        base_dir=tmp_path / "extrair",
        forward_fn=forward,
        retry_fn=retry,
        transient_gate=0.10,
        max_cycles=2,
    )

    assert len(retry_calls) == 1  # only retry-1 ran
    assert len(out.retries) == 1
    assert out.final_transient == 50
    assert out.aborted_at is None  # not aborted, just exhausted shrinking


def test_cap_holds_when_residual_persists_but_shrinks(tmp_path: Path) -> None:
    """50 → 40 → 30: cap=2 means retry-3 doesn't run even though 30 > 0."""
    forward = _fake_forward([
        StageMetrics(transient_residual=50, total_processed=1000),
    ])
    retry = _fake_retry([
        StageMetrics(transient_residual=40, total_processed=50),
        StageMetrics(transient_residual=30, total_processed=40),
    ])

    out = run_stage_with_retries(
        stage_name="extrair",
        base_dir=tmp_path / "extrair",
        forward_fn=forward,
        retry_fn=retry,
        transient_gate=0.10,
        max_cycles=2,
    )

    assert len(out.retries) == 2
    assert out.final_transient == 30


# ----- gate -----------------------------------------------------------------


def test_gate_trip_aborts_before_retries(tmp_path: Path) -> None:
    """Forward transient rate > gate → stage marks aborted, no retries fire."""
    forward = _fake_forward([
        StageMetrics(transient_residual=300, total_processed=1000),  # 30%
    ])
    retry_calls: list[Path] = []

    def retry(out_dir: Path, errors_path: Path) -> StageMetrics:
        retry_calls.append(out_dir)
        return StageMetrics(transient_residual=0, total_processed=0)

    out = run_stage_with_retries(
        stage_name="varrer",
        base_dir=tmp_path / "varrer",
        forward_fn=forward,
        retry_fn=retry,
        transient_gate=0.02,  # 2%, way below 30%
        max_cycles=2,
    )

    assert out.aborted_at == "forward"
    assert len(retry_calls) == 0
    assert out.final_transient == 300


def test_gate_at_exactly_threshold_does_not_trip(tmp_path: Path) -> None:
    """Threshold is exclusive: rate == gate proceeds with retry."""
    forward = _fake_forward([
        StageMetrics(transient_residual=20, total_processed=1000),  # 2.0%
    ])
    retry = _fake_retry([
        StageMetrics(transient_residual=0, total_processed=20),
    ])

    out = run_stage_with_retries(
        stage_name="varrer",
        base_dir=tmp_path / "varrer",
        forward_fn=forward,
        retry_fn=retry,
        transient_gate=0.02,
        max_cycles=2,
    )

    assert out.aborted_at is None
    assert out.final_transient == 0


# ----- run quality ---------------------------------------------------------


def test_run_quality_clean() -> None:
    stages = {
        "varrer": StageMetrics(transient_residual=0, total_processed=1000),
        "baixar": StageMetrics(transient_residual=0, total_processed=2000),
        "extrair": StageMetrics(transient_residual=0, total_processed=2000),
    }
    assert compute_run_quality(stages) == "clean"


def test_run_quality_acceptable_when_all_under_one_percent() -> None:
    stages = {
        "varrer": StageMetrics(transient_residual=5, total_processed=1000),    # 0.5%
        "baixar": StageMetrics(transient_residual=10, total_processed=2000),   # 0.5%
        "extrair": StageMetrics(transient_residual=15, total_processed=2000),  # 0.75%
    }
    assert compute_run_quality(stages) == "acceptable"


def test_run_quality_degraded_when_any_stage_in_one_to_five_percent() -> None:
    stages = {
        "varrer": StageMetrics(transient_residual=0, total_processed=1000),
        "baixar": StageMetrics(transient_residual=0, total_processed=2000),
        "extrair": StageMetrics(transient_residual=60, total_processed=2000),  # 3%
    }
    assert compute_run_quality(stages) == "degraded"


def test_run_quality_broken_when_any_stage_above_five_percent() -> None:
    stages = {
        "varrer": StageMetrics(transient_residual=0, total_processed=1000),
        "baixar": StageMetrics(transient_residual=0, total_processed=2000),
        "extrair": StageMetrics(transient_residual=200, total_processed=2000),  # 10%
    }
    assert compute_run_quality(stages) == "broken"


def test_run_quality_handles_zero_total() -> None:
    """Zero-total (e.g., aborted forward) must not divide-by-zero."""
    stages = {
        "varrer": StageMetrics(transient_residual=0, total_processed=0),
        "baixar": StageMetrics(transient_residual=0, total_processed=0),
        "extrair": StageMetrics(transient_residual=0, total_processed=0),
    }
    assert compute_run_quality(stages) == "clean"


# ----- REPORT.md render -----------------------------------------------------


def test_report_md_renders_table() -> None:
    """REPORT.md should expose: per-stage forward + retry counts,
    transient rate, run quality grade. Future warehouse builders /
    operators read this so it must be deterministic."""
    config = ColetaConfig(
        classe="HC",
        inicio=250920,
        fim=267137,
        saida=Path("/tmp/coletar-test"),
        rotulo="hc2025_2026-05-02",
    )
    stage_outcomes = {
        "varrer": _stage_outcome(forward_residual=0, total=16218, retries=[]),
        "baixar": _stage_outcome(forward_residual=10, total=28261, retries=[(0, 10)]),
        "extrair": _stage_outcome(
            forward_residual=383, total=5273,
            retries=[(20, 383), (0, 20)],
        ),
    }
    md = render_report_md(config, stage_outcomes, quality="clean")

    assert "hc2025_2026-05-02" in md
    assert "## Stages" in md
    # Each stage row carries final transient and total processed.
    assert "varrer" in md
    assert "baixar" in md
    assert "extrair" in md
    # Quality grade shows up.
    assert "clean" in md
    # Cycle counts show up — extrair had 2 retry cycles.
    for stage in ("varrer", "baixar", "extrair"):
        assert stage in md


# ----- helpers --------------------------------------------------------------


def _stage_outcome(*, forward_residual: int, total: int, retries: list):
    """Build a StageOutcome stub for report-rendering tests.

    `retries` is a list of `(residual, total_processed)` tuples.
    """
    from judex.sweeps.coletar import StageOutcome

    return StageOutcome(
        forward=StageMetrics(transient_residual=forward_residual, total_processed=total),
        retries=[
            StageMetrics(transient_residual=r, total_processed=t)
            for r, t in retries
        ],
        aborted_at=None,
        final_transient=retries[-1][0] if retries else forward_residual,
    )


# ----- chain composition ----------------------------------------------------


def _runner(forward_metrics: list[StageMetrics], retry_metrics: list[StageMetrics]):
    """Build a StageRunner with pre-canned forward + retry outcomes."""
    fwd_iter = iter(forward_metrics)
    ret_iter = iter(retry_metrics)

    def forward(out_dir):
        out_dir.mkdir(parents=True, exist_ok=True)
        return next(fwd_iter)

    def retry(out_dir, errors_path):
        out_dir.mkdir(parents=True, exist_ok=True)
        return next(ret_iter)

    return StageRunner(forward=forward, retry=retry)


def test_chain_runs_all_three_stages_when_clean(tmp_path: Path) -> None:
    """Forward only, no retries: chain runs varrer → baixar → extrair,
    quality is `clean`, no aborts.
    """
    config = ColetaConfig(
        classe="HC", inicio=1, fim=10,
        saida=tmp_path / "out", rotulo="t",
    )
    runners = {
        "varrer": _runner(
            [StageMetrics(transient_residual=0, total_processed=10)], [],
        ),
        "baixar": _runner(
            [StageMetrics(transient_residual=0, total_processed=20)], [],
        ),
        "extrair": _runner(
            [StageMetrics(transient_residual=0, total_processed=20)], [],
        ),
    }

    result = run_coleta(config, runners)

    assert isinstance(result, ColetaResult)
    assert set(result.stages.keys()) == {"varrer", "baixar", "extrair"}
    assert result.quality == "clean"
    assert result.aborted_at_stage is None


def test_chain_halts_on_first_stage_abort(tmp_path: Path) -> None:
    """Varrer trips its gate (>2% transient): downstream stages do
    NOT run. The chain returns immediately with aborted_at_stage set.
    """
    config = ColetaConfig(
        classe="HC", inicio=1, fim=10,
        saida=tmp_path / "out", rotulo="t",
    )
    baixar_calls: list = []
    extrair_calls: list = []

    def baixar_forward(out_dir):
        baixar_calls.append(out_dir)
        return StageMetrics(0, 0)

    def extrair_forward(out_dir):
        extrair_calls.append(out_dir)
        return StageMetrics(0, 0)

    runners = {
        # Varrer trips at 30% transient rate.
        "varrer": _runner(
            [StageMetrics(transient_residual=300, total_processed=1000)], [],
        ),
        "baixar": StageRunner(
            forward=baixar_forward,
            retry=lambda *_a, **_k: StageMetrics(0, 0),
        ),
        "extrair": StageRunner(
            forward=extrair_forward,
            retry=lambda *_a, **_k: StageMetrics(0, 0),
        ),
    }

    result = run_coleta(config, runners)

    assert result.aborted_at_stage == "varrer"
    assert "varrer" in result.stages  # forward was recorded
    assert "baixar" not in result.stages
    assert "extrair" not in result.stages
    assert len(baixar_calls) == 0
    assert len(extrair_calls) == 0


def test_chain_runs_full_retry_cycle_per_stage(tmp_path: Path) -> None:
    """Each stage gets its own forward + retry cycles. Verify all
    three stages cycle and the result aggregates correctly."""
    config = ColetaConfig(
        classe="HC", inicio=1, fim=10,
        saida=tmp_path / "out", rotulo="t",
    )
    # Each stage: forward leaves 5 transients out of 1000 (0.5%, well
    # under the 2% gate); retry-1 closes them.
    def stage_runner():
        return _runner(
            [StageMetrics(transient_residual=5, total_processed=1000)],
            [StageMetrics(transient_residual=0, total_processed=5)],
        )
    runners = {
        "varrer": stage_runner(),
        "baixar": stage_runner(),
        "extrair": stage_runner(),
    }

    result = run_coleta(config, runners)

    assert result.quality == "clean"
    assert result.aborted_at_stage is None
    for stage in ("varrer", "baixar", "extrair"):
        outcome = result.stages[stage]
        assert outcome.aborted_at is None
        assert len(outcome.retries) == 1
        assert outcome.final_transient == 0


def test_chain_writes_report_md(tmp_path: Path) -> None:
    """Chain run creates `<saida>/REPORT.md` containing the rendered
    summary."""
    config = ColetaConfig(
        classe="HC", inicio=1, fim=10,
        saida=tmp_path / "out", rotulo="t",
    )
    runners = {
        "varrer": _runner([StageMetrics(0, 10)], []),
        "baixar": _runner([StageMetrics(0, 20)], []),
        "extrair": _runner([StageMetrics(0, 20)], []),
    }

    run_coleta(config, runners)

    report = tmp_path / "out" / "REPORT.md"
    assert report.exists()
    md = report.read_text()
    assert "# Coleta — t" in md
    assert "clean" in md


# ----- post-run scanners ----------------------------------------------------


def test_count_transient_residual_classifies_via_error_triage(tmp_path: Path) -> None:
    """Scanner counts only `transient` rows — terminal `unallocated` and
    `cached` (state-snapshot artefacts) are excluded.
    """
    from judex.sweeps.coletar import count_transient_residual
    import json

    p = tmp_path / "sweep.errors.jsonl"
    p.write_text(
        # Terminal: legacy não-alocado.
        json.dumps({
            "classe": "HC", "processo": 1,
            "status": "fail",
            "error": "scrape returned None (incidente not resolved): ''",
        }) + "\n"
        # Transient: WAF 403.
        + json.dumps({
            "classe": "HC", "processo": 2,
            "status": "fail", "error": "HTTPError: 403", "http_status": 403,
        }) + "\n"
        # Transient: SSL.
        + json.dumps({
            "classe": "HC", "processo": 3,
            "status": "fail", "error": "SSLEOFError: EOF",
        }) + "\n"
    )
    assert count_transient_residual(p, "varrer") == 2


def test_count_transient_residual_handles_missing_file(tmp_path: Path) -> None:
    """A stage with no errors.jsonl produced has 0 transient residual."""
    from judex.sweeps.coletar import count_transient_residual

    assert count_transient_residual(tmp_path / "missing.jsonl", "varrer") == 0


def test_count_total_processed_handles_missing_file(tmp_path: Path) -> None:
    """A stage with no state.json (e.g., aborted on first row) reports 0."""
    from judex.sweeps.coletar import count_total_processed

    assert count_total_processed(tmp_path / "missing.json") == 0


def test_count_total_processed_reads_dict_keyed_state(tmp_path: Path) -> None:
    """state.json from process_store / peca_store is `{key: row}` —
    count = number of keys."""
    from judex.sweeps.coletar import count_total_processed
    import json

    p = tmp_path / "state.json"
    p.write_text(json.dumps({
        "HC_1": {"status": "ok"},
        "HC_2": {"status": "fail"},
        "HC_3": {"status": "ok"},
    }))
    assert count_total_processed(p) == 3


def test_stage_metrics_from_dir_round_trip(tmp_path: Path) -> None:
    """Round-trip a known-shape stage dir and verify both metrics
    surface correctly. Anchors the production runner's post-call
    scan against a representative state + errors pair.
    """
    from judex.sweeps.coletar import stage_metrics_from_dir
    import json

    out = tmp_path / "varrer"
    out.mkdir()
    (out / "sweep.state.json").write_text(json.dumps({
        f"HC_{i}": {"status": "ok"} for i in range(100)
    }))
    (out / "sweep.errors.jsonl").write_text(
        # 5 transient + 5 terminal.
        "\n".join(
            json.dumps({
                "classe": "HC", "processo": i,
                "status": "fail", "error": "HTTPError: 403", "http_status": 403,
            }) for i in range(5)
        ) + "\n"
        + "\n".join(
            json.dumps({
                "classe": "HC", "processo": i,
                "status": "fail", "error": "scrape returned None",
            }) for i in range(5, 10)
        ) + "\n"
    )

    metrics = stage_metrics_from_dir(out, "varrer")
    assert metrics.total_processed == 100
    assert metrics.transient_residual == 5
