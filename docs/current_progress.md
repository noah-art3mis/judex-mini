# Current progress — judex-mini

Branch: `main`. Prior cycle archived at
[`docs/progress_archive/2026-04-21_0805_hc-2025-arm-a-8-shard-cliff-cascade.md`](progress_archive/2026-04-21_0805_hc-2025-arm-a-8-shard-cliff-cascade.md)
— arm A of the 8-vs-16 experiment: HC 2025 @ 8 shards, full-range
re-scrape (13,755 pids). Cliffed cascade overnight — 8/8 shards,
53.5% coverage (7,356 records), 6,399 pids in recovery queue. First
direct L3-per-exit-IP reputation gradient data.

**Status as of 2026-04-21 08:09.** Corpus: **90,196 HC files** (+7,356
arm-A fresh v8+DJe re-scrapes; 2025 now content-fresh for the 53.5%
arm A covered; remaining 46.5% still stale pre-2026-04-17 content).
PDF cache: **1.5 GB / 10,841 PDFs** (arm A didn't run baixar-pecas
yet). Dead-ID graveyard: `data/dead_ids/HC.txt` (**3,348 confirmed
pids**, pre-arm-A; arm-A's NoIncidente observations not yet
aggregated). Main `judex.duckdb` and 2026 sub-warehouse unchanged.
Nothing executing (all 8 arm-A shards self-stopped on cliff).

Single live file covering the **active task's lab notebook** and the
**strategic state** across work-sessions. Archive to
`docs/progress_archive/YYYY-MM-DD_HHMM_<slug>.md` when the active
task closes out or the file grows past ~500 lines.

For *conceptual* knowledge (how the portal works, how rate limits
behave, class sizes, perf numbers, where data lives), read:

- [`docs/data-layout.md`](data-layout.md) — where files live + the three stores.
- [`docs/stf-portal.md`](stf-portal.md) — URL flow, auth triad, field→source map, DJe flow.
- [`docs/system-changes.md`](system-changes.md) — timeline of STF-side + internal changes (DJe migration, schema v1→v8, Selenium retirement, known gaps).
- [`docs/rate-limits.md`](rate-limits.md) — WAF behavior, validated defaults, robots.txt posture.
- [`docs/process-space.md`](process-space.md) — HC/ADI/RE ceilings + density.
- [`docs/performance.md`](performance.md) — HTTP-vs-Selenium numbers, caching as the real lever.
- [`docs/warehouse-design.md`](warehouse-design.md) — DuckDB warehouse schema + build pipeline.
- [`docs/data-dictionary.md`](data-dictionary.md) — schema history v1→v8.

## Working conventions

- **`analysis/`** — git-ignored scratch for this-session exploration (marimo notebooks, one-off scripts, raw JSON dumps). Safe to fill freely.
- **`config/`** — git-ignored (credentials). Canonical proxy input is `config/proxies` (flat file, one URL per line; `#` comments + blank lines OK). Sharded launchers split it round-robin into N per-shard pools at `<saida>/proxies/proxies.<letra>.txt` at launch time. Older `config/proxies.{a..p}.txt` files are leftovers from the prior dir-based mode and can be deleted.
- **All non-trivial arithmetic via `uv run python -c`** — never mental math. See `CLAUDE.md § Calculations`.
- **Sweeps write a directory**, not a file. Layout in [`docs/data-layout.md § Sweep run artifacts`](data-layout.md#sweep-run-artifacts).

---

# Active task — lab notebook

## Task

**HC 2023/2024 backfill + 8-vs-16 shard experiment arm B + arm-A
recovery.** Three concrete deliverables from this cycle:

1. **Arm B — HC 2024 @ 16 shards.** The A/B's treatment arm. Generate
   `hc_2024_full.csv` via `--full-range --dead-ids`; launch all 16
   pools `proxies.{a..p}.txt`. Cooldown since arm A's last cliff is
   ~7h40m — past the overnight reset threshold per
   `docs/rate-limits.md § Two-layer model`. **With arm A's data in
   hand, the revised prediction is that 16 may cliff *less* than 8**
   (smaller per-shard slices → less time past L2 engagement horizon).
2. **Arm-A recovery** — 6,399 ungrabbed 2025 pids from cliffed
   shards. Build recovery CSV from each shard's `sweep.state.json`
   (pids present in input CSV but missing from state); relaunch
   direct-IP single-thread with `--no-stop-on-collapse`. Yesterday's
   2026 recovery did this in ~45 min for 654 pids — so ~7–10h for
   6,399 is the budget. Queue **after** arm B to avoid confounding
   pool state.
3. **Arm C — HC 2023** at the winner's cadence. Only after the A/B
   writeup.

## Experiment — 8 vs 16 shards (arm B pending)

Arm A is complete; see archive 2026-04-21_0805 for the full
writeup. **Cliff cascade forced a metric recast** — instead of
"wall-clock to finish 13,755 pids", compare arms on: (i) records
landed per hour of productive work, (ii) coverage at fixed
wall-clock (e.g. at the 3h mark), (iii) cliff count per shard-hour.

**Revised hypothesis** (the key recalibration from arm A): the
original framing missed a third axis — **per-shard workload size vs.
L2 engagement window**. Arm A's 1,720-pid-per-shard slice kept shards
in the post-L2 danger zone 4.4× longer than 2026's 387-pid slices.
At 16 shards, per-shard workload roughly halves, so each shard may
finish before sustained axis-B engagement. The A/B now tests three
competing effects:
(i) pool-independence gain (favors 16),
(ii) per-pool request-rate penalty (favors 8 if ASN-level),
(iii) per-shard-time-in-danger-zone (favors 16 on large workloads).

**H4 — Pool-headroom-vs-workload budget model.** A new,
falsifiable prediction derived from arm A's cliff-ordering data.

A shard cliffs iff its *workload_time* exceeds its pool's
*effective_budget*:

  workload_time      ≈ slice_size / rps                   (observed rps ≈ 0.15)
  effective_budget   ≈ N_proxies × T_L2 − residual_L3_debt (N=10, T_L2≈25 min)

The pool's fresh theoretical budget is 10 × 25 min ≈ **4h 10m**.
Residual L3 debt from yesterday's session scales linearly with how
much scraping each IP in the pool absorbed the day before —
empirically estimated from arm A's cliff-order data:
- Pools that finished yesterday clean (`a`): **~3h effective**
- Pools that finished yesterday seasoned (`b`, `d`): **~2h effective**
- Pools that finished yesterday hot (`c`, `e`, `f`, `g`): **~1–2h effective**
- Pools that finished yesterday already-cliffed (`h`): **~35 min effective**

**Predicted cliff behavior per arm:**

| Arm | Shards | slice | workload_time | typical budget | cliff? |
|-----|--------|-------|---------------|----------------|--------|
| A (observed)    | 8  | 1,720 | ~3h 10m | 0.5–3h after debt | **8 / 8 cliffed** ✓ |
| B (prediction)  | 16 |   899 | ~1h 40m | ~2–3h after 36h-idle (fresh ~160 IPs) | **≤ 3 / 16 cliffed** |
| 2026 (observed) | 8  | 387   | ~45m    | ~3–4h (fresh-ish)          | **3 / 8 cliffed** (workload borderline) ✓ |

Arm B scrape target confirmed at **14,387 pids** (range
236,529..250,915, 11,113 on disk, 0 confirmed deads in range). The
total workload is only ~5% larger than arm A's 13,755 — so any
cliff-count improvement on arm B is attributable to per-shard
slice size (899 vs 1,720), not less total work. Controlled
comparison.

Arm B's 16 pools will have had ~36h idle by launch (21h overnight
gap + another ~15h from arm A ending to arm B starting). That's
closer to the "overnight full reset" threshold than arm A got, so
residual-L3 should be lower per pool than arm A saw — further
favoring the "≤ 3 cliffs" prediction.

