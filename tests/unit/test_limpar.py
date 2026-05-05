"""Pin `judex limpar` discovery + classification + planning.

`judex limpar <run_dir>` walks a finished `judex executar` run dir,
reads ``executar.state.json`` (the canonical record) — *not*
``executar.errors.jsonl`` (which is a derived view that gets narrowed
when ``--retentar-de`` rewrites it). For every non-ok record in state
it emits an :class:`ErrorRow` and routes it through
:func:`classify_unified_error` plus a small override table for the
actionable terminals + the cap-burnt gate (transient at
``retry_count >= RETRY_CAP``).

This file pins:

- ``discover_run_dirs`` — mono vs sharded auto-detection on state.json.
- ``classify_residual`` — partitioning, including overrides + cap-burnt.
- ``plan_recoveries`` — one Spawn per source dir with at least one
  *actively retryable* (REPLAY) row; CAP_BURNT does not auto-dispatch.
- ``format_summary`` — the spec's one-line format.

Tests are *behavioural*: do these inputs produce these buckets? — not
ceremonial.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from judex.sweeps.limpar import (
    Bucket,
    classify_residual,
    discover_run_dirs,
    format_summary,
    plan_recoveries,
)


STATE_FILENAME = "executar.state.json"


def _write_state(
    path: Path,
    cases: dict[str, dict],
) -> None:
    """Write a minimal but schema-valid state.json fixture.

    ``cases`` is keyed by ``"HC-12345"`` and each value carries
    ``fetch_meta`` (optional dict), ``fetch_bytes`` (url→dict),
    ``extract_text`` (url→dict). Each leaf dict needs at minimum
    ``status`` + ``retry_count`` (the only fields limpar reads beyond
    the URL key).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 2,
        "started_at": "2026-05-03T00:00:00Z",
        "snapshot_at": "2026-05-03T00:00:01Z",
        "cases": cases,
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def _meta(status: str, retry_count: int = 0) -> dict:
    return {"status": status, "ts": "x", "error": None, "retry_count": retry_count}


def _bytes_entry(status: str, retry_count: int = 0) -> dict:
    return {"status": status, "ts": "x", "error": None, "doc_type": "X",
            "retry_count": retry_count}


def _text_entry(status: str, retry_count: int = 0) -> dict:
    return {"status": status, "ts": "x", "error": None, "extractor": "pypdf",
            "retry_count": retry_count}


# ----- discover_run_dirs ----------------------------------------------------


def test_discover_run_dirs_mono(tmp_path: Path) -> None:
    """Mono layout: state.json directly at the run-dir top."""
    _write_state(
        tmp_path / STATE_FILENAME,
        {"HC-1": {"fetch_meta": _meta("ok")}},
    )
    assert discover_run_dirs(tmp_path) == [tmp_path]


def test_discover_run_dirs_sharded(tmp_path: Path) -> None:
    """Sharded layout: shard-*/state.json, sorted by suffix."""
    for letter in ("a", "b", "c"):
        _write_state(
            tmp_path / f"shard-{letter}" / STATE_FILENAME,
            {"HC-1": {"fetch_meta": _meta("ok")}},
        )
    out = discover_run_dirs(tmp_path)
    assert out == [
        tmp_path / "shard-a",
        tmp_path / "shard-b",
        tmp_path / "shard-c",
    ]


def test_discover_run_dirs_empty(tmp_path: Path) -> None:
    """No state.json anywhere → empty list."""
    assert discover_run_dirs(tmp_path) == []


def test_discover_run_dirs_sharded_skips_dirs_without_state_file(
    tmp_path: Path,
) -> None:
    """A shard dir with no state.json is dropped."""
    _write_state(
        tmp_path / "shard-a" / STATE_FILENAME,
        {"HC-1": {"fetch_meta": _meta("ok")}},
    )
    (tmp_path / "shard-b").mkdir()  # no state file
    out = discover_run_dirs(tmp_path)
    assert out == [tmp_path / "shard-a"]


