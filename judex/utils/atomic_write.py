"""Atomic-write helper for state files.

CLAUDE.md calls the atomic-write contract "load-bearing" — the way to
keep it load-bearing is one helper with one test. Replaces ad-hoc
``tmp + os.replace`` blocks previously inlined in
``judex/sweeps/store.py``, ``judex/reports/state.py``, and
``judex/reports/watchlist.py``.

The temp file lives next to the target so ``os.replace`` stays a
same-filesystem rename (atomic on POSIX). Suffix includes the PID so
two processes writing the same path don't collide on the temp file.

``fsync=True`` is for state that must survive an OS-level crash mid-
sweep (the sweep stores). Default-off is enough for end-of-run reports
where torn state on a kernel panic is acceptable.
"""

from __future__ import annotations

import os
from pathlib import Path


def atomic_write_text(path: Path, text: str, *, fsync: bool = False) -> None:
    tmp = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    with tmp.open("w", encoding="utf-8") as f:
        f.write(text)
        if fsync:
            f.flush()
            os.fsync(f.fileno())
    os.replace(tmp, path)
