"""Tests for ``judex.pipeline.run_index`` — the run-listing library
that backs ``judex listar``.

The contract under test is the four-state taxonomy
(running / stale / finished / unknown) derived from two on-disk
signals (pid file + state.json), plus the cleanup action for the
``stale`` bucket. State.json is faked with the minimum content
``run_index`` actually reads — top-level ``started_at`` / ``snapshot_at``
/ ``args`` — so these tests don't drift if the rest of the snapshot
schema changes.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from judex.pipeline.run_index import (
    RunStatus,
    list_runs,
    prune_stale_pid_files,
    summarize_run,
)


def _write_state(saida: Path, **kwargs) -> None:
    saida.mkdir(parents=True, exist_ok=True)
    base = {"started_at": "2026-05-11T19:00:00Z", "cases": {}}
    base.update(kwargs)
    (saida / "executar.state.json").write_text(
        json.dumps(base), encoding="utf-8"
    )


# 999_999_999 is large enough to be ~certainly unallocated on a normal
# Linux host (PID_MAX defaults to 4_194_304 on x86_64); the
# ``_is_pid_alive`` probe should return False without raising.
DEAD_PID = 999_999_999


def test_summarize_run_running_when_pid_file_has_live_pid(tmp_path: Path) -> None:
    saida = tmp_path / "live"
    _write_state(saida)
    (saida / "executar.pid").write_text(f"{os.getpid()}\n", encoding="utf-8")

    s = summarize_run(saida)

    assert s.status == RunStatus.RUNNING
    assert s.pids == [os.getpid()]


def test_summarize_run_stale_when_pid_file_present_but_pid_dead(tmp_path: Path) -> None:
    saida = tmp_path / "stale"
    _write_state(saida)
    (saida / "executar.pid").write_text(f"{DEAD_PID}\n", encoding="utf-8")

    s = summarize_run(saida)

    assert s.status == RunStatus.STALE
    assert s.pids == [DEAD_PID]


def test_summarize_run_finished_when_no_pid_file_but_state_present(tmp_path: Path) -> None:
    saida = tmp_path / "done"
    _write_state(saida, snapshot_at="2026-05-11T19:30:00Z")

    s = summarize_run(saida)

    assert s.status == RunStatus.FINISHED
    assert s.snapshot_at == "2026-05-11T19:30:00Z"


def test_summarize_run_unknown_when_no_state_json(tmp_path: Path) -> None:
    saida = tmp_path / "weird"
    saida.mkdir()

    s = summarize_run(saida)

    assert s.status == RunStatus.UNKNOWN
    assert s.pids == []


def test_summarize_run_extracts_rotulo_and_classe_from_args(tmp_path: Path) -> None:
    """``listar`` shows ``classe`` + ``rotulo`` for each run; those
    come from the ``args`` block that ``run_pipeline`` writes via
    ``set_original_args`` (same block ``retomar`` reads back)."""
    saida = tmp_path / "labelled"
    _write_state(saida, args={"classe": "HC", "rotulo": "hc2024-fillin"})

    s = summarize_run(saida)

    assert s.rotulo == "hc2024-fillin"
    assert s.classe == "HC"


def test_summarize_run_tolerates_missing_args_block(tmp_path: Path) -> None:
    """Pre-retomar runs lack the ``args`` block; ``listar`` shouldn't
    crash on them, just show ``None`` for the missing fields."""
    saida = tmp_path / "old"
    _write_state(saida)  # no args=

    s = summarize_run(saida)

    assert s.status == RunStatus.FINISHED
    assert s.rotulo is None
    assert s.classe is None


def test_summarize_run_tolerates_corrupt_state_json(tmp_path: Path) -> None:
    """A torn snapshot (rare but possible if a crash interrupts an
    atomic-replace mid-rename) shouldn't break listing."""
    saida = tmp_path / "broken"
    saida.mkdir()
    (saida / "executar.state.json").write_text("{not json", encoding="utf-8")

    s = summarize_run(saida)

    # File exists but isn't parseable → treat as if no state at all.
    assert s.status == RunStatus.UNKNOWN


def test_summarize_run_sharded_layout_uses_shards_pids(tmp_path: Path) -> None:
    saida = tmp_path / "sharded"
    _write_state(saida)
    (saida / "shards.pids").write_text(
        f"{os.getpid()}\n{DEAD_PID}\n", encoding="utf-8"
    )

    s = summarize_run(saida)

    assert s.pids == [os.getpid(), DEAD_PID]
    # At least one alive → still running. Mirrors ``parar``'s logic of
    # signalling every PID — the run is "running" as long as any shard is.
    assert s.status == RunStatus.RUNNING


