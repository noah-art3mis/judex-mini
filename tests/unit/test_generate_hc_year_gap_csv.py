"""Unit tests for `scripts/generate_hc_year_gap_csv.py`.

Covers the filename-parsing heuristic for `data/cases/HC/` and the
gap-CSV emission behaviour (descending order, captured IDs excluded,
well-formed header).
"""

from __future__ import annotations

import csv
from pathlib import Path
from unittest.mock import patch

from scripts.generate_hc_year_gap_csv import captured_ids, write_gap_csv


def _touch(d: Path, name: str) -> None:
    (d / name).write_text("{}")


def test_captured_ids_reads_single_record_filenames(tmp_path: Path) -> None:
    _touch(tmp_path, "judex-mini_HC_100-100.json")
    _touch(tmp_path, "judex-mini_HC_200-200.json")
    assert captured_ids(tmp_path) == {100, 200}


def test_captured_ids_reads_range_filenames(tmp_path: Path) -> None:
    _touch(tmp_path, "judex-mini_HC_10-12.json")
    assert captured_ids(tmp_path) == {10, 11, 12}


def test_captured_ids_skips_malformed_filenames(tmp_path: Path) -> None:
    _touch(tmp_path, "judex-mini_HC_abc-def.json")
    _touch(tmp_path, "judex-mini_HC_100.json")  # no dash
    _touch(tmp_path, "judex-mini_HC_200-100.json")  # lo > hi
    _touch(tmp_path, "judex-mini_HC_300-300.json")  # well-formed control
    assert captured_ids(tmp_path) == {300}


def test_write_gap_csv_emits_uncaptured_descending(tmp_path: Path) -> None:
    cases = tmp_path / "cases"
    cases.mkdir()
    _touch(cases, "judex-mini_HC_101-101.json")
    _touch(cases, "judex-mini_HC_103-103.json")

    out = tmp_path / "gap.csv"
    with patch(
        "scripts.generate_hc_year_gap_csv.year_to_id_range",
        return_value=(100, 104),
    ):
        count = write_gap_csv(year=2024, out_path=out, cases_dir=cases)

    assert count == 3
    with out.open(newline="") as f:
        rows = list(csv.reader(f))
    assert rows[0] == ["classe", "processo"]
    assert rows[1:] == [["HC", "104"], ["HC", "102"], ["HC", "100"]]


def test_write_gap_csv_emits_header_only_when_fully_captured(
    tmp_path: Path,
) -> None:
    cases = tmp_path / "cases"
    cases.mkdir()
    for n in range(100, 103):
        _touch(cases, f"judex-mini_HC_{n}-{n}.json")

    out = tmp_path / "gap.csv"
    with patch(
        "scripts.generate_hc_year_gap_csv.year_to_id_range",
        return_value=(100, 102),
    ):
        count = write_gap_csv(year=2024, out_path=out, cases_dir=cases)

    assert count == 0
    with out.open(newline="") as f:
        rows = list(csv.reader(f))
    assert rows == [["classe", "processo"]]


def test_write_gap_csv_excludes_dead_ids(tmp_path: Path) -> None:
    """IDs listed in dead_ids_path must be excluded from the gap CSV."""
    cases = tmp_path / "cases"
    cases.mkdir()
    # range 100..104; capture 101; mark 102 and 104 as dead; expect gap = [103, 100]
    _touch(cases, "judex-mini_HC_101-101.json")
    dead = tmp_path / "dead.txt"
    dead.write_text("102\n104\n")

    out = tmp_path / "gap.csv"
    with patch(
        "scripts.generate_hc_year_gap_csv.year_to_id_range",
        return_value=(100, 104),
    ):
        count = write_gap_csv(
            year=2024, out_path=out, cases_dir=cases, dead_ids_path=dead,
        )

    assert count == 2
    with out.open(newline="") as f:
        rows = list(csv.reader(f))
    assert rows[1:] == [["HC", "103"], ["HC", "100"]]


def test_write_gap_csv_include_captured_keeps_on_disk_ids(tmp_path: Path) -> None:
    """`include_captured=True` emits every pid in range except confirmed deads —
    on-disk pids are NOT filtered. Used for full-year re-scrape sweeps where
    content-staleness of existing files can't be cheaply detected."""
    cases = tmp_path / "cases"
    cases.mkdir()
    # range 100..104; 101 is on disk; 104 is dead; expect full = [103, 102, 101, 100]
    _touch(cases, "judex-mini_HC_101-101.json")
    dead = tmp_path / "dead.txt"
    dead.write_text("104\n")

    out = tmp_path / "full.csv"
    with patch(
        "scripts.generate_hc_year_gap_csv.year_to_id_range",
        return_value=(100, 104),
    ):
        count = write_gap_csv(
            year=2024,
            out_path=out,
            cases_dir=cases,
            dead_ids_path=dead,
            include_captured=True,
        )

    assert count == 4
    with out.open(newline="") as f:
        rows = list(csv.reader(f))
    assert rows[1:] == [["HC", "103"], ["HC", "102"], ["HC", "101"], ["HC", "100"]]


def test_write_gap_csv_include_captured_still_excludes_deads(tmp_path: Path) -> None:
    """Even with include_captured=True, confirmed-dead pids are filtered —
    they produce empty case JSONs regardless, so scraping them is wasted."""
    cases = tmp_path / "cases"
    cases.mkdir()
    dead = tmp_path / "dead.txt"
    dead.write_text("101\n103\n")

    out = tmp_path / "full.csv"
    with patch(
        "scripts.generate_hc_year_gap_csv.year_to_id_range",
        return_value=(100, 104),
    ):
        count = write_gap_csv(
            year=2024,
            out_path=out,
            cases_dir=cases,
            dead_ids_path=dead,
            include_captured=True,
        )

    assert count == 3
    with out.open(newline="") as f:
        rows = list(csv.reader(f))
    assert rows[1:] == [["HC", "104"], ["HC", "102"], ["HC", "100"]]
