# ADR-0004: `judex coletar` — total-run orchestrator with status-aware retry and per-stage gates

**Status**: Proposed (2026-05-02). Design grilled in the 2026-05-02 session; implementation pending.

## Context

A backfill of a (**classe**, processo_id range) today requires three forward sweeps in sequence — `varrer-processos` → `baixar-pecas` → `extrair-pecas` — followed by **ad-hoc** retry passes when transient failures (WAF 403s, Fly OCR 502s, SSL-EOF saturation tail) leave residuals. Two operational pain points:

1. **No canonical "total run" unit.** Operators chain stages with bash launchers (`runs/active/backfill-hc2025-2026-05-02/launcher-stdout-v2.log`); each chain decides when/how to retry. Recent history (HC 2026, 2026-05-01) shows a single forward `extrair-pecas` produced 383 `provider_error: 502` rows and required two manual retry cycles (`extrair-retry/` and `extrair-retry-v2/` against the same directory) before the residual stabilised. Both the *need* for retries and the *number of cycles* are implicit, not encoded.
2. **No status-aware retry.** `targets_from_errors_jsonl` blindly replays every line in `errors.jsonl`, including deterministic terminal failures (`processo_id não alocado`, real `404`s, `no_bytes` cross-stage failures). A loop iterating "until errors.jsonl is empty" never converges on stages with terminal residuals; today's bash chains avoid this by hard-coding "exactly one retry" — which the HC 2026 datapoint shows is sometimes too few.

The decisions below are surprising-without-context (a future reader will wonder "why is the cap exactly 2 and not unlimited?") and hard-to-reverse once operators internalise the chain shape.

## Decision

Add a new top-level Typer command **`judex coletar`** that owns the full backfill of a (classe, range) as a six-stage interleaved chain:

```
varrer  →  varrer-retry  →  baixar  →  baixar-retry  →  extrair  →  extrair-retry
```

Each retry stage replays only the prior forward stage's transient residual, classified by a new `judex/sweeps/error_triage.py` module. Cap of 2 retry cycles per stage with early-exit on residual=0 or no shrink. Per-stage transient-rate gate (default 2%) aborts the chain rather than firing retries against a systemic break.

Detailed locks:

| Decision               | Locked answer                                                                  |
|------------------------|--------------------------------------------------------------------------------|
| Chain shape            | Per-stage interleave (forward + retry per stage, in order)                     |
| Retry cap              | 2 cycles per stage; early-exit if residual=0 or did not shrink between cycles  |
| Replay filter          | Status-aware via `error_triage.classify_error(stage, row) → "transient" \| "terminal" \| "cross_stage" \| "ok"` |
| Classifier location    | Read-side at replay time (write path untouched)                                |
| Replay function rename | `targets_from_errors_jsonl → targets_for_replay`; old name dropped (no shim)   |
| Cooldown               | None between forward and retry                                                 |
| Retry config           | Inherits forward-pass proxy posture (sharded forward → sharded retry); `extrair-retry` uses `--provedor auto --forcar` |
| Cross-stage residual   | Reported as out-of-scope; no second baixar-retry within a coleta               |
| Output layout          | `<saida>/{varrer,varrer-retry-1,varrer-retry-2,baixar,baixar-retry-1,baixar-retry-2,extrair,extrair-retry-1,extrair-retry-2}/` + `coletar.log` + `coletar.state.json` + `REPORT.md` |
| Per-stage gate         | Default 2% transient rate per stage; per-stage configurable; abort chain on trip |
| "Done" definition      | Pragmatic: cap exhausted regardless of residual                                |
| Run quality            | `clean` (residual=0) / `acceptable` (≤1%) / `degraded` (1–5%) / `broken` (>5%) |

## Why