**H4 falsification test.** If arm B at 16 shards / ~860 pids
cliffs ≥ 6 of 16 shards, the headroom-budget model is wrong (or
missing a term, e.g. request-rate-density effects, WAF time-of-day
behavior, or pool-independence violation via ASN-level
degradation). If arm B cliffs ≤ 3, the model is supported and
becomes the operational planning heuristic for arm C and future
backfills ("size per-shard slice ≤ 70% of pool's effective budget,
accounting for residual debt").

**H5 — Sticky session duration: 10 min → 5 min.** Piggyback
experiment on arm B. Scrapegw's sticky-session knob controls how
long a session ID holds an exit IP reserved before the sticky
expires. Our driver rotates session IDs every 270s (~4.5 min) by
time-based rotation, so:

- **sticky=10** (current): IP is held for the full 10 min; after
  we rotate off at 4.5 min, the IP sits idle-reserved to our
  account for another 5.5 min. Any residual reputation debt
  ages during that idle window but the IP can't be re-leased
  to someone else mid-sticky.
- **sticky=5** (proposed): IP is released ~30s after we rotate
  off at 4.5 min. Over a 3h sweep, each IP holds a tighter
  residency → scrapegw can recycle it out of our pool sooner →
  the "IPs that are ours today" set changes faster within the
  sweep, potentially spreading L3 reputation accumulation
  across more distinct upstream IPs.

**Hypothesis.** sticky=5 shortens the per-IP sustained-load
window by a factor of ~10/5 = 2× in steady-state, which should
modestly reduce per-IP L2 engagement at the cost of slightly more
session-cookie re-establishment overhead (first few requests on a
new IP are slower while auth triad warms).

**Confound.** Arm B changes **both** shard count (8 → 16) and
sticky duration (10 → 5) from arm A. A cleaner cliff count on
arm B can't cleanly attribute to either change alone. Two ways to
de-confound if results are interesting:

1. **Arm C — HC 2023 with sticky reverted to 10 min** at the
   shard count the A/B picks. Compare cliff rate vs arm B → shows
   sticky effect in isolation.
2. Or: run a small targeted A/B on the 6,399-pid arm-A recovery
   CSV, one half at sticky=5 and the other at sticky=10 — closer
   sample size, same pool state. Cheaper.

**Falsification.** If arm B's cliff count is indistinguishable from
the H4-predicted range (≤ 3), sticky change likely didn't help or
hurt. If arm B cliffs ≤ 1 (meaningfully better than H4 predicts),
sticky=5 is plausibly contributing. If arm B cliffs ≥ 6 with
sticky=5 while H4 predicted ≤ 3, sticky=5 may actually hurt.

**H6 — Proxy freshness dominates throughput, not shard count or
sticky duration.** Live evidence from arm B (2026-04-21, 13.5 min
in): cluster throughput 10.52 rec/s vs arm A's peak 1.24 rec/s
(~8.5×). Decomposition:

- 2× from shard count (8 → 16), linear parallelism.
- **4.4× from per-shard throughput (0.15 → 0.66 rec/s)** —
  dominant factor.

The 4.4× per-shard gain traces almost entirely to **tenacity
retry-403 chains not firing** on fresh IPs. Arm A driver logs
show records returning `ok` with walls of 5–13s (tenacity
absorbing 403s and averaging in exponential backoff). Arm B
driver logs show walls of 0.5–1.5s (one HTTP call per record, no
retries). Per-IP L1 reputation (~80–100 req / 5-min window) is
at zero for freshly-fetched proxies, so requests don't nudge
into 403 territory → no retries to absorb → ~5–10× faster
per-request walls.

**Operational consequence (high confidence, landed as ops
heuristic):** the highest-leverage knob for sweep throughput is
**refreshing proxies before every sustained scrape**. Proxy
freshness > shard count > sticky duration > everything else. A
fresh 160-IP batch from scrapegw before each year's backfill
gets us arm-B-equivalent speed; reusing yesterday's pool gets us
arm-A-equivalent cascade.

**Falsification / controlled follow-up.** Can't cleanly isolate
proxy-freshness from (i) time-of-day effects (arm A ran evening
BRT vs arm B's early morning) and (ii) sticky-5 vs sticky-10.
Clean test: run arm-A's remaining 6,399-pid recovery CSV twice —
once with yesterday's `config/proxies.{a..h}.txt` (sticky-10, old
IPs) and once with `config/proxies` (fresh, sticky-5), at the
same time of day. If freshness dominates, the fresh run is ≥ 3×
faster per-shard regardless of time match. Queue under § Data
recovery below.

**Decision rule** (updated for the recast metrics) — apply after
arm B completes:
- **16 wins** → 16-arm coverage at 3h is ≥ 1.3× 8-arm's **and**
  cliff_count_B ≤ cliff_count_A. Use 16 for arm C.
- **16 loses** → 16-arm coverage at 3h is < 0.8× 8-arm's **or**
  cliff_count_B ≥ 1.5× cliff_count_A. Use 8 for arm C.
- **Ambiguous** → default to 8 conservatively, flag for follow-up.

## Next steps

**Completed this session:** arm B (HC 2024 @ 16 shards, 92% in ~32 min),
arm C launched (HC 2023 @ 16 shards, in flight from 09:16 BRT). A/B
decision landed: **16 wins, 8 retired for sustained jobs.** Full
writeup: [`docs/reports/2026-04-21-8-vs-16-shards.md`](reports/2026-04-21-8-vs-16-shards.md).

**What's still ahead** (nothing executing):

a. ✅ **Arm-A + arm-B + arm-C recovery pass** — *landed 2026-04-21*.
   7,672-pid union-recovery at 16 shards; 96.0% / 1 cliff / 43.5 min
   wall-clock. See § In flight § Recently completed for the H6
   lesson (non-refreshed pool cost 3.6× throughput). 305-pid
   shard-k residue deferred per § Data recovery #3.
b. **`baixar-pecas` for 2023/2024/2025** — new PDFs from v8 content
   path (arms A/B/C + recovery fresh case JSONs now have accurate
   `documentos[]` link lists). Separate WAF counter on
   `sistemas.stf.jus.br`, 16 shards safe (doesn't share reputation
   with `/processos/*`). **Refresh proxies first** per H6 — don't
   repeat today's 3.6× cost of skipping the preflight.
c. **`extrair-pecas` on newly-downloaded PDFs** — zero HTTP, local
   CPU. Provider choice (`pypdf` cheap / `mistral` | `chandra` high
   quality) decided per-tier.
d. **Full warehouse rebuild** at end-of-cycle. One atomic swap picks
   up all fresh content from arms A/B/C + recovery + PDFs +
   extraction. Build-stats validation now catches silent regressions
   (DJe at 0% will show as WARN, loud signal if any other field
   regresses).
e. **DJe content re-capture (not warehouse flatten).** Warehouse
   flatten turned out to already exist; the real gap is the
   extractor regression — STF migrated DJe to `digital.stf.jus.br`
   on 2022-12-19 and our scraper still hits the stub-serving old
   endpoint. Pick **§ Backlog DJe capture path 1** (andamentos-side
   metadata, 1–2h) for a cheap 80% unblock; **path 2** (Playwright
   for the new platform, 1–2 days) when full DJe index is worth
   the infra cost. Full diagnosis in § What just landed.

## Practical tips from today's experiments (landed as ops discipline)

These are the reusable rules extracted from the 8-vs-16 A/B. The
*situational* numbers live in the report; the *rules* live here.

1. **Proxy freshness is the single highest-leverage knob** (H6,
   strongly supported). The 4.4× per-shard throughput jump from arm A
   to arm B traces almost entirely to tenacity retry-403 chains *not*
   firing on fresh IPs. Refresh the pool before every sustained
   sweep — this dominates shard count and sticky duration combined.
   **Preflight step, not a tweak.**
2. **16 shards + fresh pool + sticky=5 is the default** for
   year-backfill workloads. 8-shard config retired for sustained
   jobs (remains available for small/ad-hoc sweeps).
3. **H4 sizing heuristic** (confirmed by arm B). Size per-shard slice
   so `workload_time ≤ 0.3 × effective_budget`. Practical shortcut:
   **keep each shard ≤ ~800 pids on a freshly-fetched pool.** The
   ~7,546-pid recovery at 16 shards = 472 pids/shard, ratio 0.08 —
   safe by a wide margin.
4. **One proxy file, one flag.** Both `varrer-processos` and
   `baixar-pecas` take `--proxy-pool FILE` (a flat list, one URL per
   line; `#` comments + blank lines tolerated). In sharded mode the
   launcher round-robin-splits the file into N per-shard pools at
   `<saida>/proxies/proxies.<letra>.txt` automatically. Paste a fresh
   scrapegw batch into `config/proxies` once; never maintain
   per-pool files by hand.
5. **L3-per-IP reputation persists across days.** Arm A's cliff
   ordering matched each pool's state at the *prior day's* 2026 sweep
   end — overnight idle partially clears but not fully. Consequence:
   a "rested but used" pool is not the same as a fresh one. When in
   doubt, refresh.
6. **CliffDetector axis-B window-full gate** (landed this session).
   p95 is only consulted once the rolling window fills (n = window
   size, default 50). Axis-A (WAF-shaped fail rate) stays un-gated
   so V-style collapse still catches early. Eliminates the n=20
   false-positive class arm B's shard-o hit.
7. **Unmeasured confounds to stay honest about:** time-of-day (arm A
   evening BRT vs arm B morning BRT) and ASN-level WAF thresholds
   above 16 shards (~63 STF req/s on arm B; 32 shards would push
   ~125 req/s). **Land § Backlog Request-footprint reduction items
   before any 32-shard experiment** — each cuts 15–20% of per-case
   STF HTTP calls; stacked, they buy a 30–50% politeness cushion.
8. **A second proxy provider is the only true redundancy** against
   scrapegw L3-per-IP decay. Not acted on yet; logged as the one
   structural hedge against today's single-provider fragility.

## Throughput + regime baselines (anchor for future predictions)

Empirical numbers from today's runs + prior validations. Use these
to set expectations *before* a sweep launches; deviations are the
signal that something's off (pool fatigue, time-of-day, WAF policy
shift). All "per-shard rec/s" are steady-state medians, not peaks;
cluster rec/s = per-shard × N_shards. Regime % = share of records
in the named regime over the whole sweep.

