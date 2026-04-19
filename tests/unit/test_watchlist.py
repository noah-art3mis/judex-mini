"""Watchlist file parser + snapshot I/O.

Pins down: one-per-line format, comments, blank-line tolerance, rejection
of malformed lines, and round-trip of JSON snapshots at
`state/watchlist/<classe>_<N>.json`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from judex.reports.watchlist import (
    load_snapshot,
    parse_watchlist,
    save_snapshot,
    snapshot_path,
)


def test_parses_one_per_line(tmp_path: Path) -> None:
    path = tmp_path / "watchlist.txt"
    path.write_text("HC 158802\nADI 2820\nADPF 153\n", encoding="utf-8")

    assert parse_watchlist(path) == [("HC", 158802), ("ADI", 2820), ("ADPF", 153)]


def test_ignores_comments_and_blank_lines(tmp_path: Path) -> None:
    path = tmp_path / "watchlist.txt"
    path.write_text(
        "# Famous cases\n"
        "HC 158802    # Lula\n"
        "\n"
        "ADI 2820\n"
        "  # indented comment\n",
        encoding="utf-8",
    )

    assert parse_watchlist(path) == [("HC", 158802), ("ADI", 2820)]


def test_missing_file_returns_empty_list(tmp_path: Path) -> None:
    assert parse_watchlist(tmp_path / "nope.txt") == []


def test_malformed_line_raises(tmp_path: Path) -> None:
    path = tmp_path / "bad.txt"
    path.write_text("HC 158802\nnot a line at all\n", encoding="utf-8")

    with pytest.raises(ValueError, match="line 2"):
        parse_watchlist(path)


def test_snapshot_round_trips(tmp_path: Path) -> None:
    item = {"classe": "HC", "processo_id": 158802, "relator": "Min. X"}

    save_snapshot("HC", 158802, item, root=tmp_path)
    loaded = load_snapshot("HC", 158802, root=tmp_path)

    assert loaded == item


def test_snapshot_missing_returns_none(tmp_path: Path) -> None:
    assert load_snapshot("HC", 158802, root=tmp_path) is None


def test_snapshot_path_is_predictable(tmp_path: Path) -> None:
    assert snapshot_path("HC", 158802, root=tmp_path) == tmp_path / "HC_158802.json"