# ----- classify_residual ----------------------------------------------------


def test_classify_residual_partitions_by_kind_and_classifier_output(
    tmp_path: Path,
) -> None:
    """Each non-ok record routes to the bucket implied by
    (kind, classify_unified_error) plus retry_count gate."""
    cases = {
        # REPLAY: extract_text/provider_error at retry_count < cap
        "HC-1": {
            "fetch_meta": _meta("ok"),
            "fetch_bytes": {"u1": _bytes_entry("ok")},
            "extract_text": {"u1": _text_entry("provider_error", retry_count=1)},
        },
        # REPLAY: fetch_bytes/http_error
        "HC-2": {
            "fetch_meta": _meta("ok"),
            "fetch_bytes": {"u2": _bytes_entry("http_error", retry_count=0)},
        },
        # REPLAY: fetch_meta/http_error
        "HC-3": {"fetch_meta": _meta("http_error")},
        # PROVIDER_SWITCH override: extract_text/empty
        "HC-4": {
            "fetch_meta": _meta("ok"),
            "fetch_bytes": {"u4": _bytes_entry("ok")},
            "extract_text": {"u4": _text_entry("empty")},
        },
        # REFETCH_UPSTREAM: extract_text/no_bytes (cross_stage)
        "HC-5": {
            "fetch_meta": _meta("ok"),
            "fetch_bytes": {"u5": _bytes_entry("ok")},
            "extract_text": {"u5": _text_entry("no_bytes")},
        },
        # CONFIRMED_UNALLOCATED
        "HC-6": {"fetch_meta": _meta("unallocated_pid")},
        # TERMINAL_DROPPED: fetch_bytes/empty
        "HC-7": {
            "fetch_meta": _meta("ok"),
            "fetch_bytes": {"u7": _bytes_entry("empty")},
        },
        # CAP_BURNT: extract_text/provider_error at retry_count >= cap (=2)
        "HC-8": {
            "fetch_meta": _meta("ok"),
            "fetch_bytes": {"u8": _bytes_entry("ok")},
            "extract_text": {"u8": _text_entry("provider_error", retry_count=2)},
        },
        # CAP_BURNT: extract_text/provider_error at retry_count > cap (=5 — the
        # "rc bumped past cap by tenacity inner-retries" case observed in real
        # runs)
        "HC-9": {
            "fetch_meta": _meta("ok"),
            "fetch_bytes": {"u9": _bytes_entry("ok")},
            "extract_text": {"u9": _text_entry("provider_error", retry_count=5)},
        },
        # OK case — should not appear in any bucket
        "HC-10": {
            "fetch_meta": _meta("ok"),
            "fetch_bytes": {"u10": _bytes_entry("ok")},
            "extract_text": {"u10": _text_entry("ok")},
        },
    }
    _write_state(tmp_path / STATE_FILENAME, cases)

    buckets = classify_residual([tmp_path])

    # HC-7 (fetch_bytes/empty) is now REPLAY (the WAF flake widening —
    # was TERMINAL_DROPPED prior to the kind-aware classify_unified_error).
    assert len(buckets[Bucket.REPLAY]) == 4
    assert len(buckets[Bucket.PROVIDER_SWITCH]) == 1
    assert len(buckets[Bucket.REFETCH_UPSTREAM]) == 1
    assert len(buckets[Bucket.CONFIRMED_UNALLOCATED]) == 1
    assert len(buckets[Bucket.TERMINAL_DROPPED]) == 0
    assert len(buckets[Bucket.CAP_BURNT]) == 2


def test_classify_residual_drops_ok_rows(tmp_path: Path) -> None:
    """status=ok / skipped_cached records never appear in any bucket."""
    cases = {
        "HC-1": {
            "fetch_meta": _meta("ok"),
            "fetch_bytes": {"u1": _bytes_entry("ok")},
            "extract_text": {"u1": _text_entry("skipped_cached")},
        },
    }
    _write_state(tmp_path / STATE_FILENAME, cases)
    buckets = classify_residual([tmp_path])
    assert all(len(rows) == 0 for rows in buckets.values())


