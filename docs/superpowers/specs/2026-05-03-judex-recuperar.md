# `judex recuperar`: one-command residual recovery for finished runs

Status: **draft, 2026-05-03.** Closes Gap #1 in
[`docs/recovery-patterns.md`](../../recovery-patterns.md).

> **Naming note (2026-05-05).** Originally specified and shipped as
> `judex limpar`. Renamed to `judex recuperar` to align the operator
> verb with the internal recovery vocabulary (`recovery_recipe`,
> `RECOVERY_RECIPES`, `Recipe`, `Action`) and to stop suggesting
> destructive cleanup. No backwards-compat shim — the old name is gone.

## Goal

A finished `judex executar` run leaves a **residual** — rows in
`executar.errors.jsonl` whose status is not `ok`. Today the operator
recovers that residual by:

1. Recognising the run is sharded vs. monolithic.
2. Per shard, looking at `executar.errors.jsonl`.
3. Mentally classifying each row's `(kind, status)` into a recovery
   bucket.
4. Hand-rolling a `for` loop that fans the right command across each
   bucket.

This works (`docs/recovery-patterns.md` documents it) but it has too
many manual steps for a routine post-run gesture. The shell loop is
also opaque to anyone reading later — the *intent* ("recover the
transient OCR cases") is encoded as a `for` loop over `shard-*/`, not
as a verb. **The goal is a single command that closes the residual:
walk the run dir once, partition by bucket, dispatch the right tool
per bucket, and emit a one-line summary.**

```bash
uv run judex recuperar runs/active/hc2020-sharded/
# → recovered: 532 transient · 0 cross_stage · 0 provider_switched · 1862 terminal_dropped
```

This is the same residual the user-quoted snippet recovers; `recuperar`
is a wrapper, not new physics.

## Non-goals

- **Not** a replacement for `--retentar-de` — it composes on top of it.
- **Not** auto-recovery during a live run. `recuperar` runs *post*-run, on
  a `<run_dir>` whose scheduler has exited. (Mid-run recovery is the
  scheduler's job via per-task cap=2.)
- **Not** a state-file rewriter. `recuperar` reads state + errors, writes
  nothing to them. The recoveries it dispatches mutate state via the
  same `--retentar-de` path the operator uses by hand.
- **Not** a quality-spotchecker. The "is the extracted text actually
  good?" question (Gap #4 in `recovery-patterns.md`) is out of scope —
  `recuperar` only acts on classifier output, not text plausibility.
- **Not** a way to bypass `RETRY_CAP=2`. If a row's `retry_count` is
  already at cap, `recuperar`'s dispatched `--retentar-de` still no-ops on
  it. Escalation past cap is manual (`--forcar`).

## Surface

```
judex recuperar <run_dir> [OPTIONS]

Arguments:
  run_dir          Directory of a finished `judex executar` run.
                   Auto-detects layout: sharded (shard-*/) or
                   monolithic (executar.errors.jsonl at top).

Options:
  --apply          Actually launch dispatched recoveries. Default
                   prints the plan and exits (dry-run is the safe
                   default since `recuperar` spawns detached children).
  --provedor TEXT  Provider hint forwarded to the dispatched
                   `judex executar --retentar-de` invocations.
                   [default: auto]
  --nao-perguntar  Skip the confirmation prompt under --apply.
                   Required for cron / nohup invocations.
```

## Auto-detection

```python
def discover_run_dirs(run_dir: Path) -> list[Path]:
    """Return the list of dirs containing executar.errors.jsonl.

    Sharded:    [run_dir/shard-a, run_dir/shard-b, ...] sorted by suffix.
    Monolithic: [run_dir]
    """
```

Decision rule: if `<run_dir>/shard-*/` matches *any* dir with an
`executar.errors.jsonl` inside, treat as sharded. Otherwise monolithic.
Empty residuals (no errors.jsonl at all) yield an empty bucket list and
print "nothing to recover" — not an error.

## Classification + partitioning

Single source of truth: `judex.pipeline.log.classify_unified_error`,
which already maps `(status)` → `transient | terminal | cross_stage |
ok` for the unified vocabulary. `recuperar` does not introduce a new
classifier.

The partition is `(kind, classify_unified_error(row))` plus a small
`(kind, status)` override table for the actionable terminals:

| Bucket key                              | Recovery action                                               |
|-----------------------------------------|---------------------------------------------------------------|
| `(extract_text, transient)`             | `replay`               — `--retentar-de`                      |
| `(fetch_bytes,  transient)`             | `replay`               — `--retentar-de`                      |
| `(fetch_meta,   transient)`             | `replay`               — `--retentar-de`                      |
| `(extract_text, terminal, "empty")`     | `provider_switch`      — print hint (manual `--forcar`)       |
| `(extract_text, cross_stage, "no_bytes")`| `refetch_upstream`    — print hint (manual `baixar-pecas`)    |
| `(fetch_meta,   terminal, "unallocated_pid")` | `confirmed_unallocated` — drop, count             |
| `(fetch_bytes,  terminal, "empty")`     | `terminal_dropped`     — drop, count                          |
| anything else                           | `terminal_dropped`     — drop, count                          |

Why `replay` is the only auto-dispatched action in v1: it's the only
action that the unified pipeline's existing `--retentar-de` filter
already gates correctly (transient-only, by `targets_from_errors_jsonl`).
The other actions need either an inverted filter (`--retentar-de` for
empty rows) or a different binary (`baixar-pecas`); shipping them as
auto-dispatch would either expand `executar`'s flag surface or add a
second binary's worth of plumbing. v1 prints the hint and lets the
operator decide; v2 can promote `provider_switch` and `refetch_upstream`
to auto-dispatch once the filter knobs land.

## Dispatch

For each shard dir (or the single mono dir) that has at least one
`replay`-bucket row, `recuperar --apply` spawns:

```bash
nohup uv run judex executar \
    --retentar-de <dir>/executar.errors.jsonl \
    --saida <dir> \
    --provedor <--provedor flag> \
    --nao-perguntar \
    > <dir>/recuperar.log 2>&1 &
```

Detached, one PID per source dir. PIDs are written to
`<run_dir>/recuperar.pids` (mirroring `shards.pids`). Exits immediately
after spawning — operator monitors with `judex acompanhar <run_dir>` or
`pgrep -af 'judex executar'`.

This matches the existing fan-out idiom (the `for d in shard-*; do
nohup … &` loop). `recuperar` is the named verb for that pattern.

## Summary line

```
recovered: <N1> transient · <N2> cross_stage · <N3> provider_switched · <N4> confirmed_unallocated · <N5> terminal_dropped
```

Where:
- `transient` = rows dispatched via `replay` (whether or not the
  dispatched run completed — the count is what was *handed off*).
- `cross_stage` = rows in the `refetch_upstream` bucket (printed-hint
  count; not auto-dispatched in v1).
- `provider_switched` = rows in the `provider_switch` bucket (same).
- `confirmed_unallocated` = `(fetch_meta, unallocated_pid)` count.
- `terminal_dropped` = everything else terminal.

Sum of all five = total errors.jsonl row count across the run.

Under `--dry-run` (default), the line is the same format prefixed
`would-recover: …` to make the no-action read clear.

## Exit codes

- `0` — plan computed and (under `--apply`) all spawns succeeded.
- `2` — invalid args / `<run_dir>` missing or not a finished run.
- `3` — empty residual (no errors files anywhere). Distinct from `0`
  so cron can skip the next step.

## Implementation

New module `judex/sweeps/recuperar.py`:

```python
def discover_run_dirs(run_dir: Path) -> list[Path]: ...
def classify_residual(dirs: list[Path]) -> dict[Bucket, list[ErrorRow]]: ...
def plan_recoveries(buckets: dict[Bucket, list[ErrorRow]], *, provedor: str) -> list[Spawn]: ...
def format_summary(buckets: dict[Bucket, list[ErrorRow]], *, dry_run: bool) -> str: ...
def execute_recoveries(plan: list[Spawn], pids_path: Path) -> None: ...
```

Pure functions (no side effects) for the first four; only
`execute_recoveries` spawns subprocesses. This keeps the unit tests
free of subprocess mocking.

New Typer command `recuperar` in `judex/cli.py` calls these in order.

Tests at `tests/unit/test_recuperar.py`:
- `discover_run_dirs` returns sharded list when `shard-*/` exists.
- `discover_run_dirs` returns `[run_dir]` for mono.
- `classify_residual` partitions a synthetic errors.jsonl correctly,
  including the override cells (`extract_text/empty` → `provider_switch`,
  not `terminal_dropped`).
- `plan_recoveries` emits one `Spawn` per source dir with at least one
  replay row, none for empty source dirs.
- `format_summary` matches the spec line format on a known input.
- Dry-run plan against the real `runs/active/hc2020-sharded/` (532
  transient, 826 terminal, 1036 unallocated) — pinned bucket counts.

## Sequencing

1. Spec ✓ (this file).
2. Tests (red).
3. Module (green).
4. Typer command + help text.
5. Smoke against `runs/active/hc2020-sharded/`.
6. Update `docs/recovery-patterns.md` Gaps section: cross out Gap #1,
   point at `judex recuperar`.

No promotion to `main` until smoke is clean and the unit suite is
green.
