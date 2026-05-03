"""Unit tests for ``scripts/backfill_n_pecas.py``.

Covers the pure helpers (``collect_pending_case_keys``,
``compute_n_pecas``, ``backfill``, ``atomic_write_json``) and the
end-to-end merge with ``follow_run.aggregate_state`` — the whole
point of the script is to make the live aggregator render
``pecas N/total (pct%)`` on a legacy run, so the integration is the
load-bearing assertion.
"""

from __future__ import annotations

import json
from pathlib import Path

from scripts.backfill_n_pecas import (
    atomic_write_json,
    backfill,
    collect_pending_case_keys,
    compute_n_pecas,
)
from scripts.follow_run import aggregate_state


def _make_state(cases: dict) -> dict:
    return {
        "schema_version": 2,
        "started_at": "2026-05-03T00:00:00+00:00",
        "snapshot_at": "2026-05-03T01:00:00+00:00",
        "cases": cases,
    }


def _ok_case(*, n_pecas: int | None = None) -> dict:
    """meta=ok case in the legacy or new shape — n_pecas absent
    means "legacy run, needs backfill"."""
    meta: dict = {
        "status": "ok",
        "ts": "2026-05-03T00:01:00+00:00",
        "error": None,
        "retry_count": 0,
    }
    if n_pecas is not None:
        meta["n_pecas"] = n_pecas
    return {"fetch_meta": meta, "fetch_bytes": {}, "extract_text": {}}


def _write_source_json(
    source_root: Path, classe: str, pid: int, andamento_urls: list[str],
) -> None:
    """Minimal source JSON with N andamento PDF URLs — those are
    surface-1 peca targets and survive ``filter_substantive`` when
    the doc_type is substantive (``DECISÃO MONOCRÁTICA`` here)."""
    out_dir = source_root / classe
    out_dir.mkdir(parents=True, exist_ok=True)
    rec = {
        "classe": classe,
        "processo_id": pid,
        "andamentos": [
            {
                "ts_iso": "2026-05-03T00:00:00+00:00",
                "tipo": "DECISÃO MONOCRÁTICA",
                "link": {"url": url, "tipo": "DECISÃO MONOCRÁTICA"},
            }
            for url in andamento_urls
        ],
    }
    path = out_dir / f"judex-mini_{classe}_{pid}-{pid}.json"
    path.write_text(json.dumps(rec), encoding="utf-8")


# --- collect_pending_case_keys ------------------------------------------------


def test_collect_pending_skips_cases_already_carrying_n_pecas(tmp_path: Path) -> None:
    """A shard launched with new code already populates ``n_pecas``;
    those cases are not legacy and must NOT be revisited — backfill
    is a one-way fix-up, not a recompute."""
    sa = tmp_path / "shard-a"; sa.mkdir()
    (sa / "executar.state.json").write_text(json.dumps(_make_state({
        "HC-100": _ok_case(),                  # legacy
        "HC-99":  _ok_case(n_pecas=4),         # new, already done
    })))

    keys = collect_pending_case_keys(tmp_path)

    assert keys == {"HC-100"}


def test_collect_pending_skips_non_ok_meta(tmp_path: Path) -> None:
    """Non-ok meta cases (unallocated_pid, http_error) emitted zero
    successors at scrape time — there's no n_pecas to backfill,
    AND they're naturally filtered from pecas_total since the
    aggregator only counts meta=ok records."""
    sa = tmp_path / "shard-a"; sa.mkdir()
    (sa / "executar.state.json").write_text(json.dumps(_make_state({
        "HC-100": _ok_case(),
        "HC-99":  {"fetch_meta": {"status": "unallocated_pid"},
                   "fetch_bytes": {}, "extract_text": {}},
        "HC-98":  {"fetch_meta": {"status": "http_error"},
                   "fetch_bytes": {}, "extract_text": {}},
    })))

    keys = collect_pending_case_keys(tmp_path)

    assert keys == {"HC-100"}