### `varrer-processos` (case JSON, `portal.stf.jus.br`)

| config                                          | per-shard rec/s | cluster rec/s | typical regime mix              | cliff rate    |
|-------------------------------------------------|-----------------|---------------|---------------------------------|---------------|
| 1 worker, no proxy (sweep E baseline)           | ~0.28           | ~0.28         | 90% good, 10% warn              | n/a (1 worker)|
| 4 shards + aged proxies (sweep V validation)    | ~0.26           | ~1.02         | 75% good, 20% warn, ~5% l2      | low           |
| **8 shards + aged proxies** (arm A)             | **0.15**        | **1.24**      | 60% good, 30% warn, 10% l2      | **8 / 8 (cascade)** |
| **16 shards + fresh proxies** (arm B)           | **0.66**        | **10.52**     | 95% good, 5% warn, 0% l2        | 2 / 16 (genuine) |
| **16 shards + fresh proxies** (arm C, smaller)  | **0.65**        | **9.0**       | 96% good, 4% warn, 0% l2        | 0 / 16        |
| **16 shards + 8h-cooled-not-refreshed** (recovery) | **0.22**     | **3.45**      | 78% good, 12% warn, 1.6% l2     | 1 / 16        |

Rules-of-thumb derived:
- **Per-shard floor ≈ 0.15 rec/s** when retry-403 chains are firing
  (aged pool + portal-WAF-fatigue). Anything below this means proxies
  are exhausted; investigate before continuing.
