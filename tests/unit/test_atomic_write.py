"""Tests for the atomic-write helper.

Behavior, not structure — three things matter to callers:
- the final file contains exactly the text passed in,
- a previous version is replaced cleanly,
- no temp file is left behind on a successful write.
"""

from __future__ import annotations

import os
from pathlib import Path

from judex.utils.atomic_write import atomic_write_text


def test_writes_text_to_path(tmp_path: Path) -> None:
    target = tmp_path / "state.json"
    atomic_write_text(target, '{"k": 1}')
    assert target.read_text(encoding="utf-8") == '{"k": 1}'


def test_replaces_existing_file(tmp_path: Path) -> None:
    target = tmp_path / "state.json"
    target.write_text("old", encoding="utf-8")
    atomic_write_text(target, "new")
    assert target.read_text(encoding="utf-8") == "new"


def test_no_temp_file_left_behind(tmp_path: Path) -> None:
    target = tmp_path / "state.json"
    atomic_write_text(target, "x")
    leftover = list(tmp_path.glob("*.tmp.*"))
    assert leftover == []


def test_pid_suffixed_temp_does_not_disturb_cohabiting_writer(tmp_path: Path) -> None:
    """A temp file from a different PID sharing the same directory must
    survive — this is the whole reason the helper PID-suffixes its temp
    name instead of using a fixed ``.tmp``.
    """
    target = tmp_path / "state.json"
    other_pid_tmp = target.with_suffix(target.suffix + f".tmp.{os.getpid() + 1}")
    other_pid_tmp.write_text("other-process-in-flight", encoding="utf-8")

    atomic_write_text(target, "ours")

    assert target.read_text(encoding="utf-8") == "ours"
    assert other_pid_tmp.read_text(encoding="utf-8") == "other-process-in-flight"


def test_fsync_path_writes_correctly(tmp_path: Path) -> None:
    """fsync=True is the load-bearing variant for sweep stores. Test that
    the bytes still land — actual durability isn't observable in a unit test.
    """
    target = tmp_path / "state.json"
    atomic_write_text(target, "fsynced", fsync=True)
    assert target.read_text(encoding="utf-8") == "fsynced"
