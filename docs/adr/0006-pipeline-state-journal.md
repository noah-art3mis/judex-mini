# ADR-0006: Pipeline state journal — fused snapshot+log Module with log-replay reconciliation

**Status**: Proposed (2026-05-03). Implementation underway as of the 2026-05-03 amendment below — the original D2 deferral on [ADR-0005](0005-unified-pipeline.md) slice 6 has been lifted now that legacy commands (`varrer-processos` / `baixar-pecas` / `extrair-pecas` / `coletar`) are staying alongside the unified pipeline indefinitely. Scope is a single Module deepening inside `judex/pipeline/`; no DAG / scheduler / handler changes. Doesn't block ADR-0005 from flipping to Accepted; the SIGKILL-correctness fix it carries is desirable but not in ADR-0005's validation set.

## Amendments

### 2026-05-03 — Lift D2 deferral; implement now

The original Decision (below) chose **D2** ("wait for slice 6, then fuse") over **D1** ("ship now on `dev`, before slice 6") on the rationale that D1 would require keeping legacy `process_store.py` / `peca_store.py` on a different durability contract than the unified pipeline during the validation window — "two migrations, not one."

That rationale is invalidated by a separate operational decision: **legacy commands are staying alongside the unified pipeline indefinitely** (no slice 6 in the immediate plan). With slice 6 not on the near-term roadmap, the "validation window" framing no longer applies; legacy stores sit on their own contract permanently, the unified pipeline gets the journal contract permanently, and there is no migration between the two — they belong to different code paths.

**Override**: D2 → D1. Implementation begins **now** (2026-05-03), in the worktree at `.claude/worktrees/adr-0006-state-journal/` on branch `worktree-adr-0006-state-journal`. The original Decision section (D1–D8 below) governs the design *content*; this amendment governs only the *timing*. ADR-0005 is **not** modified — slice 6 remains a future option, just not a gate on this ADR.

The "D1: Ship now on `dev`, before slice 6 — Rejected" entry under § Considered alternatives at the deferral question (was branch D) is now **adopted** with the same operational caveat the rejection captured: legacy stores stay on the legacy contract; nothing migrates.

## Context

[ADR-0005](0005-unified-pipeline.md) put the pipeline's durability contract in two places:

- `judex/pipeline/state.py` (340 lines) — `PipelineState`: in-memory canonical state, atomic 5 s snapshots to `executar.state.json`, the `record_meta` / `record_bytes` / `record_text` mutators with `retry_count` auto-increment, and the 9 status/extractor/retry-count getters the scheduler reads to gate re-seeding.
- `judex/pipeline/log.py` (386 lines) — `PipelineLog`: append-only fsynced rows to `executar.log.jsonl`, log row schema construction (`make_log_record`), the legacy `log_render` path that mimics the pre-unified-pipeline tail-of-log shape, and friend-access helpers that re-project from `state._cases` to assemble error fields.

This split was a deliberate slice-1 choice — keep the snapshot side (canonical) clean of log-formatting concerns, keep the log side (observability) free of in-memory-state concerns. Two consequences emerged after slice 5:

1. **SIGKILL recovery is not exact.** Today's load path reads `executar.state.json` only; the `executar.log.jsonl` rows that landed between the last snapshot and the kill are observability-only and don't influence reconstruction. A `kill -9` between snapshots resurrects the run with up to 5 s of completed work missing from in-memory state, which the scheduler will then re-seed and re-execute. ADR-0005 § Validation criteria 3 ("real-resume integration test") is the test that would surface this; it hasn't run yet.
2. **The write path is two-phase.** `_run_one` in `judex/pipeline/scheduler.py:343-394` mutates state via `record_meta` / `record_bytes` / `record_text`, then *re-projects* from state via `_read_task_outcome` / `_read_task_error` / `_read_task_extractor` to assemble the log row, then appends. State and log are not atomically consistent — there's a window where state shows the outcome but the log row hasn't been fsynced. This is the same window that makes (1) impossible to fix without changing the write path.

Five locked design decisions came out of the grilling session that produced this ADR (see § Decisions; full transcript in working-memory and not reproduced here).

## Decision

Fuse `state.py` + `log.py` into a single Module — name and path **unchanged** (`judex/pipeline/state.py`, class `PipelineState`) — that owns both the snapshot and the log, with reconciliation on load and atomic record-and-log on write. Concretely:

