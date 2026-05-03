"""Pin `judex limpar` discovery + classification + planning.

`judex limpar <run_dir>` walks a finished `judex executar` run dir,
partitions every non-ok row by ``(kind, classify_unified_error(row))``
plus a small ``(kind, status)`` override for the actionable terminals,
and dispatches recoveries. This file pins:

- ``discover_run_dirs`` — mono vs sharded auto-detection.
- ``classify_residual`` — partitioning, including the override cells.
- ``plan_recoveries`` — one Spawn per source dir with at least one
  replay-bucket row.
- ``format_summary`` — the spec's one-line format.

Tests are *behavioural* (do these inputs produce these buckets?), not
ceremonial (do these field names exist?) — the type checker covers the
latter.
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


# ----- discover_run_dirs ----------------------------------------------------


def _write_errors(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(r) + "\n" for r in rows),
        encoding="utf-8",
    )


def test_discover_run_dirs_mono(tmp_path: Path) -> None:
    """Mono layout: errors.jsonl directly at the run-dir top."""
    _write_errors(
        tmp_path / "executar.errors.jsonl",
        [{"kind": "fetch_meta", "classe": "HC", "processo": 1, "status": "http_error"}],
    )
    assert discover_run_dirs(tmp_path) == [tmp_path]


def test_discover_run_dirs_sharded(tmp_path: Path) -> None:
    """Sharded layout: shard-*/executar.errors.jsonl, sorted by suffix."""
    for letter in ("a", "b", "c"):
        _write_errors(
            tmp_path / f"shard-{letter}" / "executar.errors.jsonl",
            [{"kind": "fetch_meta", "classe": "HC", "processo": 1, "status": "ok"}],
        )
    out = discover_run_dirs(tmp_path)
    assert out == [
        tmp_path / "shard-a",
        tmp_path / "shard-b",
        tmp_path / "shard-c",
    ]


def test_discover_run_dirs_empty(tmp_path: Path) -> None:
    """No errors.jsonl anywhere → empty list (caller treats as 'nothing to recover')."""
    assert discover_run_dirs(tmp_path) == []


def test_discover_run_dirs_sharded_skips_dirs_without_errors_file(
    tmp_path: Path,
) -> None:
    """A shard dir with no errors.jsonl is dropped — not every shard has a residual."""
    _write_errors(
        tmp_path / "shard-a" / "executar.errors.jsonl",
        [{"kind": "fetch_meta", "classe": "HC", "processo": 1, "status": "http_error"}],
    )
    (tmp_path / "shard-b").mkdir()  # no errors file
    out = discover_run_dirs(tmp_path)
    assert out == [tmp_path / "shard-a"]


# ----- classify_residual ----------------------------------------------------


def test_classify_residual_partitions_by_kind_and_classifier_output(
    tmp_path: Path,
) -> None:
    """Each row routes to the bucket implied by (kind, classify_unified_error)."""
    rows = [
        # Replay buckets (transient)
        {"kind": "extract_text", "classe": "HC", "processo": 1,
         "status": "provider_error", "url": "u1"},
        {"kind": "fetch_bytes", "classe": "HC", "processo": 2,
         "status": "http_error", "url": "u2"},
        {"kind": "fetch_meta", "classe": "HC", "processo": 3,
         "status": "http_error"},
        # Override: extract_text/empty → provider_switch (not terminal_dropped)
        {"kind": "extract_text", "classe": "HC", "processo": 4,
         "status": "empty", "url": "u4"},
        # Cross-stage: extract_text/no_bytes → refetch_upstream
        {"kind": "extract_text", "classe": "HC", "processo": 5,
         "status": "no_bytes", "url": "u5"},
        # Confirmed-unallocated
        {"kind": "fetch_meta", "classe": "HC", "processo": 6,
         "status": "unallocated_pid"},
        # Plain terminal: fetch_bytes/empty
        {"kind": "fetch_bytes", "classe": "HC", "processo": 7,
         "status": "empty", "url": "u7"},
    ]
    _write_errors(tmp_path / "executar.errors.jsonl", rows)

    buckets = classify_residual([tmp_path])

    assert len(buckets[Bucket.REPLAY]) == 3
    assert len(buckets[Bucket.PROVIDER_SWITCH]) == 1
    assert len(buckets[Bucket.REFETCH_UPSTREAM]) == 1
    assert len(buckets[Bucket.CONFIRMED_UNALLOCATED]) == 1
    assert len(buckets[Bucket.TERMINAL_DROPPED]) == 1


def test_classify_residual_drops_ok_rows(tmp_path: Path) -> None:
    """``status=ok`` and ``status=skipped_cached`` should never appear in the
    residual, but if they do (legacy snapshot artifact), drop them — every
    non-ok bucket excludes them."""
    rows = [
        {"kind": "extract_text", "classe": "HC", "processo": 1,
         "status": "ok", "url": "u1"},
        {"kind": "extract_text", "classe": "HC", "processo": 2,
         "status": "skipped_cached", "url": "u2"},
    ]
    _write_errors(tmp_path / "executar.errors.jsonl", rows)
    buckets = classify_residual([tmp_path])
    assert all(len(rows) == 0 for rows in buckets.values())


def test_classify_residual_aggregates_across_dirs(tmp_path: Path) -> None:
    """Sharded input: rows from shard-a and shard-b both feed the same buckets."""
    _write_errors(
        tmp_path / "shard-a" / "executar.errors.jsonl",
        [{"kind": "extract_text", "classe": "HC", "processo": 1,
          "status": "provider_error", "url": "u1"}],
    )
    _write_errors(
        tmp_path / "shard-b" / "executar.errors.jsonl",
        [{"kind": "extract_text", "classe": "HC", "processo": 2,
          "status": "provider_error", "url": "u2"}],
    )
    buckets = classify_residual([tmp_path / "shard-a", tmp_path / "shard-b"])
    assert len(buckets[Bucket.REPLAY]) == 2


def test_classify_residual_tags_each_row_with_source_dir(tmp_path: Path) -> None:
    """plan_recoveries needs to know which dir each row came from to spawn
    one child per dir. The classifier preserves source_dir on every row."""
    _write_errors(
        tmp_path / "shard-a" / "executar.errors.jsonl",
        [{"kind": "extract_text", "classe": "HC", "processo": 1,
          "status": "provider_error", "url": "u1"}],
    )
    buckets = classify_residual([tmp_path / "shard-a"])
    [row] = buckets[Bucket.REPLAY]
    assert row.source_dir == tmp_path / "shard-a"


# ----- plan_recoveries ------------------------------------------------------


def test_plan_recoveries_one_spawn_per_dir_with_replay_rows(tmp_path: Path) -> None:
    """One Spawn per source dir that has at least one replay-bucket row."""
    _write_errors(
        tmp_path / "shard-a" / "executar.errors.jsonl",
        [{"kind": "extract_text", "classe": "HC", "processo": 1,
          "status": "provider_error", "url": "u1"}],
    )
    _write_errors(
        tmp_path / "shard-b" / "executar.errors.jsonl",
        [{"kind": "extract_text", "classe": "HC", "processo": 2,
          "status": "provider_error", "url": "u2"}],
    )
    buckets = classify_residual([tmp_path / "shard-a", tmp_path / "shard-b"])
    plan = plan_recoveries(buckets, provedor="auto")

    assert len(plan) == 2
    assert {s.saida for s in plan} == {tmp_path / "shard-a", tmp_path / "shard-b"}


def test_plan_recoveries_skips_dirs_with_only_terminal_rows(tmp_path: Path) -> None:
    """A shard whose residual is entirely terminal/cross_stage gets no spawn —
    `--retentar-de` would no-op there anyway."""
    _write_errors(
        tmp_path / "shard-a" / "executar.errors.jsonl",
        [{"kind": "fetch_meta", "classe": "HC", "processo": 1,
          "status": "unallocated_pid"}],
    )
    _write_errors(
        tmp_path / "shard-b" / "executar.errors.jsonl",
        [{"kind": "extract_text", "classe": "HC", "processo": 2,
          "status": "provider_error", "url": "u2"}],
    )
    buckets = classify_residual([tmp_path / "shard-a", tmp_path / "shard-b"])
    plan = plan_recoveries(buckets, provedor="auto")

    assert len(plan) == 1
    assert plan[0].saida == tmp_path / "shard-b"


def test_plan_recoveries_command_uses_retentar_de(tmp_path: Path) -> None:
    """Each Spawn carries the argv needed to invoke `judex executar
    --retentar-de`. Provedor flag is honored."""
    _write_errors(
        tmp_path / "executar.errors.jsonl",
        [{"kind": "extract_text", "classe": "HC", "processo": 1,
          "status": "provider_error", "url": "u1"}],
    )
    buckets = classify_residual([tmp_path])
    [spawn] = plan_recoveries(buckets, provedor="chandra")

    # The argv must include the retentar-de flag pointing at the source
    # errors.jsonl, the saida flag, the provedor flag, and --nao-perguntar
    # (limpar-spawned children are non-interactive by construction).
    argv = " ".join(spawn.argv)
    assert "--retentar-de" in argv
    assert "executar.errors.jsonl" in argv
    assert "--saida" in argv
    assert "--provedor chandra" in argv
    assert "--nao-perguntar" in argv


# ----- format_summary -------------------------------------------------------


def test_format_summary_apply_format() -> None:
    """`recovered: N1 transient · N2 cross_stage · N3 provider_switched · N4 confirmed_unallocated · N5 terminal_dropped`"""
    from judex.sweeps.limpar import ErrorRow

    def _row(kind: str, status: str) -> ErrorRow:
        return ErrorRow(
            source_dir=Path("/tmp"),
            kind=kind,
            classe="HC",
            processo=1,
            status=status,
            url=None,
            raw={},
        )

    buckets: dict[Bucket, list[ErrorRow]] = {
        Bucket.REPLAY: [_row("extract_text", "provider_error")] * 532,
        Bucket.REFETCH_UPSTREAM: [],
        Bucket.PROVIDER_SWITCH: [],
        Bucket.CONFIRMED_UNALLOCATED: [_row("fetch_meta", "unallocated_pid")] * 1036,
        Bucket.TERMINAL_DROPPED: [_row("fetch_bytes", "empty")] * 826,
    }
    line = format_summary(buckets, dry_run=False)
    assert line == (
        "recovered: 532 transient · 0 cross_stage · 0 provider_switched · "
        "1036 confirmed_unallocated · 826 terminal_dropped"
    )


def test_format_summary_dry_run_prefix() -> None:
    """Under `--dry-run` (default), the prefix is `would-recover:` so the
    no-action read is unambiguous."""
    from judex.sweeps.limpar import ErrorRow

    buckets: dict[Bucket, list[ErrorRow]] = {
        Bucket.REPLAY: [],
        Bucket.REFETCH_UPSTREAM: [],
        Bucket.PROVIDER_SWITCH: [],
        Bucket.CONFIRMED_UNALLOCATED: [],
        Bucket.TERMINAL_DROPPED: [],
    }
    line = format_summary(buckets, dry_run=True)
    assert line.startswith("would-recover:")


# ----- Pinned smoke against the real run dir -------------------------------
#
# Skips when the repo is checked out cold (no runs/active/). When the
# fixture exists, this catches drift in classify_unified_error + the
# limpar partitioner against a known-shape residual.

_HC2020_SHARDED = Path("runs/active/hc2020-sharded")


@pytest.mark.skipif(
    not _HC2020_SHARDED.exists(),
    reason="real run dir not present (cold checkout)",
)
def test_pinned_residual_hc2020_sharded() -> None:
    """As of 2026-05-03, the hc2020-sharded run carries:
    532 extract_text/provider_error (replay),
    826 fetch_bytes/empty (terminal_dropped),
    1036 fetch_meta/unallocated_pid (confirmed_unallocated).

    If this fails, either the residual changed (someone re-ran) or the
    classifier drifted.
    """
    dirs = discover_run_dirs(_HC2020_SHARDED)
    assert len(dirs) == 16  # 16 shards

    buckets = classify_residual(dirs)
    assert len(buckets[Bucket.REPLAY]) == 532
    assert len(buckets[Bucket.CONFIRMED_UNALLOCATED]) == 1036
    assert len(buckets[Bucket.TERMINAL_DROPPED]) == 826
    assert len(buckets[Bucket.PROVIDER_SWITCH]) == 0
    assert len(buckets[Bucket.REFETCH_UPSTREAM]) == 0
