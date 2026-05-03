# Unified pipeline: replace `varrer-processos` + `baixar-pecas` + `extrair-pecas` with a DAG scheduler

Status: **draft, exploration on `explore/unified-pipeline`**. Author: 2026-05-02. Companion to (not replacement of) ADR-0004.

## Goal

Collapse the three forward sweeps into a single command (`judex executar`) backed by a scheduler that:

1. Treats per-case work as a **DAG of tasks** (`FetchCaseMetadata` → `FetchPecaBytes` → `ExtractText`), not three serial passes.
2. Maintains **three independent worker pools** (`portal`, `sistemas`, `ocr`), each with its own concurrency, throttle, proxy posture, and circuit breaker.
3. Drives all three pools concurrently against a single target set, so the slowest pool sets the wall-clock — not the sum of three sequential phases.
4. Emits the same on-disk artefacts as today (the four-file quartet under `data/raw/pecas/` + `data/derived/pecas-texto/`, the case JSON under `data/source/processos/<classe>/`). The runtime changes; the storage contract does not.

If the prototype (§ Validation) does not show ≥40% wall-time reduction vs. the current 3-command chain on a real workload, **this branch is killed and `coletar` (ADR-0004) ships instead**.

## Relationship to ADR-0004 (`coletar`)

ADR-0004 proposes `judex coletar`, which composes the three existing commands as a six-stage chain (`varrer → varrer-retry → baixar → baixar-retry → extrair → extrair-retry`) with a status-aware classifier and per-stage transient-rate gate. That ADR is on the **retry/quality axis**.

**Status as of this spec's writing: `coletar` is already shipped.** Local-`dev` is 6 commits ahead of `origin/dev` with the orchestrator, replay classifier, and Fly OCR fallback all landed (`0abeef7 docs(adr)` → `671abfb docs(progress)`). The sequencing question is moot; `coletar` exists. The unified pipeline is therefore evaluated as a *successor*, not a *concurrent alternative*.

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

### Win 1 — Within-target pipelining

A year-of-HC sweep today does ~15k metadata fetches, then ~15k×~8 PDF byte fetches, then ~15k×~8 text extractions in three serial phases. Wall-time is the sum of three independent rate limits.

In the DAG model, case 2's `FetchCaseMetadata` runs concurrently with case 1's `FetchPecaBytes` runs concurrently with case 0's `ExtractText`. Steady-state throughput becomes:

```
throughput = min(
    portal_rate,
    sistemas_rate / avg_pecas_per_case,
    ocr_rate     / avg_pecas_per_case,
)
```

Anchor numbers (from `judex/utils/cost.py` + recent reports):

- `portal_rate` ≈ 0.33 req/s direct-IP, 4.2 req/s with 16-shard proxies (HC 2024/2025 overnight averages).
- `sistemas_rate` ≈ 0.33 req/s direct, comparable proxy speedup.
- `ocr_rate` (`pypdf`) ≈ 10 req/s local; (`mistral`) ≈ 0.29 req/s sync; (`chandra`) ≈ 0.07 req/s sync.

For a year-of-HC at proxy concurrency: **projected wall ≈ 12–15h vs. observed 27–30h serial**. ~50% reduction.

For `pypdf` extraction (free, local), ocr_rate is so far above the WAF rates that ocr never bottlenecks; pipelining gives near-pure 50% reduction. For `mistral`/`chandra`, ocr starts dominating; pipelining still wins because the WAF stages aren't paying for the OCR wall.

### Win 2 — Continuous tri-bottleneck saturation across targets

Today's manual choreography ("kick off 2025-A while 2024-B is still running") is the operator's job. Get it wrong and one of the three IPs sits idle for hours.

Unified scheduler: enqueue (HC-2025 ∪ HC-2026 ∪ HC-2027) and the scheduler keeps all three pools saturated. Cross-target parallelism is automatic, not a choreography ritual.

### Win 3 — Fail-isolation per pool

`mistral` quota exhaustion currently kills `extrair-pecas` mid-run. With per-pool breakers, `ocr` pool pauses while `portal` and `sistemas` keep draining their queues. The DAG state survives; OCR resumes when quota resets without losing the upstream work.

