"""Daily-report state file I/O: per-class high-water mark persistence.

Pins down: default when file is missing, round-trip load/save, and that
updating one class's mark doesn't clobber the others.
"""

from __future__ import annotations

from pathlib import Path

from judex.reports.state import DailyState


def test_load_missing_file_returns_empty_default(tmp_path: Path) -> None:
    path = tmp_path / "state.json"

    state = DailyState.load(path)

    assert state.max_numero == {}
    assert state.last_run_utc == ""


def test_save_then_load_round_trips(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    original = DailyState(
        max_numero={"HC": 271139, "ADI": 7500},
        last_run_utc="2026-04-19T06:00:00Z",
    )

    original.save(path)
    reloaded = DailyState.load(path)

    assert reloaded == original


def test_save_creates_parent_directory(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "dir" / "state.json"

    DailyState(max_numero={"HC": 1}, last_run_utc="").save(path)

    assert path.exists()


def test_update_one_class_preserves_others(tmp_path: Path) -> None:
    """Bumping HC's high-water mark must not drop ADI's entry."""
    path = tmp_path / "state.json"
    DailyState(
        max_numero={"HC": 100, "ADI": 50},
        last_run_utc="2026-04-19T00:00:00Z",
    ).save(path)

    state = DailyState.load(path)
    state.max_numero["HC"] = 105
    state.last_run_utc = "2026-04-20T00:00:00Z"
    state.save(path)

    reloaded = DailyState.load(path)
    assert reloaded.max_numero == {"HC": 105, "ADI": 50}
    assert reloaded.last_run_utc == "2026-04-20T00:00:00Z"