def test_classify_residual_aggregates_across_dirs(tmp_path: Path) -> None:
    """Sharded input: rows from two shards both feed the same buckets."""
    _write_state(
        tmp_path / "shard-a" / STATE_FILENAME,
        {"HC-1": {
            "fetch_meta": _meta("ok"),
            "fetch_bytes": {"u1": _bytes_entry("ok")},
            "extract_text": {"u1": _text_entry("provider_error", retry_count=0)},
        }},
    )
    _write_state(
        tmp_path / "shard-b" / STATE_FILENAME,
        {"HC-2": {
            "fetch_meta": _meta("ok"),
            "fetch_bytes": {"u2": _bytes_entry("ok")},
            "extract_text": {"u2": _text_entry("provider_error", retry_count=0)},
        }},
    )
    buckets = classify_residual([tmp_path / "shard-a", tmp_path / "shard-b"])
    assert len(buckets[Bucket.REPLAY]) == 2


def test_classify_residual_tags_each_row_with_source_dir_and_retry_count(
    tmp_path: Path,
) -> None:
    """Every ErrorRow carries source_dir (for plan_recoveries dispatch) and
    retry_count (for cap_burnt routing + cost forecasting)."""
    _write_state(
        tmp_path / "shard-a" / STATE_FILENAME,
        {"HC-1": {
            "fetch_meta": _meta("ok"),
            "fetch_bytes": {"u1": _bytes_entry("ok")},
            "extract_text": {"u1": _text_entry("provider_error", retry_count=1)},
        }},
    )
    buckets = classify_residual([tmp_path / "shard-a"])
    [row] = buckets[Bucket.REPLAY]
    assert row.source_dir == tmp_path / "shard-a"
    assert row.retry_count == 1


# ----- plan_recoveries ------------------------------------------------------


def test_plan_recoveries_one_spawn_per_dir_with_replay_rows(tmp_path: Path) -> None:
    """One Spawn per source dir that has at least one REPLAY row.
    CAP_BURNT does not trigger a spawn."""
    _write_state(
        tmp_path / "shard-a" / STATE_FILENAME,
        {"HC-1": {
            "fetch_meta": _meta("ok"),
            "fetch_bytes": {"u1": _bytes_entry("ok")},
            "extract_text": {"u1": _text_entry("provider_error", retry_count=0)},
        }},
    )
    _write_state(
        tmp_path / "shard-b" / STATE_FILENAME,
        {"HC-2": {
            "fetch_meta": _meta("ok"),
            "fetch_bytes": {"u2": _bytes_entry("ok")},
            "extract_text": {"u2": _text_entry("provider_error", retry_count=0)},
        }},
    )
    buckets = classify_residual([tmp_path / "shard-a", tmp_path / "shard-b"])
    plan = plan_recoveries(buckets, provedor="auto")

    assert len(plan) == 2
    assert {s.saida for s in plan} == {tmp_path / "shard-a", tmp_path / "shard-b"}


def test_plan_recoveries_skips_dirs_with_only_cap_burnt_rows(tmp_path: Path) -> None:
    """A shard whose entire transient residual hit cap=2 gets no spawn —
    `judex executar --retentar-de` would re-load the rows, see retry_count
    at cap, and emit '0 seeds'. Avoid the wasted spawn."""
    _write_state(
        tmp_path / "shard-a" / STATE_FILENAME,
        {"HC-1": {
            "fetch_meta": _meta("ok"),
            "fetch_bytes": {"u1": _bytes_entry("ok")},
            "extract_text": {"u1": _text_entry("provider_error", retry_count=2)},
        }},
    )
    _write_state(
        tmp_path / "shard-b" / STATE_FILENAME,
        {"HC-2": {
            "fetch_meta": _meta("ok"),
            "fetch_bytes": {"u2": _bytes_entry("ok")},
            "extract_text": {"u2": _text_entry("provider_error", retry_count=0)},
        }},
    )
    buckets = classify_residual([tmp_path / "shard-a", tmp_path / "shard-b"])
    plan = plan_recoveries(buckets, provedor="auto")

    assert len(plan) == 1
    assert plan[0].saida == tmp_path / "shard-b"