def test_collect_pending_unions_across_shards(tmp_path: Path) -> None:
    """Round-robin shard split assigns different cases per shard;
    the cluster-wide sidecar must cover every meta=ok case anywhere."""
    sa = tmp_path / "shard-a"; sa.mkdir()
    (sa / "executar.state.json").write_text(json.dumps(_make_state({
        "HC-100": _ok_case(), "HC-99": _ok_case(),
    })))
    sb = tmp_path / "shard-b"; sb.mkdir()
    (sb / "executar.state.json").write_text(json.dumps(_make_state({
        "HC-50": _ok_case(),
    })))

    keys = collect_pending_case_keys(tmp_path)

    assert keys == {"HC-100", "HC-99", "HC-50"}


# --- compute_n_pecas ----------------------------------------------------------


def test_compute_n_pecas_counts_substantive_andamento_urls(tmp_path: Path) -> None:
    """Replays handler's pipeline: walk surfaces → filter_substantive
    → URL-dedup → count. Three distinct substantive-tagged URLs
    yields n_pecas=3."""
    source_root = tmp_path / "source"
    _write_source_json(source_root, "HC", 100, [
        "https://stf.test/a.pdf",
        "https://stf.test/b.pdf",
        "https://stf.test/c.pdf",
    ])

    n = compute_n_pecas("HC-100", source_root)

    assert n == 3


def test_compute_n_pecas_dedupes_repeated_urls(tmp_path: Path) -> None:
    """Same peca URL on multiple andamentos (rare but seen on apenso
    flows) collapses to 1, matching the handler's URL-dedup at fan-out
    time. Without this, pecas_total over-counts and the % under-reads."""
    source_root = tmp_path / "source"
    _write_source_json(source_root, "HC", 100, [
        "https://stf.test/dup.pdf",
        "https://stf.test/dup.pdf",
        "https://stf.test/other.pdf",
    ])

    n = compute_n_pecas("HC-100", source_root)

    assert n == 2


def test_compute_n_pecas_returns_none_when_source_missing(tmp_path: Path) -> None:
    """Hard-kill resume edge: meta=ok in state.json but the source
    JSON write didn't durably land. Backfill skips rather than
    fabricate a zero — the aggregator then keeps falling back to
    count-only for that case (null pecas_total cluster-wide)."""
    source_root = tmp_path / "source"
    source_root.mkdir()

    n = compute_n_pecas("HC-100", source_root)

    assert n is None


def test_compute_n_pecas_returns_none_for_malformed_case_key(tmp_path: Path) -> None:
    """``HC-100`` parses; ``random-junk`` does not — return None
    rather than crash. Defensive against future case-key shape changes."""
    source_root = tmp_path / "source"
    source_root.mkdir()

    assert compute_n_pecas("not-a-pid", source_root) is None


# --- backfill (top-level) -----------------------------------------------------


def test_backfill_walks_state_and_resolves_via_source(tmp_path: Path) -> None:
    """End-to-end: states + source JSONs in, ``{case_key: n_pecas}``
    map out. The map is exactly what the sidecar file persists."""
    run_dir = tmp_path / "run"
    sa = run_dir / "shard-a"; sa.mkdir(parents=True)
    (sa / "executar.state.json").write_text(json.dumps(_make_state({
        "HC-100": _ok_case(), "HC-99": _ok_case(),
    })))

    source_root = tmp_path / "source"
    _write_source_json(source_root, "HC", 100, [
        "https://stf.test/a.pdf", "https://stf.test/b.pdf",
    ])
    _write_source_json(source_root, "HC", 99, [
        "https://stf.test/c.pdf",
    ])

    payload = backfill(run_dir, source_root, progress=False)

    assert payload == {"HC-100": 2, "HC-99": 1}


def test_backfill_skips_unresolvable_cases(tmp_path: Path) -> None:
    """A case with no source JSON simply doesn't enter the sidecar.
    The aggregator's fallback chain (state → sidecar → None) then
    sees None for that case → cluster pecas_total stays None →
    renderer drops the ratio. Better than a wrong number."""
    run_dir = tmp_path / "run"
    sa = run_dir / "shard-a"; sa.mkdir(parents=True)
    (sa / "executar.state.json").write_text(json.dumps(_make_state({
        "HC-100": _ok_case(),
        "HC-999": _ok_case(),  # source JSON missing
    })))

    source_root = tmp_path / "source"
    _write_source_json(source_root, "HC", 100, ["https://stf.test/a.pdf"])

    payload = backfill(run_dir, source_root, progress=False)

    assert payload == {"HC-100": 1}


# --- atomic_write_json --------------------------------------------------------


