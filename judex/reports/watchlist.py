"""Watchlist file parser + per-case snapshot I/O.

The watchlist is a human-maintained text file — one process per line
as ``<CLASSE> <NUMERO>`` (e.g. ``HC 158802``). ``#`` starts a comment,
blank lines are ignored, inline ``# …`` trailing comments are supported.

Snapshots of each watched case are written under a caller-supplied
``root`` directory (conventionally ``state/watchlist/``) as
``<CLASSE>_<NUMERO>.json``. They're the "last-seen" state used by
``watch_diff.diff_watched`` to decide what changed since yesterday.
"""

from __future__ import annotations

import json
from pathlib import Path

from judex.utils.atomic_write import atomic_write_text


def parse_watchlist(path: Path) -> list[tuple[str, int]]:
    """Parse the watchlist file into ``(classe, numero)`` tuples.

    Missing file → empty list (fresh install). Malformed lines raise
    ``ValueError`` with the offending line number so the user can fix
    the file rather than silently losing a case.
    """
    if not path.exists():
        return []

    entries: list[tuple[str, int]] = []
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) != 2 or not parts[1].isdigit():
            raise ValueError(f"watchlist line {lineno}: expected 'CLASSE NUMERO', got {raw!r}")
        entries.append((parts[0], int(parts[1])))
    return entries


def snapshot_path(classe: str, numero: int, *, root: Path) -> Path:
    return root / f"{classe}_{numero}.json"


def load_snapshot(classe: str, numero: int, *, root: Path) -> dict | None:
    path = snapshot_path(classe, numero, root=root)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def save_snapshot(classe: str, numero: int, item: dict, *, root: Path) -> None:
    path = snapshot_path(classe, numero, root=root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(item, ensure_ascii=False, indent=2, sort_keys=True)
    atomic_write_text(path, payload)
