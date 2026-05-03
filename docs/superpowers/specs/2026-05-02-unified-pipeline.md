# Unified pipeline: replace `varrer-processos` + `baixar-pecas` + `extrair-pecas` with a DAG scheduler

Status: **draft, exploration on `explore/unified-pipeline`**. Author: 2026-05-02. Companion to (not replacement of) ADR-0004.

## Goal

Collapse the three forward sweeps into a single fire-and-forget command (`judex executar`). The operator submits a target set once and walks away; on return the run is either done or in a clearly documented failure state, with **one log, one PID, one state file, one resume point**. No more "kick off varrer, wait, kick off baixar, wait, kick off extrair, oh wait the breaker tripped on extrair, retry from errors" choreography.

Concretely, the command is backed by a scheduler that:

1. Treats per-case work as a **DAG of tasks** (`FetchCaseMetadata` → `FetchPecaBytes` → `ExtractText`), not three serial passes — so the operator interface (one command) and the runtime structure (concurrent pools) match.
2. Maintains **three independent worker pools** (`portal`, `sistemas`, `ocr`), each with its own concurrency, throttle, proxy posture, and circuit breaker — so a stall in one pool doesn't take the whole run down.
3. Emits the same on-disk artefacts as today (the four-file quartet under `data/raw/pecas/` + `data/derived/pecas-texto/`, the case JSON under `data/source/processos/<classe>/`). The runtime changes; the storage contract does not.

The architecture is positioned as a *refinement* on top of `coletar` (which already delivers fire-and-forget for the 3-command chain via subprocess composition). The unified pipeline collapses `coletar`'s six substages — three forward + three retry — into a single process with one log and one state file, eliminating the "child sweep dir" substructure entirely. **The win is operational, not primarily throughput.**

## Relationship to ADR-0004 (`coletar`)

ADR-0004 proposes `judex coletar`, which composes the three existing commands as a six-stage chain (`varrer → varrer-retry → baixar → baixar-retry → extrair → extrair-retry`) with a status-aware classifier and per-stage transient-rate gate. That ADR is on the **retry/quality axis**.

**Status as of this spec's writing: `coletar` exists as committed, tested code on `explore/unified-pipeline`** (commits `0abeef7 docs(adr)` → `671abfb docs(progress)`), but has NOT been merged to `dev` yet. `dev` HEAD is `e996617`. The 6-commit batch (ADR-0004, replay classifier, coletar orchestrator, Fly OCR, progress doc) is production-ready but pending promotion. Promotion is independent of this exploration — `coletar` can land on `dev` whenever, and the unified pipeline is evaluated as a *successor* either way.

This spec is on the **throughput/concurrency axis**. `coletar` is still serial: every case goes through `varrer` for the whole target list before any case starts `baixar`. The unified pipeline pipelines per-case: case 2's metadata is fetched while case 1's peças are downloading and case 0's text is being extracted.

The two specs interact as follows:

| Concept                              | ADR-0004 (`coletar`)                                | This spec (unified pipeline)                                        |
|---|---|---|
| Scope                                | Orchestrate 3 commands + retries                    | Replace 3 commands with 1 scheduler                                  |
| Retry semantics                      | cap=2, status-aware, per-stage gate                  | Inherits ADR-0004's classifier + gate; applies them per-pool        |
| Concurrency model                    | Sequential phases                                    | Concurrent DAG with bounded per-pool semaphores                      |
| Wall time per year-of-HC             | Sum of 3 phases (~27–30 h)                           | Bottleneck-limited (~12–15 h projected)                              |
| Test surface                          | Classifier + cap + gate                             | All of the above + scheduler restart semantics                       |
| When written                         | Today                                               | Today                                                                |

**Sequencing decision (locked by this spec):** `coletar` has shipped; no waiting required. The unified pipeline reuses `coletar`'s `error_triage.classify_error` and per-stage gate logic verbatim — no point reimplementing them. If the prototype clears the 40% bar (§ Validation step 3), the unified pipeline supersedes `coletar`'s chain shape but keeps its classifier. If the prototype fails, `coletar` is the final form and this branch is dropped — `coletar`'s code on `dev` is already production-ready in that outcome.

This makes the `coletar` work not-wasted in either outcome.

## Why

### Win 1 (headline) — Single fire-and-forget surface