### D1. Reconciliation on load (was branch A in grilling — option **A3**)

`PipelineState.open(saida=...)` reads the snapshot, then opens the log and replays every row whose `ts > snapshot.snapshot_at` directly into the in-memory `CaseRecord` slot. After load, in-memory state matches what was last fsynced, **not** what was last snapshotted. Log rows are authoritative payloads on the cold path; snapshot is a fast-path checkpoint, not the canonical source.

### D2. Atomic record-and-log on write (was branch B-forced)

Each `record_meta` / `record_bytes` / `record_text` call performs the in-memory mutation **and** writes the log row in one operation, fsynced before return. The two-phase scheduler pattern (mutate then re-project to assemble log row) is retired. Log row construction moves from `log.py:make_log_record` into the Module's mutators; the scheduler stops calling `_read_task_outcome` / `_read_task_error` / `_read_task_extractor` from `_run_one`.

### D3. Hierarchical case→pool storage (was branch C — option **C2**)

The on-disk shape stays case-keyed at the top level with `meta` / `bytes[url]` / `text[url]` sub-records hanging off it — i.e. today's `CaseRecord` shape survives unchanged. Considered and rejected: a flat per-Pool layout (uniformity at the cost of breaking the natural `case → urls` query pattern the scheduler uses).

### D4. Replay bypasses the live mutators (was branch E — option **E1**)

The cold load+replay path deserialises log rows directly into `CaseRecord` slots via a private `_apply_log_row` helper. It does **not** call `record_meta` / `record_bytes` / `record_text`. This guarantees `retry_count` is restored from the row's stored value rather than re-incremented by the mutator's auto-increment, which would double-count attempts and trip the [ADR-0005](0005-unified-pipeline.md) cap=2 gate spuriously.

The mutator Interface stays live-handler-only — no `from_replay=True` flag. Replay is an internal concern of `open()`, not part of the contract the scheduler/handlers see.

### D5. Module name and path unchanged (was branch F — option **F1**)

The Module stays `judex/pipeline/state.py`, the class stays `PipelineState`. Considered and rejected: `judex/pipeline/journal.py` (renaming to match the new shape) and `judex/coleta/` (promotion to top-level package). F1 keeps churn minimal and matches the pre-existing import surface; the new noun ("journal") doesn't carry enough independent value to justify renaming.

`log.py` is deleted outright (no shim). Its public Interface — `PipelineLog`, `make_log_record`, `LogRecord` — vanishes; callers transition to `PipelineState`'s mutators. The legacy-shaped tail render (`log_render`) moves to a separate sibling Module if it survives, or dies with `log.py` if no caller still needs it.

### D6. Hybrid Interface — typed mutators + frozen view projection

The class surface for `PipelineState` after fusion:

```python
class PipelineState:
    @classmethod
    def open(cls, *, saida: Path, run_id: str | None = None) -> PipelineState: ...

    # Live write path (handler-facing; auto-increments retry_count, fsyncs log row)
    def record_meta(self, case_key, *, status, error=None, wall_s=0.0, regime=None) -> None: ...
    def record_bytes(self, case_key, *, url, status, error=None, doc_type=None,
                     wall_s=0.0, http_status=None, regime=None) -> None: ...
    def record_text(self, case_key, *, url, status, extractor=None, error=None,
                    wall_s=0.0, regime=None) -> None: ...

    # Read path (replaces today's 9 getters: meta_status / bytes_status / text_status /
    # text_extractor / known_bytes_urls / is_meta_complete / is_bytes_complete /
    # is_text_complete / *_retry_count)
    def view(self, case_key) -> CaseView: ...

    # Cold-path lifecycle
    def snapshot(self) -> None: ...
    def save_errors(self) -> None: ...
    def close(self) -> None: ...
```

`CaseView` is a frozen dataclass — one read, then attribute access — replacing the nine separate getter call sites in `seeds_from_targets` and the breaker. The Module-internal `_apply_log_row` and replay loop are private.

### D7. Run-id staleness defence

Snapshot payload and every log row carry a `run_id` (UUID4 allocated by `open()` on first call, or read from existing snapshot on resume). On load, log rows whose `run_id` doesn't match the snapshot's `run_id` are quarantined (raise `StaleLogError`, leaving the operator to investigate) rather than silently replayed. This guards against the failure mode where a snapshot from run A and a log from a later aborted run B end up co-resident in the same `saida/`.

