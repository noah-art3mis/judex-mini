# Current progress — judex-mini

Branch: `dev`. Prior cycle archived at
[`docs/progress_archive/2026-05-01_1750_cloud-ocr-fly-landing.md`](progress_archive/2026-05-01_1750_cloud-ocr-fly-landing.md)
— ACÓRDÃO re-extract diagnostics + Fly.io cloud-OCR pivot
(2026-05-01). Empirical close-out: local Tesseract structurally
unstable on the 4 GB WSL2 box (Pool deadlocks under OOM); landed
`tesseract_fly` provider + `--paralelo` thread-pool wrapper +
`fly/` deploy stack. Chosen path: Fly shared-cpu-2x × 60 Machines,
~$0.10 / 1k pages, ~1.8 hr per HC year-ladder. App deployed at
`judex-ocr-tesseract-arcos.fly.dev` (gru, 60 shared-cpu-2x
Machines, auto-stop-when-idle).

**Status as of 2026-05-02 20:37 BRT.** Corpus: **90,763** HC
cases. PDF cache 99,095 `.pdf.gz` (+38 from HC 2026 baixar) +
3,621 `.rtf.gz`, **109,777** `.txt.gz` (+3,956 from HC 2026
extract). 93,074 `.extractor` sidecars (gap of ~16k vs
`.txt.gz` is pre-sidecar-discipline residue, not a regression).
Warehouse rebuilt 2026-05-02 12:43 BRT (1.85 GB; DJe Phase 1
populated). Both HC backfill chains (2025 + 2021) **stopped at
user request 20:30-20:33 BRT** while in Stage C (extrair) — see
"Halt 2026-05-02 20:33 BRT" below for state snapshots + resume
commands. Now in flight: a `coletar`-orchestrator smoke test
(HC 245000-245099, exercises today's ADR-0004 commits).

## Open thread — HC 2025 fill-in + pending-outcome recheck (2026-05-03)

**What's running.** `judex executar -c HC -i 250920 -f 267137 --saida
runs/active/hc2025-fillin-<date>/` — verification pass over the full
HC 2025 case-id range. Foreground, direct-IP. Launched 2026-05-03
late evening BRT.

**Expected shape.** HC 2025 is at 82% of its case-id width
(13,365/16,218 cases scraped on disk) — at or above the empirical
70-75% allocation ceiling once `unallocated_pid` is netted out. So
this is primarily a *verification* pass:

| Population            | Count       | Per-case                         |
|-----------------------|-------------|----------------------------------|
| Cached on disk        | 13,365      | filesystem stat → skip → free    |
| Unallocated_pid slots | ~2,500      | one portal request → terminal    |
| Genuinely missed      | likely 0-100 | full pipeline (rare)            |

Wall: ~2-3h direct-IP. Validates the corpus is complete; genuine
new-case finds will be sparse and originate from prior-sweep WAF
blocks where a handful of case-ids slipped through.

**Next step (after fill-in completes — capture before this drops out
of operator memory).** Run a `--forcar` pass over the **HC 2025
pending CSV** to detect outcome flips since the last scrape:

```bash
# 1. Rebuild pending CSV from on-disk JSONs (post-fill-in)
uv run python -c "
from pathlib import Path; import json, csv
out = open('/tmp/hc2025_pending.csv', 'w', newline='')
w = csv.writer(out); w.writerow(['classe', 'processo'])
for f in Path('data/source/processos/HC').glob('*.json'):
    case = json.loads(f.read_text())
    dp = (case.get('data_protocolo') or '')
    outcome = case.get('outcome')
    is_pending = outcome is None or (
        isinstance(outcome, dict) and outcome.get('verdict') is None
    )
    if dp.startswith('2025-') and is_pending:
        w.writerow([case['classe'], case['processo_id']])
"

# 2. Re-scrape pending with --forcar (bypasses meta cache)
uv run judex executar --csv /tmp/hc2025_pending.csv --forcar \
    --saida runs/active/hc2025-pending-recheck-$(date +%Y%m%d)/

# 3. Rebuild warehouse to reflect the new outcomes
uv run judex atualizar-warehouse --classe HC
```

**Anchored numbers (pre-recheck baseline, 2026-05-03 evening).** From
on-disk JSONs at the moment of the launch:

| Year  | scraped | pending (outcome=None) | pending % |
|-------|--------:|----------------------:|----------:|
| 2026  |   3,359 |                  477  |     14.2% |
| 2025  |  13,365 |                  744  |      5.6% |
| 2024  |  12,014 |                  297  |      2.5% |
| 2023  |  11,129 |                  268  |      2.4% |
| 2022  |  10,824 |                  410  |      3.8% |
| 2021  |  12,646 |                  508  |      4.0% |

The 2025 pending ratio (5.6%) sits above the 2-3 year-old steady-state
(~2.5-4%) — suggests a real population of cases STF has decided
since our last 2025 sweep, not noise.

**Success criteria for closing this thread.** A clean before/after:
*"X of 744 HC 2025 pending cases moved to a terminal verdict over
the window <last-scrape-date> → 2026-05-03"*. That number is the
empirical answer to "how stale is our 2025 outcome data?" — a
single observation but a meaningful one for snapshot-drift
calibration (per [CONTEXT.md § Flagged ambiguities](../CONTEXT.md)).

---

## Open thread — Fly OCR cascade + queue stampede + remediation (2026-05-03)

**What happened, in order.** Ran into a sweep-load failure mode on
the Fly cloud-OCR app and worked through a two-stage fix.

**Stage 1 — OOM cascade (morning).** During the HC 2020 sharded sweep
(16 shards × `--ocr-concurrencia 4` = 64 in-flight POSTs against the
9-Machine fleet), `tesseract_fly` hit a **50.6% server-side failure
rate** (728 of 1438 cumulative attempts; 97.9% in the hour before the
fix). Fly logs revealed the root cause: every Machine OOM-killed at
`anon-rss=1863 MB` on a 2 GB shape, then hit `max_restart_count=10`
and stayed permanently stopped. Fleet collapse.

**Diagnosis.** `fly/server.py:160-167` advertised "each Fly Machine
handles one PDF at a time" in the docstring but **nothing in code
enforced it**. The `/extract` handler called
`loop.run_in_executor(None, _ocr_pdf_sync, pdf_bytes)` with `None` =
asyncio's default executor (`min(32, cpu_count + 4) = 8` workers on
shared-cpu-4x), so up to 8 concurrent OCR jobs ran on each Machine —
each holding `pdf_bytes` + a 16-page raster chunk (~176 MB) in RAM.
Memory math closed exactly: steady ~1058 MB + 5 × 176 MB ≈ 1938 MB →
OOM trip at observed 1863 MB anon-rss. The `fly.toml` memory model on
lines 53-78 implicitly assumed "1 in-flight per Machine"; the assumption
was correct, just unenforced.

**Fix 1 — Semaphore(1) + 5MB body cap.** `fly/server.py` patched to
add `_REQUEST_SEMAPHORE = asyncio.Semaphore(1)` acquired before
`await request.body()`, plus `_MAX_PDF_BYTES = 5 MB` server-side cap
as a wayward-client defence. Committed `be74d08`, deployed via
`flyctl deploy --strategy rolling` (all 9 Machines on V12). Smoke
test (real 1-page PDF) → 200 OK in 2.12s. Server-OOM rate dropped
from 50.6% → 0% in the first ~14 minutes of post-fix traffic.

**Stage 2 — queue-amplification stampede (afternoon).** Re-launched
the sharded sweep at `--ocr-concurrencia 1` (16 in-flight, 4× less
pressure). Initial signal looked clean — but log rows kept showing
`provider_error` clustered at suspicious **30.83s p25 wall time**.
88 of 161 post-deploy failures hit that exact bucket. Diagnosis: the
new `Semaphore(1)` enforced "one PDF per Machine" by *queuing* extra
requests inside the asyncio handler, which the client couldn't see.
Tenacity (`tesseract_fly.py:93-98`) had `stop_after_attempt(5)` ×
`wait_exponential(max=30)` = ~31s of total wall budget — exactly
matching the failure timing. With ~32 in-flight against 9 Machines,
queue-drain time was ~210s; tenacity gave up at 31s. Every retry hit
a still-busy fleet, returned a fast 503, exhausted the budget.
The OOM cascade was fixed; we accidentally created a queue-length
cascade in its place.

**Fix 2 — 503 fast-fail + 300s tenacity budget.** Two coupled
changes, committed together as `4cb7b2f`:

1. **`fly/server.py`** — added `if _REQUEST_SEMAPHORE.locked(): raise
   HTTPException(503)` *before* the `async with`. Converts queue
   contention into instant retryable failures so Fly's edge proxy
   load-balances retries to less-busy Machines. Smoke test: 8
   concurrent requests against the 9-Machine fleet → 7×200 + 1×503,
   the 503 returning in **240 ms** vs. the prior **300 s queue wait**.
   Roughly 1000× improvement on the failure case. The `async with`
   stays as a defence-in-depth race-window guard.
2. **`judex/scraping/ocr/tesseract_fly.py`** — switched from
   `stop_after_attempt(5)` + `wait_exponential(max=30)` to
   `stop_after_delay(300)` + `wait_exponential(max=60)`. Bounded by
   total wall budget (5 min) rather than attempt count, with single-
   backoff cap raised to 60 s so transient queue-saturation periods
   can drain. The `test_extract_gives_up_after_max_attempts_of_persistent_5xx`
   test was retired (faithful test of the new contract would need
   mocking `time.monotonic` inside tenacity; not worth the plumbing).

**Active sweeps post-fix (HC 2020 + HC 2021).** Both running at
`--ocr-concurrencia 1` against the patched server:

| run | dir | shards | targets | status |
|---|---|---|---|---|
| HC 2020 (sharded) | `runs/active/hc2020-sharded/` | 16 | 9,137 cases | resumed; ~99.6% text complete; ~620 stuck `provider_error` being chewed through with new tenacity budget |
| HC 2021 (sharded) | `runs/archive/2026-05-03-hc2021-executar/` | 16 | 7,085 cases (gap) | **done** 2026-05-03 18:32 BRT (launcher wall 5h 36m; per-shard wall 3h 31m–5h 27m). Meta ok=5,084 (71.8%) + unallocated_pid=1,975 (28.0%) + http_error=26. Bytes ok=14,671/15,751 (93.1%); text ok=13,792/14,671 (**94.0%**). 15 of 16 shards graded D individually only because per-shard text denominators include 1,080 `missing` rows that were never-fetched bytes (empty/http_error), not OCR failures — see close-out. |

Total in-flight: 32 OCR POSTs against 9 Machines. The 503 fast-fail
shape spreads load via Fly's edge proxy; tenacity's 300 s budget
absorbs queue-drain periods.

**Idempotence story (asked + answered).** The unified pipeline's
state file is per-stage per-target, the cache is URL-keyed and
corpus-shared, and re-running with the same `--saida` requeues only
non-ok work via the seed builder — gated by ADR-0005's 2-retry cap.
Practical workflow:

1. **First run** — let it go. Meta + bytes complete reliably; most
   text completes; some hit `provider_error`.
2. **Re-run same `--saida`** — auto-retries everything within 2-retry
   budget. Cache wins from parallel runs heal silently across runs.
3. **Past the cap** — `--retentar-de runs/.../executar.errors.jsonl`
   resets the budget for those specific targets.
4. **Last resort** — `extrair-pecas --csv <leftovers> --provedor
   tesseract --forcar` for genuine outliers (>1 MB or pathological
   PDFs that need local OCR).

**Outstanding (not blocking).**

- **21 HTTP 500s observed pre-relaunch** weren't fully traced. `flyctl
  logs --no-tail | grep -i exception` didn't surface a clear
  traceback, so they may be uncaught FastAPI exceptions, transient
  pdf2image failures on malformed PDFs, or OOMs during raster (less
  likely now with Semaphore(1)). Worth a Fly-log dive if they recur
  in the new run.
- **`min_machines_running = 0`** in `fly.toml` means Machines
  auto-stop when idle, contributing to cold-start 502/503 noise. Bump
  to 2-3 would reduce the tail at ~$2-3/day. Defer until current
  sweep convergence shows whether the residual matters at scale.
- **`runs/active/backfill-hc2021-2026-05-02/`** still uses the old
  three-command chain layout (varrer/baixar/extrair subdirs). Not
  resumable with `executar`'s state shape, but the cache it produced
  is corpus-shared, so its contribution survives in the new run via
  `skipped_cached`.

**Close-out — HC 2021 done (2026-05-03 18:32 BRT).** All 16 shards
emitted terminal `report.md`; aggregator counters frozen across 7
consecutive 30 s ticks; no `judex` / `uv run` processes alive.
Final tallies (sum across `shard-{a..p}/report.md`, matches monitor):

| stage            | total  | ok     | other                                          |
|------------------|-------:|-------:|------------------------------------------------|
| meta (portal)    |  7,085 |  5,084 | unallocated_pid=1,975 (28.0%); http_error=26   |
| bytes (sistemas) | 15,751 | 14,671 | empty=1,035; http_error=45                     |
| text (ocr)       | 14,671 | 13,792 | provider_error=879                             |

Aggregate text quality = `text_ok / bytes_ok` = 13,792 / 14,671 =
**94.0%** (C-grade). The per-shard `report.md` D-grades are an
artefact of the shard-side denominator including 1,080 `missing` rows
— bytes that were never fetched (empty + http_error) — not OCR
failures; the OCR pool itself converted 94.0% of fetched bytes.

The Stage 2 fix (`4cb7b2f`: 503 fast-fail + 300 s tenacity budget)
held end-to-end: OCR pool ran at 100% utilisation for the full
5h 36m, no SSL-EOF tail-storm, no fleet collapse. Per-shard wall
variance (3h 31m–5h 27m) is the expected queue-distribution effect
on a 16-shard / 9-Machine ratio with per-Machine `Semaphore(1)`.

Run dir archived in place: `runs/archive/2026-05-03-hc2021-executar/`.

Open follow-ups (not blocking):

- **1,975 `unallocated_pid` (28.0% of cases)** is high. Likely a mix
  of segredo-de-justiça / sealed cases (legitimate `pid=null`) and
  scrape-side parse misses; one pass of `judex.sweeps.error_triage.
  recovery_recipe` over `executar.errors.jsonl` (concatenated across
  shards) discriminates which.
- **879 `provider_error`** (6.0% of fetched bytes) is the residual
  OCR tail. Re-running the same `--saida` retries them within the
  ADR-0005 2-retry budget; past that, `--retentar-de` resets the
  budget for those targets specifically.
- **1,035 `empty` PDFs** (downloaded but 0-byte after decompress) are
  most likely STF-side capture gaps; cross-check `error_triage` to
  distinguish from a `baixar-pecas` write-side bug.
- **Completion-tracker refresh deferred.** `docs/completion-tracker.md`
  still shows HC 2021 at `❌ 0.5%` bytes; the table is sourced from a
  warehouse rebuild, so update it after the next `atualizar-warehouse`
  pass (the on-disk cache already carries the new bytes/text).

## Open thread — ADR-0006 state journal: rebase landed, FF to `dev` ready (2026-05-03)

**What.** ADR-0006 implementation committed as `817cfef` on
`worktree-adr-0006-state-journal` and pushed to origin. Replaces the
snapshot-only `PipelineState` with snapshot+log durability:
`PipelineState.open(saida=...)` reads the snapshot, then replays every
log row whose `ts > snapshot_at` directly into in-memory state,
bypassing the live `record_*` mutators (so `retry_count` is preserved
from the row rather than re-incremented per replayed row — fixes a
correctness bug the legacy `recover_state_from_log` carried). `run_id`
(UUID4) on every snapshot + log row is the staleness defence: a
co-resident log from a prior aborted run raises `StaleLogError` on
`open()`. Schema bumped 2→3; pre-bump state files cannot be loaded
(no backwards-compat shim per CLAUDE.md § Conventions). 848 unit tests
pass (89 in pipeline subtree, 759 unaffected).

**Diff.** 8 files, +610 / -178: `state.py` (+332 net — `open()`,
`_apply_log_row`, `StaleLogError`, run_id/snapshot_at properties),
`test_pipeline_state.py` (+224 — 4 new ADR-0006 contract tests),
`log.py` (lost `recover_state_from_log`; gained `run_id`/`retry_count`
row fields), `runner.py` (collapsed log-vs-snapshot mtime dance into
one `PipelineState.open()` call), `scheduler.py` (threads `run_id`
through every `make_log_record` call + `_read_task_retry_count`
helper), plus two test-file migrations and the ADR-0006 doc.

**Rebase landed.** After PR #14 promoted ~65 commits to `main` as
squash `734c280`, the worktree branch (originally based on `772491e`)
sat 4 commits behind the new dev tip. Used
`git rebase --onto origin/dev 772491e` to transplant just the
ADR-0006 commit onto current `dev`. New commit: `f850170` on
`worktree-adr-0006-state-journal` (force-pushed to origin).

**Conflicts resolved (4 files):**

- `state.py` — trivial: kept both `import uuid` (mine) and
  `from collections import Counter` (dev, used by the multi-stage
  progress aggregator at lines 377-411).
- `log.py` — kept the retire-comment for `recover_state_from_log`;
  updated the module docstring to reference `PipelineState.open()`'s
  native reconciliation instead of the now-deleted standalone replay
  function.
- `scheduler.py` — kept both helpers (`_read_task_chars` from dev for
  the per-task tail line, `_read_task_retry_count` from mine for the
  log-row projection). Merged the `make_log_record` call site by
  dropping my redundant `extractor = _read_task_extractor(...)` line
  (dev pre-computes `line_extractor` and `line_chars` upstream for
  the tail line) and keeping `retry_count` threading.
- `test_pipeline_log.py` — dropped the two retired
  `recover_state_from_log` tests (their concern is now in
  `test_pipeline_state.py`); ported dev's
  `test_log_record_carries_chars_and_recovers_into_state` from
  `recover_state_from_log` to `PipelineState.open()`'s replay API.

**Bonus fidelity fixes surfaced by the rebase.** `_apply_log_row` in
`state.py` was dropping two fields on replay:

- `chars` (dev added to `TaskLogRecord` for the tail-line UI; my
  replay didn't project it back into `state.text_chars`).
- `n_pecas` (dev added to in-memory state; my replay overwrote
  `rec.meta` wholesale, clobbering the snapshot's value because
  `n_pecas` isn't carried in log rows).

Both fixed in the rebase commit. Pattern for any future log-row-vs-
in-memory-state field mismatch: replay should preserve prior fields
not represented in the row.

**Test result.** 889 unit tests pass (~40 s; +41 net since the
pre-rebase 848 passed — dev's tail-line/n_pecas tests, my 4 ADR-0006
contract tests, minus the 2 retired recover tests).

**Next step.** Single FF of `dev` to `f850170` lands ADR-0006 on the
trunk. The branch is exactly 1 commit ahead of `dev` (now at
`4cb7b2f` after the 503-fast-fail + tenacity-budget commit).

## Open thread — Unified pipeline v1 landed (2026-05-02 late evening)

**What.** Replaced the three-command chain (`varrer-processos` →
`baixar-pecas` → `extrair-pecas`) and `coletar`'s six-substage
orchestrator with a single fire-and-forget `judex executar` command
backed by a three-pool asyncio DAG scheduler. **Spec-complete v1 is
on `explore/unified-pipeline` (origin)**, fast-forwarded from
`worktree-unified-pipeline-impl`. Both refs at `4af9eaa` after slice
5 (real-STF validation) passed.

**Why.** `coletar` collapsed three commands into one chain but the
operator still saw six substages, six per-substage logs, six
per-substage state files, and a launcher process tree. The unified
pipeline collapses all of that to **one process, one log, one PID,
one state file, one resume point**. The win is *operational*, not
primarily throughput — the spec was reframed mid-session from a
0.60 throughput-gate (mathematically unreachable for this workload)
to a six-point ergonomic checklist (one submission, one log, one
state file, one PID, resume across pool failures, output identical
to today). See `docs/superpowers/specs/2026-05-02-unified-pipeline.md`.

**Branch state (origin).**

```
4af9eaa feat(pipeline): comparison metrics + concurrency-aware utilisation
218f8f2 fix(pipeline): persist case JSON in handle_fetch_meta
48b2c5e feat(pipeline): per-pool circuit breaker (slice 3)
cf8d0be feat(pipeline): runner + judex executar CLI (slice 4)
fe62cd4 feat(pipeline): scheduler + handlers (slice 2)
c538d07 feat(pipeline): models + atomic state store (slice 1)
67e0fc6 feat(pipeline): scheduler prototype with mock-mode smoke test
e12f91d docs(spec): reframe from throughput gate to ergonomic checklist
ccc01c3 docs(spec): unified pipeline — DAG scheduler successor to coletar
```

`origin/explore/unified-pipeline` and `origin/worktree-unified-pipeline-impl`
both at `4af9eaa`. `dev` still at `62a1101` — unified pipeline is
NOT yet promoted to trunk.

**What's in `judex/pipeline/`.**

| File | Lines | Purpose |
|---|---|---|
| `__init__.py`     | 32  | Public re-exports |
| `models.py`       | 100 | `Task`, `PoolName`, `TaskKind`, `TaskStatus`, `PoolConfig`, `Counters` |
| `state.py`        | 200 | `PipelineState` with atomic snapshot, resume predicates, per-URL granularity |
| `pools.py`        | 110 | `Pool` runtime with `CircuitBreaker` + optional `ProxyPool`/`AdaptiveThrottle` scaffolding |
| `scheduler.py`    | 300 | Three-pool asyncio core, signal-driven graceful shutdown, periodic snapshotter |
| `handlers.py`     | 195 | Real handlers wired to scraper / `_http_get_with_retry` / `peca_cache` / `ocr.dispatch` |
| `runner.py`       | 230 | `run_pipeline(targets, saida, ...)` + `read_targets_csv` + comparison-metrics report |

Plus `scratch/pipeline_prototype.py` (kept as the throwaway prototype
that surfaced the pipelining-ceiling math), and 34 unit tests across
`tests/unit/test_pipeline_{state,scheduler,runner,pools}.py`. **Full
unit suite: 716 passed (34 new + 682 pre-existing).**

**Slice 5 receipts (real STF, direct-IP, `pypdf`).**

5-case (HC 250000-250004), wall **3.3 s**:

| pool      | started | finished | failed | utilisation |
|-----------|---------|----------|--------|-------------|
| portal    | 5       | 5        | 0      | 58%         |
| sistemas  | 10      | 10       | 0      | 63%         |
| ocr       | 10      | 9        | 1      | 30% (concurrency-aware) |

50-case (HC 250000-250049), wall **25.9 s**:

| pool      | started | finished | failed | utilisation |
|-----------|---------|----------|--------|-------------|
| portal    | 50      | 50       | 0      | 54%         |
| sistemas  | 119     | 119      | 0      | 88%         |
| ocr       | 119     | 119      | 0      | 34%         |

State-side: `meta=ok×50`, `bytes=ok×116`, `text=ok×100,
provider_error×16` (RTF-passed-to-pypdf — same outcome as legacy
`extrair-pecas --provedor pypdf`; `--provedor auto` would route those
to tesseract). Spot-checked `.txt.gz` outputs: real Portuguese
("HABEAS CORPUS 250.000 DISTRITO FEDERAL / RELATOR : MIN. FLÁVIO DINO
/ ..."), no mojibake.

**Comparison vs. legacy chain (50-case slice).**

| metric                                | this run | legacy (≈ sum-of-busy) |
|---------------------------------------|----------|------------------------|
| wall (s)                              | **25.9** | 71.8                   |
| cases                                 | 50       | 50                     |
| peças bytes ok                        | 116      | 116                    |
| peças text ok                         | 100      | 100                    |
| OCR cost (USD, `--provedor pypdf`)    | $0.0000  | $0.0000                |
| pipelining ratio                      | **0.36** | n/a                    |
| **wall savings vs sequential**        | **64%**  | n/a                    |

The 64% is higher than the analytical projection (15-25%) because
much of the work is cache-hits — HTML cache for meta, `peca_cache`
for already-fetched bytes — which makes the bottleneck pool's wall
shrink dramatically while pipelining still amortizes the fresh-fetch
tail. **Cache-aware resume gets the bigger win**; a fully-fresh
50-case run from cold cache would land closer to the 15-25% band.

**Six-point fire-and-forget checklist.**

| Invariant | Status |
|---|---|
| 1. One submission                 | ✅ `judex executar --csv …` |
| 2. One log                        | ✅ Single stderr stream |
| 3. One state file                 | ✅ `executar.state.json` (atomic snapshot) |
| 4. One PID                        | ✅ Single asyncio process |
| 5. Resume across pool failures    | ✅ Unit tests cover; integration via re-run pending |
| 6. Output identical to today      | ✅ Case JSON + four-file quartet land in `data/`; texts spot-check is real Portuguese |

**One mid-session bug, one small follow-up.**

* **Bug found and fixed (`218f8f2`).** First slice-5 run produced
  `meta=ok×10, bytes=none, text=none` because (i) the slice
  (HC 271130-271134 + 271140-271144) was unintentionally trivial —
  all 10 cases are stub filings with zero peça links — and (ii) my
  `handle_fetch_meta` was scraping into memory but never persisting
  the case JSON to `data/source/processos/<classe>/`. Legacy
  `varrer-processos` does this via `run_sweep._write_item_json`;
  the unified pipeline was missing the equivalent step. Without the
  fix, invariant #6 would silently break: `executar.state.json`
  shows `ok` but no JSON on disk for downstream consumers
  (warehouse rebuild, `validar-gabarito`, ad-hoc analysis) to find.
  Lift-and-replicated the legacy atomic-write logic into
  `handlers.py`. Same on-disk format, same atomicity contract.

* **Follow-up (non-blocking): intra-case URL dedup.** 50-case run
  showed `sistemas.started=119` but only 116 unique URLs in state
  → 3 intra-case dupes (same peça URL emitted from two surfaces of
  the same case, e.g. once via andamento, once via DJe).
  `_iter_case_pdf_targets` does not dedupe per case (CLAUDE.md
  documents this); my handler should dedupe before emitting bytes
  tasks. Cost: the dupes hit `peca_cache.has_bytes` → True → skip
  fetch, so the only cost is bookkeeping noise. ~3 lines to fix.

**Open follow-ups (priority order).**

1. **Promote `explore/unified-pipeline` → `dev`.** Currently `dev` is
   at `62a1101` (no unified pipeline). The work passes slice 5; can
   ship via `gh pr create --base dev --head explore/unified-pipeline`
   and squash-merge per CLAUDE.md § Conventions.
2. **Slice 6: removal of legacy CLI commands.** Spec says delete
   `varrer-processos` / `baixar-pecas` / `extrair-pecas` / `coletar`
   from `judex/cli.py` once slice 5 passes. Slice 5 has passed;
   removal is now unblocked. Per CLAUDE.md § Conventions, no
   backcompat shims — remove outright.
3. **Intra-case URL dedup in `handle_fetch_meta`** (above).
4. **`--provedor auto` integration** so RTF-as-PDF routes correctly.
   Same legacy parity as `extrair-pecas --provedor auto`.
5. **Real-resume integration test.** Unit tests cover; want a real
   "kill mid-run via SIGTERM, resume, verify finished" cycle as
   slice 5b receipt before promoting to `dev`.

## Open thread — HC 2020 `executar` smoke test + warehouse rebuild blocker (2026-05-03 ~02:10 BRT)

**Run in flight.** Detached `judex executar --csv runs/active/hc2020-executar/cases.csv
--saida runs/active/hc2020-executar/ --provedor auto --nao-perguntar` (env:
`FLY_TESSERACT_URL=https://judex-ocr-tesseract-arcos.fly.dev/extract`,
`JUDEX_AUTO_TESSERACT_PROVIDER=tesseract_fly`). PIDs `952184`/`952189`. Started
03:50:41 UTC (snapshot view at 05:06:58 UTC). 9,137 HC 2020 cases queued.

