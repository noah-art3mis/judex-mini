"""Unit tests for `scripts/probe_sharded.py`.

Behavior-level coverage of the pure probe() data collector + the
`judex probe` CLI plumbing. Rendering is excluded — rich output is
visual; regressions there are caught by eye, not by asserts.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from typer.testing import CliRunner

from judex.cli import app
from scripts.probe_sharded import probe, probe_shard


def _write_state(shard_dir: Path, records: list[dict]) -> None:
    shard_dir.mkdir(parents=True, exist_ok=True)
    state = {f"{r['classe']}_{r['processo']}": r for r in records}
    (shard_dir / "sweep.state.json").write_text(json.dumps(state))


def _record(pid: int, *, status: str = "ok", regime: str = "under_utilising",
            ts: str = "2026-04-20T10:00:00+00:00") -> dict:
    return {
        "ts": ts, "classe": "HC", "processo": pid, "attempt": 1,
        "wall_s": 5.0, "status": status, "error": None,
        "regime": regime,
    }


def test_probe_shard_counts_records_and_regimes(tmp_path: Path) -> None:
    shard = tmp_path / "shard-a"
    _write_state(shard, [
        _record(100, regime="warming"),
        _record(99, regime="under_utilising"),
        _record(98, regime="under_utilising"),
        _record(97, status="fail", regime="under_utilising"),
    ])

    st = probe_shard(shard, tmp_path)

    assert st.name == "shard-a"
    assert st.records == 4
    assert st.statuses["ok"] == 3
    assert st.statuses["fail"] == 1
    assert st.regimes["warming"] == 1
    assert st.regimes["under_utilising"] == 3
    assert st.min_processo == 97


def test_probe_shard_handles_missing_state_file(tmp_path: Path) -> None:
    """A shard with no sweep.state.json yet (just-launched) must not crash."""
    shard = tmp_path / "shard-a"
    shard.mkdir()

    st = probe_shard(shard, tmp_path)

    assert st.records == 0
    assert st.statuses == {}
    assert st.min_processo is None


def test_probe_shard_reads_target_from_shard_csv(tmp_path: Path) -> None:
    """When <out-root>/shards/*.shard.N.csv exists, target = row count."""
    shard = tmp_path / "shard-a"
    shard.mkdir()
    shards_dir = tmp_path / "shards"
    shards_dir.mkdir()
    # shard letter a → index 0
    (shards_dir / "foo.shard.0.csv").write_text(
        "classe,processo\nHC,100\nHC,99\nHC,98\n"
    )

    st = probe_shard(shard, tmp_path)

    assert st.target == 3


def test_probe_unions_across_shards(tmp_path: Path) -> None:
    _write_state(tmp_path / "shard-a", [_record(100), _record(99)])
    _write_state(tmp_path / "shard-b", [_record(50)])
    _write_state(tmp_path / "shard-c", [])  # empty state

    stats = probe(tmp_path)

    names = [s.name for s in stats]
    assert names == ["shard-a", "shard-b", "shard-c"]
    totals = {s.name: s.records for s in stats}
    assert totals == {"shard-a": 2, "shard-b": 1, "shard-c": 0}


def test_probe_computes_earliest_and_latest_ts(tmp_path: Path) -> None:
    """earliest_ts / latest_ts drive throughput + ETA — must be correct."""
    shard = tmp_path / "shard-a"
    _write_state(shard, [
        _record(100, ts="2026-04-20T10:00:00+00:00"),
        _record(99, ts="2026-04-20T10:01:30+00:00"),
        _record(98, ts="2026-04-20T10:00:45+00:00"),
    ])

    st = probe_shard(shard, tmp_path)

    assert st.earliest_ts == datetime(2026, 4, 20, 10, 0, 0, tzinfo=timezone.utc)
    assert st.latest_ts == datetime(2026, 4, 20, 10, 1, 30, tzinfo=timezone.utc)


def test_cli_probe_runs_once_and_prints_shard_name(tmp_path: Path) -> None:
    """`judex probe --out-root X` must invoke the underlying script and
    render every shard present in the output."""
    _write_state(tmp_path / "shard-a", [_record(100), _record(99)])
    _write_state(tmp_path / "shard-b", [_record(50)])

    result = CliRunner().invoke(app, ["probe", "--out-root", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert "shard-a" in result.output
    assert "shard-b" in result.output
    assert "TOTAL" in result.output


# --- baixar-pecas mode ----------------------------------------------------


def _write_pdfs_state(shard_dir: Path, records: list[dict]) -> None:
    """Mirror baixar-pecas: state file is `pdfs.state.json`, keyed by URL."""
    shard_dir.mkdir(parents=True, exist_ok=True)
    state = {r["url"]: r for r in records}
    (shard_dir / "pdfs.state.json").write_text(json.dumps(state))


def _pdf_record(
    pid: int, url: str, *,
    status: str = "ok",
    ts: str = "2026-04-21T20:00:00+00:00",
) -> dict:
    """Mirror baixar-pecas state-entry shape: URL-keyed, `processo_id`
    not `processo`, no `regime` field, has `doc_type` / `chars`."""
    return {
        "ts": ts, "url": url, "attempt": 1, "wall_s": 1.5,
        "status": status, "error": None, "error_type": None,
        "http_status": None, "extractor": "bytes", "chars": 50000,
        "processo_id": pid, "classe": "HC",
        "doc_type": "DECISÃO", "context": {},
    }


def test_probe_shard_detects_baixar_mode_from_pdfs_state(tmp_path: Path) -> None:
    """`pdfs.state.json` presence flips the shard into baixar mode.
    The driver-log `targets: N PDFs` line supplies the target — case-row
    counts from `<out-root>/shards/*.csv` would mix units (cases vs PDFs)
    and mislead at the cluster level."""
    shard = tmp_path / "shard-a"
    _write_pdfs_state(shard, [
        _pdf_record(100, "https://stf.test/a.pdf"),
        _pdf_record(100, "https://stf.test/b.pdf"),
        _pdf_record(99, "https://stf.test/c.pdf", status="fail"),
    ])
    (shard / "driver.log").write_text(
        "targets: 3154 PDFs across 779 processes (modo: csv ...)\n"
        "[1/3154] https://stf.test/a.pdf: ok (52370 bytes)\n"
    )

    st = probe_shard(shard, tmp_path)

    assert st.mode == "baixar"
    assert st.records == 3
    assert st.target == 3154  # PDF count from driver.log, not case count
    assert st.statuses["ok"] == 2
    assert st.statuses["fail"] == 1
    # No regime field on baixar entries — regimes counter stays empty.
    assert dict(st.regimes) == {}


def test_probe_shard_baixar_min_pid_uses_processo_id(tmp_path: Path) -> None:
    """Varrer entries use `processo`, baixar entries use `processo_id`.
    min_pid must work in both modes — otherwise the column is empty for
    baixar sweeps and the user loses a useful 'where is this shard
    chewing through pids' signal."""
    shard = tmp_path / "shard-a"
    _write_pdfs_state(shard, [
        _pdf_record(252920, "https://stf.test/x.pdf"),
        _pdf_record(252901, "https://stf.test/y.pdf"),
        _pdf_record(252915, "https://stf.test/z.pdf"),
    ])
    (shard / "driver.log").write_text("targets: 3 PDFs across 3 processes\n")

    st = probe_shard(shard, tmp_path)

    assert st.min_processo == 252901


def test_probe_shard_baixar_handles_missing_driver_log(tmp_path: Path) -> None:
    """If driver.log hasn't been written yet (fresh launch, race), target
    is None — the row still renders, just without a percentage."""
    shard = tmp_path / "shard-a"
    _write_pdfs_state(shard, [_pdf_record(100, "https://stf.test/a.pdf")])
    # No driver.log — pdfs.state.json present without it would be a
    # weird race but probe must still work.

    st = probe_shard(shard, tmp_path)

    assert st.mode == "baixar"
    assert st.records == 1
    assert st.target is None


# --- executar (unified pipeline) mode ------------------------------------


def _write_executar_state(shard_dir: Path, cases: dict) -> None:
    """Mirror executar.state.json: ``{schema_version, started_at, cases:
    {<key>: {fetch_meta, fetch_bytes, extract_text}}}``."""
    shard_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 2,
        "started_at": "2026-05-03T00:00:00+00:00",
        "snapshot_at": "2026-05-03T01:00:00+00:00",
        "cases": cases,
    }
    (shard_dir / "executar.state.json").write_text(json.dumps(payload))


def test_probe_shard_detects_executar_mode_and_walks_nested_cases(
    tmp_path: Path,
) -> None:
    """Pre-fix bug: probe iterated `data.values()` flatly, so an
    executar.state.json (`{schema_version, cases: {...}}`) yielded
    `records=3` (counting top-level non-case fields) and
    `statuses={}` (no top-level status field). Now: records = case
    count, per-stage counters populated."""
    shard = tmp_path / "shard-a"
    _write_executar_state(shard, {
        "HC-100": {
            "fetch_meta": {"status": "ok", "ts": "2026-05-03T00:01:00+00:00"},
            "fetch_bytes": {
                "u1": {"status": "ok", "ts": "2026-05-03T00:02:00+00:00"},
                "u2": {"status": "empty"},
            },
            "extract_text": {
                "u1": {"status": "ok", "extractor": "pypdf", "chars": 1200},
                "u2": {"status": "provider_error", "error": "timeout"},
            },
        },
        "HC-99": {
            "fetch_meta": {"status": "unallocated_pid"},
            "fetch_bytes": {},
            "extract_text": {},
        },
    })

    st = probe_shard(shard, tmp_path)

    assert st.mode == "executar"
    assert st.records == 2  # case count, not field count
    assert st.meta_counts["ok"] == 1
    assert st.meta_counts["unallocated_pid"] == 1
    assert st.bytes_counts["ok"] == 1
    assert st.bytes_counts["empty"] == 1
    assert st.text_counts["ok"] == 1
    assert st.text_counts["provider_error"] == 1


def test_probe_shard_executar_min_pid_parses_from_case_keys(tmp_path: Path) -> None:
    """Unified state has no per-record `processo` field — pid lives in
    the case-key string `<CLASSE>-<pid>`. Without parsing it out, the
    probe column shows `—` and the operator loses the 'where is this
    shard' signal that varrer/baixar both surface."""
    shard = tmp_path / "shard-a"
    _write_executar_state(shard, {
        "HC-252920": {"fetch_meta": {"status": "ok"}, "fetch_bytes": {}, "extract_text": {}},
        "HC-252901": {"fetch_meta": {"status": "ok"}, "fetch_bytes": {}, "extract_text": {}},
        "HC-252915": {"fetch_meta": {"status": "ok"}, "fetch_bytes": {}, "extract_text": {}},
    })

    st = probe_shard(shard, tmp_path)

    assert st.min_processo == 252901


def test_probe_shard_executar_uses_csv_target(tmp_path: Path) -> None:
    """Executar shares the case-row CSV target convention with varrer
    (one CSV row = one case = one meta task), so the percentage
    column is anchored on a denominator the operator already trusts."""
    shard = tmp_path / "shard-a"
    _write_executar_state(shard, {
        "HC-100": {"fetch_meta": {"status": "ok"}, "fetch_bytes": {}, "extract_text": {}},
    })
    shards_dir = tmp_path / "shards"
    shards_dir.mkdir()
    (shards_dir / "year.shard.0.csv").write_text(
        "classe,processo\nHC,100\nHC,99\nHC,98\nHC,97\nHC,96\n"
    )

    st = probe_shard(shard, tmp_path)

    assert st.target == 5
    assert st.records == 1  # only one case has a state entry yet


def test_probe_shard_executar_takes_precedence_over_varrer(tmp_path: Path) -> None:
    """If a stale `sweep.state.json` and a fresh `executar.state.json`
    coexist (e.g. operator re-launched on top of an old run dir), the
    executar file wins. Varrer's flat schema would mis-count the
    nested `cases` dict as one record otherwise."""
    shard = tmp_path / "shard-a"
    _write_executar_state(shard, {
        "HC-100": {"fetch_meta": {"status": "ok"}, "fetch_bytes": {}, "extract_text": {}},
    })
    # Stale flat-shape state from a prior varrer run:
    (shard / "sweep.state.json").write_text(json.dumps({
        "HC_999": {"status": "ok", "regime": "warming"},
    }))

    st = probe_shard(shard, tmp_path)

    assert st.mode == "executar"
    assert st.records == 1  # from cases dict, not the stale varrer file


def test_cli_probe_renders_executar_mode_with_stages_header(tmp_path: Path) -> None:
    """End-to-end smoke: a sharded executar run produces a table that
    visibly includes the per-stage counts and the renamed `stages`
    column header (vs `regimes` for varrer)."""
    _write_executar_state(tmp_path / "shard-a", {
        "HC-100": {
            "fetch_meta": {"status": "ok"},
            "fetch_bytes": {"u": {"status": "ok"}},
            "extract_text": {"u": {"status": "provider_error"}},
        },
    })
    _write_executar_state(tmp_path / "shard-b", {
        "HC-50": {
            "fetch_meta": {"status": "ok"},
            "fetch_bytes": {"v": {"status": "ok"}},
            "extract_text": {"v": {"status": "ok"}},
        },
    })

    result = CliRunner().invoke(app, ["probe", "--out-root", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert "shard-a" in result.output
    assert "shard-b" in result.output
    # Per-stage labels in the cell.
    assert "meta" in result.output
    assert "bytes" in result.output
    assert "text" in result.output
    # The error count must surface — that's the operator's main signal.
    assert "prov-err" in result.output
    # Column header reflects executar mode.
    assert "stages" in result.output


def test_cli_probe_errors_when_no_shards(tmp_path: Path) -> None:
    """An out-root with no shard-* subdirs must exit non-zero with a
    clear error — protects against silent misuse (typo in path, etc)."""
    empty = tmp_path / "empty"
    empty.mkdir()

    result = CliRunner().invoke(app, ["probe", "--out-root", str(empty)])

    assert result.exit_code != 0
    assert "no shard-*" in result.output