`coletar` collapses three commands into one chain, but the operator still sees six substages, six per-substage logs, six per-substage state files, and a launcher process tree with multiple children. Resuming a partial run requires understanding which substage you're in.

`judex executar` collapses all of that into **one process, one log file, one state file, one PID**. Resume is uniform: `--retomar` reads the state file, finds tasks whose status isn't `ok`, requeues them, runs. There is no "which substage are we resuming from" question because there are no substages — there are only tasks, each tagged with their pool.

This is the load-bearing benefit. It's qualitative (no benchmark passes/fails), and it accumulates: every backfill saved from the cognitive overhead of six substages compounds the operator's confidence that long runs are tractable.

### Win 2 — Continuous tri-bottleneck saturation across targets

Today's manual choreography ("kick off 2025-A while 2024-B is still running") is the operator's job. Get it wrong and one of the three IPs sits idle for hours. `coletar` doesn't fix this — each `coletar` instance still drives the three stages serially.

Unified scheduler: enqueue (HC-2025 ∪ HC-2026 ∪ HC-2027) into one process and the scheduler keeps all three pools saturated. Cross-target parallelism is automatic, not a choreography ritual. **This is the closest thing the rewrite has to a "throughput" win**, and even here the win is the operator not having to choreograph it, not the absolute speedup.

### Win 3 — Fail-isolation per pool

`mistral` quota exhaustion currently kills `extrair-pecas` mid-run; under `coletar` it trips the per-stage gate and aborts the chain. With per-pool breakers in the unified scheduler, the `ocr` pool pauses while `portal` and `sistemas` keep draining their queues. The DAG state survives; OCR resumes when quota resets without losing the upstream work — the run never has to "abort and restart."

### Win 4 — Within-target pipelining (bonus, not headline)

A year-of-HC sweep at the unified scheduler runs all three pools concurrently against a single target set. Steady-state throughput is bottleneck-bound: `min(portal_rate, sistemas_rate / avg_pecas_per_case, ocr_rate / avg_pecas_per_case)`.

Honest math: for this workload the bottleneck is **always sistemas** because peças/case (~8) × per-task wall (~3 s direct-IP) dominates the per-case portal cost. The pipelining ceiling is bounded by `1 − max(a, b, c) / (a + b + c)`. For typical anchors that ceiling is **15–25% wall-time reduction** vs. fully sequential, not the 40–55% an earlier draft of this spec claimed. At proxy concurrency it stays in the same band; OCR-heavy runs (Mistral / Chandra) drop the win further as OCR comes to dominate total wall.

This is real but secondary. If fire-and-forget is the goal, the 15–25% bonus is gravy; the rewrite would still pay off without it.

### Win 5 — Adaptive scheduling (deferred to v2)

Out-of-scope for v1, but the architecture enables it: when `sistemas` 403-storms, the scheduler can prioritise emitting more `FetchCaseMetadata` from the next target year to keep `portal` busy, rather than blocking on a stalled `sistemas` queue. Today's design has no place to put that logic.

## Non-goals

- **No change to on-disk layout.** Source JSONs stay at `data/source/processos/<classe>/<incidente>.json`. PDF cache stays as the four-file quartet (`<sha1>.pdf.gz`, `<sha1>.txt.gz`, `<sha1>.elements.json.gz`, `<sha1>.extractor`) under `data/raw/pecas/` + `data/derived/pecas-texto/`. The runtime changes; the storage contract does not. Validated via `tests/ground_truth/*.json` continuing to pass.
- **No change to the case-parsing or peça-classification logic.** `scraper._decode`, `extract_partes`, `peca_classification.filter_substantive`, `peca_targets.collect_peca_targets`, `lawyer_canonical` — all reused as library code by the new scheduler.
- **No change to ADR-0004's `error_triage` module.** It lands first, the scheduler imports it.
- **No change to the warehouse, exports, backups, validators.** `atualizar-warehouse`, `exportar`, `fazer-backup`, `validar-gabarito` are out of scope; they do not change.
- **No backwards-compat shims.** Per `CLAUDE.md § Conventions`, when the unified pipeline lands, `varrer-processos` / `baixar-pecas` / `extrair-pecas` are removed outright. No deprecation warnings, no convenience wrappers, no aliases. Sharded launchers (`shard_launcher.py`) are removed; sharding is internal to the scheduler.
- **No change to `--prever` per-command in the interim.** While `coletar` ships and the prototype is being validated, per-command forecasts remain. If unified pipeline lands, `--prever` becomes a single forecast that models all three pools in parallel.
- **No multi-process scheduler in v1.** Single-process asyncio with bounded semaphores. OCR pool delegates to subprocess workers when the provider is CPU-bound (`pypdf`, `tesseract`); to async HTTP for API providers (`mistral`, `chandra`, `gemini`). Multi-process scheduler is a v2 question only if a single Python process can't drive all three pools at proxy concurrency (anchor: HC 2024 single-process `varrer-processos` sustained 4.2 req/s with 16 shards — well within asyncio's range).

