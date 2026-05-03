"""Backfill ``n_pecas`` from source JSONs into a run-dir sidecar file.

The mono / sharded aggregator falls back to count-only for the
``pecas`` progress-line stage when the live ``executar.state.json``
lacks ``n_pecas`` on its meta records (i.e. the run was launched with
code from before that field existed). This script reconstructs what
the case-meta handler WOULD have stamped, by walking the source
JSONs the handler already wrote, and emits a cluster-wide sidecar
file the aggregator merges in non-destructively.

Why a sidecar (and not patching ``executar.state.json`` directly):
each live shard process holds its state in memory and snapshots it
back to disk at every snapshot interval — so any in-place patch we
write to disk gets clobbered by the next snapshot. The sidecar is a
file the live shards never touch; the aggregator reads both files at
each tick and merges, so the pecas ratio renders without restarting
the run.

Usage::

    uv run python scripts/backfill_n_pecas.py runs/active/<dir>

Reads:
  * ``<run_dir>/shard-*/executar.state.json`` — for case keys with
    meta=ok and missing n_pecas.
  * ``<source_root>/<CLASSE>/judex-mini_<CLASSE>_<pid>-<pid>.json``
    — the case JSON the meta handler wrote at scrape time. Default
    ``data/source/processos`` (per CLAUDE.md § data-layout).

Writes:
  * ``<run_dir>/n_pecas.json`` — atomic; ``{case_key: int}``.
    Re-running on the same run_dir overwrites in place.

Idempotent. Safe to re-run while the live run is ongoing.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Optional

from judex.sweeps.peca_classification import filter_substantive
from judex.sweeps.peca_targets import _iter_case_pdf_targets


def collect_pending_case_keys(run_dir: Path) -> set[str]:
    """Union of meta=ok case keys across every shard's state file
    that don't already carry ``n_pecas``. We only backfill the legacy
    gap; if a shard was launched with new code its meta records
    already have the field and we leave them alone."""
    keys: set[str] = set()
    for sf in run_dir.glob("shard-*/executar.state.json"):
        try:
            d = json.loads(sf.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue  # mid-write race; next backfill run will catch up
        for case_key, case in (d.get("cases") or {}).items():
            if not isinstance(case, dict):
                continue
            meta = case.get("fetch_meta") or {}
            if meta.get("status") != "ok":
                continue
            if meta.get("n_pecas") is not None:
                continue
            keys.add(case_key)
    return keys


def compute_n_pecas(case_key: str, source_root: Path) -> Optional[int]:
    """Replay the meta handler's fan-out count for one case.

    Mirrors the handler's pipeline at ``judex/pipeline/handlers.py
    :_emit_fetch_bytes`` for the no-CLI-filter case (no
    ``--impte-contains``, no ``--doc-type`` allow/exclude — i.e. the
    default for a year-of-HC sweep): walk every peca URL surface,
    drop tier-C procedural docs via ``filter_substantive``, dedup by
    URL. The result is the integer that handler stamped onto each new
    run's meta record at the moment it emitted successors.

    Returns None when:
      * the case key isn't ``<CLASSE>-<pid>`` shaped
      * the source JSON is missing (case meta=ok but JSON not yet
        flushed — rare, surfaces only on a hard-kill resume)
      * the source JSON is malformed (likely a stale half-write)

    Caller treats None as "skip this case" — the sidecar simply
    omits it; the aggregator then keeps falling back to count-only
    for that case. Better than fabricating a wrong number.
    """
    if "-" not in case_key:
        return None
    classe, pid_str = case_key.rsplit("-", 1)
    try:
        pid = int(pid_str)
    except ValueError:
        return None
    path = source_root / classe / f"judex-mini_{classe}_{pid}-{pid}.json"
    if not path.is_file():
        return None
    try:
        item = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if isinstance(item, list):
        # Range files have a list shape; pick the matching record
        # rather than counting across the whole batch.
        item = next((r for r in item if r.get("processo_id") == pid), None)
        if item is None:
            return None
    targets = list(_iter_case_pdf_targets(item))
    targets = filter_substantive(targets)
    # URL dedup matches the handler's final step. Same peca URL can
    # appear via multiple surfaces (andamento + DJe), and the live
    # handler dedupes before counting successors.
    targets = list({t.url: t for t in targets}.values())
    return len(targets)


def backfill(
    run_dir: Path,
    source_root: Path,
    *,
    progress_every: int = 1000,
    progress: bool = True,
) -> dict[str, int]:
    """Compute ``{case_key: n_pecas}`` for every meta=ok case in
    ``run_dir`` whose state record is missing the field. Cases that
    can't be resolved (no source JSON, malformed, etc.) are silently
    omitted — the aggregator handles missing entries the same way as
    missing-from-state."""
    keys = collect_pending_case_keys(run_dir)
    if progress:
        print(
            f"[backfill] {len(keys)} meta=ok cases need n_pecas; "
            f"reading source JSONs from {source_root}",
            file=sys.stderr,
        )
    out: dict[str, int] = {}
    missed = 0
    for i, key in enumerate(sorted(keys)):
        n = compute_n_pecas(key, source_root)
        if n is None:
            missed += 1
            continue
        out[key] = n
        if progress and (i + 1) % progress_every == 0:
            print(f"[backfill]   {i + 1}/{len(keys)}", file=sys.stderr)
    if progress:
        total = sum(out.values())
        print(
            f"[backfill] computed {len(out)} cases; "
            f"missed {missed}; pecas_total={total}",
            file=sys.stderr,
        )
    return out


def atomic_write_json(path: Path, payload: dict) -> None:
    """Write JSON via tempfile + rename so a concurrent reader (the
    live aggregator) never sees a half-written sidecar."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        prefix=path.name + ".", suffix=".tmp", dir=path.parent,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except Exception:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description=(
            "Backfill n_pecas sidecar from source JSONs so the live "
            "aggregator can render the pecas %% on a run that "
            "started before the field existed."
        ),
    )
    ap.add_argument("run_dir", type=Path)
    ap.add_argument(
        "--source-root", type=Path, default=Path("data/source/processos"),
        help="Root of judex-mini_<CLASSE>_<pid>-<pid>.json files "
             "(default: data/source/processos).",
    )
    ap.add_argument(
        "--quiet", action="store_true",
        help="Suppress progress chatter on stderr.",
    )
    args = ap.parse_args(argv)

    if not args.run_dir.is_dir():
        print(f"error: {args.run_dir} is not a directory", file=sys.stderr)
        return 1
    if not args.source_root.is_dir():
        print(
            f"error: --source-root {args.source_root} is not a directory",
            file=sys.stderr,
        )
        return 1

    payload = backfill(
        args.run_dir, args.source_root, progress=not args.quiet,
    )
    if not payload:
        print(
            "[backfill] no entries computed; sidecar not written",
            file=sys.stderr,
        )
        return 1

    sidecar = args.run_dir / "n_pecas.json"
    atomic_write_json(sidecar, payload)
    if not args.quiet:
        print(
            f"[backfill] wrote {sidecar} ({len(payload)} entries; "
            f"sum={sum(payload.values())})",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
