"""Tests for `judex scrape` — the one-command close-out chain.

`scrape` is pure orchestration over three existing library functions:

    run_pipeline(...)           # the scrape itself (portal/sistemas/ocr)
    run_until_stable(run_dir)   # the converging residual drain
    _run_warehouse(...)         # full DuckDB rebuild so the run is visible

These tests pin the *orchestration contract*, not the behaviour of the
three callees (each is tested in its own module):

1.  The three stages run in order, against the run `scrape` just created.
2.  A non-zero rc from the scrape short-circuits — no drain, no warehouse.
3.  `--shards` is rejected before any work starts (mono-only command).
4.  `--sem-recuperar` / `--sem-warehouse` opt out of the tail stages.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

import judex.cli as cli
from judex.cli import app
from judex.sweeps.recuperar import Bucket, LoopResult


runner = CliRunner()


def _write_csv(tmp_path: Path) -> Path:
    csv = tmp_path / "alvos.csv"
    csv.write_text("classe,processo\nHC,250920\n", encoding="utf-8")
    return csv


@pytest.fixture
def chained_stubs(monkeypatch: pytest.MonkeyPatch):
    """Stub the three stage callees, recording call order + the run_dir
    each stage receives. ``run_pipeline`` rc is mutable per-test via the
    returned dict's ``pipeline_rc`` key.
    """
    state: dict = {"calls": [], "drain_dir": None, "pipeline_rc": 0,
                   "warehouse_rc": 0}

    def fake_run_pipeline(*args, **kwargs):
        state["calls"].append("pipeline")
        state["pipeline_saida"] = kwargs.get("saida")
        return state["pipeline_rc"]

    def fake_run_until_stable(run_dir, **kwargs):
        state["calls"].append("recuperar")
        state["drain_dir"] = run_dir
        return LoopResult(
            final_buckets={b: [] for b in Bucket},
            passes_run=1, converged=True,
            stopped_for_no_progress=False, stopped_for_max_passes=False,
        )

    def fake_run_warehouse(*args, **kwargs):
        state["calls"].append("warehouse")
        return state["warehouse_rc"]

    # ``scrape`` imports run_pipeline / run_until_stable lazily inside the
    # function body, so patch them at their definition modules; _run_warehouse
    # is a module-level name in cli.
    monkeypatch.setattr("judex.pipeline.runner.run_pipeline", fake_run_pipeline)
    monkeypatch.setattr("judex.sweeps.recuperar.run_until_stable", fake_run_until_stable)
    monkeypatch.setattr(cli, "_run_warehouse", fake_run_warehouse)
    return state


def test_scrape_runs_pipeline_then_drain_then_warehouse(
    tmp_path: Path, chained_stubs: dict,
) -> None:
    saida = tmp_path / "run"
    result = runner.invoke(app, [
        "scrape", "--csv", str(_write_csv(tmp_path)),
        "--saida", str(saida), "--nao-perguntar",
    ])
    assert result.exit_code == 0, result.output
    assert chained_stubs["calls"] == ["pipeline", "recuperar", "warehouse"]


def test_scrape_drains_the_run_it_just_created(
    tmp_path: Path, chained_stubs: dict,
) -> None:
    """The drain must target the same --saida the scrape wrote to — not a
    default or the newest run dir. Otherwise scrape would drain the wrong
    collection."""
    saida = tmp_path / "run"
    runner.invoke(app, [
        "scrape", "--csv", str(_write_csv(tmp_path)),
        "--saida", str(saida), "--nao-perguntar",
    ])
    assert chained_stubs["drain_dir"] == saida
    assert chained_stubs["pipeline_saida"] == saida


def test_scrape_short_circuits_when_pipeline_fails(
    tmp_path: Path, chained_stubs: dict,
) -> None:
    chained_stubs["pipeline_rc"] = 2
    saida = tmp_path / "run"
    result = runner.invoke(app, [
        "scrape", "--csv", str(_write_csv(tmp_path)),
        "--saida", str(saida), "--nao-perguntar",
    ])
    assert result.exit_code == 2
    assert chained_stubs["calls"] == ["pipeline"]  # drain + warehouse skipped


def test_scrape_rejects_shards_before_any_work(
    tmp_path: Path, chained_stubs: dict,
) -> None:
    """scrape is mono-only — the chained drain/warehouse can't hang off a
    detached shard fleet. --shards must error out before run_pipeline."""
    saida = tmp_path / "run"
    result = runner.invoke(app, [
        "scrape", "--csv", str(_write_csv(tmp_path)),
        "--saida", str(saida), "--nao-perguntar",
        "--shards", "2", "--proxy-pool", str(tmp_path / "p.txt"),
    ])
    assert result.exit_code == 2
    assert chained_stubs["calls"] == []


def test_scrape_sem_warehouse_skips_build(
    tmp_path: Path, chained_stubs: dict,
) -> None:
    saida = tmp_path / "run"
    result = runner.invoke(app, [
        "scrape", "--csv", str(_write_csv(tmp_path)),
        "--saida", str(saida), "--nao-perguntar", "--sem-warehouse",
    ])
    assert result.exit_code == 0, result.output
    assert chained_stubs["calls"] == ["pipeline", "recuperar"]


def test_scrape_sem_recuperar_skips_drain(
    tmp_path: Path, chained_stubs: dict,
) -> None:
    saida = tmp_path / "run"
    result = runner.invoke(app, [
        "scrape", "--csv", str(_write_csv(tmp_path)),
        "--saida", str(saida), "--nao-perguntar", "--sem-recuperar",
    ])
    assert result.exit_code == 0, result.output
    assert chained_stubs["calls"] == ["pipeline", "warehouse"]