### D8. Schema bump 2 → 3, no backwards-compat shim

Per [`CLAUDE.md § Conventions`](../../CLAUDE.md#conventions). Pre-bump state files cannot be loaded; old runs in `runs/active/` either complete on the legacy code (during the deferral window) or are abandoned at promote time.

## What's NOT in this ADR

- **Multi-process pipeline.** Single-event-loop, single-process is inherited unchanged from ADR-0005.
- **Per-Pool Adapter Protocols.** Considered (was Design B in grilling, rejected). With one consumer (`judex executar` after slice 6) and no live second Adapter for any Protocol, `LogSink` / `SnapshotPolicy` would be speculative seams by [`docs/agents/domain.md`](../agents/domain.md)'s "one Adapter = hypothetical Seam" rule. `PoolSlot` has three live Adapters (portal/sistemas/ocr) but [ADR-0003](0003-surface-3-dje-capture-path.md) Phase 2 (digital_stf as a fourth Pool) is explicitly deferred until a coverage gap demands it. Protocols can be added later when a real second Adapter shows up; the cost of ripping them out preemptively is low.
- **Parametric `record(task, ...)` mutator.** Considered (was Design A in grilling, rejected on this axis). Cuts against [ADR-0005](0005-unified-pipeline.md)'s typed-vocabulary direction (typed `TaskStatus` enum); a wrong `task.kind` plus a payload missing `url` would be a runtime error rather than a type error. Three typed mutators are kept; only the read path collapses (D6's `view()`).
- **Renaming the Module.** Considered (was option F2/F3, rejected). `state.py` keeps its name; CONTEXT.md sharpens its description of the snapshot+log relationship at implementation time, but no new project-canon noun is introduced.

## Open implementation questions (resolved at slice time)

