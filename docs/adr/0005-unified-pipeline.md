# ADR-0005: Unified pipeline — single-process DAG scheduler replacing the three-command chain

**Status**: Proposed (2026-05-03). Supersedes [ADR-0004](0004-coleta-orchestrator-with-status-aware-retry.md) on the orchestration axis; inherits its `error_triage.classify_error` classifier and per-stage **Transient gate** (now per-Pool, default 2%) verbatim. Lives on `explore/unified-pipeline`. Flips to **Accepted** when slice 6 (legacy command removal) lands; validation criteria below. Full design context in [`docs/superpowers/specs/2026-05-02-unified-pipeline.md`](../superpowers/specs/2026-05-02-unified-pipeline.md).

## Context

`judex coletar` (ADR-0004) collapsed the three forward sweep commands into one chain, but the operator still saw six substages, six per-substage logs, six per-substage state files, and a launcher process tree. Resuming a partial run required understanding which substage was failing and replaying the right `errors.jsonl` against the right CLI.

The chain was also strictly serial across stages — every case completed `varrer` before any case started `baixar`. So the three load-bearing endpoints (`portal.stf.jus.br`, `sistemas.stf.jus.br`, OCR backend) were never simultaneously saturated; in any given hour two of the three were idle.

## Decision

Replace the three forward commands (`varrer-processos` → `baixar-pecas` → `extrair-pecas`) and the `coletar` orchestrator with a single fire-and-forget command — `judex executar` — backed by a three-pool asyncio DAG scheduler. Concretely:

1. **DAG, not chain.** Per-case task graph (`fetch_meta` → `fetch_bytes` → `extract_text`); tasks emit successors. No global stage gate.
2. **Three independent worker pools** (`portal`, `sistemas`, `ocr`) — each with its own concurrency knob, throttle, circuit breaker, and (for `portal`/`sistemas`) proxy posture.
3. **Single-process asyncio.** Bounded `asyncio.Semaphore` per pool; sync handlers run on the default threadpool via `asyncio.to_thread`. Multi-process is a v2 question only if benchmarks force it.
4. **One log, one state file, one PID, one resume point.** State is held in memory, snapshotted to disk every 5 s; the append-only log (`executar.log.jsonl`) is fsynced per row.
5. **Storage contract unchanged.** Source JSONs (`data/source/processos/<classe>/<incidente>.json`) and the PDF four-file quartet (`data/raw/pecas/`, `data/derived/pecas-texto/`) are bit-identical to the legacy chain's outputs. `validar-gabarito` is the regression test.
6. **Reuse ADR-0004's classifier verbatim.** `error_triage.classify_error` and the **Transient gate** (now per-Pool, default 2%) carry over unchanged.
7. **Retire `Sharded mode` and `shard_launcher.py`.** Concurrency is per-Pool (`--portal-concurrencia` / `--sistemas-concurrencia` / `--ocr-concurrencia`); proxies are per-Pool (`--proxies-portal` / `--proxies-sistemas`).
8. **No backwards-compat shims.** When validation completes, `varrer-processos` / `baixar-pecas` / `extrair-pecas` / `coletar` are deleted outright (slice 6).

## What's NOT inherited from ADR-0004

- The orchestrator-of-three-commands mechanism is retired.
- The per-stage launcher pattern (one subprocess per substage) is retired.
- `cross_stage` residual is renamed to `cross_pool` residual to match the per-Pool framing.

## Open issues (resolved during this ADR's commit batch)

### 1. ✅ ~~Cap=2 retry cap missing~~ (fixed 2026-05-03)

ADR-0004 specifies "cap of 2 retry cycles per stage with early-exit when the residual is empty or stops shrinking." The unified pipeline initially had **no cap**: `scheduler.seeds_from_targets` re-seeded every transient-classified task on every `--retomar` invocation indefinitely.

Fixed in this ADR's commit batch:

- Each task record in `executar.state.json` now carries an integer `retry_count` field (auto-incremented by `record_meta` / `record_bytes` / `record_text` on every re-recording).
- `judex/pipeline/state.py` exposes `meta_retry_count` / `bytes_retry_count` / `text_retry_count` getters.
- `_is_retryable_status` in `judex/pipeline/scheduler.py` gains a `retry_count` parameter; returns `False` when `retry_count >= RETRY_CAP` (=2) regardless of status class.
- `seeds_from_targets` reads the per-task retry count from state and threads it through.
- `SCHEMA_VERSION` bumped 1 → 2 to make the field's presence explicit; pre-bump state files cannot be loaded (per `CLAUDE.md § Conventions`: no backwards-compat shims).

Pinned by three tests in `tests/unit/test_pipeline_scheduler.py`: `test_retry_count_auto_increments_on_re_recording` (mutator contract), `test_seeds_skips_meta_at_retry_cap` (cap gates re-seeding for fetch_meta), `test_seeds_retries_meta_below_retry_cap` (the dual — under-cap tasks still re-seed), `test_seeds_skips_bytes_and_text_at_retry_cap` (same gate applies to all three pools).

