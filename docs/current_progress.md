# Current progress — judex-mini

Branch: `main`. Tip: `04b852a` + **uncommitted** `filter_skip` /
`body_head` instrumentation (this session, 8 new tests, 226/226
green). Prior cycle archived at
[`docs/progress_archive/2026-04-18_0342_sharded-backfill-plus-instrumentation.md`](progress_archive/2026-04-18_0342_sharded-backfill-plus-instrumentation.md)
— 4-shard backfill launch, data/ + docs/ reorg, `filter_skip` +
`body_head` landing.

Single live file covering the **active task's lab notebook**
(plan / expectations / observations / decisions) and the **strategic
state** across work-sessions (what landed, what's in flight, what's
next, known limitations, operational reference). Convention at
`CLAUDE.md § Progress tracking`. Archive to
`docs/progress_archive/YYYY-MM-DD_HHMM_<slug>.md` when the active
task closes out or the file grows past ~500 lines.

For *conceptual* knowledge (how the portal works, how rate limits
behave, class sizes, perf numbers, where data lives), read:

- [`docs/data-layout.md`](data-layout.md) — where files live + the three stores.
- [`docs/stf-portal.md`](stf-portal.md) — URL flow, auth triad, field→source map.
- [`docs/rate-limits.md`](rate-limits.md) — WAF behavior, validated defaults, robots.txt posture.
- [`docs/process-space.md`](process-space.md) — HC/ADI/RE ceilings + density.
- [`docs/performance.md`](performance.md) — HTTP-vs-Selenium numbers, caching as the real lever.

## Working conventions