def test_plan_recoveries_command_uses_retentar_de(tmp_path: Path) -> None:
    """Each Spawn carries the argv to invoke `judex executar
    --retentar-de`. Provedor flag is honored; --nao-perguntar is implicit."""
    _write_state(
        tmp_path / STATE_FILENAME,
        {"HC-1": {
            "fetch_meta": _meta("ok"),
            "fetch_bytes": {"u1": _bytes_entry("ok")},
            "extract_text": {"u1": _text_entry("provider_error", retry_count=0)},
        }},
    )
    buckets = classify_residual([tmp_path])
    [spawn] = plan_recoveries(buckets, provedor="chandra")

    argv = " ".join(spawn.argv)
    assert "--retentar-de" in argv
    assert "executar.errors.jsonl" in argv
    assert "--saida" in argv
    assert "--provedor chandra" in argv
    assert "--nao-perguntar" in argv


# ----- plan_recoveries: non-REPLAY buckets (limpar v2) ---------------------


def test_classify_residual_routes_outlier_skipped_to_provider_switch(
    tmp_path: Path,
) -> None:
    """``outlier_skipped`` is a kind=terminal extract_text status emitted
    when a PDF exceeds the cloud-OCR body cap. Recovery is local
    Tesseract (no body cap), which limpar dispatches via PROVIDER_SWITCH
    — same bucket as ``empty`` but with a different destination provider.
    Sub-issue 02 routing through limpar's classifier.
    """
    _write_state(
        tmp_path / STATE_FILENAME,
        {"HC-1": {
            "fetch_meta": _meta("ok"),
            "fetch_bytes": {"u1": _bytes_entry("ok")},
            "extract_text": {"u1": _text_entry("outlier_skipped")},
        }},
    )
    buckets = classify_residual([tmp_path])
    assert len(buckets[Bucket.PROVIDER_SWITCH]) == 1
    assert buckets[Bucket.PROVIDER_SWITCH][0].status == "outlier_skipped"


def test_plan_dispatches_provider_switch_empty_via_extrair_urls_chandra(
    tmp_path: Path,
) -> None:
    """A PROVIDER_SWITCH row with status=empty must dispatch
    ``judex extrair-urls`` against a materialised URL list, with
    ``--provedor chandra --forcar``. URL-scoped (no over-extraction)
    and skips the meta + bytes stages that already succeeded.
    """
    _write_state(
        tmp_path / STATE_FILENAME,
        {"HC-1": {
            "fetch_meta": _meta("ok"),
            "fetch_bytes": {"u1": _bytes_entry("ok")},
            "extract_text": {"u1": _text_entry("empty")},
        }},
    )
    buckets = classify_residual([tmp_path])
    plan = plan_recoveries(buckets, provedor="auto")

    assert len(plan) == 1
    spawn = plan[0]
    argv_str = " ".join(spawn.argv)
    assert "extrair-urls" in argv_str
    assert "--provedor chandra" in argv_str
    assert "--forcar" in argv_str
    # The materialised URL file path appears in argv and exists on disk.
    assert spawn.source_errors_file is not None
    assert spawn.source_errors_file.exists()
    assert "u1" in spawn.source_errors_file.read_text()


def test_plan_dispatches_provider_switch_outlier_via_extrair_urls_tesseract(
    tmp_path: Path,
) -> None:
    """A PROVIDER_SWITCH row with status=outlier_skipped must dispatch
    against local tesseract (the only provider without the body cap)."""
    _write_state(
        tmp_path / STATE_FILENAME,
        {"HC-1": {
            "fetch_meta": _meta("ok"),
            "fetch_bytes": {"u1": _bytes_entry("ok")},
            "extract_text": {"u1": _text_entry("outlier_skipped")},
        }},
    )
    buckets = classify_residual([tmp_path])
    plan = plan_recoveries(buckets, provedor="auto")

    assert len(plan) == 1
    argv_str = " ".join(plan[0].argv)
    assert "extrair-urls" in argv_str
    assert "--provedor tesseract" in argv_str
    assert "--forcar" in argv_str
    # Must NOT route to a cloud provider — defeats the purpose.
    for cloud in ("chandra", "mistral", "tesseract_modal", "tesseract_fly"):
        assert f"--provedor {cloud}" not in argv_str