### 2. ✅ ~~`handle_fetch_meta` lacks storage-level idempotence~~ (fixed 2026-05-03)

`handle_fetch_bytes` (line 268) and `handle_extract_text` (line 322) both check the on-disk cache before doing the expensive work. `handle_fetch_meta` did not — every invocation called `scrape_processo_http` unconditionally, so a hard-kill resume against state stale at the 5 s snapshot interval re-hit `portal.stf.jus.br` (the WAF-hottest endpoint) for every case whose JSON had been written but whose meta outcome hadn't been snapshotted.

Fixed in this ADR's commit batch: `handle_fetch_meta` now reads the cached `<source_dir>/<classe>/judex-mini_<classe>_<n>-<n>.json` if it exists, populates the case dict from disk, records `meta=ok`, and emits `fetch_bytes` successors via the same `_emit_fetch_bytes` helper used by the post-scrape success path. `--forcar` bypasses the guard for explicit re-scrape. Pinned by `tests/unit/test_pipeline_handlers.py::test_handle_fetch_meta_skips_scrape_when_case_json_exists` (asserts no HTTP call when JSON pre-exists) and `…_falls_through_to_scrape_on_malformed_cache` (asserts a half-written cache falls back to fresh scrape rather than silently emitting zero successors).

### Remaining blockers

Both originally-flagged code-correctness issues are now resolved. The remaining blockers between Proposed and Accepted are the **operational validation criteria** below (real-resume integration test, full HC-year Coleta, `validar-gabarito` parity).

## Consequences

**Operator-facing.** One submission (`judex executar --csv year.csv --saida runs/active/<label>`), one log, one state file, one PID. `tail -f executar.log.jsonl` is the canonical live monitor (matches the legacy `launcher-stdout.log` shape per CLAUDE.md § Conventions). Resume is uniform: `--retomar` requeues every non-`ok` task whose status is transient (subject to the cap=2 once it lands).

**Validation window.** Legacy commands remain operable in parallel until slice 6. The two paths produce a **Coleta** but are *not mutually resumable* (different run-dir layouts, different state-file shapes). Pick one path per `(classe, processo_id range)`. Surfaced explicitly in [CONTEXT.md § Flagged ambiguities](../../CONTEXT.md).

**Vocabulary changes** (full glossary updates in [CONTEXT.md § Operational vocabulary](../../CONTEXT.md)):

- `Sweep` rebound to "one Pool's body of work" (no longer "one execution of varrer/baixar/extrair").
- `Coleta` rebound to "one execution of `judex executar`" (no longer "six sweeps in per-stage interleave").
- `Pool` and `Task` added as project canon.
- `Sharded mode` retired in favor of `Proxy mode` (per-Pool); `Shard` retired entirely.
- `Cross-stage residual` renamed to `Cross-pool residual`.
- **Regime** broadened from WAF-throttle-relationship to "failure-rate trajectory of any Sweep"; explicitly observation-only telemetry under the unified pipeline (the circuit breaker is the actor).

**Testing.** Three-command integration tests are retired alongside the commands in slice 6. Pipeline unit tests (34 as of slice 5, in `tests/unit/test_pipeline_{state,scheduler,runner,pools}.py`) replace them. `validar-gabarito` remains the regression for output identity.

## Validation criteria (for flipping to Accepted)

The ADR moves from Proposed to Accepted when **all** of the following hold:

1. ✅ Unit suite passes (716 tests as of slice 5).
2. ✅ Slice-5 receipts: 50-case real-STF Coleta produces clean output with measurable wall savings vs. the equivalent `coletar` chain (slice 5 measured 64% savings, partly cache-aided; honest expectation on fully-fresh runs is the analytical 15–25% per the spec § Win 4).
3. ⏳ Real-resume integration test: SIGTERM a mid-run Coleta, `--retomar`, verify finished and output identical to a single-pass run.
4. ⏳ One full HC-year Coleta via `judex executar` (target: HC 2026 Q1, ~1k cases) finishing at **`run quality = acceptable`** or better.
5. ⏳ `validar-gabarito` green over the full HC ground-truth set after a unified Coleta.
6. ✅ Cap=2 retry cap implemented and pinned (resolved 2026-05-03 — see § Open issues).

When all six are checked: bump Status to Accepted (date), squash slice 6 (legacy command removal) onto `dev`, mark ADR-0004 fully Superseded.

## References

- Full design context: [`docs/superpowers/specs/2026-05-02-unified-pipeline.md`](../superpowers/specs/2026-05-02-unified-pipeline.md) — 11 Decisions to lock, framework rejections (Airflow / Dagster / Prefect / Ray), risk register, anti-decisions list.
- Inherited classifier: [ADR-0004](0004-coleta-orchestrator-with-status-aware-retry.md).
- Operational glossary: [CONTEXT.md § Operational vocabulary](../../CONTEXT.md).