def test_summarize_run_sharded_preferred_over_mono(tmp_path: Path) -> None:
    """When both files exist (a misconfigured run, or a transitional
    state), ``shards.pids`` wins — same precedence as
    ``judex.cli._read_pids``. Signalling only the mono pid in a
    sharded layout would orphan the other N-1 children."""
    saida = tmp_path / "both"
    _write_state(saida)
    (saida / "executar.pid").write_text(f"{DEAD_PID}\n", encoding="utf-8")
    (saida / "shards.pids").write_text(f"{os.getpid()}\n", encoding="utf-8")

    s = summarize_run(saida)

    assert s.pids == [os.getpid()]
    assert s.status == RunStatus.RUNNING


def test_list_runs_returns_empty_for_missing_root(tmp_path: Path) -> None:
    assert list_runs(tmp_path / "ghost") == []


def test_list_runs_returns_empty_for_empty_root(tmp_path: Path) -> None:
    (tmp_path / "empty").mkdir()
    assert list_runs(tmp_path / "empty") == []


def test_list_runs_sorts_newest_first_by_mtime(tmp_path: Path) -> None:
    older = tmp_path / "older"
    newer = tmp_path / "newer"
    _write_state(older)
    time.sleep(0.01)
    _write_state(newer)

    result = list_runs(tmp_path)

    assert [r.saida.name for r in result] == ["newer", "older"]


def test_list_runs_skips_files_at_root(tmp_path: Path) -> None:
    """Loose files (a stray log, a script) under the runs root shouldn't
    show up as zero-status entries — only directories are run dirs."""
    _write_state(tmp_path / "real-run")
    (tmp_path / "stray.log").write_text("not a run\n", encoding="utf-8")

    result = list_runs(tmp_path)

    assert [r.saida.name for r in result] == ["real-run"]


def test_prune_stale_pid_files_removes_only_stale(tmp_path: Path) -> None:
    live = tmp_path / "live"
    stale = tmp_path / "stale"
    done = tmp_path / "done"
    _write_state(live)
    _write_state(stale)
    _write_state(done)
    (live / "executar.pid").write_text(f"{os.getpid()}\n", encoding="utf-8")
    (stale / "executar.pid").write_text(f"{DEAD_PID}\n", encoding="utf-8")

    removed = prune_stale_pid_files(tmp_path)

    assert removed == [stale / "executar.pid"]
    assert (live / "executar.pid").exists()  # untouched
    assert not (stale / "executar.pid").exists()  # cleaned


def test_prune_stale_pid_files_handles_sharded_layout(tmp_path: Path) -> None:
    """A sharded run with a dead shards.pids gets cleaned just like a
    mono run with a dead executar.pid."""
    stale = tmp_path / "stale-sharded"
    _write_state(stale)
    (stale / "shards.pids").write_text(
        f"{DEAD_PID}\n{DEAD_PID + 1}\n", encoding="utf-8"
    )

    removed = prune_stale_pid_files(tmp_path)

    assert removed == [stale / "shards.pids"]
    assert not (stale / "shards.pids").exists()


def test_prune_stale_pid_files_returns_empty_when_nothing_to_prune(tmp_path: Path) -> None:
    live = tmp_path / "live"
    _write_state(live)
    (live / "executar.pid").write_text(f"{os.getpid()}\n", encoding="utf-8")

    assert prune_stale_pid_files(tmp_path) == []


# ---------------------------------------------------------------------------
# n_targets + elapsed time (the `listar` enrichment columns)


def test_summarize_run_counts_cases_as_n_targets(tmp_path: Path) -> None:
    """``listar`` shows ``alvos`` so the operator can size a run at a
    glance. It comes from ``len(state.cases)`` — the same source of
    truth ``executar`` uses internally."""
    saida = tmp_path / "with-cases"
    _write_state(saida, cases={"HC:1": {}, "HC:2": {}, "HC:3": {}})

    assert summarize_run(saida).n_targets == 3


def test_summarize_run_n_targets_is_none_when_state_missing(tmp_path: Path) -> None:
    saida = tmp_path / "blank"
    saida.mkdir()

    assert summarize_run(saida).n_targets is None