- **Per-shard ceiling ≈ 0.7 rec/s** on a fresh batch — bottlenecked
  by the 5-XHR-fan-out per case + proxy wall, not WAF.
- **Cluster throughput is roughly linear in shard count** as long as
  per-shard stays in the green; sub-linear when individual shards drop
  into warn/l2.
- **`good` < 80% over a full sweep** = the pool is no longer fresh
  for this host; refresh it or expect a cliff cascade.

### `baixar-pecas` (PDF bytes, mostly `portal.stf.jus.br`)

| config                                              | per-shard rec/s | cluster rec/s | typical regime mix    | cliff rate |
|-----------------------------------------------------|-----------------|---------------|-----------------------|------------|
| 16 shards + portal-fatigued pool (HC 2025, 2026-04-21) | **0.06–0.17** | **2.14**      | mostly ok, sparse fail/http_error | none observed yet |
| 16 shards + fresh pool against `sistemas` host (no clean datapoint) | (projected) ~0.7 | (projected) ~12 | (projected) all ok    | n/a        |

`baixar-pecas` is bytes-only (one GET per PDF, no XHR fan-out), so on
a fresh-vs-host pool it should outpace `varrer-processos` per shard.
The current 2025 sweep is much slower because andamento attachments
come from `portal.stf.jus.br/processos/downloadPeca.asp` — the same
WAF bucket as case JSONs, which our pool already exhausted today.
**The fresh-host projection is unmeasured** — the next 2024 PDF run
on a refreshed batch is the cleanest opportunity to nail it down.

### Regime ladder reference

Source: `docs/rate-limits.md § Operating regimes`. CliffDetector
classifies each rolling window of records into one of:

| regime              | meaning                                            | typical fail-rate | action                       |
|---------------------|----------------------------------------------------|-------------------|------------------------------|
| `under_utilising`   | wastefully polite; pool has slack                  | 0–5%              | could push harder            |
| `healthy`           | steady scraping, L1 absorbed, L2 not engaged       | 5–10%             | nothing — this is the target |
| `l2_engaged`        | Pareto frontier; as fast as WAF tolerates pre-block | 10–20%           | fine for short bursts        |
| `approaching_collapse` | adaptive block firing; retry budget at risk     | 20–30%            | rotation; consider stopping  |
| `collapse`          | V-style cliff; gaps < 15 records between cycles    | > 30%             | stop, cool down ≥ 60 min     |

Decision is the worse of axis A (WAF-shape-filtered fail rate) and
axis B (p95 wall_s). Both axes are window-full-gated as of
2026-04-21 to suppress the n=20 false-positive class.

## Per-year completion tracker (HC)

Three pipeline stages per year. Status legend: ✅ ≥95% content-fresh /
landed · 🔄 actively in flight · 🟡 partial / older scrape, content-stale ·
❌ not started or sparse-on-disk. **Sources:** `cases` from on-disk
inventory + today's arm-A/B/C/recovery sweeps; `pecas` from
`data/cache/pdf/*.pdf.gz` count and known sweep launches; `extracted`
from `*.txt.gz` count. Per-year peças/extracted attribution is
approximate (the cache is URL-keyed, not year-keyed); refine when a
year-scoped probe is needed.

| year | width  | on-disk | cases                                     | peças                                   | extracted    |
|-----:|-------:|--------:|-------------------------------------------|-----------------------------------------|--------------|
| 2026 |  4,001 |   3,098 | ✅ done (initial sweep, pre-cycle)         | 🟡 partial (older ad-hoc runs)          | 🟡 partial   |
| 2025 | 16,200 |  13,346 | ✅ arm A + recovery (96% landed)           | 🔄 ~52% in flight (direct-IP, ETA ~17h) | ❌            |
| 2024 | 14,387 |  12,300 | ✅ arm B + recovery                        | ❌                                       | ❌            |
| 2023 | 12,644 |  10,841 | ✅ arm C (100% / 0 cliffs)                 | ❌                                       | ❌            |
| 2022 | 13,057 |   1,156 | ❌ **next backfill target — 11,901 missing** | ❌                                       | ❌            |
| 2021 | 14,508 |   7,423 | 🟡 51% on-disk, content-stale              | ❌                                       | ❌            |
| 2020 | 15,754 |   4,207 | 🟡 27% on-disk, content-stale              | ❌                                       | ❌            |
| 2019 | 14,352 |     914 | ❌ 13,438 missing                          | ❌                                       | ❌            |
| 2018 | 13,969 |     945 | ❌ 13,024 missing                          | ❌                                       | ❌            |
| 2017 | 12,604 |   2,053 | ❌ 10,551 missing                          | ❌                                       | ❌            |
| 2016 |  7,049 |   4,382 | 🟡 62% on-disk, content-stale              | ❌                                       | ❌            |
| 2015 |  6,319 |   5,584 | 🟡 88% on-disk, content-stale              | ❌                                       | ❌            |
| 2014 |  5,338 |   4,333 | 🟡 81% on-disk, content-stale              | ❌                                       | ❌            |

**Cumulative cache as of 2026-04-22:** 37,997 PDFs (.pdf.gz) + 32,529
extracted texts (.txt.gz) = 4.2 GB. The 86% extraction ratio reflects
prior `extrair-pecas` runs that processed everything in cache at the
time; new PDFs landed by the in-flight 2025 sweep are not yet
extracted.

