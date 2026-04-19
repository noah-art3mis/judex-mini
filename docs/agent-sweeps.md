# Running sweeps from a Claude Code / agent session

Operational notes for launching, monitoring, and surviving long-running
sweeps driven through an agent harness. Not needed on turns that don't
touch sweeps — read this before kicking one off.

## Context-window pitfalls

A 60-minute sweep in the background will chew through your context
window if you drive it the obvious way. Lessons learned the hard way
on 2026-04-17 (4-sweep session that ended with ~150k tokens of
duplicate log buffer in context):

- **Don't `| tee` the driver's stdout to its log file.** The
  `run_sweep.py` driver already writes everything durable to
  `<out>/sweep.log.jsonl` and `<out>/sweep.state.json` atomically.
  Piping stdout through `tee` means every `TaskOutput` poll returns
  the full buffered log (early-sweep lines repeated each time — the
  buffer flushes slowly). Use `> <out>/driver.log 2>&1` (or simply
  don't redirect and let the agent harness capture stdout) so
  `TaskOutput` only returns the final completion summary.
- **Poll `sweep.state.json`, not `TaskOutput`, for progress.** One
  small Python snippet reading the state file gives you
  `{ok, fail, last_processo, wall}` in ~100 tokens. `TaskOutput` on
  a live sweep returns tens of thousands of tokens of stale stdout.
  Reserve `TaskOutput` for the completion notification (block=true
  with a long timeout; it returns when the background bash exits).
- **Use `run_in_background: true` on the Bash call that launches the
  sweep.** Foreground bash calls time out at 2–10 min; sweeps take
  55–90 min. Background bash gives you a task id you can check on.
- **If something goes wrong, `kill -TERM <pid>` via `pkill -TERM -f
  run_sweep.*<label-fragment>`.** The driver installs SIGTERM
  handlers; it will finish the in-flight process, write
  `sweep.errors.jsonl` + `report.md`, and exit cleanly. The state is
  always `--resume`-safe because per-record writes are atomic.
- **WAF cooldowns matter across sweeps, not just within them.** See
  [`docs/rate-limits.md § Two-layer model`](rate-limits.md#two-layer-model-sweep-v-2026-04-17)
  before stacking paper-era sweeps back-to-back. The short version:
  wait 30–90 min between sweeps, overnight for a full IP reset.

## Surviving session death (the "detached-sweep" pattern)

The Claude Code / Cursor window can die (crash, OOM, reload, explicit
close) without killing the in-flight sweep. This is not accidental —
the launcher is structured to detach from the controlling shell, and
everything durable goes to disk atomically per record. Four structural
pieces make it work:

1. **Detach at launch.**
   `nohup ./scripts/launch_hc_backfill_sharded.sh > runs/active/<dir>/launcher-stdout.log 2>&1 & disown`
   — `nohup` ignores SIGHUP (sent when the terminal closes); `& disown`
   drops the job from the shell's job table so it isn't killed when
   the shell exits. The launcher's `run_sweep.py` children inherit the
   detached state via `nohup`'s parent group.
2. **Persist PIDs.** The launcher writes child PIDs to
   `runs/active/<dir>/shards.pids`. On reconnect, `pgrep -af run_sweep`
   finds them, but the pids file is authoritative when multiple sweeps
   overlap.
3. **Atomic state per record.** `src/sweeps/process_store.py` writes
   `sweep.state.json` via `tempfile → os.replace` (atomic on POSIX) and
   appends to `sweep.log.jsonl` with `fsync` after each record. A
   process killed mid-record loses at most the in-flight record;
   `--resume` skips already-ok records, so driver-restart is safe.
4. **Session-independent alerting.** A cron monitor scheduled via
   `/schedule` polls `sweep.state.json` on a cron expression (e.g.
   `13,43 * * * *`). The cron runs in the harness, not in the window,
   so heartbeats survive window death.

### Reconnecting from a fresh window

```bash
cat runs/active/<dir>/shards.pids                          # discover PIDs
pgrep -af "run_sweep.*<label-fragment>"                    # verify alive
PYTHONPATH=. uv run python scripts/probe_sharded.py \      # read state
    --out-root runs/active/<dir>
cat docs/current_progress.md                               # restore context
# Stop cleanly if needed:
xargs -a runs/active/<dir>/shards.pids kill -TERM
```

### What does NOT survive session death

- Claude Code conversation state (thinking, plans, Bash task ids). The
  `run_in_background` task id is gone with the window. Mitigation: the
  lab-notebook at `docs/current_progress.md` is the out-of-band memory —
  write observations as they happen; the fresh window's first act is
  to read it.
- Cron jobs with a short `expires_after`. Use 7-day expiry (or longer)
  so monitoring outlives the window that scheduled it.
- Any state the driver held in memory but hadn't yet flushed to disk.
  With the current atomic contracts this is <1 record; don't break the
  contract (see `src/sweeps/process_store.py`).