def test_elapsed_seconds_for_finished_run_uses_snapshot_minus_started(
    tmp_path: Path,
) -> None:
    saida = tmp_path / "done"
    _write_state(
        saida,
        started_at="2026-05-11T19:00:00+00:00",
        snapshot_at="2026-05-11T19:30:00+00:00",
    )
    s = summarize_run(saida)

    # 30 minutes.
    assert s.elapsed_seconds() == 1800.0


def test_elapsed_seconds_tolerates_z_suffix(tmp_path: Path) -> None:
    """The state journal writes both ``+00:00`` and ``Z`` suffixes
    depending on which snapshot codepath fired; both must parse."""
    saida = tmp_path / "z-suffix"
    _write_state(
        saida,
        started_at="2026-05-11T19:00:00Z",
        snapshot_at="2026-05-11T19:05:00Z",
    )

    assert summarize_run(saida).elapsed_seconds() == 300.0


def test_elapsed_seconds_returns_none_when_started_at_missing(tmp_path: Path) -> None:
    saida = tmp_path / "no-start"
    _write_state(saida)
    # _write_state seeds started_at; clear it.
    import json
    p = saida / "executar.state.json"
    data = json.loads(p.read_text())
    del data["started_at"]
    p.write_text(json.dumps(data))

    assert summarize_run(saida).elapsed_seconds() is None


def test_format_elapsed_buckets() -> None:
    """``listar`` magnitude buckets — same as ``relatar``'s ``_fmt_wall``."""
    from judex.pipeline.run_index import format_elapsed

    assert format_elapsed(None) == "—"
    assert format_elapsed(8) == "8s"
    assert format_elapsed(75) == "1m 15s"
    assert format_elapsed(3725) == "1h 2m"


# ---------------------------------------------------------------------------
# Archive scanning + label resolution


def test_list_runs_include_archive_merges_both_roots(tmp_path: Path) -> None:
    """``--incluir-arquivo`` should walk both ``runs/active/`` and the
    sibling ``runs/archive/`` and return one mtime-sorted list."""
    active = tmp_path / "active"
    archive = tmp_path / "archive"
    _write_state(active / "live")
    _write_state(archive / "old")

    result = list_runs(active, include_archive=True)

    names = {r.saida.name for r in result}
    assert names == {"live", "old"}


def test_list_runs_no_archive_flag_keeps_scope_tight(tmp_path: Path) -> None:
    active = tmp_path / "active"
    archive = tmp_path / "archive"
    _write_state(active / "live")
    _write_state(archive / "old")

    result = list_runs(active)

    assert {r.saida.name for r in result} == {"live"}


def test_find_by_label_exact_match(tmp_path: Path, monkeypatch) -> None:
    """``find_by_label("hc2021")`` finds the run whose ``args.rotulo``
    equals that string. This is what powers ``judex parar hc2021``."""
    active = tmp_path / "runs" / "active"
    _write_state(active / "anything", args={"rotulo": "hc2021-fillin"})
    _write_state(active / "other", args={"rotulo": "hc2024-fillin"})

    monkeypatch.chdir(tmp_path)
    from judex.pipeline.run_index import find_by_label

    matches = find_by_label("hc2021-fillin")

    assert len(matches) == 1
    assert matches[0].saida.name == "anything"


def test_find_by_label_matches_directory_name(tmp_path: Path, monkeypatch) -> None:
    """When ``args.rotulo`` is missing (pre-retomar runs), label lookup
    falls back to the directory name. That's the ergonomic affordance
    that keeps legacy runs addressable by name too."""
    active = tmp_path / "runs" / "active"
    _write_state(active / "hc2020-sharded")  # no args block

    monkeypatch.chdir(tmp_path)
    from judex.pipeline.run_index import find_by_label

    matches = find_by_label("hc2020-sharded")

    assert [m.saida.name for m in matches] == ["hc2020-sharded"]


def test_label_candidates_filters_by_prefix(tmp_path: Path, monkeypatch) -> None:
    """``judex parar hc20<tab>`` should expand to hc2020-… / hc2021-…
    but not 2026-05-02-validation. Tab-completion contract."""
    active = tmp_path / "runs" / "active"
    _write_state(active / "hc2020-sharded", args={"rotulo": "hc2020-sharded"})
    _write_state(active / "hc2021-fillin", args={"rotulo": "hc2021-fillin"})
    _write_state(active / "2026-05-02-validation")

    monkeypatch.chdir(tmp_path)
    from judex.pipeline.run_index import label_candidates

    out = label_candidates("hc20")

    assert set(out) == {"hc2020-sharded", "hc2021-fillin"}
    assert "2026-05-02-validation" not in out