**Backfill priority queue** (cases column, derived from %alive_have):
1. **2022** (11,901 missing, near-zero coverage) — single arm-B-sized
   sweep, ~25 min at 16-shard fresh-pool.
2. **2019, 2018, 2017** (~37k missing combined) — three sequential
   year sweeps; would close the 2017–2022 hole.
3. **2021, 2020, 2016, 2015, 2014** (mixed-coverage, content-stale) —
   `--full-range` re-scrapes, smaller marginal value than the missing-
   year sweeps; defer until 2017–2022 closes.
4. **Pre-2014** (paper-era, ≤47% density per `docs/process-space.md`) —
   not a near-term priority; lower yield per request.

---

# Strategic state

## What just landed (most recent cycle)

- **Canonical lawyer classifier + judge↔lawyer network notebook**
  (this session, 2026-04-22). Extended
  `judex/analysis/lawyer_canonical.py` from a pure name canonicalizer
  into the project-canonical party classifier: new
  `LawyerKind` enum (`sentinel / placeholder / pro_se / institutional
  / juridical / court / with_oab / bare`), `LawyerEntry` NamedTuple,
  and `classify(nome) → (kind, key, oab_codes)` built on
  `canonical_lawyer()`. Accent-insensitive institutional-prefix match
  is the load-bearing fix — `DEFENSORIA PUBLICA DA UNIAO` (4,766 rows,
  no acute accents) was slipping past every ad-hoc `DEFENSORIA
  PÚBLICA` prefix check as a "bare" lawyer. Now it lands in
  `institutional`. Also catches OAB codes outside parentheticals
  (`OAB/SP 148022`, `OAB-PE 48215`) via `_extract_oab_anywhere`.
  +17 pinning tests; 568 total. Full-corpus bucket distribution
  (HC ADV): institutional 5,254 rows (70%), with_oab 1,405,
  sentinel 181, bare 579, placeholder 74, pro_se 4, juridical 2,
  court 0. On IMPTE: sentinel 3,012 (the "phantom IMPTE" rows the
  docstring warned about), institutional 8,726, with_oab 64,111,
  bare 18,470.

  CLAUDE.md `§ Non-obvious gotchas` now points all future notebooks
  at `judex.analysis.lawyer_canonical` — the failure-mode catalog
  (accent variants, non-parenthetical OABs, law firms, courts-as-
  parties, sentinel typos) is one call away instead of one regex
  per notebook away.

  Also shipped: `analysis/hc_judge_lawyer_network.py` — Marimo
  notebook with three reactive views. **(1) pyvis bipartite with
  Barnes-Hut physics** (Obsidian-style), sandboxed in an
  `iframe srcdoc` to stop pyvis's dark-theme CSS from bleeding
  into the host page. Plain-text tooltips (vis-network renders
  `title` via `innerText`, so `<b>` / `<br>` showed as literal
  text — switched to `\n` delimiters). **(2) log₂(lift) heatmap**
  clipped to ±4 to avoid outlier saturation. **(3) minister ↔
  minister cosine projection** on lawyer-distribution vectors.
  Reactive filters: top-N (default 60), min-pair edge count
  (default 2), year range (default 2015–2026), `LawyerKind`
  multiselect (default `[with_oab]` — the critical default,
  dropping `institutional` from the defaults because it swamps
  minister-cosine into 0.99-everywhere meaninglessness).

  Self-describing filter banner renders the active state + the
  universe size + the edge count at the top, so the exported
  snapshot documents itself. Snapshot shipped to
  `analysis/reports/2026-04-22-hc-judge-lawyer-network.html`
  (~200 KB with `with_oab`-only default).

  **Substantive finding:** `ADV.(A/S)` is ~72% institutional in
  the HC corpus — the banca-de-renome (Toron, Bottini, etc.) lives
  in `IMPTE.(S)`, not `ADV.(A/S)`. The two roles capture different
  institutional facts (filer vs. lawyer-of-record after possible
  DP takeover). For private-bar coverage use
  `analysis/hc_famous_lawyers.py`; this notebook is the ADV-rep
  map.

  **Old-vs-new `partes` format check** (by year): `"E OUTRO(A/S)"`
  tail prevalence dropped from ~3% in 2017–2021 to <1% in 2022+,
  confirming the scraper's split-row migration. Partes-per-case
  mean rose 1.03 → 1.13 in 2023–2024 (splitting visible in
  aggregate). `LawyerKind` bucket shares are stable across years
  (institutional 77-86%, with_oab 13-25%) — classifier is
  era-robust. Cross-year trend analysis on co-lawyers-per-case is
  NOT reliable without controlling for rescrape vintage though —
  an older case rescraped under the new scraper will suddenly
  show more ADV rows than it did before.

- **Warehouse build-stats validation** (this session). Added
  population-rate thresholds per case-level field (`partes`,
  `andamentos`, `pautas`, `sessao_virtual`, `publicacoes_dje`) to
  `judex/warehouse/builder.py` as `MIN_POPULATION_RATES`. After
  every build, the stats print to stdout + threshold misses produce
  warnings that show up in `BuildSummary.validation_warnings`. New
  `--estrito` flag (`judex atualizar-warehouse --estrito`) promotes
  warnings to a non-zero exit for CI. **Caught the DJe-regression
  immediately on a live 2023 build**: `0.0% (threshold ≥ 5.0%) [WARN]`.
  Prevents the silent field-wide regression pattern that went
  undetected from 2026-04-19 through 2026-04-21. +4 tests; 547
  total.

