"""Persistent dead-ID store — aggregate NoIncidente observations across sweeps.

A "dead ID" is a `processo_id` that STF's `listarProcessos.asp` returns
with HTTP 200 + empty Location header — the canonical "this ID was never
allocated" signal. The scraper flags these as `status="fail",
error_type="NoIncidente", body_head=""` (see
``judex/sweeps/process_store.py:AttemptRecord``).

Confirmation threshold = ≥ N independent observations, all with empty
``body_head``. A non-empty ``body_head`` on a NoIncidente fail means
the Location header carried some unexpected string — usually a proxy
soft-block, not a genuine STF unallocation — so that observation does
not count toward confirmation.

Outputs:
- ``<classe>.txt`` — sorted one-pid-per-line, for the next sweep's
  filter.
- ``<classe>.candidates.tsv`` — all observed NoIncidente pids with
  observation counts, including still-unconfirmed ones.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "DeadObservation",
    "collect_observations",
    "classify_confirmed",
    "write_dead_id_files",
    "load_dead_ids",
]


@dataclass(frozen=True)
class DeadObservation:
    """One NoIncidente observation from one sweep's state file.

    ``body_head_empty`` is the high-confidence signal: the Location
    header on STF's `listarProcessos.asp` comes back verbatim as the
    empty string for a genuinely-unallocated processo_id.
    """

    sweep_path: Path
    body_head_empty: bool


def _iter_state_files(roots: Iterable[Path]) -> Iterator[Path]:
    for root in roots:
        if not root.exists():
            continue
        yield from root.rglob("sweep.state.json")


def collect_observations(
    roots: Iterable[Path],
    classe: str,
) -> dict[int, list[DeadObservation]]:
    """Scan sweep state files under ``roots``; group NoIncidente by processo."""
    by_pid: dict[int, list[DeadObservation]] = {}
    for state_path in _iter_state_files(roots):
        try:
            state = json.loads(state_path.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        if not isinstance(state, dict):
            continue
        for rec in state.values():
            if not isinstance(rec, dict):
                continue
            if rec.get("classe") != classe:
                continue
            if rec.get("status") != "fail":
                continue
            if rec.get("error_type") != "NoIncidente":
                continue
            pid = rec.get("processo")
            if not isinstance(pid, int):
                continue
            by_pid.setdefault(pid, []).append(DeadObservation(
                sweep_path=state_path,
                body_head_empty=(rec.get("body_head") == ""),
            ))
    return by_pid


def classify_confirmed(
    observations: dict[int, list[DeadObservation]],
    *,
    min_observations: int = 2,
    require_empty_body: bool = True,
) -> list[int]:
    """Return sorted pids meeting the confirmation threshold."""
    confirmed: list[int] = []
    for pid, obs in observations.items():
        if require_empty_body:
            empties = sum(1 for o in obs if o.body_head_empty)
            if empties >= min_observations:
                confirmed.append(pid)
        elif len(obs) >= min_observations:
            confirmed.append(pid)
    return sorted(confirmed)


def write_dead_id_files(
    observations: dict[int, list[DeadObservation]],
    *,
    out_dir: Path,
    classe: str,
    min_observations: int = 2,
) -> tuple[Path, Path]:
    """Write ``<classe>.txt`` (confirmed) + ``<classe>.candidates.tsv`` (all)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    txt_path = out_dir / f"{classe}.txt"
    tsv_path = out_dir / f"{classe}.candidates.tsv"

    confirmed = classify_confirmed(observations, min_observations=min_observations)
    if confirmed:
        txt_path.write_text("\n".join(str(p) for p in confirmed) + "\n")
    else:
        txt_path.write_text("")

    lines = ["processo_id\tn_observations\tn_empty_body"]
    for pid in sorted(observations):
        obs = observations[pid]
        n = len(obs)
        n_empty = sum(1 for o in obs if o.body_head_empty)
        lines.append(f"{pid}\t{n}\t{n_empty}")
    tsv_path.write_text("\n".join(lines) + "\n")

    return txt_path, tsv_path


def load_dead_ids(path: Path) -> set[int]:
    """Read a ``<classe>.txt`` file (one pid per line) → set of ints.

    Missing file → empty set. Blank lines and ``#``-comments ignored.
    Invalid integer lines silently skipped (conservative — a malformed
    entry should not be treated as "dead").
    """
    if not path.exists():
        return set()
    out: set[int] = set()
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        try:
            out.add(int(line))
        except ValueError:
            continue
    return out