def test_plan_splits_provider_switch_by_status_one_spawn_each(
    tmp_path: Path,
) -> None:
    """A dir with both empty and outlier_skipped rows yields TWO spawns
    — different destination providers can't share an extrair-urls call."""
    _write_state(
        tmp_path / STATE_FILENAME,
        {
            "HC-1": {
                "fetch_meta": _meta("ok"),
                "fetch_bytes": {"u1": _bytes_entry("ok")},
                "extract_text": {"u1": _text_entry("empty")},
            },
            "HC-2": {
                "fetch_meta": _meta("ok"),
                "fetch_bytes": {"u2": _bytes_entry("ok")},
                "extract_text": {"u2": _text_entry("outlier_skipped")},
            },
        },
    )
    buckets = classify_residual([tmp_path])
    plan = plan_recoveries(buckets, provedor="auto")

    # Two PROVIDER_SWITCH spawns — one for each provider.
    argv_strs = [" ".join(s.argv) for s in plan]
    has_chandra = any("--provedor chandra" in s for s in argv_strs)
    has_tesseract = any("--provedor tesseract" in s for s in argv_strs)
    assert has_chandra
    assert has_tesseract


def test_plan_dispatches_refetch_upstream_via_executar_csv(tmp_path: Path) -> None:
    """A REFETCH_UPSTREAM row (no_bytes on extract_text) must dispatch
    ``judex executar --csv`` against a CSV of (classe, processo) pairs.
    The bytes that are present in cache are skipped automatically by
    the runner; only the missing bytes are refetched + their text
    re-extracted. No --forcar (caches honoured)."""
    _write_state(
        tmp_path / STATE_FILENAME,
        {"HC-1": {
            "fetch_meta": _meta("ok"),
            "fetch_bytes": {"u1": _bytes_entry("ok")},
            "extract_text": {"u1": _text_entry("no_bytes")},
        }},
    )
    buckets = classify_residual([tmp_path])
    plan = plan_recoveries(buckets, provedor="auto")

    assert len(plan) == 1
    argv_str = " ".join(plan[0].argv)
    assert "executar" in argv_str
    assert "--csv" in argv_str
    assert "--forcar" not in argv_str
    # Materialised CSV exists with the case row.
    assert plan[0].source_errors_file is not None
    assert plan[0].source_errors_file.exists()
    csv_text = plan[0].source_errors_file.read_text()
    assert "HC,1" in csv_text or "HC,1\r" in csv_text  # CSV writer line


def test_plan_combines_replay_and_provider_switch_in_same_dir(
    tmp_path: Path,
) -> None:
    """A dir with a REPLAY row AND a PROVIDER_SWITCH row gets BOTH
    spawns. The buckets are independent — recovery isn't a single-
    bucket affair anymore."""
    _write_state(
        tmp_path / STATE_FILENAME,
        {
            "HC-1": {
                "fetch_meta": _meta("ok"),
                "fetch_bytes": {"u1": _bytes_entry("ok")},
                "extract_text": {"u1": _text_entry("provider_error", retry_count=0)},
            },
            "HC-2": {
                "fetch_meta": _meta("ok"),
                "fetch_bytes": {"u2": _bytes_entry("ok")},
                "extract_text": {"u2": _text_entry("empty")},
            },
        },
    )
    buckets = classify_residual([tmp_path])
    plan = plan_recoveries(buckets, provedor="auto")

    assert len(plan) == 2
    argv_strs = [" ".join(s.argv) for s in plan]
    has_replay = any("--retentar-de" in s for s in argv_strs)
    has_switch = any("extrair-urls" in s for s in argv_strs)
    assert has_replay
    assert has_switch


