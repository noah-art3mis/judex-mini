"""One-shot migration: flip legacy `status="fail" + error_type="NoIncidente"
+ body_head==""` records to the new `status="unallocated"` shape.

Walks every `sweep.state.json` under `--runs-root` (and every `sweep.log.jsonl`
record by replay) and rewrites in place using atomic_write_text. Idempotent:
records already in the new shape are left untouched.

After this runs, the aggregator at `judex/utils/unallocated_pids.py` only
reads `status="unallocated"`; the legacy multi-condition predicate is gone.
See ADR-0002.

Usage:

    uv run python scripts/migrate_unallocated_status.py --runs-root runs/

    # Dry run (count what would change, write nothing):
    uv run python scripts/migrate_unallocated_status.py --runs-root runs/ --dry-run
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from judex.utils.atomic_write import atomic_write_text


def _is_legacy_unallocated(rec: dict) -> bool:
    return (
        rec.get("status") == "fail"
        and rec.get("error_type") == "NoIncidente"
        and rec.get("body_head") == ""
    )


def _flip(rec: dict) -> dict:
    """Return a copy with the new status; clears the now-redundant error fields."""
    out = dict(rec)
    out["status"] = "unallocated"
    out["error"] = None
    out["error_type"] = None
    return out


def migrate_state_file(path: Path, *, dry_run: bool) -> int:
    """Rewrite a sweep.state.json in place. Returns count of flipped records."""
    try:
        state = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return 0
    if not isinstance(state, dict):
        return 0

    flipped = 0
    new_state: dict = {}
    for k, rec in state.items():
        if isinstance(rec, dict) and _is_legacy_unallocated(rec):
            new_state[k] = _flip(rec)
            flipped += 1
        else:
            new_state[k] = rec

    if flipped and not dry_run:
        atomic_write_text(
            path,
            json.dumps(new_state, ensure_ascii=False, indent=0),
            fsync=True,
        )
    return flipped


def migrate_log_file(path: Path, *, dry_run: bool) -> int:
    """Rewrite a sweep.log.jsonl in place. Returns count of flipped records.

    The log is the canonical durable record (state.json is reconstructed from
    it on store init), so it must be migrated too — otherwise the next process
    that opens the store replays legacy shape and overwrites the migrated
    state.
    """
    if not path.exists():
        return 0
    flipped = 0
    out_lines: list[str] = []
    with path.open() as f:
        for raw in f:
            line = raw.strip()
            if not line:
                out_lines.append("")
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                out_lines.append(raw.rstrip("\n"))
                continue
            if isinstance(rec, dict) and _is_legacy_unallocated(rec):
                out_lines.append(json.dumps(_flip(rec), ensure_ascii=False))
                flipped += 1
            else:
                out_lines.append(raw.rstrip("\n"))

    if flipped and not dry_run:
        atomic_write_text(path, "\n".join(out_lines) + "\n", fsync=True)
    return flipped


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--runs-root", type=Path, action="append",
        help="Directory to walk (recursively) for sweep state + log files. "
             "Repeatable. Default: runs/",
    )
    ap.add_argument(
        "--dry-run", action="store_true",
        help="Count what would change; do not write. Useful for "
             "estimating impact before committing.",
    )
    args = ap.parse_args(argv)

    roots = args.runs_root or [Path("runs")]
    total_state = 0
    total_log = 0
    n_state_files = 0
    n_log_files = 0
    for root in roots:
        if not root.exists():
            continue
        for state_path in root.rglob("sweep.state.json"):
            n_state_files += 1
            total_state += migrate_state_file(state_path, dry_run=args.dry_run)
        for log_path in root.rglob("sweep.log.jsonl"):
            n_log_files += 1
            total_log += migrate_log_file(log_path, dry_run=args.dry_run)

    suffix = " (dry run, no writes)" if args.dry_run else ""
    print(
        f"migrated{suffix}: {total_state} state records across {n_state_files} files; "
        f"{total_log} log records across {n_log_files} files"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