1. **Where does `derive_errors_file` live?** Today it's a free function in `judex/pipeline/log.py` that re-projects from state. Inside the fused Module (as `save_errors`) is the natural home if no other caller needs it; outside (a sibling reader) if it's used by post-hoc analysis. Decide at slice time by searching for callers.
2. **Run-id allocation seed.** Either UUID4 (D7's current sketch) or a deterministic `hash(saida.resolve(), started_at)`. UUID4 is simplest and the staleness check only needs uniqueness, not determinism. Default to UUID4 unless a debugging requirement surfaces.
3. **Does `log_render` survive?** It's the legacy-shaped tail-of-log renderer mentioned in [`CLAUDE.md § Conventions`](../../CLAUDE.md). If still in use at slice time, it moves to a sibling reader Module (`log_render.py`) that opens the journal read-only. If unused, dies with `log.py`.

## Consequences

**Operator-facing.** No CLI surface change. `judex executar --retomar` after a SIGKILL produces the same in-memory state as `--retomar` after a SIGTERM (both restore to last fsynced row). `judex probe --watch` continues to read the snapshot file — its 5 s staleness window is unchanged.

**Scheduler.** `_run_one` in `judex/pipeline/scheduler.py` simplifies: one `state.record_*` call per task, no second-phase log assembly. The 9 getter call sites in `seeds_from_targets` (and any other reader) collapse to one `state.view(case_key)` lookup followed by attribute access.

**Tests.** The mutator contract tests, retry-count auto-increment tests, `is_*_complete` predicate tests, and all scheduler tests gating on `retry_count` survive unchanged (D2's behaviour change is internal). Four new tests are added (priority order):

1. `test_load_recovers_post_snapshot_log_rows` — record → snapshot → record more (log only) → discard in-memory → `open()` → assert all rows recovered. Headline correctness test.
2. `test_replay_is_idempotent` — applying the same log row twice doesn't perturb `retry_count` or any other field. Forces D4 (replay bypasses mutators).
3. `test_load_quarantines_stale_log` — snapshot from run A + log from run B in the same `saida/` → `open()` raises `StaleLogError`. Forces D7.
4. `test_cap_2_holds_across_load_boundary` — record 2 failures, snapshot, kill, `open()`, attempt third → blocked by cap. Pins [ADR-0005](0005-unified-pipeline.md)'s cap=2 across the new load path.

The `snapshot()` roundtrip test gains an assertion that the payload embeds `snapshot_at` and `run_id`. The `load()` test gains "and ignores log rows ≤ snapshot_at."

**CONTEXT.md.** [`CONTEXT.md § Operational vocabulary`](../../CONTEXT.md) currently describes a Coleta as producing "one log (executar.log.jsonl), one state file (executar.state.json)." Sharpen at slice time to "one append-only log (load-bearing for SIGKILL-exact recovery), one periodic snapshot (fast-path checkpoint)." Few-words edit; not pre-emptive.

**Performance.** Cold-path load gets slower (snapshot read + log scan + replay vs. snapshot read alone). Snapshots are pruned at startup once successfully loaded (snapshot is now a fast-path index, not canonical) — but pruning is a future optimisation; first cut keeps the full log forever. Live write path is unchanged in semantics; the per-row fsync was already there in `log.py`.

## Designs considered and rejected

The grilling session produced three parallel sub-agent designs along orthogonal constraints. The rejected ones are pinned here so future agents don't re-derive them:

- **Design A — Minimise (4 entry points)**. Parametric `record(task, ...)` collapsing the three typed mutators. Rejected: cuts against [ADR-0005](0005-unified-pipeline.md)'s typed-vocabulary direction; wrong `task.kind` becomes a runtime error rather than a type error. **Adopted from A**: the `view()` frozen-projection pattern (D6), which doesn't fight typing because it's a read.
- **Design B — Flexibility (3 Adapter Protocols)**. `PoolSlot` / `LogSink` / `SnapshotPolicy` Protocols at the seams. Rejected: two of three are speculative seams by [`docs/agents/domain.md`](../agents/domain.md)'s "one Adapter = hypothetical Seam" rule (`LogSink` has only file + in-memory-test; `SnapshotPolicy` has only `IntervalSnapshot(5.0)`). The third (`PoolSlot`) has three live Adapters but ADR-0003 Phase 2 is deferred. Add Protocols later when a real second Adapter appears.
- **Design C — Common-caller (typed mutators, atomic record+log)**. Adopted as the spine (D1–D4 + D6's typed mutator half). Trade-off: `record_*` signatures widen with `wall_s` / `regime` / `http_status` that the in-memory `CaseRecord` doesn't store but the log row does (they pass through to the row only). Acceptable cost; the alternative — leaving log row construction in the scheduler — preserves the two-phase write coupling D2 retires.

Considered alternatives at the deferral question (was branch D):
- **D1: Ship now on `dev`, before slice 6.** Rejected: requires keeping the legacy `process_store.py` / `peca_store.py` (used by retired commands during the validation window) on a different durability contract than the unified pipeline. Two migrations, not one.
- **D2: Wait for slice 6 (legacy deleted), then fuse.** Adopted. One migration; the only consumer is `judex executar` by then.

## Validation criteria (for flipping to Accepted)

The ADR moves from Proposed to Accepted when:

1. ⏳ The unified pipeline is in place (slices 1–5 of [ADR-0005](0005-unified-pipeline.md) — landed). *Originally read "ADR-0005 is Accepted (slice 6 has landed)"; relaxed by the 2026-05-03 amendment that lifted the slice-6 gate.*
2. ⏳ All four new tests above pass on dev.
3. ⏳ The full unit suite passes (currently 716 as of ADR-0005 slice 5; the four new tests bring the floor to 720).
4. ⏳ Real-SIGKILL integration test: `kill -9` a mid-run Coleta between snapshot intervals, `--retomar`, verify finished output identical to a single-pass run. (This is ADR-0005 § Validation 3 strengthened from SIGTERM to SIGKILL — the SIGTERM variant doesn't differentiate this Module from the legacy split.)
5. ⏳ One full HC-year Coleta on the fused Module finishes at `run quality = acceptable` or better (mirror of ADR-0005 § Validation 4).

## References

- Inherited orchestration: [ADR-0005](0005-unified-pipeline.md).
- Speculative-Seam rule: [`docs/agents/domain.md`](../agents/domain.md).
- No-backwards-compat convention: [`CLAUDE.md § Conventions`](../../CLAUDE.md#conventions).
- Operational glossary: [`CONTEXT.md § Operational vocabulary`](../../CONTEXT.md).
- Live module surface this consolidates: `judex/pipeline/state.py:100` (`PipelineState`), `judex/pipeline/log.py` (`PipelineLog`, `make_log_record`, `log_render`), `judex/pipeline/scheduler.py:343-394` (`_run_one` two-phase write).