- **DJe extractor regression — full diagnosis, no fix yet** (this
  session, via manual browser verification of HC 267809).

  **Root cause:** STF migrated DJe on **2022-12-19** (per the footer
  note on the old portal: *"Até o dia 19/12/2022, o Supremo Tribunal
  Federal mantinha dois Diários de Justiça Eletrônicos com conteúdos
  distintos"*). New DJe content lives at
  **`digital.stf.jus.br/publico/publicacoes`**, an entirely different
  host. Our scraper hits `portal.stf.jus.br/servicos/dje/listarDiarioJustica.asp`
  — which now serves only migration-redirect stubs for post-2022 DJe
  ("Para consultar essa publicação, acesse https://digital.stf.jus.br/…").
  Those stubs are rendered client-side via JS, so `requests` gets an
  empty shell; browsers show the redirect placeholders.

  **Other endpoints explored + ruled out:**
  - `portal.stf.jus.br/servicos/dje/pesquisarDiarioJustica.asp` —
    historical (pre-2022-12-19) archive. **403 on GET**, and the
    form expects `Número DJ/DJe` or `Período` (date range) — not
    incidente-keyed, so can't be used as a drop-in fix even for old
    cases.
  - `abaDecisoes.html` (cached as part of each case scrape) — lists
    *internal* STF decisions (5 "Decisão" mentions in HC 228072) but
    **0 DJe URLs**. Not a fallback.
  - `digital.stf.jus.br/publico/publicacoes` (the real post-2022
    source) — returns `202` + AWS WAF challenge JS from
    `token.awswaf.com`. Requires a headless browser to pass.

  **Consequence:** 0 of 3,118 2026 HCs + 0 arm A/B/C = 0% DJe capture
  across all 2023–2026 content. HC 125290's 4 DJe entries (and the
  other ~10 pre-2022 cases with DJe) are pre-migration carry-forward
  via `reshape_to_v8`, not live capture — those files were written
  when the old endpoint still returned server-rendered DJe content.
  Pre-2022 DJe is effectively frozen at what we already have; no
  systematic re-fetch is possible via GET.

  **What we still get without fixing DJe:**
  - `andamentos` already capture each `"ACÓRDÃO PUBLICADO, DJE N"` /
    `"DECISÃO PUBLICADA"` event as a structured row with date — so
    "when did this case get a DJe publication?" is answerable from
    andamentos alone.
  - `sessao_virtual[].documentos[]` still capture the Voto / Relatório
    PDFs → `baixar-pecas` + `extrair-pecas` already ingest the full
    decision texts. The missing piece is the *DJe index envelope*
    (DJE number, section, divulgation date) as a separate structure,
    not the decision texts themselves.

  **Three viable paths forward, queued (not picked):**
  1. **Andamentos-side DJe metadata extraction** (cheap). Parse
     `"DJE 123 de 05/02/2025 ..."` patterns from andamento strings,
     emit structured `{dje_numero, dje_data, secao}` alongside the
     existing andamento row. Small regex + schema addition; gets
     ~80% of DJe-level warehouse queries working without touching
     the external endpoint.
  2. **Playwright integration for `digital.stf.jus.br`** (real fix).
     Headless browser loads the page, solves the AWS WAF challenge,
     captures the `aws-waf-token` cookie, then `requests` uses that
     cookie for the actual API calls (the new platform is a SPA
     backed by a JSON API — once past WAF, direct-to-hit). New
     dependency, ~1–2 days of integration work, most reliable
     long-term.
  3. **AWS WAF challenge reverse-engineering** (brittle). Python
     libraries exist (`aws-waf-token` solvers) but STF can flip the
     challenge type (reCAPTCHA, Turnstile) at any time. Not
     recommended.

  **Build-stats validation will keep this visible.** Every future
  warehouse build will print `publicacoes_dje: 0.0% (threshold ≥ 5.0%)
  [WARN]` until path 1 or 2 lands. Don't silence — the warning is
  load-bearing.

- **CliffDetector axis-B window-full gate** (this session). Axis B
  (p95 wall_s) was firing false positives at n=MIN_OBS=20 because
  `int(0.95 * 20) = 19` made p95 equal to the max element — a single
  slow HTTP record with no retries/no fails could trip collapse. Fix:
  `p95` is only consulted once the rolling window is full (n == 50
  for default window size). Axis A (WAF-shaped fail rate) remains
  un-gated so V-style collapse still catches early. Caught by arm B's
  shard-o which cliffed at 20/899 on a single 66.67s HTTP record with
  zero WAF signal. +2 tests; 1 existing test updated to use 55 targets
  so the window actually fills. **Arm B's shard-o is officially
  flagged as a detector false-positive**, not a genuine cliff, for
  the A/B writeup's honesty.

- **Arm A — HC 2025 @ 8 shards cliff cascade** (full details in
  archive `2026-04-21_0805`). 53.5% coverage at 3h03m productive
  wall-clock; 8/8 shards cliffed across a 2.5h window. First direct
  L3-per-exit-IP reputation gradient measurement — cliff order
  matched pool state at yesterday's 2026 end.

- **`judex probe` CLI** (commit `865f6d9`). Rich-table live view of
  sharded sweeps — done/target, %, rec/s, min pid, severity-ordered
  colored regimes, elapsed/ETA. `--watch N` auto-refresh.
  Canonical monitoring surface; replaces the ad-hoc
  `scripts/probe_sharded.py` invocations. +7 tests.

- **`--full-range` mode on `generate_hc_year_gap_csv.py`** (same
  commit). Keeps on-disk pids in the output — only confirmed deads
  are filtered. Used for year re-scrapes where content-staleness of
  existing files can't be cheaply detected (`mtime` was clobbered by
  v8 renorm). +2 tests.

- **Progress doc refactor** (commit `08b19b0`). Marked 2026 ✅,
  spec'd 8-vs-16 experiment, archived prior cycle.

Tests: **538 green**. Cumulative cache: 1.5 GB PDFs, 90,196 HC cases.

## In flight

**Nothing executing.** Arms A/B/C + recovery all landed this cycle.
Content-freshness for HC 2023–2025 now covers 7,367 + 13,240 + 10,926
+ 7,356 = 38,889 fresh case JSONs via arms B/C + recoveries (arm A
initial 7,356, then 7,367 of its 7,672-pid recovery queue landed
across 2023/2024/2025 union). Corpus-wide freshness status moves
from "~half of 2025" to "~96% of 2023–2025 + 100% of 2026."

### Recently completed (today)

**HC recovery pass — 2026-04-21 afternoon** (task (a) from prior
next-steps). 7,672-pid union-recovery CSV (arms A/B/C target minus
ok-landed minus deads). 16 shards, interleave-sharded, reused proxy
batch (not refreshed — 8.5h cooldown since arm C). 7,367/7,672
landed (**96.0%**), **1 cliff (shard-k at 174/479)**, 305 pids for
residue. Wall-clock **43.5 min** vs 12-min fresh-pool prediction —
3.6× slowdown traces to L3 residual debt on reused batch. H6 tip #1
"refresh before every sustained sweep" now supported with **inverse
evidence**: skipping refresh cost 3.6× throughput even after 8.5h
idle. Run dir: `runs/active/2026-04-21-hc-recovery/`. H4 cliff
prediction (0–1) held (1 observed). The CliffDetector axis-B
window-full fix explicitly earned its keep — shards l (warn=133)
and p (warn=211) both made it to 100% despite elevated stress; under
the pre-fix detector they would have false-positive-cliffed.

