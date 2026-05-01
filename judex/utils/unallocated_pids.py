"""Persistent unallocated-pid store — aggregate `status="unallocated"`
observations across sweeps.

A processo_id is **unallocated** when STF's `listarProcessos.asp` returns
HTTP 200 with no `incidente=<n>` in the redirect Location — the canonical
"this number was never bound to an incidente" signal. The scraper records
these as ``status="unallocated"`` (with empty ``body_head``) on the
``AttemptRecord``; non-empty ``body_head`` NoIncidente responses stay in
the ``status="fail" + error_type="NoIncidente"`` bucket because they may
be proxy soft-blocks rather than genuine unallocations. See
``docs/adr/0002-distinguish-unallocated-processo-id-from-scrape-failure.md``.

Confirmation threshold = ≥ N independent observations. With the body_head
boundary applied at write time (run_sweep.py), every ``status="unallocated"``
observation already implies ``body_head==""``, so the predicate here is
single-field.

Outputs:
- ``<classe>.txt`` — sorted one-pid-per-line, for the next sweep's
  ``--excluir-nao-alocados`` filter.
- ``<classe>.candidates.tsv`` — all observed unallocated pids with
  observation counts, including still-unconfirmed ones; also the
  source the warehouse builder reads to populate the
  ``unallocated_pids`` table.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "UnallocatedObservation",
    "collect_observations",
    "classify_confirmed",
    "write_unallocated_pid_files",
    "load_unallocated_pids",
]


@dataclass(frozen=True)
class UnallocatedObservation:
    """One ``status="unallocated"`` observation from one sweep's state file."""

    sweep_path: Path


def _iter_state_files(roots: Iterable[Path]) -> Iterator[Path]:
    for root in roots:
        if not root.exists():
            continue
        yield from root.rglob("sweep.state.json")


def collect_observations(
    roots: Iterable[Path],
    classe: str,
) -> dict[int, list[UnallocatedObservation]]:
    """Scan sweep state files under ``roots``; group unallocated pids by processo."""
    by_pid: dict[int, list[UnallocatedObservation]] = {}
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
            if rec.get("status") != "unallocated":
                continue
            pid = rec.get("processo")
            if not isinstance(pid, int):
                continue
            by_pid.setdefault(pid, []).append(
                UnallocatedObservation(sweep_path=state_path)
            )
    return by_pid


def classify_confirmed(
    observations: dict[int, list[UnallocatedObservation]],
    *,
    min_observations: int = 2,
) -> list[int]:
    """Return sorted pids meeting the confirmation threshold."""
    return sorted(
        pid for pid, obs in observations.items() if len(obs) >= min_observations
    )


def write_unallocated_pid_files(
    observations: dict[int, list[UnallocatedObservation]],
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

    lines = ["processo_id\tn_observations"]
    for pid in sorted(observations):
        lines.append(f"{pid}\t{len(observations[pid])}")
    tsv_path.write_text("\n".join(lines) + "\n")

    return txt_path, tsv_path


def load_unallocated_pids(path: Path) -> set[int]:
    """Read a ``<classe>.txt`` file (one pid per line) → set of ints.

    Missing file → empty set. Blank lines and ``#``-comments ignored.
    Invalid integer lines silently skipped (conservative — a malformed
    entry should not be treated as unallocated).
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