## Architecture

```
                    ┌──────────────────────────┐
                    │   target enumeration     │   (CSV / range / errors-replay)
                    └────────────┬─────────────┘
                                 ▼
                    ┌──────────────────────────┐
                    │  Scheduler (asyncio)     │
                    │                          │
                    │  ┌────────────────────┐  │
                    │  │  Task queue (per-  │  │
                    │  │  pool FIFO; bounded│  │
                    │  │  buffer)           │  │
                    │  └─────────┬──────────┘  │
                    │            │             │
                    │  ┌─────────┼──────────┐  │
                    │  ▼         ▼          ▼  │
                    │ Portal  Sistemas    OCR  │
                    │ Pool    Pool        Pool │
                    │ (sema   (sema       (sema│
                    │  K1)     K2)         K3) │
                    └────┬────────┬─────────┬──┘
                         │        │         │
                         ▼        ▼         ▼
                    ┌──────────────────────────┐
                    │  PipelineState           │   (per-case DAG progress;
                    │  on-disk JSON,           │    snapshot-not-rewrite, à la
                    │  atomic snapshot)        │    peca_store post-2026-04-30)
                    └──────────────────────────┘
```

### Worker pools

Each pool exposes the same interface:

```python
class Pool:
    name: str                     # "portal" | "sistemas" | "ocr"
    concurrency: int              # asyncio.Semaphore bound
    throttle: ThrottlePolicy      # per-pool sleep/backoff
    breaker: CircuitBreaker       # per-pool 403/quota trip
    proxies: ProxyPool | None     # portal & sistemas only

    async def run(self, task: Task) -> TaskResult: ...
```

The throttle and breaker are the existing `judex/sweeps/throttle.py` / `circuit_breaker.py` machinery, lifted out of the per-command drivers and parameterised per pool.

### Tasks

```python
@dataclass(frozen=True)
class Task:
    kind: Literal["fetch_meta", "fetch_bytes", "extract_text"]
    case_key: tuple[str, int]       # (classe, processo_id)
    payload: dict                    # task-specific args
    pool: str                        # routing tag
```

Three concrete kinds:

1. **`fetch_meta(classe, processo_id)`** — `pool="portal"`. Calls existing `judex/scraping/scraper.py`. On success, parses peça URLs via `peca_targets.collect_peca_targets` + `peca_classification.filter_substantive`, emits one `fetch_bytes` task per URL. Writes the source JSON to `data/source/processos/<classe>/<incidente>.json`.
2. **`fetch_bytes(url, sha1)`** — `pool="sistemas"`. Calls existing `judex/scraping/pdf_cache.py`. On success, emits one `extract_text` task. Writes `<sha1>.pdf.gz`.
3. **`extract_text(sha1, provedor)`** — `pool="ocr"`. Calls existing `judex/scraping/ocr/dispatch.py`. Terminal task. Writes `<sha1>.txt.gz` + `<sha1>.elements.json.gz` + `<sha1>.extractor`.

Each task is idempotent at the storage level: re-running a task with the same arguments produces the same on-disk result (or skips, per `--retomar` / `--forcar`).

### Scheduler loop

Single asyncio loop. Three coroutines, one per pool, each:

```python
async def pool_worker(pool: Pool, queue: asyncio.Queue):
    async with asyncio.Semaphore(pool.concurrency):
        while task := await queue.get():
            async with pool.semaphore:
                result = await pool.run(task)
                state.record(task, result)
                for follow_up in derive_follow_ups(task, result):
                    queues[follow_up.pool].put_nowait(follow_up)
                queue.task_done()
```

Backpressure: each pool's queue is bounded (e.g., `maxsize=1000`). When `sistemas` queue is full, `portal` workers block on `put_nowait`, naturally pacing `fetch_meta` to the rate `sistemas` can drain. Prevents the scheduler from materialising 100k pending bytes-fetches in memory.