**Arm C — HC 2023 @ 16 shards — completed.** 12,644/12,644 at 100%,
**0 cliffs**, 23.4 min productive wall-clock. Validated the new
default (16/fresh/sticky=5) on a third workload.
`runs/active/2026-04-21-hc-2023/`.

**A/B decision landed (2026-04-21 ~09:16): 16 wins decisively.**
Wall-clock 0.17×, cliffs 3 vs 8, coverage 1.72×. Full writeup:
[`docs/reports/2026-04-21-8-vs-16-shards.md`](reports/2026-04-21-8-vs-16-shards.md).
**16 shards + fresh proxies + sticky=5 is the new default** for
year-backfill workloads; 8 shards retired for sustained jobs.

**Arm B — HC 2024 @ 16 shards — completed.** 92.0% coverage
(13,240/14,387) in 31.5 min productive. 3 cliffs (1 detector
false-positive now fixed + 2 genuine late-stage). Residue folded
into the recovery pass above. `runs/active/2026-04-21-hc-2024/`.

## Backlog — ordered

### DJe capture — three paths (post-diagnosis, 2026-04-21)

STF migrated DJe to `digital.stf.jus.br` on 2022-12-19; our scraper
hits the old (stub-serving) endpoint. See § What just landed for
the full diagnosis. Pick **1** for fast metadata-level repair; pick
**2** when full DJe index is worth the infrastructure cost. Don't
pick **3**.

1. **Andamentos-side DJe metadata extraction** (1–2 hours of work).
   Regex-parse strings like `"ACÓRDÃO PUBLICADO DJE-N DIVULG.
   DD/MM/YYYY PUBLIC. DD/MM/YYYY"` from existing `andamentos` rows.
   Emit a new `dje_events` table in the warehouse: `{processo_id,
   dje_numero, divulgado_iso, publicado_iso, secao}`. Doesn't need
   any new HTTP; works on the corpus we already have. Gets ~80% of
   DJe-metadata-level queries unblocked.
2. **Playwright for `digital.stf.jus.br`** (1–2 days). Headless
   browser loads the new DJe platform, passes the AWS WAF challenge,
   captures the `aws-waf-token` cookie, then reverse-engineered API
   calls with that cookie get full DJe index including decision
   texts. New dependency but only used for the DJe tab, not the main
   scrape. Best long-term.
3. ⛔ **AWS WAF challenge reverse-engineering** — not recommended.
   STF can flip challenge type (reCAPTCHA / Turnstile) anytime;
   maintenance nightmare.

### Warehouse

1. **Rename `pdfs` table → `pecas`.** Holds all peças (PDF + RTF).
2. **`content_version` column on `cases`.** Enable cheap skip of
   content-fresh pids in future year re-scrapes — avoids the need
   for `--full-range` indiscriminate re-scraping.
3. **Decide on `data_protocolo_iso` redundancy** under v8.
4. ✅ **DJe warehouse flatten** — *landed* (this cycle's investigation
   confirmed `_flatten_publicacoes_dje` already exists in
   `builder.py`). The warehouse ingests DJe correctly; the problem is
   that `publicacoes_dje=[]` in the source JSONs due to the extractor
   regression above, not the builder.

### Data recovery

1. ✅ **Arm-A + arm-B + arm-C recovery** — *landed 2026-04-21*.
   Union-recovery CSV approach (targets minus ok minus deads)
   produced 7,672 pids; 16-shard pass at 96.0% / 1 cliff; see
   § In flight § Recently completed.
2. ✅ **Arm C — HC 2023** — *landed 2026-04-21*. 100% / 0 cliffs.
3. **Second-pass recovery for shard-k residue** (305 pids). Tiny
   queue; one shard, direct-IP or single small pool. Low priority —
   those 305 pids are a 0.3% tail across 2023–2025; doesn't
   materially change downstream warehouse/analysis quality. Defer
   unless a specific analysis needs them.
4. **PDFs + text extraction** per year once case-JSON scrapes land.
   Now unblocked — all four years content-fresh enough for peça
   fan-out. See § Next steps (b) / (c).

### Cliff detector hardening (partially done + future)