- **`analysis/`** — git-ignored scratch for this-session exploration (marimo notebooks, one-off scripts, raw JSON dumps). Safe to fill freely.
- **All non-trivial arithmetic via `uv run python -c`** — never mental math. See `CLAUDE.md § Calculations`.
- **Sweeps write a directory**, not a file. Layout in [`docs/data-layout.md § Sweep run artifacts`](data-layout.md#sweep-run-artifacts).

---

# Active task — lab notebook

## Task

**Await 4-shard HC backfill completion and validate the new
`filter_skip` / `body_head` log shape on the first post-instrumentation
sweep.** The monitor-while-backfill-runs task from the archived cycle
continues — four shards are still in flight under
`runs/active/2026-04-17-hc-full-backfill-sharded/shard-{0..3}/` (20 451
global records / 16 823 ok as of 03:42 UTC, shard-1 already at 28
`l2_engaged` observations handled cleanly by the rotator). The live
shards will *not* emit the new fields (they imported the old code);
the next sweep launched after commit will be the first to carry them.

## Plan

1. **Passive monitoring via `scripts/probe_sharded.py`.** Same
   regime-watching + alarm response as the archived cycle. Links
   under [Reference § Live sharded-sweep probe](#live-sharded-sweep-probe).
2. **Commit the instrumentation changes** (user confirmation
   pending) so the next sweep picks them up.
3. **Validate the new log shape on a small fresh sweep** once the
   backfill is done (or via a `--retry-from` of the current
   `sweep.errors.jsonl` slice). Expectation: NoIncidente fails
   show `filter_skip=true` + `body_head="/processos/listarProcessos.asp?..."`;
   real WAF fails show `filter_skip=false`.
4. **Write consolidated `REPORT.md` on completion.** Merge 4 shard
   state files, compute global fail/ok/regime distribution, archive
   per-shard dirs.

## Expectations / hypotheses

**H1 (expected).** Backfill runs to completion mostly
`under_utilising` / `healthy` with occasional `l2_engaged` handled
by time-based + reactive rotation. Net wall: ~40–42 h from the
sharded launch (sublinear scaling, PDF-fetch-bound in dense
territory). Zero `collapse` transitions.

**H0 (would falsify).** Backfill trips `collapse` in dense
territory — the WAF-shape fix worked on the dead zone but not on
real 403s, or ScrapeGW exits go hot past what rotation can absorb.

**H2 (unexpected).** The ScrapeGW concurrent-request cap bites at
16 sockets (4 shards × 4 tab-workers) — simultaneous transport
errors across shards. If this fires, provider-dashboard-first.

## Observations

_(append-only log. UTC timestamps.)_

- **2026-04-18 03:42 UTC — shard state at archive time.** Global
  20 451 recs / 16 823 ok / 3 628 fail. Regimes: 130 warming + 6 344
  under_utilising + **34 l2_engaged** (28 on shard-1, 6 on shard-3).
  Shard-3 still at `min_processo=29` (highest-work territory); all
  four shards fresh-mtime.
- **2026-04-18 03:40 UTC — `filter_skip` + `body_head` landed
  (uncommitted).** 8 new tests green, full suite 226/226.
  `CliffDetector.observe` now returns `is_bad`; `resolve_incidente`
  raises `NoIncidenteError(http_status, location)` instead of
  returning `None`; `AttemptRecord` gains `filter_skip` +
  `body_head`; `run_one` + `_to_attempt_record` thread both through.
  Dead `Optional[ProcessFetch]` / `Optional[StfItem]` branches
  deleted now that the None-return path is gone. Live shards still
  run the old code — new fields appear only on the next
  freshly-launched sweep.

## Decisions

_(populated when the next landmark event happens)_

## Open questions

1. **ScrapeGW concurrent-request cap.** We run 4 shards × 4
   tab-workers ≈ 16 simultaneous sockets. Provider contract on
   concurrency is unspecified. If shards start throwing transport
   errors at the same second, check the provider dashboard first.
2. **Rolling-median wall_s breaker.** Carried forward from the
   archived cycle. Secondary breaker that catches what p95 misses
   (e.g. single 120 s outliers that don't move p95 but signal an
   adaptive block). Spec lives in the archived strategic section.
3. **Validate `filter_skip` / `body_head` shape in a live sweep.**
   Unit tests cover the record shape; but we haven't yet confirmed
   a real STF `NoIncidente` response comes through with the
   expected `body_head="/processos/listarProcessos.asp?..."` value.
   First post-instrumentation sweep resolves this.

## Next steps

1. **User decision: commit + push the `filter_skip` / `body_head`
   changes.** Suggested commit message:
   `feat: add filter_skip + body_head to sweep log`.
2. **Keep monitoring shards.** Next milestone is first OK in dense
   territory from shard-3 (HC < 68 250).
3. **On backfill completion:** consolidated `REPORT.md`, archive
   per-shard dirs, decide whether to launch the next class (ADI? RE?).
4. **ScrapeGW concurrent-request cap audit** (~15 min): check
   provider docs or dashboard for a concurrency limit.
5. **Rolling-median wall_s breaker** — secondary safety net for
   V-style patterns; spec in archived strategic section.

---

# Strategic state

## What just landed

- **`filter_skip` + `body_head` instrumentation (this session,
  uncommitted).** `AttemptRecord` gains two Optional fields;
  `CliffDetector.observe` returns `is_bad`; `NoIncidenteError`
  replaces Optional-return from `resolve_incidente`. 8 new tests,
  226/226 green. Changes span `src/sweeps/shared.py`,
  `src/sweeps/process_store.py`, `src/scraping/scraper.py`,
  `scripts/run_sweep.py`, `scripts/class_density_probe.py`,
  `scripts/validate_ground_truth.py`. Dead `Optional[...]` branches
  removed.
- **Unified CLI `judex` console script** (`04b852a`). Typer-based
  Portuguese CLI with 5 subcommands: `coletar / exportar /
  varredura / pdfs / validar-gabarito / sondar-densidade`. Invoke
  via `uv run judex --help`.
- **Sharded-sweep primitive + 4-shard HC backfill launch
  (2026-04-18, archived cycle).** `scripts/shard_csv.py`,
  `scripts/probe_sharded.py`,
  `scripts/launch_hc_backfill_sharded.sh`; atomic `pdf_cache.write`;
  42 disjoint ScrapeGW sessions across `config/proxies.{a,b,c,d}.txt`.
- **Five-axis repo layout (2026-04-18, archived cycle).** `config/`
  / `runs/` / `data/cache/` / `data/cases/` / `data/exports/` /
  `docs/reports/`. `runs/` fully gitignored; ends per-sweep
  `sweep.log.jsonl` churn in `git status`. Full spec at
  [`docs/data-layout.md`](data-layout.md).
- **WAF-handling stack + proxy rotation (2026-04-17, further-archived
  cycle).** CliffDetector rolling-window regime classifier +
  time-based proxy-pool rotation + credential redaction +
  WAF-shape fail filter + 30 s floor on reactive rotation. See
  [`docs/progress_archive/2026-04-18_0152_proxy-rotation-validated.md`](progress_archive/2026-04-18_0152_proxy-rotation-validated.md)
  for the full chain.
- **Progress-tracking convention** (`bb54e48`).
  `CLAUDE.md § Progress tracking`. Single live file covering both
  lab notebook and strategic state.

## In flight

### 4-shard concurrent HC backfill

- **Location:** `runs/active/2026-04-17-hc-full-backfill-sharded/shard-{0..3}/`
- **Shard PIDs** (at current launch): 812450 / 812457 / 812466 / 812475
- **Proxy pools** (all disjoint): `proxies.a.txt` (10) /
  `.b.txt` (10) / `.c.txt` (12) / `.d.txt` (10) = 42 total sessions
- **HC range per shard:** shard-0 273000..204751, shard-1
  204750..136501, shard-2 136500..68251, shard-3 68250..1
- **Latest probe (03:42 UTC):** 20 451 recs / 16 823 ok / 3 628 fail;
  34 `l2_engaged` observations handled cleanly
- **Stop cleanly:**
  `xargs -a runs/active/2026-04-17-hc-full-backfill-sharded/shards.pids kill -TERM`
- **Progress probe:** see [Reference § Live sharded-sweep probe](#live-sharded-sweep-probe)

## Next steps — queue

1. **Commit `filter_skip` + `body_head` changes.** Pending user
   confirmation. One-line subject:
   `feat: add filter_skip + body_head to sweep log`.
2. **Active-task follow-ups** (see lab-notebook section above).
3. **ScrapeGW concurrent-request cap audit.** (~15 min)
4. **Rolling-median wall_s breaker.** Secondary breaker that
   catches adaptive-block patterns p95 misses.
5. **Selenium retirement phase 2.** Re-capture ground-truth
   fixtures under HTTP + audit `deprecated/` self-containment.
   Spec at `docs/superpowers/specs/2026-04-17-selenium-retirement.md`.
6. **PDF extraction quality follow-ups.** See archived cycle for
   the Unstructured OCR pipeline state + known gaps around
   `scripts/reextract_unstructured.py` not routing through
   `pdf_driver`.

## Known limitation — denominator composition and right-censoring

Preserved across cycles. Under FGV's §b rule (the project default —
see [`docs/hc-who-wins.md § Research question`](hc-who-wins.md#research-question)),
our `fav_pct` denominator is the set of cases with a recognized
terminating verdict. Pending cases excluded. Real costs for
mixed-vintage corpora: selection bias via processing speed,
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
# Unit tests (226 tests, <5 s)
uv run pytest tests/unit/

# Ground-truth validation (HTTP parity against 6 fixtures)
PYTHONPATH=. uv run python scripts/validate_ground_truth.py

# HTTP scrape, one process, with PDFs
uv run judex coletar -c ADI -i 2820 -f 2820 -o json -d data/cases/ADI --sobrescrever

# Wipe all regenerable caches (safe; HC case JSONs under data/cases/ survive)
rm -rf data/cache
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

HTML export (interactive plotly preserved) — via the unified Typer
hub:

```bash
# all five → exports/html/*.html (gitignored)
uv run judex exportar

# single notebook or custom out-dir
uv run judex exportar --apenas hc_famous_lawyers
uv run judex exportar --diretorio-saida /tmp/share
```

The `judex` hub exposes the scraper and every sweep-adjacent
script: `coletar / exportar / varredura / pdfs / validar-gabarito /
sondar-densidade`. Run `uv run judex --help` for the list;
`uv run judex <cmd> --help` shows each subcommand's flags.
