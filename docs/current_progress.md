# Current progress — judex-mini

Branch: `main`. Tip: `290c99c` (pushed:
`1ae0920` refactor drop-html-field, `290c99c` docs archive + cron
monitoring session). Prior cycle archived at
[`docs/progress_archive/2026-04-18_2030_steady-state-monitoring-plus-economics.md`](progress_archive/2026-04-18_2030_steady-state-monitoring-plus-economics.md)
— 8.5 h cron-monitored backfill, HC density map reconciled, Selenium
bake-off, bandwidth economics.

**Status as of 2026-04-18 ~20:30 UTC: HC 4-shard backfill still
running at steady state.** 46 773 ok / 15 049 fail global, 0.75 ok/s
aggregate. Quota runway ~22 h (3.61 GB of 5 GB topup remaining vs
shard-1's ~38 h solo-chew need = ~17 h gap). Cron monitor armed on
`:13` / `:43`. See
[archived observation log](progress_archive/2026-04-18_2030_steady-state-monitoring-plus-economics.md#observations)
for the full session history.

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

**Ride the HC 4-shard backfill through completion and decide the
quota-wall strategy when it hits.** 4 shards running since 11:55 UTC
relaunch, currently at 46 773 ok / 15 049 fail / 0 new errors in
8.5 h of continuous load. Shard-1 (uniformly-dense middle) is the
bottleneck at 0.38 proc/s with ~38 h solo-chew remaining; other
shards will finish earlier and go idle. ScrapeGW quota runs out
before shard-1 completes by ~17 h at current burn. Cron
(`b27687d1`, `:13`/`:43`) monitors for dead workers, `collapse`
regime, >5 new ProxyError entries, or 30-min global-ok stall.

## Plan

1. **Let the cron heartbeat run.** No manual intervention unless an
   alert fires. Workers are independent of the Claude session; the
   cron only matters while this session is alive.
2. **Quota-wall decision when it hits.** Reactive topup (+5 GB,
   100 BRL) is the default; preemptive topup is an alternative.
3. **Post-HC harvest** — consolidated REPORT, reconcile process-space
   doc, ship the CliffDetector noise-reduction fix.

## Expectations / hypotheses

**H1 (expected).** Steady-state throughput (46 ok/min aggregate)
holds until either (a) HC completion or (b) 407 ProxyError cluster
signals quota exhaustion. Regime churn stays at the
`l2_engaged ⇄ approaching_collapse` edge without crossing into
`collapse`. Rotator continues to self-correct alerts within 1 tick.

**H0 (would falsify).** Throughput degrades, OR a new error class
(403/429/5xx) appears in `errors.jsonl`, OR a shard dies without a
clean shutdown. Any of these would force diagnosis.

**H2 (unexpected).** Shard-1 hits a dense cluster that breaks the
p95-outlier pattern (sustained >15s wall_s for 100+ records in a
row), suggesting a subset of HC cases is genuinely harder to scrape
(e.g. multi-volume cases with 20+ andamento PDFs). Would warrant a
per-case wall_s histogram post-backfill.

## Observations

_(append-only log. UTC timestamps.)_

- **2026-04-18 20:30 UTC — session archived, fresh file seeded.**
  Prior 8.5 h cron-monitored session (12:12 → 20:23 UTC) archived
  to `docs/progress_archive/2026-04-18_2030_steady-state-monitoring-plus-economics.md`.
  Carries the full density map / throughput progression / Selenium
  bake-off record. Workers still running at original PIDs
  (4719/4720/4721/4722); cron unchanged.

## Decisions

- **2026-04-18 20:30 UTC — archive the monitoring session, keep
  running.** The active task has evolved from "diagnose the
  overnight collapse and decide resume" to "ride the steady-state
  backfill to completion." Fresh active-task scope narrows to
  quota-wall handling + post-backfill harvest.

## Open questions

1. **CliffDetector noise-reduction** — make `filter_skip=True`
   fails neutral for the fail_rate axis; consider raising the p95
   threshold from ~7 s to ~10 s to match observed dense-territory
   baseline. (Queued for post-backfill.)
2. **Rolling-median wall_s breaker** — secondary safety net for
   V-style patterns the p95 axis misses. (Carried forward.)
3. **Quota-wall decision** — reactive vs preemptive top-up.
   Pending user call when the first 407 lands or before bedtime,
   whichever comes first.
4. **Scale beyond 4 shards?** — WAF headroom verified at 4× over
   8.5 h, untested at 8× or 16×. The arithmetic suggests it works
   (per-shard WAF counter is independent), but empirically unverified.

## Next steps

1. **Hands-off cron monitoring.** Nothing to do unless alert fires.
2. **Quota-wall strategy (user decision).** Three options surfaced
   in archived file § Decisions — default is reactive top-up.
3. **Post-backfill consolidated REPORT.md** merging all 4 shards'
   final state. Template: archived cycle's observation log.
4. **Post-backfill: reconcile `docs/process-space.md`** — HC
   ceiling numbers there are stale (doc says 25–40 k real HCs;
   G-probe + this sweep confirm ~216 k). One `uv run python`
   session against `data/cases/HC/*.json`.
5. **Post-backfill: `CliffDetector` noise-reduction PR** in
   `src/sweeps/shared.py` — one-liner + one new test.
6. **Post-backfill: next-class decision** — ADI (~400 MB, 8 BRL,
   rounding error) vs RE (~80 GB, ~1 600 BRL, real budgeting call).
7. **Carried-forward:**
   - Stratified-by-density sharding for next sweep (shard-1
     solo-bottleneck is fixable).
   - Rolling-median `wall_s` breaker.
   - Selenium retirement phase 2 — re-capture ground-truth
     fixtures under HTTP + audit `deprecated/` self-containment.
     Spec at `docs/superpowers/specs/2026-04-17-selenium-retirement.md`.

---

# Strategic state

## What just landed

- **Raw `html` field dropped from `StfItem`** (`1ae0920`). All 6
  ground-truth fixtures updated in lockstep. Shrinks case JSONs by
  ~50–200 KB each.
- **Cron-monitored 8.5 h backfill session** (archived). Empirical
  confirmation that HTTP + 4-shard proxy rotation sustains
  ~1 rec/s aggregate with zero WAF pressure. Four
  `approaching_collapse` alert trips, all benign p95/fail-rate
  detector noise; rotator self-corrected every one within 1 tick.
- **HC density map reconciled** (archived). G-probe (Apr 16)
  extrapolation of ~216 k real HCs is accurate; `docs/process-space.md`
  numbers are stale.
- **Throughput progression documented** (archived). Selenium
  amortised 20 s/case → HTTP cold 0.87 s/case → HTTP 4-shard
  0.98 s/case aggregate. ~8–10× end-to-end wall-clock speedup.
- **Selenium-vs-HTTP-with-proxies bake-off** (archived). HTTP wins
  every axis except resilience-to-STF-changes (which is why
  `deprecated/scraper.py` is frozen, not deleted).
- **`filter_skip` + `body_head` instrumentation** (`c463f14`) and
  unified CLI `judex` hub (`04b852a`) — already landed pre-session.

## In flight

### 4-shard concurrent HC backfill

- **Location:** `runs/active/2026-04-17-hc-full-backfill-sharded/shard-{0..3}/`
- **Shard PIDs (since 11:55 UTC relaunch):** 4719 / 4720 / 4721 / 4722
- **Proxy pools (all disjoint):** `proxies.a.txt` (10) /
  `.b.txt` (10) / `.c.txt` (12) / `.d.txt` (10) = 42 total sessions
- **HC range per shard:** shard-0 273000..204751, shard-1
  204750..136501, shard-2 136500..68251, shard-3 68250..1
- **Latest probe (20:23 UTC):** 46 773 ok / 15 049 fail / 0 new errors
- **Bandwidth:** 1.39 GB used of 5 GB top-up (3.61 GB remaining);
  ~22 h runway at 168 MB/h burn
- **Cron monitor:** job `b27687d1`, `13,43 * * * *`, session-only,
  7-day auto-expire
- **Stop cleanly:**
  `xargs -a runs/active/2026-04-17-hc-full-backfill-sharded/shards.pids kill -TERM`
- **Progress probe:** `PYTHONPATH=. uv run python scripts/probe_sharded.py --out-root runs/active/2026-04-17-hc-full-backfill-sharded`

## Next steps, ordered

1. Hands-off cron monitoring until alert or completion.
2. Quota-wall decision when the first 407 lands.
3. Post-backfill: consolidated REPORT + archive per-shard dirs.
4. Post-backfill: update `docs/process-space.md` with the ~216 k
   HC reality (see Doc amendments below).
5. Post-backfill: update `docs/performance.md` with the HTTP 4-shard
   aggregate throughput (0.98 s/case, 1.02 rec/s).
6. Post-backfill: update `docs/rate-limits.md` with the "8.5 h
   continuous 4-shard, zero 403/429" empirical result (promotes
   the V-sweep's "rotation > throttle" lesson to confirmed).
7. Post-backfill: `CliffDetector` noise-reduction PR.
8. Next-class decision (ADI then RE, or RE directly).

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
via bracketing, Kaplan-Meier win curves on mature vintages.

## Known gaps in the `sessao_virtual` port

- **Vote categories are partial** — only codes 7/8/9 land in the final `votes` dict. See [`docs/stf-portal.md § sessao_virtual`](stf-portal.md#sessao_virtual--not-from-abasessao).
- **`documentos` values are mixed types**: string with extracted text (success) or original URL (fetch failed). Consumers must check `startswith("https://")`.
- **Tema branch has only one fixture test (tema 1020).** If you see drift there, probe another tema + add a fixture.

## Doc amendments queued (for post-backfill)

Items this session produced that *should* update the conceptual
docs once the backfill completes. Do not amend live to avoid
contradicting in-flight observations:

- **`docs/process-space.md`** — already accurate (line 21:
  HC ~216 k, 69 % bimodal). **No amendment needed.** My earlier
  read of "25–40 k stale number" was wrong; the doc was ahead of
  me. Noted here so future-me doesn't re-survey.
- **`docs/rate-limits.md`** — line 172/262 still describes the
  world as "9-day full HC backfill from a single IP." That's
  still true for single IP but the doc hasn't absorbed the
  4-shard + proxy-rotation empirical validation. Add a section
  documenting: "8.5 h / 4 shards / 42 sessions / 0 × HTTP
  403/429/5xx" → rotation + sharding make full-HC ~2.5 days, not
  9 days, and the bandwidth cost is linear (~208 BRL regardless
  of shard count). Promote "rotation > throttle" from hypothesis
  to confirmed.
- **`docs/performance.md`** — line 133 says `3.60 s/process` is
  the HTTP-with-retry-403 single-worker baseline. Add: HTTP +
  4-shard proxy rotation gives **0.98 s/case aggregate** (per-
  shard 0.19 ok/s, unchanged from single-worker — rotation
  enables parallelism, doesn't speed up individual requests).
- **`docs/hc-who-wins.md`** — check whether the notebook-strand
  layout's sample-size estimates presume the old density ceiling;
  if so, the 216 k reality affects "what fraction of HCs does
  strand X need to cover" math.

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
```

**Stopping a running sweep cleanly.**

```bash
ps -ef | grep run_sweep | grep -v grep           # find the pid
kill -TERM <pid>                                 # clean stop
# or: pkill -TERM -f "run_sweep.*<label>"
```

## Live sharded-sweep probe

```bash
PYTHONPATH=. uv run python scripts/probe_sharded.py \
    --out-root runs/active/2026-04-17-hc-full-backfill-sharded

grep -cH "\[rotate\]" \
    runs/active/2026-04-17-hc-full-backfill-sharded/shard-*/driver.log

pgrep -af "run_sweep.*hc_full_backfill_shard"
```

## Launching sharded sweeps

```bash
# Shard a CSV into N range-partitions
PYTHONPATH=. uv run python scripts/shard_csv.py \
    --csv tests/sweep/<input>.csv \
    --shards 4 --out-dir tests/sweep/shards/

# Launch N concurrent backfill shards
nohup ./scripts/launch_hc_backfill_sharded.sh \
    > runs/active/<dir>/launcher-stdout.log 2>&1 & disown

# Stop all shards cleanly
xargs -a runs/active/<dir>/shards.pids kill -TERM
```

## Marimo notebooks / judex CLI hub

```bash
uv run judex --help
uv run judex exportar --apenas hc_famous_lawyers
uv run marimo edit analysis/hc_famous_lawyers.py
```