### State

`PipelineState` is one JSON file per `--saida` directory:

```jsonc
{
  "schema_version": 1,
  "started_at": "2026-05-02T14:00:00Z",
  "cases": {
    "HC-252920": {
      "fetch_meta":   {"status": "ok", "ts": "..."},
      "fetch_bytes": {
        "<sha1_a>": {"status": "ok",       "ts": "..."},
        "<sha1_b>": {"status": "http_403", "ts": "...", "error": "..."}
      },
      "extract_text": {
        "<sha1_a>": {"status": "ok", "extractor": "pypdf", "ts": "..."}
      }
    }
  }
}
```

Snapshot-not-rewrite: state is held in memory, snapshotted to disk every N seconds (or on shutdown), atomic via `tempfile → os.replace`. This is the same lesson learned in `peca_store.py` on 2026-04-30 — per-record rewrites cap throughput; periodic snapshot does not.

Restart semantics: on startup, load state, enumerate targets, skip any task whose `status == "ok"` (and, for `extract_text`, whose recorded `extractor == --provedor`). Everything else is enqueued.

### Sharding

V1: single-process. Concurrency knobs:

- `--portal-concurrencia N` (default: 1 direct-IP, scales with `--proxies-portal FILE`)
- `--sistemas-concurrencia N` (default: 1 direct-IP, scales with `--proxies-sistemas FILE`)
- `--ocr-concurrencia N` (default: 4 for CPU providers, 8 for API providers)

Proxies attach per-pool, not per-shard. The proxy pool is a list; the worker semaphore picks the next free proxy on each task. This deletes the entire `shard_launcher.py` machinery — sharding becomes a concurrency knob, not a process-spawning subsystem.

V2 (only if benchmarked-to-be-needed): multi-process scheduler with shared state-store.

## CLI

```
uv run judex executar \
    # INPUT MODE (one of)
    -c HC -i 252000 -f 253000
    --csv alvos.csv
    --retomar-de <state.json>           # resume from prior run

    # POOL CONFIG
    --portal-concurrencia 16 --proxies-portal config/proxies-portal.txt
    --sistemas-concurrencia 16 --proxies-sistemas config/proxies-sistemas.txt
    --ocr-concurrencia 4 --provedor pypdf

    # STAGE FILTER (re-run a single pool against existing state)
    --apenas-estagio {meta,bytes,text}
    --forcar                             # ignore sidecar/state on filtered stage

    # ERROR-REPLAY (composes with ADR-0004's classifier)
    --replay-de <state.json>             # transient-only, per error_triage

    # EXECUTION
    --saida runs/active/<date>-<label>
    --rotulo <label>
    --dry-run
    --nao-perguntar
    --retomar
    --janela-circuit 50 --limiar-circuit 0.8
```

`--apenas-estagio text` is the new way to spell "re-extract a year with chandra" — it filters to `extract_text` tasks only, keeping the other pools idle. Equivalent to today's `extrair-pecas --csv … --provedor chandra --forcar`.

`--replay-de` plus `error_triage.classify_error` reproduces ADR-0004's retry semantics: only `transient` rows are re-enqueued; `terminal` and `cross_stage` are reported. Per-pool gate (default 2%) trips only that pool.

## Migration plan (the one we discussed)

1. **Design note** (this file). Lock the architecture and the success criterion.
2. ~~`coletar` lands first~~ — already on `explore/unified-pipeline` (commits `0abeef7` → `671abfb`); promotion to `dev` is mechanical.
3. **Scheduler scaffold + smoke test.** `scratch/pipeline_prototype.py` (already in this worktree). Three asyncio.Queues, three pool worker coroutines, mock-mode smoke test that validates correctness without spending WAF budget. **Done.** Mock confirmed scheduler terminates cleanly, processes all expected tasks, saturates the bottleneck pool. (The earlier "~150 lines, half a day" budget held.)
4. ~~Decision point on throughput threshold~~ — removed; the success criterion is ergonomic, not a benchmark gate. The mock-mode work was still useful: it surfaced the pipelining ceiling math that this spec now reflects.
5. **Real implementation.** New module `judex/pipeline/`. Imports `error_triage` and pool primitives from `judex/sweeps/`. Adds `judex executar` to `judex/cli.py`. Persistent state (snapshot-not-rewrite), signal handlers, breaker integration, proxy pools.
6. **Ergonomic validation.** Run `judex executar` on a recent backfill target (e.g., HC 2026 Q1). Verify the six fire-and-forget invariants in § Validation hold. `validar-gabarito` must remain green. Wall-time ratio vs. an equivalent `coletar` run goes in the run's `report.md` as an artefact.
7. **Removal.** Delete `varrer-processos` / `baixar-pecas` / `extrair-pecas` / `coletar` from `judex/cli.py`. Delete `shard_launcher.py`, `run_sweep.py`, `baixar_pecas.py`, `extrair_pecas.py` driver modules (parsing/extraction logic stays as library code). Delete the per-stage drivers' tests. Update `CLAUDE.md`, `docs/cost-estimates.md`, `docs/peca-sweep-conventions.md`, `docs/agent-sweeps.md`, `docs/data-layout.md`. One squash commit on `dev`.

