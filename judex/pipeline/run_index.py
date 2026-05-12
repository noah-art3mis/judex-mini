"""Run-directory introspection — the "list runs" library used by
``judex listar``.

This sits one layer below the CLI on purpose: ``judex listar`` is a
thin Typer wrapper around ``list_runs()``; future affordances (a
no-arg ``judex acompanhar`` that auto-targets the newest *running*
run, a smarter ``judex parar`` default, a ``runs/status.py``-style
script) can reuse the same primitive without dragging Typer + rich
into their import graph.

The four lifecycle states fall out of two on-disk signals:

* ``<saida>/executar.pid`` (mono) or ``<saida>/shards.pids`` (sharded)
  — written by ``run_pipeline`` / the sharded launcher at entry,
  unlinked in their finally blocks. SIGKILL is the only path that
  leaves a stale pid file behind (Python can't run finally on signal 9).
* ``<saida>/executar.state.json`` — the atomic 5 s snapshot.

| pid file? | any PID alive? | state.json? | status     |
|-----------|---------------|-------------|------------|
| yes       | yes           | (any)       | running    |
| yes       | no            | (any)       | stale      |
| no        | —             | yes         | finished   |
| no        | —             | no          | unknown    |

``finished`` collapses "natural completion" and "graceful SIGTERM"
into one bucket because the operator's recovery path is identical
for both (``relatar`` / ``recuperar`` / ``retomar``). The
``stale`` bucket is the one that earns its keep — it surfaces
SIGKILL-leaked pid files that ``parar`` would no-op on, and
``prune_stale_pid_files`` is the matching cleanup action.

State.json is read with ``json.loads(path.read_text())`` — fine for
the listing path (one-shot, small enough top level), but a streaming
parser would be worth it if a 50 MB state ever shows up.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional


class RunStatus(str, Enum):
    RUNNING = "running"
    STALE = "stale"
    FINISHED = "finished"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class RunSummary:
    saida: Path
    status: RunStatus
    pids: list[int]
    rotulo: Optional[str]
    classe: Optional[str]
    started_at: Optional[str]
    snapshot_at: Optional[str]
    mtime: float
    n_targets: Optional[int] = None

    def elapsed_seconds(self) -> Optional[float]:
        """Wall-time of the run as a float.

        * ``running`` → ``now - started_at`` (live duration).
        * ``finished`` / ``stale`` → ``snapshot_at - started_at`` (the
          last snapshot is the closest thing to "when the run ended"
          we can derive from disk without parsing logs).
        * ``unknown`` or missing timestamps → ``None``.
        """
        if not self.started_at:
            return None
        try:
            started = _parse_iso(self.started_at)
        except ValueError:
            return None
        if self.status == RunStatus.RUNNING:
            return (datetime.now(tz=timezone.utc) - started).total_seconds()
        if self.snapshot_at:
            try:
                snap = _parse_iso(self.snapshot_at)
            except ValueError:
                return None
            return (snap - started).total_seconds()
        return None


def _parse_iso(s: str) -> datetime:
    """Tolerate the ``Z`` suffix Python's stdlib didn't accept until 3.11.
    ``executar.state.json`` writes both flavours depending on the snapshot
    code path."""
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def format_elapsed(seconds: Optional[float]) -> str:
    """``5400 → "1h 30m"``, ``75 → "1m 15s"``, ``8 → "8s"``, ``None → "—"``.
    Same magnitude buckets the report.md wall formatter uses, so operator
    eyes don't need to context-switch between ``listar`` and ``relatar``."""
    if seconds is None or seconds < 0:
        return "—"
    s = int(round(seconds))
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m {s % 60}s"
    h, rem = divmod(s, 3600)
    return f"{h}h {rem // 60}m"


def _is_pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _read_pid_file(path: Path) -> list[int]:
    out: list[int] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(int(line))
        except ValueError:
            continue
    return out


def _discover_pids(saida: Path) -> tuple[list[int], bool]:
    """Return ``(pids, pid_file_present)``. Sharded layout wins when
    both files exist — mirrors ``judex.cli._read_pids``."""
    shards = saida / "shards.pids"
    if shards.exists():
        return _read_pid_file(shards), True
    mono = saida / "executar.pid"
    if mono.exists():
        return _read_pid_file(mono), True
    return [], False


