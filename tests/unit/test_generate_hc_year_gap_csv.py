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