**Spot-check verdict at ~5.6 % through: healthy.** Snapshot from `executar.state.json`:

| stage      | ok    | fail | fail %  | dominant failure |
|-----------:|------:|-----:|--------:|---------------------------------------------------|
| meta       | 769   | 123  | 13.8 %  | `unallocated_pid` (terminal-normal STF state)     |
| bytes      | 3373  | 20   | 0.59 %  | `empty` (0-byte STF response, magic-byte guard)   |
| text       | 2178  | 38   | 1.71 %  | 34× Fly Tesseract HTTP 404 + 1× `OutlierPdfError` (>1 MB cloud-OCR refusal) + 3× misc |

Fully-through-all-stages: **512 / 9137 cases**. Throughput drift 0.21 → 0.17
cases/s (heavy-tail OCR jobs at 430 s / 275 s / 171 s pulling the average).
Auto-routing mix: rtf=1016, pypdf=1080, tesseract_fly=78, tesseract=8 — exactly
what HC 2020 should look like.

**Artifact-layout parity confirmed.** `executar` writes the same on-disk
quartet as the legacy chain: case JSON in `data/source/processos/HC/`, peça
bytes in `data/raw/pecas/<sha1>.{pdf,rtf}.gz`, text in
`data/derived/pecas-texto/<sha1>.txt.gz` + `.extractor` sidecar. Run-dir
holds `executar.state.json` (atomic, periodic snapshot) +
`executar.log.jsonl` (append-only, per-URL events).
`executar.errors.jsonl` and `report.md` write at clean exit only —
`judex/pipeline/runner.py:405-411`. Spot-checked 8 `.txt.gz` files across
all four extractors: real Portuguese, no mojibake, plausible sizes.