- **`--cliff-require-sustained K` flag** (still open). Arm A's
  shard-h cliffed on one 70s record after proxy rotation had briefly
  cleared the walls — genuine WAF pattern but the single-sample trip
  lost throughput. K=3 ("regime must be at collapse for K consecutive
  observations") would absorb rotation-forgiveness patterns on
  already-full windows. Distinct from the window-full-gate fix
  (which addressed arm-B's shard-o false positive at small n).
- ✅ **Axis-B window-full gate** — landed this session. Prevents
  false-positive collapse at n=MIN_OBS=20 where p95 ≡ max element.

### Operational hygiene

- **Bytes-cache suffix rename** `<sha1>.pdf.gz` → `<sha1>.bytes.gz`.
  Full playbook in 2026-04-19_2355 archive. Queued; safe now that no
  sweep is live.
- **`baixar-pecas --excluir-mortos`** — minor diff (dead IDs already
  naturally skipped via missing case JSON).
- **Pre-filter `baixar-pecas` by cache-hit** — opt-in helper that
  drops CSV rows whose URLs are all cached.
- **Fix `scripts/monitor_overnight.sh`** — scope stale-shard alerts
  to the currently-active tier.
- ✅ **`peca_targets._find_case_file` no longer walks the tree** —
  *landed 2026-04-21*. Was calling `r.rglob(name)` once per pid, so
  baixar-pecas startup was O(N_pids × N_files) per shard. Production
  layout is `<root>/<CLASSE>/judex-mini_*.json` flat under the
  bucket; replaced rglob with `(root/classe/name).is_file()` plus a
  fallback for callers that pass the classe-bucket directly. +1
  perf-guard test (asserts a buried case file is invisible to the
  direct probe). Stale: the running PDF sweep launched before the fix
  already paid the rglob tax; future invocations cold-start in seconds.
- **`pgrep` self-match gotcha in sweep-wait loops.** A background
  `until [ "$(pgrep -c -f <rotulo>_shard_)" = "0" ]; do sleep … done`
  never exits because the bash waiter's own command line contains
  the literal `<rotulo>_shard_` substring, so `pgrep -f` matches the
  waiter itself. Bit us on the 2026-04-21 recovery (~30 min of false
  "still running" state until manually killed). Correct patterns:
  (i) match the actual script path, e.g.
  `pgrep -f 'scripts/run_sweep\.py.*<rotulo>_shard_'`; or (ii) poll
  each shard's `sweep.state.json` + check for a terminal `done`/
  `collapse` marker; or (iii) use `pgrep -f <pattern> | grep -v $$`
  to exclude the shell running the check. Worth a one-paragraph
  addition to `docs/agent-sweeps.md` § Detached-sweep pattern.

### Request-footprint reduction (re-prioritized — STF-politeness hedge)

**Motivation change as of 2026-04-21.** These items were previously
queued as "scraper optimization" / perf tweaks. After seeing arm-B
land at 10.52 rec/s (×6 URLs per case = ~63 STF HTTP req/sec) and
projecting scale to 32 shards (~125 req/sec), the right framing is
no longer throughput — it's **reducing our observable footprint on
STF's `/processos/*` endpoint** before we decide to scale aggressively.
Each item below cuts 15–20% of HTTP calls per case without losing
data. Stacked, they reduce per-case STF load by 30–50%, which is a
stronger guarantee of STF comfort than any after-the-fact throttle
alarm. **Promoted from "not blocking" to operational priority before
any scale-up past 16 shards.**

1. **Delete `abaDecisoes.asp` fetch** (−1 GET; no downstream reader).
   Highest-ROI: free win, zero data impact.
2. **Class-gate `abaRecursos.asp`** — skip on HC/AI by default; −1 GET
   per case for the classes that dominate our workload.
3. **Audit + gate `abaDeslocamentos.asp`** — check downstream readers
   before cutting; probably gateable by class.
4. **Class-gate `abaPautas` / `abaPeticoes`** on monocratic classes
   (HC decisions often monocratic → pautas empty → skip safe).

**Companion observability (V1 only, to measure the impact of the
cuts above + catch STF gradual-throttle):** add a `clean_p50` column
to `judex probe` — rolling p50 of `wall_s` filtered to
`status=ok AND retries={}`. That's the pure STF-response-time
signal, isolated from our own retry-chain latency. No thresholds,
no alarms yet — just the number, visible. After arm B + arm C give
us 2–3 data points for the "normal" range, we decide whether to
add V2 (color-coded ratio) or V3 (auto-throttle). V1 is ~20 lines
of code; V3 is a design session.

**Not doing (out of scope):** a proxy-provider change, a UA-
identification scheme, or coordinated outreach to STF. Those are
policy moves, not technical ones; queue separately if ever needed.

## Known limitations

- **Stale-cache content residue.** 2024 + 2023 + ~half of 2025
  structurally v8 but content-stale (partes truncated, pautas empty,
  no `publicacoes_dje`). 2026 is content-fresh; 53.5% of 2025
  (arm-A coverage) now content-fresh.
- **Main `judex.duckdb` pre-session data.** Rebuild deferred to
  end-of-cycle (after arms B, C, and all PDF + extraction land).
- **Scrapegw L3-per-IP reputation decay.** Arm A gave direct
  evidence: pools that cliffed yesterday cliff earlier today after
  21h idle. Overnight gap is "mostly but not fully" cleared. A
  second proxy provider is the only true redundancy.

## Known gaps

- **`publicacoes_dje` → warehouse** (see Backlog § Warehouse #1).
- **PDF enrichment status tracking** — no persisted field answers
  "has this case been through PDF enrichment?" Derivable from
  `extractor` slots; rollup script proposed but not landed.

---

# Reference — how to run things

```bash
# Unit tests (~15 s, 538 tests)
uv run pytest tests/unit/

# Live probe of a sharded sweep (rich table, throughput, ETA, regimes)
uv run judex probe --out-root runs/active/<dir>
uv run judex probe --out-root runs/active/<dir> --watch 30   # auto-refresh

# Ground-truth validation
uv run python scripts/validate_ground_truth.py

# Full-range year re-scrape (what arms A/B/C use)
uv run python scripts/generate_hc_year_gap_csv.py \
    --year <YYYY> --out tests/sweep/hc_<YYYY>_full.csv \
    --dead-ids data/dead_ids/HC.txt --full-range

#   Then launch sharded:
uv run judex varrer-processos --csv tests/sweep/hc_<YYYY>_full.csv \
    --rotulo hc_<YYYY> --saida runs/active/<date>-hc-<YYYY> \
    --diretorio-itens data/cases/HC \
    --shards <N> --proxy-pool config/proxies --retomar

#   Aggregate dead-IDs periodically
uv run python scripts/aggregate_dead_ids.py --classe HC

#   PDF bytes (separate WAF counter, 16 shards safe)
uv run judex baixar-pecas --csv <case-list> \
    --saida runs/active/<date>-hc-<YYYY>-pdfs \
    --shards 16 --proxy-pool config/proxies --retomar --nao-perguntar

#   PDF text extraction (zero HTTP; local)
uv run judex extrair-pecas -c HC -i <lo> -f <hi> --nao-perguntar

#   Warehouse rebuild
uv run judex atualizar-warehouse --ano <year> --classe HC \
    --saida data/warehouse/judex-<year>.duckdb
# Or full corpus:
uv run judex atualizar-warehouse
```

## Recovery from CliffDetector collapse

```bash
# If one or more shards cliff mid-sweep:
xargs -a runs/active/<label>/shards.pids kill -TERM

# Identify ungrabbed pids from each cliffed shard's sweep.state.json
# → build a recovery CSV covering only those pids

# Relaunch on direct IP (bypasses the degraded proxy pool):
nohup uv run python scripts/run_sweep.py \
    --csv <recovery.csv> --label <label>_recovery \
    --out runs/active/<label>-recovery \
    --items-dir <items_dir> \
    --resume --no-stop-on-collapse \
    > runs/active/<label>-recovery/launcher-stdout.log 2>&1 & disown
```

## Data model — peças → cases

Unchanged. See prior archive for the three-hop layout
(case JSON → URL → sha1 → cache quartet).
