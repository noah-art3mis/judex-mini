"""Tests for `src/data/missing.py:check_missing_processes`.

Regression driver: when a single case is exported to `.json`, the file
contains a bare dict (v3+ shape), not a list of dicts. Iterating a
dict iterates its keys; the original code then tried `item["processo_id"]`
on each key string, producing `"string indices must be integers"` and
silently swallowing the error via `except Exception`. That meant the
missing-retry loop in `run_scraper_http` never surfaced the real
missing-count for single-case exports. Fix: detect bare-dict shape
and treat it as `[dict]`.
"""

from __future__ import annotations

import json
from pathlib import Path

from src.data.missing import check_missing_processes
from src.data.output import OutputConfig


def _json_only() -> OutputConfig:
    return OutputConfig(csv=False, jsonl=False, json=True)


def test_bare_dict_json_treated_as_single_case(tmp_path: Path) -> None:
    """v3+: one-case export is a bare dict — not a 1-element list.

    Before the fix this returned [158802] (falsely "missing") because
    the exception was silently swallowed.
    """
    out_dir = tmp_path
    path = out_dir / "judex-mini_HC_158802-158802.json"
    path.write_text(json.dumps({"processo_id": 158802, "classe": "HC"}))

    missing = check_missing_processes(
        "HC", 158802, 158802, str(out_dir), _json_only()
    )
    assert missing == []


def test_list_of_dicts_json_still_works(tmp_path: Path) -> None:
    """Legacy v2 shape: 1-element list wrapping the dict. Must still parse."""
    out_dir = tmp_path
    path = out_dir / "judex-mini_HC_100-100.json"
    path.write_text(json.dumps([{"processo_id": 100, "classe": "HC"}]))

    assert check_missing_processes("HC", 100, 100, str(out_dir), _json_only()) == []


def test_missing_detected_when_bare_dict_has_wrong_processo_id(tmp_path: Path) -> None:
    """If the on-disk JSON is for a different processo_id than requested,
    the requested one is still missing."""
    out_dir = tmp_path
    path = out_dir / "judex-mini_HC_500-500.json"
    path.write_text(json.dumps({"processo_id": 999, "classe": "HC"}))

    assert check_missing_processes("HC", 500, 500, str(out_dir), _json_only()) == [500]


def test_range_with_bare_dict_doesnt_crash(tmp_path: Path) -> None:
    """Multi-process range where the on-disk file is (somehow) a bare
    dict must not throw — the range just comes back as fully missing
    except for the one processo_id present."""
    out_dir = tmp_path
    path = out_dir / "judex-mini_HC_10-12.json"
    path.write_text(json.dumps({"processo_id": 11, "classe": "HC"}))

    assert sorted(check_missing_processes("HC", 10, 12, str(out_dir), _json_only())) == [10, 12]