**Two non-blocking signals to track:**

1. **34× Fly Tesseract 404s (1.5 % of text jobs).** Error-reported URL is the
   bare host (`https://judex-ocr-tesseract-arcos.fly.dev/`, no `/extract`),
   suggesting the worker is responding 404 to certain payloads or the
   redirected response URL is being captured. Easily re-tried from
   `executar.errors.jsonl` once the run is done. Watch for the rate
   climbing past ~3 %.
2. **OCR wall-time spikes** (430 s, 275 s, 171 s) push avg to 4.8 s and ETA
   to ~14 h. All complete `ok` — Fly cold-start / queue tail, not failure.

### Warehouse rebuild blocker — 13,747 stray case JSONs at the wrong path

**Triggered by the user's "rebuild the warehouse" follow-up.** `uv run judex
atualizar-warehouse` crashed in `_bulk_insert` at
`judex/warehouse/builder.py:877`:

```
ConstraintException: Constraint Error: Duplicate key
"classe: HC, processo_id: 253283" violates primary key constraint.
```

Root cause: **13,747 case JSONs are duplicated at `data/source/processos/*.json`
(parent dir) AND at `data/source/processos/HC/*.json` (canonical)**. The
builder's traversal is `cases_root.rglob("judex-mini_*.json")`
(`builder.py:812`) — recursive, so both copies enter the `cases` insert and
collide on `(classe, processo_id)` PK.

Stray range: HC 198000-267137 (2021-2025). Mtime window: 2026-05-02
**14:12 → 15:22 BRT** (≈70 min, hour-bucket distribution: 14h = 4811 files,
15h = 8936 files). **Confirmed not the active run** — newest mtime in parent
dir is 15:22 BRT yesterday; nothing modified in the last 60 min as of
2026-05-03 02:18 BRT (`find … -mmin -60` returns empty), and the live HC
2020 `executar` sweep's recent JSONs land correctly under
`data/source/processos/HC/`. Sample of 25 strays vs `HC/` twins:

- 25/25 same byte size
- 25/25 sha1-different
- single field-level diff: **`_meta.extraido` only** — strays' timestamp
  is ~18 h newer than `HC/` twins' (parent ≈ `2026-05-02T14:50:36`,
  `HC/` ≈ `2026-04-21T18:49:28` on the spot-checked file)

Interpretation: a sweep yesterday afternoon re-scraped this range and wrote
the JSONs to `data/source/processos/<f>.json` instead of
`data/source/processos/HC/<f>.json`. Case content is identical to the
existing `HC/` copy — only the `_meta.extraido` timestamp moved. **No data
was lost.** The strays are functionally redundant; the canonical `HC/` copy
is intact (just with an older scrape-timestamp).

**The active HC 2020 `executar` run is writing to the correct path** —
files at 02:06 BRT today land under `data/source/processos/HC/`. So the
mis-pathed-write bug isn't firing on this run, but the strays at the parent
level are blocking the warehouse rebuild and stand as evidence of a
historical regression worth tracing (most likely candidates: yesterday's
`coletar` smoke test or the `executar` sweep that wrote at 14:22 BRT).
Whichever pipeline emitted these had a missing `<classe>/` segment in its
case-store write path.

**Side artefact.** `data/derived/warehouse/judex.duckdb.tmp` (522 MB) is the
half-built rebuild from this attempt. Safe to delete; the canonical
`judex.duckdb` (1.85 GB, 2026-05-02 12:43 BRT) is untouched.

**Resolution (02:21 → 02:28 BRT).** Moved all 13,747 strays into `HC/` with
overwrite via `find … -maxdepth 1 -name 'judex-mini_*.json' -exec mv -f -t
.../HC/ {} +`. Atomic per-file rename within the same filesystem; race-free
against the active sweep (no path overlap, HC 187xxx vs 198000+). Spot-check
post-move: `_meta.extraido = 2026-05-02T14:50:36.579461` on
`HC_255555-255555.json` (the newer timestamp won, as intended). Parent-dir
JSON count: 0. `judex.duckdb.tmp` deleted. Re-ran `uv run judex
atualizar-warehouse` → **clean build in 414.8 s, atomic swap to 3.05 GB
warehouse**, all five quality thresholds passed:

```
  cases                 90,835
  partes               317,860
  andamentos         1,242,860
  documentos            36,405
  pautas                15,459
  publicacoes_dje       85,803
  decisoes_dje          13,311
  pdfs                 115,056
  unallocated_pids      24,568
```

**Carried-over investigation.** Whichever sweep wrote into the parent dir
during the **2026-05-02 14:12 → 15:22 BRT** window (4811 files in 14h, 8936
in 15h, range HC 198000-267137) had a missing `<classe>/` segment in its
case-store write path. Worth grepping launcher logs from that window to
identify the offending command before the next big sweep. Verifier guard
for after the fix:

```bash
ls data/source/processos/*.json 2>/dev/null | wc -l   # must be 0
find data/source/processos/ -maxdepth 1 -type d       # must be only HC/
```

## Open thread — Fly OCR cluster cost shape (2026-05-02 late evening)

**Why.** The first real Fly invoice landed (May 1+2 = $8.70 over
181.5 Machine-hours) and revealed two surprises: (a) the prior
`$0.0118/hr per Machine` quote in `fly/README.md` and
`tesseract_fly.py:cost()` was **4× under-anchored** because it
ignored the "Additional RAM" line item, and (b) RAM is **82% of
the per-Machine bill** at the old `[[vm]] memory = "4gb"`, not the
expected CPU-dominated split. The bill anchored a real per-hour
rate of $0.0479 / Machine-hour.

**Landed on `dev`.**

- `71e3d43 feat(fly): chunked rasterize + 2 GB Machine, bill-anchor cost surface`
  — `fly/server.py` switched from upfront `convert_from_bytes(pdf_bytes,
  dpi=200)` (peak RAM ≈ 11 MB × n_pages) to chunked
  `_RASTER_CHUNK_PAGES = 4` rasterization (peak RAM ≈ 50 MB regardless
  of page count). `[[vm]] memory: "4gb" → "2gb"`. Cost docstring
  rewritten with two-meter pricing model anchored to the real invoice.
  Per-Machine rate: $0.0479/hr → $0.0256/hr (**~47% reduction**).
- `62a1101 docs(fly): smoke-test report for streaming refactor + 1 GB Machine`
  — full report at `docs/reports/2026-05-02-fly-streaming-refactor-smoke-test.md`.

**Cluster state right now.**

| Field | Value |
|---|---|
| Branch | `dev` |
| Local `fly.toml` | `memory = "2gb"`, `shared-cpu-2x` |
| Live cluster | 10 Machines × shared-cpu-2x × 2 GB ✓ matches local |
| Live image | streaming refactor (chunked rasterize) ✓ matches local |
| Per-Machine rate | $0.0256/hr |
| Was scaled to | 100 Machines pre-test; **needs restore to 100** |

**Smoke-test results so far.** 1-page PDF: ✅ clean (~4 s wall,
991 chars, accents intact). 123-page PDF: server-side 200 OK at
~270 s wall but client got empty body — diagnosed as
`async def extract()` blocking the asyncio event loop during sync
OCR work, so `/healthz` fails and Fly's proxy drops the upstream
connection. **No OOM in logs**, so 2 GB is genuinely sufficient
for 123-page PDFs. 295-page PDF (`37ee397e8732…`, 5.4 MB gz):
**not yet run** — direct user concern about long-PDF handling.

**Open follow-ups (priority order).**

1. **Run 295-page PDF test** against the live 2 GB cluster to
   pin "very long PDFs handled correctly" empirically, not by
   design extrapolation.
2. **`async def` → `run_in_executor` one-liner** so long-request
   responses don't get dropped on the way back through the proxy.
   Pinned by re-running the 123-page PDF and getting clean text.
3. **Restore cluster to 100 Machines** (`flyctl scale count 100`)
   before any production sweep.
4. **Money optimization choices** still on the table — current
   $0.0256/hr; achievable lower bounds:
   - `shared-cpu-2x` + `memory = "1gb"`: $0.0143/hr (44% further
     cut). Headroom ~314 MB over peak ~710 MB working set — tight,
     silent-OOM risk on edge PDFs (Pillow large-image spikes).
   - `shared-cpu-4x` + `memory = "1gb"`: $0.0174/hr (39% cut)
     **and** 2× wall speedup on 3+ page PDFs (4 parallel Tesseract
     instances vs 2). Risk: 4 concurrent Tesseract working sets
     (~600 MB) plus baseline (~400 MB) ≈ 1 GB exact — needs the
     2 GB shape to be safe in practice.
   - Both options are shape-only — `server.py` reads
     `os.cpu_count()` so the worker pool auto-scales to whatever
     the deployed shape provides. No Python change required.
5. **Investigate health-check failures** on started Machines —
   noticed during smoke test that `1 critical` checks were
   common, possibly from `/healthz` being blocked during long
   OCRs (same async-blocking root cause as #2).

**Decision pending.** Whether to spend engineering effort on the
remaining ~$0.10–$0.20/ladder savings, or stop here. The headline
win (4 GB → 2 GB, 47% off the per-Machine rate) is locked in;
further cuts are diminishing returns.

### Update 2026-05-03 — tesserocr swap + included-RAM-tier insight

**Three things landed since the prior entry.**

1. **pytesseract → tesserocr** (`fly/server.py`, commits `83766eb`,
   `6588012`, `557835e`). The pytesseract path spawned a fresh
   `tesseract` subprocess per page (~150 ms LSTM model load × N
   pages, parallelized across 2 workers ≈ 4-8 s wasted on a
   50-page PDF). Swapped to tesserocr (Cython libtesseract
   bindings) with a per-thread `PyTessBaseAPI` via
   `threading.local`, held by a **module-scoped**
   `ThreadPoolExecutor` (per-chunk pool would re-init the LSTM
   for every PDF, defeating the swap). The model is now loaded
   N_workers times for the entire server lifetime, not per page.
   Estimated 1.3-2× speedup on multi-page PDFs.
2. **CPU-detection investigation** ruled out a non-bug. Confirmed
   via `flyctl ssh console`: `os.cpu_count()` returns **2** on
   `shared-cpu-2x` (matches the configured shape, no Firecracker
   leakage). `/sys/fs/cgroup/cpu.max` does not exist on Fly —
   Firecracker microVMs present vCPUs to the guest directly,
   without a cgroup hierarchy. The cgroup-quota fallback in
   `_resolve_page_workers()` is dead code on Fly (works as
   portability insurance for redeploys to k8s/Fargate).
3. **Included-RAM-tier insight rewrites the cost-shape choice.**
   `shared-cpu-Nx` ships with N × 256 MB included RAM in the
   per-second CPU rate (verified via Fly pricing docs). At our
   `[[vm]] memory = "1gb"`, that means:
   - shared-cpu-2x: 512 MB included → 512 MB additional billed
   - shared-cpu-4x: **1024 MB included → 0 MB additional billed**

   The CPU-rate jump from 2x → 4x ($0.0087 → $0.0174 in gru) is
   exactly offset by the eliminated additional-RAM line, so the
   per-Machine bill is only 22% higher despite 2× the vCPU count.
   Per-page-slot cost drops ~39%.

**Cost-shape comparison (gru rates, all at 1 GB total RAM).**

| Shape               | Workers | $/hr (gru) | Pages/sec (est) | $/page-slot/hr      |
|---------------------|---------|------------|-----------------|---------------------|
| shared-cpu-2x @ 1gb | 2       | $0.0143    | ~2.0            | $0.00715            |
| shared-cpu-4x @ 1gb | 4       | $0.0174    | ~4.0            | $0.00435 ← sweet spot |
| shared-cpu-8x @ 2gb | 8       | ~$0.0349   | ~7.0            | $0.00499            |

Pages/sec figures are estimates from per-page OCR ~1 s × worker
count, with sub-linear scaling assumed at 8 workers (process-
global libtesseract state contention). **Needs empirical
validation** — the table is the basis for picking 4x as the
landed choice, not a measured baseline.

**Landed shape.** `[[vm]] size = "shared-cpu-4x"`, `memory = "1gb"`.
Memory peak re-derived for 4 workers: 310 MB baseline + 400 MB
tesserocr (4 × ~100 MB) + 176 MB raster = **886 MB peak**, ~14%
headroom over the 1 GB ceiling. Tighter than the prior 2x shape
(~33% headroom) but above the empirically-confirmed safe floor.

**Experiment to run post-deploy.**

1. ~~Smoke-test 5-10 PDFs spanning page counts on the new 4x
   cluster.~~ **Run on the 1 GB live cluster 2026-05-03 ~02:57 BRT
   ahead of the 2 GB scale-up** (artifacts at
   `analysis/fly-1gb-smoke-2026-05-03/`). Test set spanned 10 → 295
   pages; only the 10-page PDF (single-chunk, 5.7 s wall) returned
   200 + clean Portuguese text. Every PDF >16 pages — i.e. every
   request that needed a *second* raster chunk — returned 502 +
   empty body, with five corresponding `oom-killed` events in
   `flyctl logs`:

   | pages | wall (s) | result | anon-rss at kill |
   |------:|---------:|:------:|-----------------:|
   | 10    |  5.7     | ok     | (no kill)        |
   | 31    |  5.8     | 502    | 847 MB           |
   | 51    | 22.7     | 502    | 862 MB           |
   | 63    | 35.3     | 502    | 863 MB           |
   | 143   | 28.3     | 502    | 855 MB           |
   | 295   | 124.7    | 502    | 842 MB           |

   Mean kill-RSS 854 MB on a 1024 MB ceiling — matches the prior
   session's 861 MB datapoint cited in commit `308426e` to within
   1%, so the OOM ceiling is reproducible. The boundary is now
   pinned at **17-pages-or-more** (one full chunk + any second-
   chunk overlap), tighter than the 123-page bound speculated
   before. Smoking gun: the 295-page case OCR'd ~16 pages
   successfully (~5 s/chunk × 1 chunk = ~5 s) before the kernel
   killed it during chunk-2 raster — partial-OCR walls (5.8/22.7/
   35.3/28.3 s) confirm work-then-die, not proxy-immediate 502.
   Confirms the calculated 1234 MB peak doesn't fit on the 1 GB
   ceiling by ≥210 MB; 2 GB needed.

   **2 GB re-run after `flyctl scale memory 2048` (2026-05-03 ~03:13
   BRT, artifacts at `analysis/fly-2gb-smoke-2026-05-03/`).** Same 6
   PDFs, same image (`deployment-01KQNVP194VNVC5TXPJ1MQZXBK`), only
   the memory ceiling changed:

   | pages | pdf MB | 1 GB outcome   | 2 GB outcome              | 2 GB s/page |
   |------:|-------:|:--------------:|:-------------------------:|------------:|
   | 10    | 2.08   | ✓ ok           | ✓ ok (5.9 s)              | 0.53        |
   | 31    | 1.24   | OOM 847 MB     | ✓ ok (18.7 s)             | 0.59        |
   | 51    | 1.62   | OOM 862 MB     | ✓ ok (28.5 s)             | 0.53        |
   | 63    | 1.39   | OOM 863 MB     | ✓ ok (**213.8 s**)        | **3.38**    |
   | 143   | 2.27   | OOM 855 MB     | ✗ ReadTimeout (900 s)     | n/a         |
   | 295   | 5.67   | OOM 842 MB     | ✗ ReadTimeout (900 s)     | n/a         |

   **Crucial receipt: zero `Out of memory` lines in `fly.log` over
   the entire 2 GB run** (`grep -c 'Out of memory' fly.log → 0`,
   over 191 log lines). The two `Main child exited normally`
   entries at 03:04 are from the `flyctl scale memory 2048` rolling
   restart (graceful uvicorn shutdown before VM resize), not from
   the smoke test. So the 143/295-page failures are *server-stalled*,
   not OOM-killed — `/healthz` continued returning 200 every 30 s
   throughout, meaning the asyncio loop stayed alive and the OCR
   worker was just running very, very slowly. This is the
   degradation-without-death signature, distinct from the 1 GB
   crash-kill signature.

   **Smoke-test cases were *picked from the largest 0.01% of the
   corpus* (the 5383 KB / 295-page outlier is the single biggest PDF
   in 103,952 cached files), so the n=4 percentile distribution
   above is meaningless as a percentile claim — the test inputs were
   selected to stress the cluster, not sampled uniformly. The
   right percentile question is over the *corpus*, not the test set:**

   **Corpus-wide PDF distribution** (`data/raw/pecas/`, n=103,952
   `.pdf.gz` files, computed 2026-05-03):

   | Stat        |   Compressed |  Est. pages | Implication on 4x @ 2gb |
   |:-----------:|-------------:|------------:|-------------------------|
   | Total       | 14.92 GB     | —           | manageable on disk      |
   | p50 (median)|   123.5 KB   |   3 pages   | single-chunk, ~2 s wall (fast path) |
   | mean        |   150.5 KB   |   ~4 pages  | tail-skewed; mean > median by 22% |
   | p95         |   411.1 KB   |   12 pages  | single-chunk, ~7 s wall (still fast) |
   | p99         |   507.4 KB   |   13 pages  | single-chunk, ~7 s wall |
   | p99.5       |   517.9 KB   |   13 pages  | single-chunk, ~7 s wall |
   | p99.9       |   628.4 KB   |   14 pages  | single-chunk, ~8 s wall |
   | p99.99      |  1284.6 KB   |   67 pages  | **slowdown zone** (~3 s/page, ~200 s wall) |
   | max         |  5382.9 KB   |  295 pages  | **stall zone** (≥900 s, the test outlier) |

   Page counts at percentiles ≤p99.9 are direct page-counts of the
   PDF at that exact size-rank; max is empirical (the smoke-test's
   295-page case). The mid-percentile values are *page counts*
   (not estimated from a regression — those would underestimate
   the tail since text-heavy PDFs compress 5× better than scans).

   **Punch line: corpus-fraction projection of the smoke-test boundaries.**

   | Boundary on 2 GB cluster      | Corpus fraction       | Count   |
   |-------------------------------|-----------------------|---------|
   | ≤16 pages (single-chunk fast) | **99.51%**            | 103,442 |
   | 17-63 pages (multi-chunk fast)| **0.48%**             | 502     |
   | 64-143 pages (slowdown zone)  | **0.007%**            | 7       |
   | >143 pages (stall zone)       | **0.001%**            | 1       |

   So the literal "40% headroom holds" claim resolves favorably for
   real production traffic: **99.99% of corpus PDFs are inside the
   smoke-test's confirmed-clean-zone** (≤63 pages, no OOM, no
   stall, ≤30 s wall on the 2 GB cluster). The chunk-overlap
   slowdown affects ~7 PDFs across the entire corpus; the stall
   affects exactly 1 (the 5382 KB / 295-page outlier we deliberately
   used as a stress test). Chunk-overlap fix is nice-to-have, not
   a launch blocker for the year-ladder backfills against the
   existing 99.99% short-PDF traffic.

   **Bigger reframe (2026-05-03 close-out): every PDF in the
   smoke-test set is *already excluded* from the production Fly
   path.** `tesseract_fly.py:67` has a `OUTLIER_BYTES = 1 MB`
   threshold; `extract()` raises `OutlierPdfError` for any
   `.pdf.gz > 1 MB compressed`, which the sweep runner records as
   `status='outlier_skipped'` and surfaces in `report.md` with a
   copy-pasteable local-OCR command. All 6 smoke-test PDFs (10p,
   31p, 51p, 63p, 143p, 295p) are 1.24-5.67 MB — every one
   exceeds the threshold and would never reach Fly in a real
   sweep. Across the 103,952-PDF corpus, only 17 files (0.016%)
   are above 1 MB.

   **What this means for the open follow-ups (priority list above
   superseded):**
   - **Chunk-overlap patch**: tested empirically against the
     unpatched 2 GB run by deploying the `del chunk_imgs;
     gc.collect()` form and re-running the same 6 PDFs. Result:
     **patch added 10-18% wall on every PDF and did not move the
     63-page cliff** (10p 5.9→7.0 s; 31p 18.7→21.2 s; 51p
     28.5→31.3 s; 63p 213.8→247.5 s; 143p still timed out). The
     cliff is therefore *not* memory-overlap — most plausible
     remaining cause is **shared-cpu CPU-credit exhaustion**
     (4 workers burst-running for ~30-60 s deplete Fly's
     shared-cpu credit pool, then throttle to baseline). Reverted
     the patch (`git checkout fly/server.py` + `flyctl deploy`,
     2026-05-03 ~04:10 BRT). Cluster is back on the un-patched
     image at 2 GB.
   - **CPU-credit hypothesis**: only worth chasing if we ever
     loosen the 1 MB outlier threshold. Right now it's an
     unreachable failure mode behind a guard. Park.
   - **Production status**: 4x @ 2gb is **production-ready as-is**
     for the 99.984% of corpus that flows through Fly; the 0.016%
     outliers go to local Tesseract via the existing
     `outlier_skipped` flow. Restore Machine count + resume HC
     backfills whenever convenient.

   **Cost re-anchor (2026-05-03).** `tesseract_fly.py:cost()`
   currently returns `n_pages * 0.005 / 1000` (anchored to the old
   shared-cpu-2x @ 4gb shape's $0.0479/Machine-hr). Re-derived
   against the current 4x @ 2gb shape ($0.0286/Machine-hr) and
   the empirical 0.55 s/page mean on 4 workers (smoke-test
   fast-path): **~$0.0011 / 1k pages** = **128× cheaper than
   Modal's $0.140 / 1k**. Year-ladder backfill (~46k OCR pages):
   $0.05 on Fly vs $6.50 on Modal. Re-anchor `cost.py` next time
   the file is touched; cost-test bounds in `tests/unit/test_cost.py`
   tolerate ±10%, so the change is non-breaking.

   **What the 2 GB pass actually proved.**
   1. **OOM at the small/mid end is fixed.** 31/51-page PDFs that
      OOM-killed on 1 GB at anon-rss ~847-862 MB now complete cleanly
      with intact Portuguese text (54,514 / 88,002 chars); the
      40%-headroom math holds for the bottleneck case the design
      was built for.
   2. **A new degradation mode appeared at 63+ pages.** No OOM in
      `flyctl logs` (zero `Out of memory` lines during the 2 GB run),
      but per-page OCR jumped ~6× between 51 and 63 pages — the
      63-page case took 213.8 s where the trend predicts ~35 s.
      The 143-page case never returned within the script's 900 s
      client read-timeout despite Fly's `/healthz` pings continuing
      to succeed every 30 s (asyncio loop alive, server still
      running). Most plausible cause: memory pressure short of OOM
      causing GC churn / page-cache thrash as the 4-worker tesserocr
      pool's resident model + chunk-overlap PIL rasters approach
      the 2 GB ceiling on long PDFs. Empirically, the *operational*
      ceiling for the 4x @ 2gb shape on this workload is ≤63 pages
      with acceptable wall, not the 295+ that fly.toml's static
      memory math suggests.
   3. **Calculated 40% headroom is misleading at the long tail.**
      Toml comment: peak 1234 MB on 2048 MB = 40%. But the kernel
      OOM-killer (we saw on 1 GB) fired at ~83% of the configured
      ceiling, suggesting the *effective* OOM threshold is ~1700 MB
      on 2 GB, and the 1234 MB calc only accounts for *steady-state
      first-chunk* — chunk-2 overlap before GC adds another 176 MB
      transient, putting peak closer to 1410 MB and effective
      headroom at ~17%.

   **Open follow-ups (priority order, post-2-GB-receipt).**

   1. **Diagnose the 63+ page slowdown.** Two cheap experiments:
      (a) add `del chunk_imgs; gc.collect()` between chunks in
      `_ocr_pdf_sync` (forces release of chunk-1 PIL images before
      chunk-2 allocs), redeploy, re-run the same 6-PDF smoke test
      and look for the 63-page wall returning to the 35-s trendline;
      (b) drop `_RASTER_CHUNK_PAGES` from 16 to 8 — halves peak
      raster spike from 176 MB to 88 MB at the cost of 2× the
      pdftoppm parse cost, but trades fixed overhead for an ironclad
      no-pressure ceiling.
   2. **Larger N for real percentiles.** Sample 50-100 random ACÓRDÃO
      PDFs from `data/raw/pecas/` spanning page-count buckets,
      re-run, then claim p50/p90/p99 with statistical force. Without
      this, current "p95/p99 ≡ max" caveat is the honest read.
   3. **Restore cluster to production count** (whatever the next
      sweep needs — currently 10 Machines, was 100 pre-test in the
      2 GB-streaming-refactor cycle).
   4. **Decide whether 2 GB at $0.0347/hr is the right shape vs
      shared-cpu-8x @ 2gb.** If the 63-page slowdown is the chunk-
      overlap effect (mitigation #1 above), 4x @ 2gb still wins on
      $/page-slot. If it's hard libtesseract concurrency contention,
      8x @ 2gb might not help and a different chunk strategy is
      needed.

2. ~~Sample wall_seconds vs the prior 2x baseline for matched~~
   PDFs. Expected: ~50% reduction in per-PDF wall (4 workers
   vs 2). If actual <40% reduction, suspect contention in
   libtesseract's process-global state and consider whether
   stepping up to shared-cpu-8x @ 2gb is worth the cost-per-slot
   regression ($0.00499 vs $0.00435 — slightly worse, but only
   meaningful if 8x scales near-linearly).
3. Validate the per-page-slot cost claim against a real
   end-to-end sweep bill. Compare $/1k pages between the prior
   2x runs and the first 4x run. If the 39% saving holds, lock
   in 4x as the cluster-wide default; if it degrades to <25%,
   revisit (likely cause: 4-worker contention eating the
   apparent throughput gain).

Open question: would 8 workers + `OMP_NUM_THREADS=2` (instead of
8 workers + OMP=1) recover any tail throughput on the 8x shape?
The math says no — cross-page parallelism dominates per-page OMP
parallelism whenever the page pool is saturated, which it almost
always is given chunk_size=16. But worth one A/B run if 8x
becomes a serious candidate.

## Active task — HC year-ladder backfill via 3-stage chain

**Why.** Iterate `varrer-processos → baixar-pecas → extrair-pecas`
per HC year, working backward from 2026, to close out the four-year
HC ladder (2022-2026) with current Fly-cloud OCR for ACÓRDÃOs and
correct EMENTAs corpus-wide.

**Chain shape (per year).** Sequential, idempotent (`set -e` +
`--retomar` everywhere). Run dir: `runs/active/backfill-hc<YYYY>-<date>/`.

```bash
export PATH="$HOME/.fly/bin:$PATH"
export FLY_TESSERACT_URL=https://judex-ocr-tesseract-arcos.fly.dev/extract
export JUDEX_AUTO_TESSERACT_PROVIDER=tesseract_fly

setsid nohup bash -c '
# Pre-warm the Fly OCR cluster — eliminates the Stage-C cold-start 502
# storm without paying for an always-warm pool. ~$0.002/pulse; auto-stop
# returns Machines to $0 ~5 min after the run finishes.
fly machine start --select -a judex-ocr-tesseract-arcos || true
sleep 15

uv run judex varrer-processos -c HC -i <PID_LO> -f <PID_HI> \
    --saida runs/active/backfill-hc<YYYY>-<date>/varrer \
    --diretorio-itens data/source/processos \
    --rotulo hc<YYYY>_backfill_<date> --retomar

uv run judex baixar-pecas -c HC -i <PID_LO> -f <PID_HI> \
    --saida runs/active/backfill-hc<YYYY>-<date>/baixar \
    --retomar --nao-perguntar

uv run judex extrair-pecas -c HC -i <PID_LO> -f <PID_HI> \
    --provedor auto \
    --saida runs/active/backfill-hc<YYYY>-<date>/extrair \
    --paralelo 10 --retomar --nao-perguntar
' > runs/active/backfill-hc<YYYY>-<date>/launcher-stdout.log 2>&1 < /dev/null &
disown
```

**Template invariants** (don't drop these — each one is a scar from a
real failure mode this session):

- `setsid nohup … </dev/null & disown` — full session detach. Plain
  `nohup` survives terminal SIGHUP but not WSL VM suspend (HC 2026
  original chain died this way ~2 hr in on 2026-05-01).
- **No `set -e`** in the wrapper. `baixar-pecas` exits non-zero when
  *any* failures occur (e.g. 10 stable surface-2 404s), and `set -e`
  would kill the chain before Stage C runs. Each stage's own
  `--retomar` makes re-launching after a manual stop safe.
- `fly machine start --select` pre-warm pulse before any extrair work.
  `--paralelo 10` matches the cluster's organic warm-up rate; pre-warm
  ensures the cluster is ready when the parallel barrage hits. Without
  pre-warm, even the new tenacity retry can't always catch all
  cold-start 502s when 10 requests fire against 0 warm Machines.
- `--paralelo 10` (not 60). The 60-parallel number was tuned for the
  always-warm Modal cluster; on Fly with `min_machines_running = 0`
  it overwhelms the wake-on-request capacity. 10 lets the proxy keep
  pace with demand. Trade: ~30 min wall vs ~11 min on HC 2026, but
  with a much higher final success rate.
- `|| true` on the pre-warm — a transient `fly` CLI failure shouldn't
  kill the chain. The retry layer in `tesseract_fly.py` will absorb
  the cold-start storm if pre-warm doesn't fire.

**Per-year PID ranges** (from warehouse, refresh if corpus grows):

| Year | PID range          | Cases captured / total |
| ---- | ------------------ | ---------------------- |
| 2026 | 267,138 → 271,139  | 3,099 / 4,001          |
| 2025 | 250,920 → 267,137  | 13,365 / 16,200        |
| 2024 | 236,530 → 250,918  | 12,014 / 14,387        |
| 2023 | 223,886 → 236,833  | 11,129 / 12,644        |
| 2022 | 210,964 → 223,885  | 10,824 / 13,057        |

**HC 2026 chain in flight** (PID 1280502, launched 2026-05-01 17:40
BRT). Stage A (varrer) ~done (4001/4002 walked, 3097 ok + 903 dead
PIDs); stage B + C will auto-trigger via `&&`. Expected total
wall ~2.5 hr.

**Resumed 2026-05-02 12:44 BRT** after the original chain's parent
bash died ~19:42 (likely WSL VM suspend; nohup survives SIGHUP but
not VM exit). Used `setsid nohup … </dev/null & disown` for full
session detach this time. Stage B finished clean (downloaded=32,
cached=5,231, failed=10 — all 10 are stable 404s on
`digital.stf.jus.br/.../votos/<id>/conteudo.pdf` surface-2 IDs that
were captured in `sessao_virtual.documentos[].url` but no longer
resolve; harmless edge case, not a regression). Critical wrinkle:
the chain template's `set -e` interpreted `baixar-pecas`'s non-zero
exit (10 failures present) as a hard fail, so Stage C never ran via
the chain — had to launch standalone. **Followup**: either drop
`set -e` in the chain wrapper or change `baixar-pecas` to exit 0
when failures are present but capped (the failures live in
`pdfs.errors.jsonl` regardless).

Stage C (`extrair-pecas --provedor auto --paralelo 60`) launched
standalone at ~12:45 BRT. Auto router decided **pypdf=4,806 / 
tesseract_fly=446** (91% / 9% split) — `--provedor auto`
forecast: $0.03 / ~30 min, vs forced-`tesseract_fly` forecast of
$0.33 / ~262 min. Validates the auto router's value:
~11× cheaper, ~8× faster on this corpus shape.

**Known issue — Fly OCR 502s under cold-cluster load.** During
Stage C's first ~30 min, ~9% of OCR-routed requests
(~300 / ~3,500 attempted) returned `provider_error (HTTPError: 502
Bad Gateway)` from `judex-ocr-tesseract-arcos.fly.dev`. Diagnosis:
the cluster has `min_machines_running = 0` (`fly/fly.toml`), so all
60 Machines start `stopped`. Local `--paralelo 60` fires faster than
Fly's auto-start can warm Machines (5s cold-start), so the Fly edge
proxy routes some requests to Machines mid-boot and bounces them
with 502. Confirmed by Fly status during the run: cluster sat at
11-14 `started` Machines for most of Stage C, never warming the full
60 because `auto_stop_machines = "stop"` re-idles them as soon as a
batch wave passes. **502 is purely a transport signal** — the PDF
content is fine; verified by spot-opening source `.pdf.gz` for
several 502'd URLs (they parse cleanly outside the OCR path).

Stage C final tally (HC 2026, 2026-05-02 12:48-13:00 BRT, 11.3 min
wall): ok=4,869 (92.3%) / provider_error=383 (7.3%) / cached=11 /
no_bytes=10. **All 383 failures are Fly OCR transport, none are PDF
content** — auto-router routed 446 PDFs to `tesseract_fly`, only 63
succeeded (~14%). The other 383 = the entire OCR failure budget on
this run, all 502 / ReadTimeout from cold-start cluster.

Three mitigation paths, ordered by lift:

1. ✅ **Tenacity retry landed in `judex/scraping/ocr/tesseract_fly.py`**
   (2026-05-02). Wraps `_post_extract()` with retry-on-transient
   (502/503/504 + `requests.ConnectionError` + `requests.Timeout`,
   incl. ReadTimeout) at **5 attempts × `wait_exponential(2, 2, 30)`**
   (originally 3 × max=10; bumped after observing the in-flight
   retry pass needed more headroom against a 60-Machine cold cluster
   under `--paralelo 20`). 4xx (auth, malformed PDF) fails fast —
   no retry budget wasted. Pinned by 4 tests in
   `tests/unit/test_ocr_tesseract_fly.py` (suite 670 pass). With
   pre-warm pulse + `--paralelo 10` (chain template), the retry
   becomes the safety net for transient hits during the active run,
   not the primary cold-start mitigation. Expected post-fix failure
   budget on a re-run of HC 2026: **<5 PDFs (out of 446 OCR-routed)**,
   down from 383.
2. **Bump `min_machines_running = 20` in `fly/fly.toml`** before
   the next year's chain. Pre-warms a permanent pool, eliminating
   cold-start at the cost of ~$0.30/day idle billing. Right move
   for the upcoming HC 2025/2024/2023/2022 ladder where each year
   is 3-4× larger than 2026 — the retry alone gets us to ~95%, but
   pre-warming closes the rest.
3. **Drop `--paralelo 60 → --paralelo 20`** to match warm-cluster
   capacity. Lower throughput but higher reliability without infra
   changes. Useful as a stopgap if (2) doesn't ship.

Recommended sequencing: (1) shipped today; (2) is the next
follow-up before HC 2025 launches. (3) is a fallback knob, not a
permanent answer.

Failed 502 URLs are recoverable in-place via:

```bash
uv run judex extrair-pecas \
    --retentar-de runs/active/backfill-hc2026-2026-05-01/extrair/extracao.errors.jsonl \
    --provedor tesseract_fly \
    --saida runs/active/backfill-hc2026-2026-05-01/extrair-retry \
    --paralelo 20 --nao-perguntar
```

(Force `tesseract_fly` because `auto` would re-route the same way;
drop `--paralelo` to match warm capacity.)

**HC 2026 — closed out 2026-05-02 14:30 BRT.** Retry pass v2 (with
the new tenacity 5×30 retry + pre-warmed cluster + `--paralelo 10`)
processed 310 previously-failed URLs with **0 failures** (cost
$0.04, 3,453 pages OCR'd). Combined coverage: **5,179 ok / 10
legitimately-dead surface-2 voto IDs = 99.8% effective**, well
past the ≥99% close-out threshold. OCR quality validated by
8-sample ACÓRDÃO spot-check: EMENTA + ACÓRDÃO markers present in
100%, body text clean Portuguese, char counts plausible
(2.4k-23.7k range). Empirical validation that the four-layer
defense (pre-warm + paralelo 10 + tenacity 5×30 + auto router)
turns a 7.3% failure rate into 0% on the same workload.

**HC 2025 chain regression caught + fixed (commit `b5cd7d2`).**
First varrer-processos run since the Phase 1 parser fix
(`ae19d73`) surfaced an `AttributeError: 'NoneType' object has no
attribute 'encode'` on every redirect-form DJe entry —
`_resolve_publicacoes_dje:150` called `detail_fetcher(None)`
without checking. ~47% case error rate by record 1,300. Killed
the chain, fixed (skip the detail fetch when `detail_url is
None`), restarted from the same `--saida` (resume picked up the
~480 captured cases). Post-restart error rate: 0 in the first
2,750 records. HC 2026 didn't surface this because Stage A ran
2026-05-01 *before* the parser fix landed; the bug was latent
until the next varrer-processos invocation.

**Halt 2026-05-02 20:33 BRT — both backfill chains stopped at
user request.** Both chains had progressed Stage A (varrer) and
Stage B (baixar) cleanly and were in Stage C (extrair) at halt
time. SIGTERM was sent at 20:30 BRT; the `--paralelo 10`
extractors didn't drain in 10s (workers blocked on in-flight
`tesseract_fly` round-trips), so escalated to SIGKILL at 20:33.
State snapshots at halt:

| Chain    | Stage C progress              | Throughput / ETA              | State file mtime |
| -------- | ----------------------------- | ----------------------------- | ---------------- |
| HC 2025  | 13,512 / 28,261 (47.8%)       | 0.76 tgt/s · ETA ~323 min     | 20:33            |
| HC 2021  | 1,179  / 10,062 (~11.7%)      | early ramp                    | 20:32            |

HC 2025 ok=5,784 / cached=6,162 / no_bytes=11 / fail=1,543 at
halt — the ~11% running fail rate is well above HC 2026's
post-mitigation 0%, which would have been worth a regime probe
mid-run. SIGKILL is safe because `peca_store.py`'s atomic
write contract (tempfile + fsync + rename) means each
`pdfs.state.json` is either the prior or current snapshot,
never a half-write; `--retomar` resumes from the last flushed
record. Resume commands (Stage C only — Stages A + B are
fully done):

```bash
uv run judex extrair-pecas -c HC -i 250920 -f 267137 \
    --provedor auto --saida runs/active/backfill-hc2025-2026-05-02/extrair \
    --paralelo 10 --retomar --nao-perguntar

uv run judex extrair-pecas -c HC -i 198000 -f 210963 \
    --provedor auto --saida runs/active/backfill-hc2021-2026-05-02/extrair \
    --paralelo 10 --retomar --nao-perguntar
```

**`coletar`-orchestrator smoke test in flight** (PID 504746,
launched 20:22 BRT). Exercises today's three commits — `42f1d12
feat(coletar): orchestrator for the 6-stage pipeline (ADR-0004)`,
`53d3ce3 feat(replay): status-aware retry replay via
error_triage classifier`, `0abeef7 docs(adr): ADR-0004 coleta
orchestrator with status-aware retry`. Scope: HC 245000-245099
(100 cases, narrow slice of HC 2024 PID range). Run dir
`runs/active/coletar-smoke-2026-05-02/` with the orchestrator's
own `varrer/`, `baixar/`, `extrair/` sub-dirs (one launcher log
at the run root, not per-stage). At 20:37 BRT: extrair sub-stage
50/171 (29.2%) at 0.08 tgt/s, ETA ~24.6 min — slow rate worth
watching but plausible given the small denominator and the
`tesseract_fly` Modal hop dominating any non-pypdf doc.

**Monitor.** Same pattern across all 3 stages:

```bash
tail -f runs/active/backfill-hc2026-2026-05-01/launcher-stdout.log
```

(Per CLAUDE.md § Conventions, this is the canonical live sweep
monitor — don't reach for anything fancier first.)

**Done when.** Stage C's `report.md` shows ≥99% ok across the
year's targets; spot-check 5–10 ACÓRDÃO `.txt.gz` files (`EXTRATO
DE ATA` and `RELATÓRIO`/`VOTO` markers should appear exactly once
per doc). Then move on to HC 2025, repeating the chain with the
next PID range. After all five years close out, rebuild the
warehouse: `uv run judex atualizar-warehouse --classe HC`.

## In-flight side-quest — ADR-0003 Phase 1 (DJe parser fix)

**Why.** Today's HC 2026 baixar-pecas / extrair-pecas pre-flight surfaced that surface 3 (`publicacoes_dje[]`) emits zero URLs for HC 2023+ in every case JSON since STF's DJe content-URL migration on **2022-12-19** (date pinned by STF's own footer — *"Até o dia 19/12/2022, o Supremo Tribunal Federal mantinha dois Diários de Justiça Eletrônicos com conteúdos distintos"*). Initial diagnosis (system-changes.md row 2026-04-21) blamed the new `digital.stf.jus.br` platform's AWS WAF and queued Playwright as the only fix. Reconnaissance today refuted that: **the legacy `listarDiarioJustica.asp` endpoint still serves the publication metadata** for every year — our `parse_dje_listing` parser was hard-requiring the `abreDetalheDiarioProcesso(...)` JS-callback shape that STF kept only for procedural Distribuição entries. Substantive entries (Decisão / Acórdão / Despacho) post-migration use plain redirect-anchor shape, which the parser silently dropped. ADR-0003 codifies the diagnosis + fix path.

**Phase 1 — landed (parser + tests + types + ADR + docs):**

- ✅ `judex/scraping/extraction/dje.py` — `_DJ_HEADER_RE` loosened to match *"DJ do dia DD/MM/YYYY"* without DJ number; new redirect-anchor branch in the parsing loop emits `PublicacaoDJe` entries with `external_redirect=https://digital.stf.jus.br/publico/publicacoes`, `detail_url=None`, `incidente_linked=None`.
- ✅ `judex/data/types.py` — `PublicacaoDJe.numero: int → Optional[int]`; `detail_url: str → Optional[str]`; `incidente_linked: int → Optional[int]`; new `external_redirect: Optional[str]`. Pre-migration entries unchanged in shape.
- ✅ `tests/unit/test_extract_dje.py` — 4 new tests against captured HC 236529 (HC 2024) + HC 267138 (HC 2026) listing fixtures. Existing 10 tests still pass. Full unit suite 665/665 pass.
- ✅ ADR-0003 (`docs/adr/0003-surface-3-dje-capture-path.md`) — full diagnosis + Phase 1 vs Phase 2 (deferred Playwright) + open questions.
- ✅ ADR-0001 — header updated to "step 3 validates 2 of 3 surfaces; surface 3 awaits ADR-0003".
- ✅ `docs/system-changes.md` row dated 2022-12-19 — corrected from "Playwright queued" to "Phase 1 in progress; Phase 2 deferred".

**Phase 1 — landed (renormalize HC 2023-2026 case JSONs, no STF traffic):**

- ✅ One-shot Python pass: read every HC 2023-2026 case JSON, extract `dje_listing.html` from per-case tar.gz cache at `data/raw/html/HC_<pid>.tar.gz`, run patched parser, atomic-write the case JSON when parser yields ≥1 entry. Conservative selection: skip cases with already-populated `publicacoes_dje[]` (preserves HC 2022's 18,585 legacy entries; explicit non-goal of Phase 1).
- ✅ Run summary (528s wall, ~76 files/s): **20,690 cases populated, 51,361 publication entries surfaced.** 14,933 cases unchanged (degenerate-cache HTML — page-shell with no result content). 299 cases without HTML cache. Year-by-year coverage: 2023 → 15,660 / 2024 → 19,588 / 2025 → 22,328 / 2026 → 4,727.
- ✅ Manual portal verification: HC 223889 (2023, 1 entry, `numero=None`, `data=2023-01-09`) matches what STF's browser page shows.

**Phase 1 — pending:**

- ✅ Ran `uv run judex atualizar-warehouse --classe HC` 2026-05-02 12:43 BRT (~6 min, atomic swap, 1.85 GB warehouse). Empirical close-out by year (HC, post-migration):

  | Year | `publicacoes_dje` coverage | Was | `decisoes_dje.rtf_url` |
  | ---- | --------------------------:| ---:| ----------------------:|
  | 2022 |                      74.5% | 74.5% (legacy era unchanged) | 10,128 (legacy) |
  | 2023 |                  **49.8%** | **0%** | 0 (Phase 2 deferred) |
  | 2024 |                  **57.0%** | **0%** | 0 (Phase 2 deferred) |
  | 2025 |                  **72.8%** | **0%** | 0 (Phase 2 deferred) |
  | 2026 |                  **73.0%** | **0%** | 0 (Phase 2 deferred) |

  Pub-entry counts match the renormalize report exactly for 2025 (22,328) and 2026 (4,727); 2023/2024 land within ~3% of the renormalize numbers (warehouse flatten/dedupe path). All-zero `decisoes_dje.rtf_url` for 2023+ is the literal storage manifestation of "Phase 2 deferred" (per ADR-0003).
- ✅ Commit Phase 1 to `dev` — landed as `ae19d73 feat(dje): capture post-migration redirect entries (ADR-0003 Phase 1)`.
- [ ] Field-coverage audit (Sampled 50-500 per year × 21 fields × cliff/always-empty/drop-recent flags) — looking for OTHER systematic gaps similar to the DJe regression. Slow scan (90k file glob + sample); previous attempts hit Bash buffering / timeout problems. **Park for a focused offline run** rather than fighting the tool plumbing live.

**Phase 2 — explicitly deferred** unless a downstream analysis demands DJe-only decision content text. The metadata layer (Phase 1) covers ~80% of DJe queries per system-changes.md note; full content recovery requires Playwright + AWS WAF challenge solving (1-2 day lift). Forcing question for later: *does any analysis need DJe-only content beyond what surfaces 1 + 2 already provide?* Owner: data-side comparison on HC 2022, the only year with both legacy DJe content and full surface-1/2 coverage.

**HC 2022 enrichment — open follow-up.** Phase 1's selection skipped HC 2022 (already populated, no regression risk). But the cached HTML for those cases has been refreshed since the original 2022 scrape (HC 210826 has 1 entry on disk, parser would emit 3 from current cache: 1 legacy + 2 redirect). Renormalizing HC 2022 with a *merge-not-replace* strategy could add ~2 redirect entries per case on top of existing legacy entries — strict gain, no data loss. Not blocked by anything; defer until Phase 1 ships and proves stable.

## Backlog (carried over from prior cycle)

1. **Urgent — DJe scraper regression** (post-2022 blackout).
   Path 1 (andamentos-side regex parse) is the cheap mitigation;
   Path 2 (Playwright against `digital.stf.jus.br`) is the proper
   fix. See archived cycle § "Urgent — DJe scraper regression"
   for the full diagnosis + 200-case empirical table.
2. **HC 2017–2021 case sweeps** — ~37k missing case widths combined,
   ordered by year-density. Once cases land, re-use the 3-stage
   chain above per year.
3. **Schema cleanup** — drop `andamentos.link_text` /
   `documentos.text` / `decisoes_dje.rtf_text` from the warehouse
   build path (queries already use `pdfs_substantive`'s join).
4. **`publicacoes_dje` → warehouse** — open warehouse gap noted in
   prior archive § Backlog.
5. **`pick_provider` env-var override** is in place
   (`JUDEX_AUTO_TESSERACT_PROVIDER`) but the auto-router default
   remains `"tesseract"` for unit-test stability. Consider flipping
   the default to `"tesseract_fly"` once the Fly path proves stable
   over a full year-ladder.

## Where things live (durable pointers)

- [`docs/data-layout.md`](data-layout.md) — file/store map.
- [`docs/stf-portal.md`](stf-portal.md) — URL flow, auth triad, field map.
- [`docs/system-changes.md`](system-changes.md) — STF-side timeline + schema history.
- [`docs/rate-limits.md`](rate-limits.md) — WAF behavior, validated defaults.
- [`docs/process-space.md`](process-space.md) — class sizes + density.
- [`docs/cost-estimates.md`](cost-estimates.md) — per-unit anchors.
- [`docs/warehouse-design.md`](warehouse-design.md) — DuckDB schema + build.
- [`docs/data-dictionary.md`](data-dictionary.md) — schema history v1→v8.
- [`docs/completion-tracker.md`](completion-tracker.md) — per-year coverage.
- [`docs/reports/`](reports/) — promoted narratives (validation sweeps, OCR bakeoff).
- [`docs/superpowers/specs/`](superpowers/specs/) — major-feature design specs.
- [`fly/`](../fly/) — Fly.io OCR app (Dockerfile + server.py + fly.toml + README).

## Working conventions

- **`analysis/`** — git-ignored scratch for this-session exploration.
- **`config/`** — git-ignored (credentials). Canonical proxy input is
  `config/proxies` (flat file).
- **All non-trivial arithmetic via `uv run python -c`** — never mental
  math. See `CLAUDE.md § Arithmetic`.
- **Sweeps write a directory**, not a file. Layout in
  [`docs/data-layout.md § Sweep run artifacts`](data-layout.md#sweep-run-artifacts).
- **Live sweep monitor**: `tail -f <run_dir>/launcher-stdout.log` is
  the canonical view across all 3 pipeline stages — see
  `CLAUDE.md § Conventions`. Don't roll bespoke monitor scripts.
- **Archive convention**: when the active task closes out or this file
  grows past ~500 lines, move it (or the cycle-specific portion) to
  `docs/progress_archive/YYYY-MM-DD_HHMM_<slug>.md`.
- **Per-thread status convention** (added 2026-05-03 because the file
  hit 1196 lines with implicit-status threads). Every top-level
  section uses one of three prefixes:
  - `## Open thread — <slug> (<date>)` — active, still load-bearing
    for the current session. Default for new sections.
  - `## Resolved — <slug> (<date>)` — closed but kept in the file as
    short-term context (e.g. resume commands the next session might
    still want). Archive at the *next* session boundary, not the
    moment of resolution.
  - `## Active task — <slug>` / `## In-flight side-quest — <slug>` —
    multi-cycle work, distinct from a single-thread "open"/"resolved"
    pair. Stays at the top.

  When all `## Open thread` and `## Resolved` sections drain (or the
  file passes ~500 lines), apply the archive convention above. The
  flip from `Open thread` → `Resolved` is the load-bearing signal —
  it makes "what's still alive in this notebook" greppable without
  reading every section.