def summarize_run(saida: Path) -> RunSummary:
    """One run dir → one ``RunSummary``. Reads at most two files:
    the pid file (shards.pids or executar.pid) for liveness, and
    executar.state.json for label + timestamps. Never touches the
    log files."""
    pids, pid_file_present = _discover_pids(saida)
    any_alive = any(_is_pid_alive(p) for p in pids)

    state_path = saida / "executar.state.json"
    state_meta: dict = {}
    if state_path.exists():
        try:
            state_meta = json.loads(state_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            state_meta = {}

    if pid_file_present and any_alive:
        status = RunStatus.RUNNING
    elif pid_file_present:
        status = RunStatus.STALE
    elif state_meta:
        status = RunStatus.FINISHED
    else:
        status = RunStatus.UNKNOWN

    args = state_meta.get("args") or {}
    try:
        mtime = saida.stat().st_mtime
    except OSError:
        mtime = 0.0

    cases = state_meta.get("cases")
    n_targets = len(cases) if isinstance(cases, dict) else None

    return RunSummary(
        saida=saida,
        status=status,
        pids=pids,
        rotulo=args.get("rotulo"),
        classe=args.get("classe"),
        started_at=state_meta.get("started_at"),
        snapshot_at=state_meta.get("snapshot_at"),
        mtime=mtime,
        n_targets=n_targets,
    )


def list_runs(
    root: Path = Path("runs/active"),
    *,
    include_archive: bool = False,
) -> list[RunSummary]:
    """Every sub-directory of ``root`` summarised, sorted newest-first
    by directory mtime. Missing / non-directory ``root`` → empty list.

    ``include_archive=True`` additionally walks ``runs/archive/`` (or
    the sibling ``archive/`` of ``root``, whichever exists) and merges
    the results into one mtime-sorted list. Used for the "where did
    that run from last week go?" query.
    """
    roots = [root]
    if include_archive:
        # Always look in the sibling ``archive/`` of whatever ``root`` is.
        # This keeps custom ``--root`` scopes honest (e.g. a tmp_path
        # under test won't suddenly pick up the project's real archive).
        sibling = root.parent / "archive"
        if sibling != root and sibling.exists():
            roots.append(sibling)

    summaries: list[RunSummary] = []
    for r in roots:
        if not r.exists() or not r.is_dir():
            continue
        summaries.extend(summarize_run(p) for p in r.iterdir() if p.is_dir())
    return sorted(summaries, key=lambda s: s.mtime, reverse=True)


def find_by_label(
    label: str,
    *,
    include_archive: bool = True,
) -> list[RunSummary]:
    """Return every run whose ``rotulo`` or directory name equals or
    starts-with ``label``. Used by ``_resolve_run_dir`` to support
    ``judex parar hc2021-fillin`` instead of the full path.

    Match precedence within the returned list is *not* defined here —
    callers should sort by specificity (exact > prefix) before picking.
    ``include_archive`` defaults True because addressing a run by name
    is almost always followed by ``relatar`` / ``recuperar`` /
    ``arquivar``, all of which work on archived dirs too.
    """
    candidates = list_runs(include_archive=include_archive)
    matches: list[RunSummary] = []
    for s in candidates:
        if s.rotulo == label or s.saida.name == label:
            matches.append(s)
        elif s.rotulo and s.rotulo.startswith(label):
            matches.append(s)
        elif s.saida.name.startswith(label):
            matches.append(s)
    return matches


def label_candidates(prefix: str = "") -> list[str]:
    """Every known label (``rotulo`` or directory name) under
    ``runs/active/`` + ``runs/archive/`` whose start matches ``prefix``.

    Used by the Typer shell-completion callback on ``<saida>``
    arguments so ``judex parar <tab>`` enumerates real run names.
    """
    seen: set[str] = set()
    out: list[str] = []
    for s in list_runs(include_archive=True):
        for name in (s.rotulo, s.saida.name):
            if not name or name in seen:
                continue
            if name.startswith(prefix):
                seen.add(name)
                out.append(name)
    return out


def prune_stale_pid_files(root: Path = Path("runs/active")) -> list[Path]:
    """Delete pid files (``executar.pid`` and/or ``shards.pids``) from
    runs whose status is ``stale``. Returns the list of removed paths.

    The cleanup action for the ``stale`` state — surfaces SIGKILL leaks
    that ``parar`` would otherwise no-op on, and makes a follow-up
    ``parar`` report cleanly that the run is gone."""
    removed: list[Path] = []
    for summary in list_runs(root):
        if summary.status != RunStatus.STALE:
            continue
        for fname in ("executar.pid", "shards.pids"):
            p = summary.saida / fname
            if p.exists():
                p.unlink()
                removed.append(p)
    return removed
