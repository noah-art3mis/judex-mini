"""Tests for judex.utils.dead_ids — NoIncidente aggregation across sweeps."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from judex.utils.dead_ids import (
    DeadObservation,
    collect_observations,
    load_dead_ids,
    write_dead_id_files,
)


def _write_state(
    path: Path,
    entries: list[dict],
) -> None:
    """Write a fake sweep.state.json at `path` with the given AttemptRecord dicts."""
    path.parent.mkdir(parents=True, exist_ok=True)
    state = {f"{e['classe']}_{e['processo']}": e for e in entries}
    path.write_text(json.dumps(state))


def _dead(classe: str, processo: int, body_head: str = "") -> dict:
    return {
        "classe": classe,
        "processo": processo,
        "status": "fail",
        "error_type": "NoIncidente",
        "http_status": 200,
        "body_head": body_head,
    }


def _ok(classe: str, processo: int) -> dict:
    return {
        "classe": classe,
        "processo": processo,
        "status": "ok",
        "error_type": None,
        "body_head": None,
    }


def _error(classe: str, processo: int) -> dict:
    return {
        "classe": classe,
        "processo": processo,
        "status": "error",
        "error_type": "HTTPError",
        "http_status": 403,
        "body_head": None,
    }


def test_ok_and_error_not_counted(tmp_path: Path) -> None:
    """status=ok and status=error must not produce DeadObservations."""
    _write_state(tmp_path / "sweep-a" / "sweep.state.json", [
        _ok("HC", 100),
        _error("HC", 101),
    ])
    obs = collect_observations([tmp_path], classe="HC")
    assert obs == {}


def test_single_noincidente_observation(tmp_path: Path) -> None:
    """One NoIncidente observation → pid in observations with one entry."""
    _write_state(tmp_path / "sweep-a" / "sweep.state.json", [_dead("HC", 200)])
    obs = collect_observations([tmp_path], classe="HC")
    assert set(obs.keys()) == {200}
    assert len(obs[200]) == 1
    assert obs[200][0].body_head_empty is True


def test_non_empty_body_head_marks_obs_weak(tmp_path: Path) -> None:
    """body_head != '' → observation exists but body_head_empty=False."""
    _write_state(tmp_path / "sweep-a" / "sweep.state.json", [
        _dead("HC", 300, body_head="SomeWeirdProxyPage"),
    ])
    obs = collect_observations([tmp_path], classe="HC")
    assert len(obs[300]) == 1
    assert obs[300][0].body_head_empty is False


def test_multi_sweep_aggregation(tmp_path: Path) -> None:
    """Two independent sweep dirs observing same pid → two observations."""
    _write_state(tmp_path / "sweep-a" / "sweep.state.json", [_dead("HC", 400)])
    _write_state(tmp_path / "sweep-b" / "sweep.state.json", [_dead("HC", 400)])
    obs = collect_observations([tmp_path], classe="HC")
    assert len(obs[400]) == 2


def test_classe_filter(tmp_path: Path) -> None:
    """Observations from other classes are ignored."""
    _write_state(tmp_path / "sweep-a" / "sweep.state.json", [
        _dead("HC", 500),
        _dead("ADI", 501),
    ])
    obs = collect_observations([tmp_path], classe="HC")
    assert set(obs.keys()) == {500}


def test_write_promotes_confirmed_to_txt(tmp_path: Path) -> None:
    """≥2 observations with empty body → pid lands in HC.txt (sorted)."""
    _write_state(tmp_path / "sweep-a" / "sweep.state.json", [
        _dead("HC", 700),
        _dead("HC", 600),  # out of order — must sort
    ])
    _write_state(tmp_path / "sweep-b" / "sweep.state.json", [
        _dead("HC", 700),
        _dead("HC", 600),
    ])
    obs = collect_observations([tmp_path], classe="HC")
    out = tmp_path / "out"
    txt, tsv = write_dead_id_files(obs, out_dir=out, classe="HC", min_observations=2)
    assert txt.read_text().splitlines() == ["600", "700"]
    # tsv has header + one row per observed pid (sorted)
    rows = tsv.read_text().splitlines()
    assert rows[0] == "processo_id\tn_observations\tn_empty_body"
    assert rows[1:] == ["600\t2\t2", "700\t2\t2"]


def test_single_observation_stays_candidate(tmp_path: Path) -> None:
    """Single NoIncidente stays in candidates.tsv, NOT in HC.txt."""
    _write_state(tmp_path / "sweep-a" / "sweep.state.json", [_dead("HC", 800)])
    obs = collect_observations([tmp_path], classe="HC")
    out = tmp_path / "out"
    txt, tsv = write_dead_id_files(obs, out_dir=out, classe="HC", min_observations=2)
    assert txt.read_text() == ""
    assert "800\t1\t1" in tsv.read_text()


def test_nonempty_body_blocks_confirmation(tmp_path: Path) -> None:
    """Two NoIncidente observations but one non-empty body → stays candidate."""
    _write_state(tmp_path / "sweep-a" / "sweep.state.json", [_dead("HC", 900)])
    _write_state(tmp_path / "sweep-b" / "sweep.state.json", [
        _dead("HC", 900, body_head="SoftBlockPage"),
    ])
    obs = collect_observations([tmp_path], classe="HC")
    out = tmp_path / "out"
    txt, tsv = write_dead_id_files(obs, out_dir=out, classe="HC", min_observations=2)
    assert txt.read_text() == ""
    assert "900\t2\t1" in tsv.read_text()


def test_empty_runs_tree(tmp_path: Path) -> None:
    """No sweep.state.json files anywhere → empty txt + tsv header only."""
    obs = collect_observations([tmp_path], classe="HC")
    out = tmp_path / "out"
    txt, tsv = write_dead_id_files(obs, out_dir=out, classe="HC", min_observations=2)
    assert txt.read_text() == ""
    assert tsv.read_text() == "processo_id\tn_observations\tn_empty_body\n"


def test_malformed_state_file_skipped(tmp_path: Path) -> None:
    """A corrupt sweep.state.json doesn't crash the aggregator."""
    bad = tmp_path / "sweep-bad" / "sweep.state.json"
    bad.parent.mkdir(parents=True)
    bad.write_text("not json {[")
    _write_state(tmp_path / "sweep-a" / "sweep.state.json", [_dead("HC", 1000)])
    obs = collect_observations([tmp_path], classe="HC")
    assert set(obs.keys()) == {1000}


def test_load_dead_ids_roundtrip(tmp_path: Path) -> None:
    """load_dead_ids reads the sorted pid-per-line format."""
    path = tmp_path / "HC.txt"
    path.write_text("100\n200\n300\n")
    assert load_dead_ids(path) == {100, 200, 300}


def test_load_dead_ids_missing_file(tmp_path: Path) -> None:
    """Missing file → empty set (no crash)."""
    assert load_dead_ids(tmp_path / "nope.txt") == set()


def test_load_dead_ids_ignores_blanks_and_comments(tmp_path: Path) -> None:
    path = tmp_path / "HC.txt"
    path.write_text("# header\n100\n\n200\n")
    assert load_dead_ids(path) == {100, 200}