Step 7 is the one that must NOT be skipped or softened. Per `CLAUDE.md § Conventions`, no backcompat shims; the old commands die when the new one ships.

## Validation

The criterion is **ergonomic**, not a benchmark. The unified pipeline succeeds if all of the following hold for a real backfill against an HC year:

1. **One submission.** The operator runs `judex executar --csv year.csv --saida runs/active/<label>` and walks away. No follow-up commands needed for the run to complete. (Errors that need human triage are surfaced; transient retries happen inside the scheduler.)
2. **One log.** A single `executar.log` (or `tail -f launcher-stdout.log`) tells the operator what's happening across all three pools. No need to multiplex three `tail -f`s.
3. **One state file.** A single `executar.state.json` describes per-case task status. `--retomar` is uniform: requeue anything whose status isn't `ok`.
4. **One PID.** Killing the process kills the whole run cleanly. State flushes on signal.
5. **Resume across pool failures.** If the OCR API quota dies overnight, the run pauses cleanly; `--retomar` the next day finishes without re-running portal or sistemas tasks that already succeeded.
6. **Output artefacts identical to today.** `validar-gabarito` stays green; the four-file quartet contents and source JSONs match what the 3-command chain would have produced for the same input.

The throughput win (~15–25% per-target, plus continuous tri-bottleneck saturation across targets) is **not** part of the success criterion. It's a bonus measured post-hoc and reported, not a gate.

### Soft sanity check (optional)

Before declaring the implementation done, run one comparison on a 50-case HC slice: unified pipeline vs. `coletar` chain on the same slice, both at the operator's preferred connectivity. Report the wall-time ratio in the run's `report.md`. Use this only as evidence in case anyone wonders later "did the rewrite at least *not* make things worse" — not as a gate.

## Risks