def test_atomic_write_json_replaces_existing_file(tmp_path: Path) -> None:
    """Re-running backfill must overwrite the previous sidecar atomically
    — no half-written state visible to a concurrent aggregator read."""
    sidecar = tmp_path / "n_pecas.json"
    sidecar.write_text('{"HC-1": 1}')

    atomic_write_json(sidecar, {"HC-1": 5, "HC-2": 7})

    assert json.loads(sidecar.read_text()) == {"HC-1": 5, "HC-2": 7}


# --- end-to-end with aggregate_state -----------------------------------------


def test_aggregate_state_merges_sidecar_to_compute_pecas_total(tmp_path: Path) -> None:
    """The whole point of the script: a legacy run whose state.json
    lacks ``n_pecas`` should, AFTER backfill, produce a non-None
    pecas_total in ``aggregate_state`` so the renderer can emit
    ``pecas N/total (pct%)``."""
    run_dir = tmp_path
    sa = run_dir / "shard-a"; sa.mkdir()
    (sa / "executar.state.json").write_text(json.dumps(_make_state({
        "HC-100": {
            "fetch_meta": {"status": "ok"},  # no n_pecas
            "fetch_bytes": {"u1": {"status": "ok"}, "u2": {"status": "empty"}},
            "extract_text": {"u1": {"status": "ok"}},
        },
        "HC-99": {
            "fetch_meta": {"status": "ok"},  # no n_pecas
            "fetch_bytes": {},
            "extract_text": {},
        },
    })))

    # Sanity: pre-backfill, pecas_total is None.
    pre = aggregate_state(run_dir)
    assert pre["pecas_total"] is None

    # Write the sidecar (simulating the script's output).
    (run_dir / "n_pecas.json").write_text(json.dumps({"HC-100": 2, "HC-99": 1}))

    post = aggregate_state(run_dir)
    assert post["pecas_total"] == 3
    # Other agg numbers untouched by the merge.
    assert post["pecas"]["ok"] == 1
    assert post["text_total"] == 1


def test_aggregate_state_falls_back_to_none_for_partial_sidecar(tmp_path: Path) -> None:
    """If the sidecar covers some but not all meta=ok cases (e.g.
    backfill ran while a shard was still scraping new cases), ANY
    missing case poisons the cluster total. Renderer drops the ratio
    rather than under-count. Re-running backfill picks up the new
    cases on next tick."""
    run_dir = tmp_path
    sa = run_dir / "shard-a"; sa.mkdir()
    (sa / "executar.state.json").write_text(json.dumps(_make_state({
        "HC-100": _ok_case(),  # in sidecar
        "HC-50":  _ok_case(),  # NOT in sidecar
    })))
    (run_dir / "n_pecas.json").write_text(json.dumps({"HC-100": 3}))

    agg = aggregate_state(run_dir)

    assert agg["pecas_total"] is None


def test_aggregate_state_prefers_state_n_pecas_over_sidecar(tmp_path: Path) -> None:
    """If both are present, the live state wins — it's authoritative
    (came from the actual handler at scrape time, not a re-read of
    the source JSON which may have been partially rewritten on a
    re-scrape). Sidecar is strictly a backfill for missing values."""
    run_dir = tmp_path
    sa = run_dir / "shard-a"; sa.mkdir()
    (sa / "executar.state.json").write_text(json.dumps(_make_state({
        "HC-100": _ok_case(n_pecas=5),
    })))
    (run_dir / "n_pecas.json").write_text(json.dumps({"HC-100": 999}))

    agg = aggregate_state(run_dir)

    assert agg["pecas_total"] == 5  # state wins


def test_aggregate_state_tolerates_corrupt_sidecar(tmp_path: Path) -> None:
    """A truncated sidecar (rare; only if backfill was killed
    mid-write — but ``atomic_write_json`` makes that nearly
    impossible) is silently treated as absent, not crashy."""
    run_dir = tmp_path
    sa = run_dir / "shard-a"; sa.mkdir()
    (sa / "executar.state.json").write_text(json.dumps(_make_state({
        "HC-100": _ok_case(n_pecas=3),
    })))
    (run_dir / "n_pecas.json").write_text("{this is not json")

    agg = aggregate_state(run_dir)

    assert agg["pecas_total"] == 3  # sidecar ignored; state still works
