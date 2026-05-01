"""Tests for judex.utils.unallocated_pids — aggregation across sweeps."""

from __future__ import annotations

import json
from pathlib import Path

from judex.utils.unallocated_pids import (
    collect_observations,
    load_unallocated_pids,
    write_unallocated_pid_files,
)


def _write_state(path: Path, entries: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    state = {f"{e['classe']}_{e['processo']}": e for e in entries}
    path.write_text(json.dumps(state))


def _unalloc(classe: str, processo: int) -> dict:
    return {
        "classe": classe,
        "processo": processo,
        "status": "unallocated",
        "http_status": 200,
        "body_head": "",
    }


def _ok(classe: str, processo: int) -> dict:
    return {"classe": classe, "processo": processo, "status": "ok"}


def _fail_proxy_noise(classe: str, processo: int) -> dict:
    """A non-empty body_head NoIncidente that lands in the fail bucket."""
    return {
        "classe": classe,
        "processo": processo,
        "status": "fail",
        "error_type": "NoIncidente",
        "http_status": 200,
        "body_head": "SomeWeirdProxyPage",
    }


def _error(classe: str, processo: int) -> dict:
    return {
        "classe": classe,
        "processo": processo,
        "status": "error",
        "error_type": "HTTPError",
        "http_status": 403,
    }


def test_only_unallocated_status_counted(tmp_path: Path) -> None:
    """Only status=unallocated produces observations; ok/fail/error are ignored."""
    _write_state(tmp_path / "sweep-a" / "sweep.state.json", [
        _ok("HC", 100),
        _error("HC", 101),
        _fail_proxy_noise("HC", 102),
        _unalloc("HC", 103),
    ])
    obs = collect_observations([tmp_path], classe="HC")
    assert set(obs.keys()) == {103}
    assert len(obs[103]) == 1


def test_multi_sweep_aggregation(tmp_path: Path) -> None:
    """Two independent sweeps observing the same pid → two observations."""
    _write_state(tmp_path / "sweep-a" / "sweep.state.json", [_unalloc("HC", 400)])
    _write_state(tmp_path / "sweep-b" / "sweep.state.json", [_unalloc("HC", 400)])
    obs = collect_observations([tmp_path], classe="HC")
    assert len(obs[400]) == 2


def test_classe_filter(tmp_path: Path) -> None:
    """Observations from other classes are ignored."""
    _write_state(tmp_path / "sweep-a" / "sweep.state.json", [
        _unalloc("HC", 500),
        _unalloc("ADI", 501),
    ])
    obs = collect_observations([tmp_path], classe="HC")
    assert set(obs.keys()) == {500}


def test_write_promotes_confirmed_to_txt(tmp_path: Path) -> None:
    """≥2 observations → pid lands in HC.txt (sorted)."""
    _write_state(tmp_path / "sweep-a" / "sweep.state.json", [
        _unalloc("HC", 700), _unalloc("HC", 600),
    ])
    _write_state(tmp_path / "sweep-b" / "sweep.state.json", [
        _unalloc("HC", 700), _unalloc("HC", 600),
    ])
    obs = collect_observations([tmp_path], classe="HC")
    txt, tsv = write_unallocated_pid_files(
        obs, out_dir=tmp_path / "out", classe="HC", min_observations=2,
    )
    assert txt.read_text().splitlines() == ["600", "700"]
    rows = tsv.read_text().splitlines()
    assert rows[0] == "processo_id\tn_observations"
    assert rows[1:] == ["600\t2", "700\t2"]


def test_single_observation_stays_candidate(tmp_path: Path) -> None:
    """One observation → not in HC.txt; still listed in candidates.tsv."""
    _write_state(tmp_path / "sweep-a" / "sweep.state.json", [_unalloc("HC", 800)])
    obs = collect_observations([tmp_path], classe="HC")
    txt, tsv = write_unallocated_pid_files(
        obs, out_dir=tmp_path / "out", classe="HC", min_observations=2,
    )
    assert txt.read_text() == ""
    assert "800\t1" in tsv.read_text()


def test_empty_runs_tree(tmp_path: Path) -> None:
    """No sweep.state.json anywhere → empty txt + tsv header only."""
    obs = collect_observations([tmp_path], classe="HC")
    txt, tsv = write_unallocated_pid_files(
        obs, out_dir=tmp_path / "out", classe="HC", min_observations=2,
    )
    assert txt.read_text() == ""
    assert tsv.read_text() == "processo_id\tn_observations\n"


def test_malformed_state_file_skipped(tmp_path: Path) -> None:
    """A corrupt sweep.state.json doesn't crash the aggregator."""
    bad = tmp_path / "sweep-bad" / "sweep.state.json"
    bad.parent.mkdir(parents=True)
    bad.write_text("not json {[")
    _write_state(tmp_path / "sweep-a" / "sweep.state.json", [_unalloc("HC", 1000)])
    obs = collect_observations([tmp_path], classe="HC")
    assert set(obs.keys()) == {1000}


def test_load_unallocated_pids_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "HC.txt"
    path.write_text("100\n200\n300\n")
    assert load_unallocated_pids(path) == {100, 200, 300}


def test_load_unallocated_pids_missing_file(tmp_path: Path) -> None:
    assert load_unallocated_pids(tmp_path / "nope.txt") == set()


def test_load_unallocated_pids_ignores_blanks_and_comments(tmp_path: Path) -> None:
    path = tmp_path / "HC.txt"
    path.write_text("# header\n100\n\n200\n")
    assert load_unallocated_pids(path) == {100, 200}