| risk                                                                            | mitigation                                                                                          |
|---|---|
| asyncio scheduler can't saturate three pools from one process                   | Step-3 prototype measures this directly. If sustained throughput < single-pool baseline, escalate to multi-process v2 (out of scope for v1). |
| State-snapshot races on shutdown                                                | Single writer (the scheduler), atomic `tempfile → os.replace`, signal handlers flush before exit. Same contract as `peca_store` post-2026-04-30. |
| DAG state harder to reason about during incidents                               | `judex probe --out-root` + `judex analisar-regimes` get a `--por-pool` flag. Per-pool throughput / regime trajectory is visible. Pin via integration test that captures a known-good regime trajectory and asserts the analyser reproduces it from the unified log. |
| Per-pool breakers don't compose well (e.g., portal-trip needs sistemas to know) | Pools are independent by design; cross-pool signalling is *not* added in v1. If a pattern emerges where it's needed, surface in v2. |
| Provider switching footgun (`--apenas-estagio text` typo'd → re-scrapes)        | `--apenas-estagio` *required* when `--provedor` differs from any value already in state. CLI guards before launch; tested. |
| Migration touches too many docs at once                                         | Step 7 is one squash commit, but `CLAUDE.md` updates land alongside the implementation, not after. |
| `coletar`'s implementation work feels wasted if unified ships                   | It isn't — `error_triage` and per-stage gate are reused verbatim. The chain-shape work is shed; the classifier work is permanent. |
| Branch lives indefinitely without merging                                       | Kill criterion (§ Validation) is binary. If step-3 prototype fails the 0.60 bar, branch is closed within the same week, no "let's iterate." |

## Decisions to lock

1. **`coletar` ships first.** Sequencing locked above. The unified pipeline is exploratory; `coletar` is committed.
2. **Single command name: `judex executar`.** Portuguese, parity with existing command names. Not `pipeline`, not `run`, not `sweep`.
3. **DAG, not pipeline-of-stages.** Per-case task graph; tasks emit their successors. No global "stage 1 done, advance to stage 2" gate.
4. **Single-process asyncio in v1.** Multi-process is a v2 question only if benchmarks force it.
5. **State is one snapshot file per `--saida`.** No per-task file. Snapshot, not per-record rewrite.
6. **Storage contract unchanged.** Four-file quartet stays. Source JSONs stay. `validar-gabarito` is the regression test.
7. **No backcompat.** When unified ships, `varrer-processos` / `baixar-pecas` / `extrair-pecas` / `coletar` are removed.
8. **Success criterion is ergonomic, not throughput.** The unified pipeline ships if the six fire-and-forget invariants in § Validation hold on a real backfill. Wall-time ratio vs. `coletar` is reported as an artefact, not as a gate. (Earlier draft locked a `t_proto / t_baseline ≤ 0.60` throughput gate; that gate is mathematically unreachable for this workload's bottleneck shape and was the wrong frame for what the rewrite is actually buying.)
9. **Reuse ADR-0004's `error_triage`.** The unified pipeline's `--replay-de` semantics are exactly ADR-0004's retry semantics, applied per-pool instead of per-stage.
10. **Portuguese flag names.** `--apenas-estagio`, `--portal-concurrencia`, `--sistemas-concurrencia`, `--ocr-concurrencia`, `--proxies-portal`, `--proxies-sistemas`, `--provedor`, `--forcar`, `--retomar`, `--rotulo`, `--saida`, `--nao-perguntar`. English kept for `--dry-run` and short flags `-c/-i/-f`.
11. **Asyncio + bounded semaphores, NOT a DAG framework.** Considered Airflow, dbt, Prefect, Dagster, Ray — all rejected. dbt is the wrong layer (SQL-on-warehouse). Airflow is the wrong shape (time-of-day batch with static DAGs and minute/hour-granularity tasks; this workload is per-record streaming with dynamic task emission and sub-second tasks at ~120k/year-of-HC volume — Airflow's metadata DB and scheduler are not designed for that). Prefect 2 / Dagster are closer-fit but cost ~10× operational complexity (server, agents, state DB) for a single-machine scraper, and their retry primitives don't know about pool-scoped 403 budgets — we'd write custom retry/backoff inside their abstractions anyway. Ray is wrong scale. The load-bearing complexity is per-pool throttle/breaker logic that's already in `judex/sweeps/` and tuned to STF's WAF behaviour; the right move is to compose those existing modules into a thin asyncio scheduler, not to wrap them in a generic DAG runtime that doesn't know about WAF reputation.

## Open questions (to resolve before step 5, not before step 3)

- **Proxy assignment policy.** Round-robin per task, or sticky-per-case? Sticky reduces session-cookie churn but hampers concurrency. Default round-robin until a workload exhibits the pain.
- **OCR pool with mixed providers.** Can a single run mix providers (e.g., pypdf for tier-A, chandra for tier-B)? V1: no — one `--provedor` per run. V2 maybe, driven by tier-aware re-extraction needs.
- **Reporting cadence.** Per-pool live progress every 5 s? Every record? Match `tail -f launcher-stdout.log` shape exactly so existing operator habits transfer.
- **`judex probe` evolution.** Currently sharded-only. With unified pipeline, sharding is internal — does `probe` watch one run dir and break out per-pool, or does it stay sharded-aware? Lean toward the former.
- **Cost forecasting.** Today's `--prever` is per-command. Unified `--prever` needs to model `min(portal, sistemas/peças, ocr/peças)` and emit a single bottleneck-limited estimate. Math lives in `judex/utils/cost.py`; new function `forecast_unified(targets, pool_config)`.

## Anti-decisions (explicitly NOT in scope)

- Adaptive scheduling (Win 5). Architecture supports it; v1 does not implement it. No "scheduler observes pool starvation and reorders queue."
- Multi-process workers. Single-process asyncio in v1.
- Mixed providers per run.
- Cross-pool signalling beyond per-pool breakers.
- Storage redesign. Four-file quartet stays.
- Content-addressing (`sha256(bytes)` vs. `sha1(url)`). Out of scope, same as it was for the OCR-knob spec.