1. **Closes the implicit-retry gap.** The HC 2026 datapoint (forward extrair → 383 transients → retry-v1 leaves 84 → retry-v2 closes them) is encoded in the cap=2 + early-exit semantics. Operators no longer need to remember to launch retries.
2. **Status-aware classifier converges.** Today's `targets_from_errors_jsonl` replays `unallocated` rows forever (status-blind). Filtering to `transient`-only makes the loop terminate naturally — terminal rows are dropped, cross-stage rows are reported out-of-scope, only transients re-enter.
3. **Per-stage gate catches systemic breaks early.** Healthy transient rates observed across HC 2025/2026 sit at <0.1% (varrer, baixar) and 5–10% (extrair, dominated by Fly OCR baseline). A gate at 2% catches varrer's cookies-block / proxy-pool-dead failure modes; the same threshold trips on an anomalous extrair Fly bounce (HC 2026's 7.3% would have aborted), forcing the operator to investigate provider stability rather than burn retry cycles against a saturated dependency.
4. **Pragmatic "done" + run-quality classifier separates mechanical completion from quality grading.** `done` means cap exhausted; quality is a separate signal in `REPORT.md`. This avoids the strict-definition trap where `done` never fires when a transient tail persists.

## Consequences

- **New CLI surface.** `judex coletar` joins `varrer-processos` / `baixar-pecas` / `extrair-pecas` / `fazer-backup` / `atualizar-warehouse` / `exportar` / `validar-gabarito` in `judex/cli.py`. Per-stage commands remain as primitives — operators can still run them stand-alone for ad-hoc work.
- **`error_triage.py` becomes the single source of truth for what counts as transient.** Classifier patterns must stay in sync with what `peca_store` and `process_store` write. A regression test scans recent run dirs and asserts every observed `(status, error)` tuple maps to a known kind — fails loudly when an unmapped pattern appears, instead of silently classifying as `terminal` (the safe default for unknown rows).
- **Operational vocabulary added to CONTEXT.md** — `Coleta`, `Error triage`, `Transient residual`, `Cross-stage residual`, `Transient gate`, `Run quality` — this commit.
- **Sharded inheritance has a merge step.** Per-shard `errors.jsonl` files must be merged before retry replay (since the retry runs as a single sharded sweep against the union). `coletar` orchestrates this; the operator does not see it.
- **`coletar` resume tracks (stage, cycle).** `coletar.state.json` records `{stage, cycle, finished}`; `--retomar` picks up at the right cycle without restarting from varrer. Each child sweep dir has its own `state.json` for intra-cycle resume; the coletar layer composes those.
- **Existing bash chains keep working.** No deprecation; `runs/active/backfill-*` directories produced by the bash launchers remain readable. `judex coletar` is additive.
- **Forecasts unchanged.** `--prever` already covers per-stage cost; `coletar`'s cost forecast is the sum of per-stage forecasts. The cap=2 retries add at most ~2× the per-stage cost in the worst case (rare).

## Considered alternatives

- **Bash launcher with Python helpers (status quo refined).** Rejected: convergence loop and status-aware filtering both require Python; bash glue around them decays under refactors and has no test surface.
- **Convergent loop without a cap (iterate until residual=0).** Rejected: terminal rows persist forever; either the loop never terminates or it requires the same status-aware classifier *and* a "did the residual shrink?" check — i.e., it converges to cap=2-with-early-exit anyway, just spelled differently. Cap=2 makes the worst-case wall and cost predictable.
- **Persisted `kind` field in `errors.jsonl` (write-side classification).** Rejected: only one consumer of `errors.jsonl` exists in this codebase (replay), so the schema cost is not justified. Read-side classification is reusable for analytics later. Avoids touching `peca_store.py` / `process_store.py`, which `CLAUDE.md § Don't break these` flags as load-bearing atomic-write contracts.
- **Stage-specific retry caps (e.g., baixar gets 3 cycles since bytes is load-bearing).** Rejected: empirical residuals at <0.1% (HC 2025 baixar = 10/28k = 0.04%) don't justify the per-stage policy carve-out. Operator can drain manually via `baixar-pecas --retentar-de`.
- **Auto-trigger second baixar-retry from extrair's `no_bytes` residual.** Rejected: would re-introduce variable-cap retry logic specifically for the bytes stage, conflicting with cap=2 uniformity. Surfaced as a `cross_stage_residual` count instead — operator sees the signal and chooses.
- **Uniform global gate (e.g., "abort if any stage > 5%").** Rejected: extrair's healthy 5–10% would mis-fire a global 5% gate on every healthy run. Per-stage with a uniform default (2%) and per-stage override knobs is the right shape — anchors on each stage's healthy baseline while still catching anomalies.
- **Strict "done" definition (residual must be 0).** Rejected: conflicts directly with cap=2 (Q2 lock). Strict either re-introduces unbounded retry or never fires `done`, making chain completion unobservable.