ADR-0004's per-stage transient-rate gate maps directly: per-pool gate trips only that pool, not the whole sweep.

### Win 4 — One observability surface

`judex executar` emits one progress stream with per-pool breakdowns. `judex probe --watch` becomes the single live monitor instead of three `tail -f`s on three launcher logs. Regime analysis (cliff/SSL-EOF detection) reads one log and segregates by pool tag.

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

1. **Design note** (this file). Lock the architecture and the kill criterion.
2. ~~**`coletar` lands first**~~ — already done on local `dev` (commits `0abeef7` → `671abfb`).
3. **Throwaway prototype.** `scratch/pipeline_prototype.py`. ~150 lines, in-process asyncio, three semaphores, no persistence, runs against a 50-case HC slice. Measures wall-time vs. an equivalent sequential 3-command run on the same slice. Half a day.
4. **Decision point.**
   - If prototype wall < 0.6× sequential wall → continue to step 5.
   - Else → kill branch, archive design note under `docs/superpowers/specs/archive/`. `coletar` (already on `dev`) is the final form.
5. **Real implementation.** New module `judex/pipeline/`. Imports `error_triage` and pool primitives from `judex/sweeps/`. Adds `judex executar` to `judex/cli.py`.
6. **Parity validation.** Run `judex executar` on a recent backfill target (e.g., HC 2026 Q1) and compare output to the existing source JSONs + cache state. `validar-gabarito` must remain green.
7. **Removal.** Delete `varrer-processos` / `baixar-pecas` / `extrair-pecas` / `coletar` from `judex/cli.py`. Delete `shard_launcher.py`, `run_sweep.py`, `baixar_pecas.py`, `extrair_pecas.py` driver modules (parsing/extraction logic stays as library code). Delete the per-stage drivers' tests. Update `CLAUDE.md`, `docs/cost-estimates.md`, `docs/peca-sweep-conventions.md`, `docs/agent-sweeps.md`, `docs/data-layout.md`. One squash commit on `dev`.

Step 7 is the one that must NOT be skipped or softened. Per `CLAUDE.md § Conventions`, no backcompat shims; the old commands die when the new one ships.

## Validation

The kill criterion is empirical, not a debate.

- **Slice:** 50 cases sampled from HC 2024 (representative peça-density and outcome-shape).
- **Baseline:** sequential `varrer-processos` → `baixar-pecas` → `extrair-pecas --provedor pypdf` on the slice. Direct-IP, no proxies. Measures `t_baseline`.
- **Prototype:** `scratch/pipeline_prototype.py` on the same slice, same connectivity. Measures `t_proto`.
- **Pass:** `t_proto / t_baseline ≤ 0.60`.
- **Fail:** `t_proto / t_baseline > 0.60`. Branch dies.

The 0.60 threshold is conservative: theoretical pipelining gives ~0.50, so we leave 0.10 for asyncio overhead and the scheduler's bookkeeping. If we can't even hit 0.60, the architectural complexity isn't paying for itself.

If proxies are stable enough to test with, run a second proxy-mode comparison: 16-shard sequential (current production posture) vs. unified scheduler with `concurrencia=16`. Anchor target: same 0.60.

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
8. **Kill criterion is `t_proto / t_baseline ≤ 0.60` on a 50-case HC 2024 slice.** Below 0.60 → continue. Above → branch dies, `coletar` is the final form.
9. **Reuse ADR-0004's `error_triage`.** The unified pipeline's `--replay-de` semantics are exactly ADR-0004's retry semantics, applied per-pool instead of per-stage.
10. **Portuguese flag names.** `--apenas-estagio`, `--portal-concurrencia`, `--sistemas-concurrencia`, `--ocr-concurrencia`, `--proxies-portal`, `--proxies-sistemas`, `--provedor`, `--forcar`, `--retomar`, `--rotulo`, `--saida`, `--nao-perguntar`. English kept for `--dry-run` and short flags `-c/-i/-f`.

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