# ----- format_summary -------------------------------------------------------


def test_format_summary_apply_format() -> None:
    """`recovered: N1 transient · N2 cap_burnt · N3 cross_stage · N4 provider_switched · N5 confirmed_unallocated · N6 terminal_dropped`"""
    from judex.sweeps.limpar import ErrorRow

    def _row(kind: str, status: str) -> ErrorRow:
        return ErrorRow(
            source_dir=Path("/tmp"),
            kind=kind,
            classe="HC",
            processo=1,
            status=status,
            url=None,
            retry_count=0,
        )

    buckets: dict[Bucket, list[ErrorRow]] = {
        Bucket.REPLAY: [_row("extract_text", "provider_error")] * 301,
        Bucket.CAP_BURNT: [_row("extract_text", "provider_error")] * 231,
        Bucket.REFETCH_UPSTREAM: [],
        Bucket.PROVIDER_SWITCH: [],
        Bucket.CONFIRMED_UNALLOCATED: [_row("fetch_meta", "unallocated_pid")] * 1036,
        Bucket.TERMINAL_DROPPED: [_row("fetch_bytes", "empty")] * 826,
    }
    line = format_summary(buckets, dry_run=False)
    assert line == (
        "recovered: 301 transient · 231 cap_burnt · 0 cross_stage · "
        "0 provider_switched · 1036 confirmed_unallocated · 826 terminal_dropped"
    )


def test_format_summary_dry_run_prefix() -> None:
    """Under dry-run, prefix is `would-recover:`."""
    from judex.sweeps.limpar import ErrorRow

    buckets: dict[Bucket, list[ErrorRow]] = {
        Bucket.REPLAY: [],
        Bucket.CAP_BURNT: [],
        Bucket.REFETCH_UPSTREAM: [],
        Bucket.PROVIDER_SWITCH: [],
        Bucket.CONFIRMED_UNALLOCATED: [],
        Bucket.TERMINAL_DROPPED: [],
    }
    line = format_summary(buckets, dry_run=True)
    assert line.startswith("would-recover:")


# ----- Pinned smoke against the real run dir -------------------------------


_HC2020_SHARDED = Path("runs/active/hc2020-sharded")


@pytest.mark.skipif(
    not _HC2020_SHARDED.exists(),
    reason="real run dir not present (cold checkout)",
)
def test_pinned_residual_hc2020_sharded() -> None:
    """As of post-first-limpar-pass on 2026-05-03, the hc2020-sharded run
    carries (per state.json), under the kind-aware classifier:

    - 739 REPLAY (mostly fetch_bytes/empty at retry_count < 2 — the
      WAF flake widening; previously TERMINAL_DROPPED)
    - 318 CAP_BURNT (extract_text/provider_error at retry_count >= 2,
      plus fetch_bytes/empty at retry_count >= 2)
    - 1036 CONFIRMED_UNALLOCATED (fetch_meta/unallocated_pid)
    - 0 TERMINAL_DROPPED (the empty-as-terminal path is gone)

    Total non-ok = 2093. If this fails, either the residual changed
    (someone re-ran) or the classifier drifted.
    """
    dirs = discover_run_dirs(_HC2020_SHARDED)
    assert len(dirs) == 16

    buckets = classify_residual(dirs)
    assert len(buckets[Bucket.REPLAY]) == 739
    assert len(buckets[Bucket.CAP_BURNT]) == 318
    assert len(buckets[Bucket.CONFIRMED_UNALLOCATED]) == 1036
    assert len(buckets[Bucket.TERMINAL_DROPPED]) == 0
    assert len(buckets[Bucket.PROVIDER_SWITCH]) == 0
    assert len(buckets[Bucket.REFETCH_UPSTREAM]) == 0
    # Total preserved across the policy change
    total = sum(len(buckets[b]) for b in Bucket)
    assert total == 2093
