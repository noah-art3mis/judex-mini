# Current progress — judex-mini

Branch: `main` (up to date with origin). Latest tip: `bb54e48`.

Single live file covering the **active task's lab notebook**
(plan / expectations / observations / decisions) and the **strategic
state** across work-sessions (what landed, what's in flight, what's
next, known limitations, operational reference). Convention at
`CLAUDE.md § Progress tracking`. Archive to
`docs/progress_archive/YYYY-MM-DD_HHMM_<slug>.md` when the active task
closes out or the file grows past ~500 lines.

For *conceptual* knowledge (how the portal works, how rate limits
behave, class sizes, perf numbers, where data lives), read:

- [`docs/data-layout.md`](data-layout.md) — where files live + the three stores.
- [`docs/stf-portal.md`](stf-portal.md) — URL flow, auth triad, field→source map.
- [`docs/rate-limits.md`](rate-limits.md) — WAF behavior, validated defaults, robots.txt posture.
- [`docs/process-space.md`](process-space.md) — HC/ADI/RE ceilings + density.
- [`docs/performance.md`](performance.md) — HTTP-vs-Selenium numbers, caching as the real lever.

## Working conventions

- **`analysis/`** — git-ignored scratch for this-session exploration (marimo notebooks, one-off scripts, raw JSON dumps). Safe to fill freely.
- **All non-trivial arithmetic via `uv run python -c`** — never mental math. See `CLAUDE.md § Calculations`. The rate-budget doc (`docs/reports/2026-04-16-D-rate-budget.md`) is the cautionary tale.
- **Sweeps write a directory**, not a file. Layout in [`docs/data-layout.md § Sweep run artifacts`](data-layout.md#sweep-run-artifacts).

---

# Active task — lab notebook

## Task

**Monitor the 4-shard concurrent HC backfill to completion.** The
monolithic single-worker backfill at
`runs/archive/2026-04-17-hc-full-backfill/` was SIGTERM'd
at 23:08 local after confirming the WAF-shape fix held over
1 656 fresh dead-zone records (all `under_utilising`, p50
0.87 s, p95 1.74 s, 7 rotations, driver-projected ETA for
remaining work = 5 330 min ≈ 89 h single-worker). It was
replaced with a **4-shard concurrent deployment** under
`runs/active/2026-04-17-hc-full-backfill-sharded/shard-{0..3}/`,
each shard consuming a disjoint 10–12-session ScrapeGW pool
(`proxies.txt` / `.b.txt` / `.c.txt` / `.d.txt`; 42 total
sessions across 4 files, zero overlap). Expected wall-time for
the remaining ~259 k records: ~16 h + dense-territory PDF
overhead vs. ~4–7 d single-worker.

Prior cycle archived at
[`docs/progress_archive/2026-04-18_0152_proxy-rotation-validated.md`](progress_archive/2026-04-18_0152_proxy-rotation-validated.md)
— CliffDetector + ProxyPool + WAF-shape fix + canary validation +
backfill relaunch. Reference for hypotheses, observation tables,
and the (now-resolved, see Decisions) canary-vs-backfill
divergence.

## Plan

1. **Passive monitoring** via `scripts/probe_sharded.py`
   (see [Reference § Live sharded-sweep probe](#live-sharded-sweep-probe)).
   Watch each shard's `regime` distribution and `min_processo`
   progression.
2. **Alarm response** (if any shard's regime → `approaching_collapse`
   or `collapse`): that shard stops cleanly via SIGTERM; diagnose
   via its `sweep.errors.jsonl` + `driver.log` `[rotate]` events.
   Other shards keep running — circuit breaker is per-shard.
3. **Milestone checkpoints:**
   - **+1 h:** every shard has processed ≥ 2 000 fresh records.
     Confirms all 4 proxy pools are healthy concurrently.
   - **+8 h:** shard 3 (lowest HC, densest paper-era territory)
     is first into heavy PDF work — log first dense-territory
     OK wall_s + regime state.
   - **+16 h:** projected completion; check for shard stragglers.
4. **On completion:** merge all 4 shard states into a
   consolidated `sweep.state.json` for downstream analyses,
   archive per-shard dirs, write a completion `REPORT.md`.

## Expectations / hypotheses

**H1 (expected).** Backfill runs to completion with regime mostly
`under_utilising` / `healthy`, occasional `l2_engaged` transitions
as proxy rotation handles real WAF pressure. Zero `collapse`
transitions. Throughput climbs to ~3–5 rec/sec in dense territory,
total wall ~4–7 days for 216 k extant HCs (varies with proxy
bandwidth + how often reactive rotations fire).

**H0 (would falsify).** Backfill trips `collapse` in dense
territory — meaning the fix works on `NoIncidente` but not on real
403s, or ScrapeGW exits get warm past what rotation can handle.

**H2 (unexpected but plausible).** Canary-style soft-block
surfaces in the backfill — fast uniform fails with `wall_s`
clustering tightly. If this happens, the hypothesis (a)
"soft-block" explanation from the archive gets promoted.

## Observations

_(append-only log. UTC timestamps.)_

- **2026-04-18 ~02:55 UTC — pre-shard monolithic state.**
  16 709 records / 13 943 ok / 2 766 fail. Fresh-sweep regime
  distribution since relaunch: 19 warming + 1 637 under_utilising.
  Zero 403, zero 429, zero retries. Last-200-records wall_s
  distribution: p50 = 0.87 s, p95 = 1.74 s. Dead-zone traversal
  was **not** rate-limited; the single-worker bottleneck was the
  per-record proxy round-trip floor, not WAF.
- **2026-04-18 ~03:08 UTC — monolithic SIGTERM, clean exit.**
  Stop signal hit at HC 271346 (record 1 655/273 000); driver
  finished the in-flight record at HC 271345, printed `stopping
  before item 1657/273000`, reported `proxy rotations during
  sweep: 7`, and wrote `sweep.errors.jsonl` + `report.md` (80 KB)
  before exiting. **Summary line from the exit transcript:**
  `ok=0 fail=1 656 error=0 skipped=0 429×0 5xx×0 · 0.85 proc/s
  · eta 5 330.2 min`. The `ok=0` is a display artifact of the
  progress counter (resets on each `--resume` invocation and
  counts only fresh attempts) — the 13 943 pre-existing ok
  records were skipped via `--resume` and never re-attempted.
  The 89-hour ETA directly motivated the 4-shard scale-out.
  7 rotations over 1 656 records ≈ one per ~200 s, matching the
  270 s timer cadence with zero reactive rotations — i.e. the
  rotator fired on schedule, not under WAF pressure.
- **2026-04-18 ~03:10 UTC — canary v2 complete.**
  50-record sweep against `proxies.txt` (now 10 distinct
  sessions), range HC 193000..192951. Result: 11 ok / 39 fail,
  regime held `warming`→`under_utilising`, **0 / 39 fails
  counted by the WAF-shape filter** (all NoIncidente, all
  `wall_s` 0.78–3.05 s, zero retries, zero 403/429/5xx). Full
  analysis at
  [`docs/reports/2026-04-17-proxy-canary-v2.md`](reports/2026-04-17-proxy-canary-v2.md).
- **2026-04-18 ~03:11 UTC — 4-shard backfill launched.**
  Pids: 740399 (shard-0, proxies.txt), 740407 (shard-1,
  proxies.b.txt), 740416 (shard-2, proxies.c.txt), 740422
  (shard-3, proxies.d.txt). Each shard's state seeded from the
  monolithic `sweep.state.json` (ok records only, partitioned
  by the same range-split rule as `scripts/shard_csv.py`):
  6 698 / 6 276 / 964 / 5 ok records pre-seeded per shard.
  T+30 s probe: all four shards writing, 26 warming + 4
  under_utilising globally, zero failures beyond the 23
  retry-candidate fails inherited by shard-0.
- **2026-04-18 ~03:30 UTC — scaling turned out sublinear.**
  Aggregate throughput after ~25 min: ~1.7 rec/sec (shard-0
  ~1.0 burning through dead-zone retries, shards 1–3 at
  0.2–0.26 each doing real dense-territory fetches). The
  earlier "16 h ETA at 4×" estimate assumed linear scaling;
  actual projection is ~40–42 h because the per-record bottleneck
  in dense territory is PDF fetch + parse, not proxy throughput.
  Still a ~2× improvement over 89 h monolithic but not 4×.
- **2026-04-18 ~03:52 UTC — data/ + docs/ layout reorg landed.**
  Commits `217623c` (reshuffle — 113 files, 19 renames, 92
  tracked-file deletions) + `80f8157` (code paths — 14 files).
  Five-axis structure: `config/` (secrets) / `runs/` (operational
  state) / `data/cache/` (regenerable) / `data/cases/` (scientific
  product) / `data/exports/` (derived) / `docs/reports/` (curated
  narratives). Shards SIGTERM'd at 23:48, relaunched at 00:04
  under new paths via launcher idempotency (each shard's state
  file preserved by plain `mv`; `--resume` picked up where it
  left off). Net throughput lost: ~5 records across 15 min. Full
  spec at [`docs/data-layout.md`](data-layout.md).
- **2026-04-18 ~03:58 UTC — `data/output/sample/` discovery.**
  Spot-check during the cleanup phase revealed that sample/
  was **not** a duplicate of `hc_backfill/` — it held 13 018
  distinct HC JSONs from earlier sweeps, with zero filename
  overlap. Merged into `data/cases/HC/` (total now 17 674 HC
  records). A naive "looks redundant, delete it" would have
  destroyed ~13 k scientific records. Rule confirmed: **always
  verify before deleting gitignored data**; the git safety net
  doesn't cover it.
- **2026-04-18 UTC (parallel strand) — lawyer-facing reports
  rewritten + CLI consolidated into `judex` hub.** Independent
  of the shard monitoring, in parallel:
  - **5 marimo notebooks** (`hc_famous_lawyers`,
    `hc_admissibility`, `hc_top_volume`,
    `hc_minister_archetypes`, `hc_explorer`) rewritten end-to-end
    in Portuguese juridical idiom — dropped "shrinkage", "IC
    Wilson", "empirical Bayes", "HC-mill", "arquétipos",
    "procedural punt" and other data-science terms from visible
    prose; chart titles and column labels translated
    (`fav_pct` → `% procedência`, `wins` → `procedência`,
    `losses on merits` → `denegação de mérito`, etc.);
    executive conclusion moved to the top of each notebook;
    caveats compacted as "Nota metodológica" at the bottom.
    `hc_famous_lawyers` absorbed the case readings from
    `docs/pdf-sweeps/2026-04-17-famous-lawyers-ocr/READINGS.md`
    inline (HC 135.027 Lama Asfáltica, HC 135.041 OSCIPs /
    Lei 9.296, HC 173.047 3-2 detail, HC 188.395 HC-COVID,
    HC 202.903 Missawa), added a stacked-bar plot of outcomes
    per advogado. Five HTMLs re-exported and audit-validated
    (14 banned terms × 5 files = 70 checks, all pass).
  - **`judex` console script** wired via `[project.scripts]`
    in `pyproject.toml`; CLI implementation lives in
    `src/cli.py` (so it's editable-installed by `uv sync`),
    `main.py` collapsed to a 12-line shim.
  - **Seven argparse scripts → five native Typer subcommands.**
    Collapsed `scrape` into `varrer-processos` (range mode
    auto-synthesises a CSV + auto-defaults `--rotulo` and
    `--saida`). Collapsed `fetch-pdfs` + `reextract` into
    `varrer-pdfs` with three modes: default is two-pass pypdf
    + OCR rescue; `--sem-ocr-resgate` for pypdf only; `--ocr`
    for OCR only. Graceful fallback when
    `UNSTRUCTURED_API_KEY` is absent (skips rescue with yellow
    warning instead of exiting non-zero). Retired
    `scripts/export_notebooks_html.sh` in favour of
    `judex exportar`. Retired `--backend selenium` CLI guard
    (invariant pinned by `test_http_backend_no_selenium.py`).
    Retired `tests/unit/test_main_backend.py` (was testing the
    removed flag).
  - **Portuguese command names + help text** throughout:
    `varrer-processos / varrer-pdfs / exportar / validar-gabarito
    / sondar-densidade`. Long flags in Portuguese (`--classe`,
    `--processo-inicial`, `--saida`, `--rotulo`, `--retomar`,
    `--simular`, `--ocr-resgate`, `--min-caracteres`), short
    flags preserved (`-c -i -f -o -d -l -g`).
  - **Tests: 217 passing** (down from 221 — 4 backend tests
    retired with the flag). Zero regressions.

## Decisions

- **2026-04-18 ~03:00 UTC — scale from 1 to 4 concurrent workers.**
  Triggered by user observing slow dead-zone traversal and
  noting that 42 disjoint ScrapeGW sessions are now available
  (4 prepared files with 10/10/12/10 entries, zero cross-file
  overlap). Chose range-partitioning over round-robin: preserves
  HC-descending order within shards, keeps "shard i is at HC X"
  reasoning intuitive.
- **2026-04-18 ~03:00 UTC — `pdf_cache.write` made atomic.**
  Concurrent shards can race on shared PDF URLs when an
  andamento citation appears in two cases on different shards.
  Patched `src/utils/pdf_cache.py` with `_atomic_write()`
  (tempfile + `os.replace`, pid-suffixed to avoid racer
  collisions). 221/221 unit tests green post-patch.
- **2026-04-18 ~03:15 UTC — canary-vs-backfill divergence
  resolved.** Canary v2 reproduced the same fast-uniform
  `NoIncidente` shape with 10 distinct sessions that v1 produced
  with 1 effective session. Shape is **STF's actual response for
  unallocated HCs**, not a ScrapeGW soft-block artifact.
  Hypothesis (a) "soft-block" and (c) "intermittent" both ruled
  out. CliffDetector's WAF-shape filter correctly treats it as
  zero WAF pressure (0/39 counted). See REPORT-v2.
- **2026-04-18 ~03:52 UTC — five-axis layout adopted.** The
  old `data/output/` mixed product + exports + tests + samples
  in one tier, and `docs/sweep-results/` mixed curated narrative
  with per-run ephemera. The reorg separates them by
  *ownership-and-lifetime*: who writes, who reads, and whether
  it's safe to delete. Deletion stakes are now path-visible
  (`data/cache/` = throwaway; `data/cases/` = precious). See
  the four-axes table at the top of `docs/data-layout.md`.

## Session lessons (2026-04-18)

Meta-learnings worth carrying forward to future sessions:

- **"Verify before delete" for any gitignored store.** The
  `data/output/sample/` near-miss (13 k HCs almost deleted as
  "duplicates") is the canonical example. Before any `rm -rf`
  on gitignored paths, spot-check a handful of records for
  filename/content overlap against the presumed "real" copy.
  Git won't save you here.
- **Scaling assumptions are sublinear for mixed workloads.**
  4 shards gave ~2× aggregate throughput, not 4×, because dense-
  territory records are PDF-fetch-bound rather than proxy-
  throughput-bound. Linear back-of-envelope extrapolations under-
  estimate wall time. Next time: measure the per-shard bottleneck
  before projecting.
- **Launcher idempotency pays for itself on migrations.** The
  sharded launcher's "state already has N records — leaving
  untouched" short-circuit made the 15-min migration + relaunch
  a ~5-record throughput loss. Preserving state across path
  changes via plain `mv` + `--resume` is robust; no special
  migration code needed.
- **`git add -u` during a reorg grabs unrelated uncommitted
  work.** During Commit B staging, `git add -u` silently pulled
  in a separate in-progress `main.py` → `judex` subcommand
  refactor (README, main.py, pyproject, uv.lock, tests). Had to
  `git restore --staged` each one. Prefer explicit file lists
  when the working tree has multiple parallel changesets.
- **Path-visible semantics beats documentation.** A reader who
  sees `data/cache/pdf/<sha1>.txt.gz` knows three things without
  a doc lookup: it's cache (deletable), URL-keyed (content-
  addressed), gzipped (reading needs decompress). The old
  `data/pdf/...` required reading CLAUDE.md to infer the same.
  Structure is the cheapest documentation.

## Open questions

1. **(Resolved — see Decisions)** Canary-vs-backfill divergence.
2. **(Resolved — landed)** Two-axis regime documentation now at
   [`docs/rate-limits.md § The two CliffDetector axes`](rate-limits.md#the-two-cliffdetector-axes).
3. **Still open — `filter_skip` / `body_head` instrumentation.**
   Add `filter_skip` boolean to `sweep.log.jsonl` (makes
   CliffDetector's view of each record visible in the log) and
   `body_head` to `sweep.errors.jsonl` on `NoIncidente` fails
   (distinguishes real STF "no such incidente" from any future
   proxy soft-block synthetic responses). ~8 lines total; not
   blocking the backfill.
4. **New — ScrapeGW concurrent-request cap.** We're now at
   4 shards × 4 tab-workers = ~16 concurrent sockets. ScrapeGW
   hasn't complained so far, but we don't have an explicit
   contract on this from the provider. If shards start throwing
   transport errors simultaneously, check provider dashboard
   first.

## Next steps

1. **+1 h: confirm all 4 shards healthy.** Probe
   `scripts/probe_sharded.py`; every shard should have ≥ 500
   fresh records, all in `warming` / `under_utilising`.
2. **+8 h: first dense-territory OK observation.** Shard 3
   (HC 68 250..1) will hit pre-computer-era paper HCs first —
   heavy PDF workloads. Log first OK wall_s.
3. **`filter_skip` + `body_head` instrumentation** (~30 min).
   Queued for any quiet slot; not blocking.
4. **Write consolidated `REPORT.md` on completion.** Merge 4
   shard state files, compute global fail/ok/regime distribution,
   archive per-shard dirs.

---

# Strategic state

## What just landed

- **WAF-handling stack + proxy rotation (2026-04-17 → 2026-04-18).**
  See archived cycle for the full five-commit chain (`b960568` …
  `b5cca20`). Headline: CliffDetector rolling-window regime
  classifier + time-based proxy-pool rotation + credential
  redaction + `--throttle-sleep` removal + WAF-shape fail filter +
  30 s floor on reactive rotation. 221/221 unit tests green. Live
  HC backfill relaunched via `--proxy-pool` with 10 distinct
  ScrapeGW Brazilian residential sessions. Fix validated in
  production at 900-record scale.
- **Progress-tracking convention landed** (`bb54e48`). `handoff.md`
  consolidated into this file; convention documented in
  `CLAUDE.md § Progress tracking`. Archive format:
  `docs/progress_archive/YYYY-MM-DD_HHMM_<slug>.md`.
- **Sharded-sweep primitive (2026-04-18).** New scripts:
  `scripts/shard_csv.py` (range-partitioning), `scripts/probe_sharded.py`
  (cross-shard state union), `scripts/launch_hc_backfill_sharded.sh`
  (idempotent N-shard launcher with per-shard state bootstrap).
  Enables N concurrent workers against disjoint proxy pools +
  disjoint CSV slices, sharing the `data/cases/HC/`,
  `data/cache/html/`, and `data/cache/pdf/` caches safely (pdf_cache now
  writes atomically via tempfile + `os.replace`).
- **Canary v2 (10 distinct sessions) resolved the
  canary-vs-backfill divergence.** Report at
  [`docs/reports/2026-04-17-proxy-canary-v2.md`](reports/2026-04-17-proxy-canary-v2.md);
  v1 archived at
  [`docs/reports/2026-04-17-proxy-canary-v1.md`](reports/2026-04-17-proxy-canary-v1.md) (+ [PLAN](reports/2026-04-17-proxy-canary-v1-PLAN.md)).
- **Two-axis regime documented** in
  [`docs/rate-limits.md § The two CliffDetector axes`](rate-limits.md#the-two-cliffdetector-axes).
- **Five-axis repo layout (2026-04-18, commits `217623c` +
  `80f8157`).** `config/` (secrets) / `runs/` (operational) /
  `data/cache/` + `data/cases/` + `data/exports/` / `docs/reports/`.
  `runs/` is fully gitignored — ends per-sweep `sweep.log.jsonl`
  churn in `git status`. `data/output/sample/` merged into
  `data/cases/HC/` (13 018 distinct HCs preserved; 17 674 total
  now). Full spec at [`docs/data-layout.md`](data-layout.md).
- **`judex` console script hub (2026-04-18, parallel strand).**
  Every CLI surface — scrape, sweep, PDF download, OCR
  re-extract, notebook HTML export, ground-truth diff, density
  probe — now goes through `uv run judex <cmd>`. Five
  subcommands, all Typer-native with Portuguese help text:
  `varrer-processos` (absorbed scrape), `varrer-pdfs`
  (absorbed fetch-pdfs + reextract under `--ocr-resgate` /
  `--ocr` flags, with OCR rescue on by default + graceful
  fallback when `UNSTRUCTURED_API_KEY` is absent), `exportar`,
  `validar-gabarito`, `sondar-densidade`. Implementation in
  `src/cli.py`; `main.py` is a thin shim that re-exports
  `app`. Entry point wired via `[project.scripts] judex =
  "src.cli:app"`. 217/217 unit tests green. Retired
  `scripts/export_notebooks_html.sh` and
  `tests/unit/test_main_backend.py` (both obsolete after the
  collapse).
- **Five lawyer-facing HC reports rewritten in Portuguese
  forensic idiom (2026-04-18).** All five marimo notebooks
  (`hc_famous_lawyers`, `hc_admissibility`, `hc_top_volume`,
  `hc_minister_archetypes`, `hc_explorer`) stripped of
  data-science jargon; executive conclusions moved to the
  top; chart titles/column labels Portuguese-native;
  `hc_famous_lawyers` absorbed five case readings inline
  (HC 135.027, HC 135.041, HC 173.047 3-2 detail, HC 188.395
  HC-COVID, HC 202.903). Five HTMLs in `exports/html/` audit-
  pass 14 banned-term checks. Target audience: the lawyer
  reading the report, not the data scientist who built the
  pipeline.

## In flight

### 4-shard concurrent HC backfill

- **Location:** `runs/active/2026-04-17-hc-full-backfill-sharded/shard-{0..3}/`
- **Shard PIDs** (at launch): 740399 / 740407 / 740416 / 740422
- **Proxy pools** (all disjoint): `proxies.txt` (10) / `.b.txt`
  (10) / `.c.txt` (12) / `.d.txt` (10) = 42 total sessions
- **HC range per shard:** shard-0 273000..204751, shard-1
  204750..136501, shard-2 136500..68251, shard-3 68250..1
- **Launcher:** `scripts/launch_hc_backfill_sharded.sh`
  (idempotent — re-running leaves already-seeded shards alone;
  skips labels already in-flight)
- **State at relaunch:** 13 943 ok records seeded across the 4
  shards (6 698 / 6 276 / 964 / 5). 2 766 previously-failed
  HCs re-enter the work queue via `--resume` semantics.
- **Stop cleanly:**
  `xargs -a runs/active/2026-04-17-hc-full-backfill-sharded/shards.pids kill -TERM`
- **Progress probe:** see [Reference § Live sharded-sweep probe](#live-sharded-sweep-probe)

## Next steps — queue

1. **Active-task follow-ups** (see above).
2. **Canary divergence investigation** (when spare time).
3. **Circuit breaker blind spot for V-style patterns.** Secondary
   breaker on rolling-median `wall_s` — noted in archived cycle's
   strategic section. Now partially addressed by CliffDetector's
   p95 axis, but the explicit rolling-median breaker would catch
   cases the p95 axis misses (e.g. a single 120 s outlier doesn't
   move p95 but does signal WAF adaptive block).
4. **Selenium retirement phase 2.** Re-capture ground-truth
   fixtures under HTTP + audit `deprecated/` self-containment.
   Spec at `docs/superpowers/specs/2026-04-17-selenium-retirement.md`.
5. **PDF extraction quality follow-ups.** See archived cycle for
   the Unstructured OCR pipeline state + known gaps around
   `scripts/reextract_unstructured.py` not routing through
   `pdf_driver`.

## Known limitation — denominator composition and right-censoring

Preserved from the archived cycle. Under FGV's §b rule (the
project default — see [`docs/hc-who-wins.md § Research question`](hc-who-wins.md#research-question)),
our `fav_pct` denominator is the set of cases with a recognized
terminating verdict. Pending cases excluded. Real costs for mixed-
vintage corpora: selection bias via processing speed,
right-censoring thrown away, denominator shrinkage on fresh data,
parser-gap pollution, temporal incomparability. Mitigations (not
yet implemented): split `None` into `pending` vs `parser_gap`,
report %-pending alongside every `fav_pct`, sensitivity analysis
via bracketing, Kaplan-Meier win curves on mature vintages. Full
discussion in
[`docs/progress_archive/2026-04-18_0152_proxy-rotation-validated.md § Known limitation`](progress_archive/2026-04-18_0152_proxy-rotation-validated.md).

## Known gaps in the `sessao_virtual` port

- **Vote categories are partial** — only codes 7/8/9 land in the final `votes` dict. See [`docs/stf-portal.md § sessao_virtual`](stf-portal.md#sessao_virtual--not-from-abasessao).
- **`documentos` values are mixed types**: string with extracted text (success) or original URL (fetch failed). Consumers must check `startswith("https://")`.
- **Tema branch has only one fixture test (tema 1020).** If you see drift there, probe another tema + add a fixture.

---

# Reference — how to run things

```bash
# Unit tests (221 tests, <4 s)
uv run pytest tests/unit/

# Ground-truth validation (HTTP parity against 6 fixtures)
PYTHONPATH=. uv run python scripts/validate_ground_truth.py

# HTTP scrape, one process, with PDFs
uv run judex varrer-processos -c ADI -i 2820 -f 2820 --saida runs/coletas/ADI-2820

# Wipe all regenerable caches (safe; HC case JSONs under data/cases/ survive)
rm -rf data/cache  # HTML fragments, sessao JSON, PDF text, requests.db
```

## Running sweeps

```bash
# One-shot sweep over a CSV of (classe, processo) pairs
PYTHONPATH=. uv run python scripts/run_sweep.py \
    --csv tests/sweep/shape_coverage.csv \
    --label my_sweep \
    --parity-dir tests/ground_truth \
    --out runs/active/<date>-<label>

# Long sweep with proxy rotation
PYTHONPATH=. uv run python scripts/run_sweep.py \
    --csv tests/sweep/<input>.csv \
    --label long_sweep \
    --proxy-pool config/proxies.a.txt \
    --out runs/active/<date>-<label>

# Resume (skip already-ok processes)
PYTHONPATH=. uv run python scripts/run_sweep.py \
    --csv <same-csv> --label <same> --out <same-dir> --resume

# Retry only previously-failed processes
PYTHONPATH=. uv run python scripts/run_sweep.py \
    --retry-from runs/archive/<dir>/sweep.errors.jsonl \
    --label <label>_retry \
    --out runs/active/<date>-<label>-retry
```

**Stopping a running sweep cleanly.** The driver installs SIGINT/
SIGTERM handlers. On signal it finishes the in-flight process,
breaks the loop, then writes `sweep.errors.jsonl` + `report.md`
and exits with its normal status code.

```bash
ps -ef | grep run_sweep | grep -v grep           # find the pid
kill -TERM <pid>                                 # clean stop
# or: pkill -TERM -f "run_sweep.*<label>"
```

`SIGKILL` is last resort: per-record writes are atomic so
`sweep.log.jsonl` + `sweep.state.json` are always consistent and
the run is resumable via `--resume`, but `sweep.errors.jsonl` and
`report.md` won't be written. A `--resume` run regenerates both.

## Live sharded-sweep probe

Check progress across all 4 shards without burning context.
Returns in <1 s.

```bash
# union of all 4 shard states + per-shard regime + mtime
PYTHONPATH=. uv run python scripts/probe_sharded.py \
    --out-root runs/active/2026-04-17-hc-full-backfill-sharded

# count rotation events across all shards
grep -cH "\[rotate\]" \
    runs/active/2026-04-17-hc-full-backfill-sharded/shard-*/driver.log

# confirm all 4 shard workers still alive
pgrep -af "run_sweep.*hc_full_backfill_shard"
```

## Launching sharded sweeps

```bash
# Shard a CSV into N range-partitions
PYTHONPATH=. uv run python scripts/shard_csv.py \
    --csv tests/sweep/<input>.csv \
    --shards 4 --out-dir tests/sweep/shards/

# Launch N concurrent backfill shards (HC-specific launcher,
# reads 4 pre-staged proxy files at repo root)
nohup ./scripts/launch_hc_backfill_sharded.sh \
    > runs/active/<dir>/launcher-stdout.log 2>&1 & disown

# Stop all shards cleanly
xargs -a runs/active/<dir>/shards.pids kill -TERM
```

## Marimo notebooks under `analysis/`

HC analysis lives in five marimo notebooks — see
[`docs/hc-who-wins.md § Notebook layout`](hc-who-wins.md#notebook-layout--investigation-strands-2026-04-17).

```bash
# interactive editor (opens a browser tab, full reactivity)
uv run marimo edit analysis/hc_famous_lawyers.py

# view-only
uv run marimo run analysis/hc_famous_lawyers.py

# headless (WSL/SSH/container) — marimo prints a localhost URL; forward the port first
uv run marimo run --headless analysis/hc_famous_lawyers.py
```

Swap for `hc_explorer.py`, `hc_top_volume.py`,
`hc_minister_archetypes.py`, `hc_admissibility.py`.

HTML export (interactive plotly preserved) — via the unified Typer
hub (`main.py`):

```bash
# all five → exports/html/*.html (gitignored)
uv run judex exportar

# single notebook or custom out-dir
uv run judex exportar --apenas hc_famous_lawyers
uv run judex exportar --diretorio-saida /tmp/share
```

The same hub exposes the scraper and every sweep-adjacent script
— `varrer-processos / varrer-pdfs / exportar / validar-gabarito /
sondar-densidade`. Run `uv run judex --help` for the list;
`uv run judex <cmd> --help` shows each subcommand's flags
(Portuguese-native, with English flags preserved on the underlying
argparse scripts).
