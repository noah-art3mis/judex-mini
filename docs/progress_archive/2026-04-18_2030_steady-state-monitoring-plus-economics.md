# Current progress — judex-mini

Branch: `main`. Tip: `a0b384a` (pushed: `c463f14` feat filter_skip/
body_head, `d48763b` docs archive, `a0b384a` chore shard CSVs).
Prior cycle archived at
[`docs/progress_archive/2026-04-18_0342_sharded-backfill-plus-instrumentation.md`](progress_archive/2026-04-18_0342_sharded-backfill-plus-instrumentation.md)
— 4-shard backfill launch, data/ + docs/ reorg, `filter_skip` +
`body_head` landing.

**Status as of 2026-04-18 ~20:25 UTC: 4-shard backfill is running
cleanly at steady state.** Relaunched at 11:55 UTC after overnight
`collapse` exit; 12 consecutive 30-min cron probes show +46 ok/min
aggregate, zero new ProxyError/4xx/5xx since the overnight 03:29 UTC
cluster. Global: 45 484 ok / 14 329 fail. Four `approaching_collapse`
alerts fired along the way, all diagnosed benign (PDF-outlier p95 or
dead-zone fail_rate), rotator self-corrected every one within 1 tick.
See Observations § 2026-04-18 monitoring-session.

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

**Diagnose the overnight 4-shard collapse and decide the resume
strategy.** All 4 shards hit `regime=collapse` and stopped cleanly
around 2026-04-18 03:30 UTC, about 3.5 h after launch. State is
fully `--resume`-safe (atomic per-record writes), cooldown is past
the 60-min minimum, and each shard's `report.md` + `sweep.errors.jsonl`
is written. The question now: *which* fail shape dominated
(NoIncidente in deep territory vs. real WAF 403s vs. a 5xx
cluster), and whether to resume as-is, drop the deepest shard, or
change strategy before relaunching.

## Plan

1. **Read the four `report.md` + `sweep.errors.jsonl` tails
   per shard** (user picked this option). Classify the fail shapes:
   NoIncidente-fast vs. retry-403-exhausted vs. 5xx. Expect shard-3
   (deepest HC range, 53 % fail rate) to look different from shards
   1–2 (4–5 % fail rate).
2. **Write a short decision note** into Decisions below. The likely
   fork:
   (a) resume all 4 as-is (re-trip inevitable),
   (b) resume shards 0–2 only, defer shard-3 for a different tactic,
   (c) restructure the backfill (more proxy sessions, lower
       concurrency, throttle on shard-3 specifically).
3. **Validate the new `filter_skip` / `body_head` log shape on the
   first resumed (or replacement) sweep.** The overnight collapse
   happened under the *old* code (pre-commit) so the pre-collapse
   records carry neither field; the first post-commit sweep
   resolves Open Question #3.
4. **Write a consolidated overnight `REPORT.md`** once the diagnosis
   and resume decision land. Merge the 4 shard states, compute
   global fail/ok/regime distribution, archive per-shard dirs.

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
- **2026-04-18 ~04:00 UTC — three commits pushed to `origin/main`.**
  `c463f14` feat (filter_skip/body_head), `d48763b` docs (archive),
  `a0b384a` chore (4 shard CSVs, 273 k rows). Working tree clean.
- **2026-04-18 ~03:30 UTC — all 4 shards tripped `collapse` and
  exited cleanly.** Final summaries from each `driver.log`:

  | shard | fresh ok | fail | error | 5xx |
  |---|---|---|---|---|
  | 0     | 1456     | 2930 | 3     | 7   |
  | 1     | 1812     |  470 | 3     | 4   |
  | 2     | 2114     |  334 | 3     | 7   |
  | 3     | 1912     | 2170 | 3     | 3   |

  Regime histogram (global, overnight): 130 warming + 14 353
  under_utilising + 120 `l2_engaged` + 93 `approaching_collapse`
  + **4 `collapse`** (one per shard). Each shard: single collapse
  observation → driver saw it, called `request_shutdown()`,
  finished in-flight record, wrote `errors.jsonl` + `report.md`,
  exited. No zombies, no state loss. **H0 confirmed, H1 falsified.**
- **2026-04-18 ~08:45 UTC — status check.** No workers running
  (`pgrep -cf run_sweep` = 0). Cooldown at 5+ h, well past the
  60 min minimum. Working tree clean, `origin/main` up to date.
  shard-3's 53 % fail rate vs. shards 1–2's 4–5 % fail rate
  *looked* like dense-territory WAF cost, but the error-tail
  investigation below inverts that read.
- **2026-04-18 ~08:55 UTC — error-tail investigation: the "collapse"
  was the 1 GB ScrapeGW prepaid-bandwidth quota running out, not
  STF WAF (user confirmation 09:00 UTC).** Per-shard
  `sweep.errors.jsonl` tallies: **5 904 `NoIncidente` fails
  (zero 403, zero 429, zero 5xx — all correctly filtered by the
  WAF-shape filter), 12 `ProxyError: Unable to connect`**. The 12
  ProxyErrors cluster in three synchronised waves across all 4
  shards at 06:01, 06:15, 06:30 UTC — each error `wall_s ≈ 852 s`
  (≈ tenacity's full retry budget against a dead proxy). Every
  shard's `regime='collapse'` observation lands on the final
  record of that shard's log; the p95 axis (p95 > 60 s) tripped
  because three 14-minute ProxyErrors in a 50-record window drag
  the rolling p95 to ~852 s. **Fail_rate axis was ~0.04 % (12 WAF-
  shape out of 28 643 records).** The WAF-shape filter worked
  exactly as designed; the CliffDetector's p95 axis caught an
  infrastructure failure, not a WAF adaptive block. **H0 refuted
  a second time — the collapse was H2 (provider-side), not H0
  (dense-territory WAF).** Detailed tallies:

  | shard | NoIncidente | ProxyError | HTTP 403/429/5xx | Last-50 p95 |
  |---|---|---|---|---|
  | 0     | 2 930       | 3          | 0 / 0 / 0        | 852.12 s    |
  | 1     |   470       | 3          | 0 / 0 / 0        | 851.94 s    |
  | 2     |   334       | 3          | 0 / 0 / 0        | 850.79 s    |
  | 3     | 2 170       | 3          | 0 / 0 / 0        | 851.83 s    |

- **2026-04-18 ~11:55 UTC — user topped up another 1 GB + relaunched
  all 4 shards.** Proxy probe (one session from each of the 4 pools,
  `resolve_incidente('ADI', 2820)`) came back 100 % ok with 2.3–3.5 s
  wall across all pools. Launcher run via `nohup
  ./scripts/launch_hc_backfill_sharded.sh`; all 4 shards spawning
  workers immediately (resume fast-forwards through the 16 823 ok
  records). **The new `filter_skip` + `body_head` fields are live
  in the log** — first `NoIncidente` record post-relaunch carries
  `{filter_skip: true, body_head: "", http_status: 200}`,
  validating Open Question #5 in practice. Open Question #3
  (body_head distinguishes real STF from hypothetical soft-block)
  is partially resolved: we now know STF's dead-zone shape is
  `http_status=200 + empty Location`, so any future non-empty
  body_head at the same wall_s profile is the divergence signal.

- **2026-04-18 12:12 UTC — first post-launch probe confirms
  `filter_skip` + `body_head` land on live NoIncidente records.**
  Sample from shard-0 `sweep.log.jsonl`:
  `{processo: 272765, status: 'fail', http_status: 200, wall_s: 0.511,
  filter_skip: true, body_head: ''}`. Exactly the predicted shape.
  **Open Question #5 resolved in practice.** Throughout the ensuing
  12-probe monitoring session, every NoIncidente record carried
  the same shape — no drift, no soft-block divergence.

- **2026-04-18 12:13 UTC — `/loop 30m` cron scheduled
  (job `b27687d1`, cron `13,43 * * * *`, session-only,
  auto-expires in 7 days).** Self-contained probe prompt: pgrep
  workers → `probe_sharded.py` → `errors.jsonl` tail → alert on
  dead PID / new collapse / ≥5 new approaching_collapse / >5 new
  ProxyError / 30-min global-ok stall. Reports ≤80 words when
  healthy, expands on alert.

- **2026-04-18 12:12 UTC → 20:23 UTC — 12 consecutive cron probes
  ticked on :13 / :43.** All 4 workers stayed alive at the same
  PIDs (4719/4720/4721/4722) the whole time. Throughput **eerily
  flat**: per-tick ok deltas
  `+1 129 / +1 345 / +1 445 / +1 352 / +1 369 / +1 281 / +1 368 /
   +1 394 / +1 415 / +1 374 / +1 485`.
  12-tick average ≈ 46 ok/min, max deviation ±20 %. Zero new
  `ProxyError` / `HTTP 403` / `HTTP 429` / 5xx in `errors.jsonl`
  across all 4 shards for the full 8.5-hour span. `errors.jsonl`
  mtimes still Apr 18 03:29–31 (overnight cluster).

- **2026-04-18 12:12 UTC → 20:23 UTC — 4 `approaching_collapse`
  alert trips, all benign.** Each fell into one of two patterns:
  - **p95 outlier** (shard-0 at 11:13, shard-1 at 14:13 and 16:43):
    single record with wall_s ≈ 50–130 s (PDF-heavy case) pushed
    the rolling-window p95 axis past threshold. Next 30–50 fast
    records rolled the outlier out, regime auto-downgraded
    (`[regime] approaching_collapse → under_utilising`).
    Rotator fired reactive rotation at the 30 s floor during the
    pressure window.
  - **Dead-zone fail_rate** (shard-3 at 15:43): 9+ consecutive
    `filter_skip=true` NoIncidente records (HC 54827–54836) tripped
    the fail_rate axis. Correctly classified, zero network cost
    past the initial redirect probe.

  Each alert stabilised within 1 tick. **Zero actual WAF
  pressure, zero permanent errors, zero manual intervention.**
  Rotator + CliffDetector + proxy-pool-rotation stack doing
  exactly what they were designed for.

- **2026-04-18 20:23 UTC — per-shard progress snapshot.**

  | shard | ok     | fail   | total  | % of 68 250 | range depth reached |
  |-------|--------|--------|--------|-------------|---------------------|
  | 0     | 13 111 |  4 183 | 17 294 | 25.3 %      | min_processo 216670 (lifetime) |
  | 1     | 14 127 |  1 154 | 15 281 | 22.4 %      | 138 722             |
  | 2     | 10 602 |  1 289 | 11 891 | 17.4 %      | 124 610             |
  | 3     |  7 644 |  7 703 | 15 347 | 22.5 %      | 29                  |

  Shard-1 is the bottleneck — its range (204 750..136 501) is
  uniformly dense, 0.38 proc/s, ETA ≈ 38 h alone. Other shards
  will finish much earlier and go idle. HC backfill completion
  is tomorrow afternoon UTC at the earliest.

- **2026-04-18 20:30 UTC — ScrapeGW commercial reality check
  (user dashboard read).** Current topup bought 5 GB for 100 BRL
  (~20 BRL/GB ≈ 4 USD/GB). After 8.47 h: **1.39 GB used,
  3.61 GB remaining.** Actual bytes-per-record came in much
  better than projected:

  | axis                     | projected (from overnight) | actual (this session) |
  |--------------------------|----------------------------|-----------------------|
  | KB / ok record (dense)   | 137                        | **64**                |
  | KB / record (blended)    | 96                         | **47**                |
  | burn rate                | ≈290 MB/h                  | **168 MB/h**          |
  | runway from 3.61 GB      | —                          | **22.0 h**            |

  The 2× improvement over projection: (a) HTTP path fetches less
  per case than the Selenium-era assumptions baked into the early
  estimate; (b) `filter_skip=True` NoIncidente records are ~0.5 KB
  each (just the redirect probe); (c) steady-state dense PDFs are
  shorter than the overnight mix's worst cases.

  **Binding constraint: shard-1 needs 38.7 h alone, runway is
  22 h — quota wall comes ≈17 h before shard-1 finishes.** Other
  shards finish earlier and stop burning, but shard-1 will still
  outrun the budget. Full-HC project cost projected at ~10.5 GB
  total (2.39 GB sunk + 8.1 GB to go) = ~210 BRL. That's ~42 USD
  for the complete HC corpus of Brazil's highest court — cheap.

  Class-scaling budget (at 55 KB/ok blended): ADI ~7 k cases =
  ~400 MB = 8 BRL (rounding error). RE ~1.5 M cases =
  potentially ~80 GB = ~1 600 BRL. **RE is where bandwidth
  budgeting becomes a real decision.**

  Three options surfaced for the quota-wall decision (user hasn't
  picked yet):
  1. **Reactive topup** — let it run, top up 5 GB (100 BRL) the
     moment the cron catches the first 407. ~10–15 min lost
     work. *Default recommendation.*
  2. **Preemptive topup** — buy another 5 GB tonight to cover the
     17 h gap with headroom. Zero interruption, 200 BRL sunk.
  3. **Kill shard-1 early** — accept partial HC coverage,
     ~50 k real cases missing. Bad for the research question.

- **2026-04-18 20:50 UTC — HC density map: G-probe (Apr 16)
  predictions vs live-sweep observations, 25 k-wide symmetric
  buckets.** The G-probe's ~216 k real-HC extrapolation was
  accurate; my earlier "200 k surprise" was a stale-memory
  error. Bimodal distribution — 33–40 % density below 50k
  (paper / early-electronic era), 86–93 % from 50k up (modern
  era).

  ```
  bucket             G-probe density              observed               est.    done    fill
  ------------------------------------------------------------------------------------------
       0..  24,999  [▓▓▓▓▓▓▓▓·················] 33.1%  100%  (n=     5)   8,266       5    0.1%
   25,000.. 49,999  [▓▓▓▓▓▓▓▓▓▓···············] 40.0%  (untouched)      10,000       0    0.0%
   50,000.. 74,999  [▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓····] 86.7%   49.7% (n=15,950) 21,675   7,930   36.6%
   75,000.. 99,999  [▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓····] 86.7%  (untouched)      21,675       0    0.0%
  100,000..124,999  [▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓····] 86.7%   90.2% (n=   696) 21,675     628    2.9%
  125,000..149,999  [▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓····] 86.7%   91.3% (n=14,232) 21,675  12,997   60.0%
  150,000..174,999  [▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓··] 93.3%  100%  (n= 1,858)  23,325   1,858    8.0%
  175,000..199,999  [▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓··] 93.3%   90.9% (n= 6,248) 23,325   5,680   24.4%
  200,000..224,999  [▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓··] 93.3%   88.5% (n= 5,568) 23,325   4,925   21.1%
  225,000..249,999  [▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓··] 93.3%  100%  (n= 1,750)  23,325   1,750    7.5%
  250,000..270,999  [▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓····] 86.7%   71.1% (n=15,200) 18,202  10,812   59.4%
  ------------------------------------------------------------------------------------------
  TOTAL (0..270994) [█████░░░░░░░░░░░░░░░░░░░░] 21.5%                  216,468  46,585   21.5%
  ```

  Legend: ▓ G-probe predicted density · █ fraction of estimated
  real HCs already captured.

  Fill pattern mirrors shard geography — the `fill %` column
  tells you where each shard is right now:
  - **60 % @ 125k–149k** = shard-2 active middle (deepest bucket hit).
  - **59 % @ 250k–270k** = shard-0 active top.
  - **36 % @ 50k–74k**   = shard-3 top-of-range (descending from 68k).
  - **8 % / 24 % @ 150k–199k** = shard-1 range (slowest, dense middle).
  - **2.9 % @ 100k–124k** = gap between shards 2 and 3; neither has reached it yet.

  Validation quality:
  - **150k..249k buckets match G-probe within ±2 pp** — probe
    methodology is accurate in this range.
  - **50k..74k shows 49.7 % observed vs 86.7 % predicted** is
    **sampling artefact, not density drift**: shard-3 just
    entered this bucket from the top (HC ~68k), the lower half
    is full of real cases it hasn't touched yet. Observed
    density will climb to ~87 % as shard-3 descends.
  - **250k..270k shows 71.1 % vs 86.7 %** because G under-sampled
    the ~6 k "reserved but not filed" numbers at the top
    (270 995..273 000). Real density past 270 994 is ~0 %.
  - **Buckets 25k..49,999 and 75k..99,999 untouched** — waiting
    for shards 3 and 2 to descend into them respectively. At
    current 0.4 proc/s for shard-3, the 25k..49k bucket is
    ~30 h out.

  **Scope reality check:**

  | horizon                                          | real HCs   | captured | remaining |
  |--------------------------------------------------|------------|----------|-----------|
  | G-probe full HC universe                         | ~216,466   | 46,428   | ~170,000  |
  | Dense zone (50k and up, 87-93 % density)         | ~198,200   | 46,423   | ~151,800  |
  | Sparse zone (below 50k, 20-47 % density)         | ~18,266    | 5        | ~18,261   |

  At current ~0.75 ok/s aggregate, remaining ~170 k real HCs
  need **~63 h of wall clock**. If we cut the 1k..49,999 sparse
  zone entirely (8 % of the corpus, mixed-era provenance,
  marginal analytical value), we save ~5 GB / ~100 BRL and
  ~30 h of wall clock.

- **2026-04-18 20:55 UTC — throughput progression (Selenium →
  HTTP → sharded HTTP).** Four measured eras, per-case wall
  time on a single HC-sized record:

  | era                                  | per-case wall | throughput        | ceiling                              |
  |--------------------------------------|--------------:|-------------------|--------------------------------------|
  | Selenium amortised (WAF-limited)     | ~20 s         | 0.05 case/s       | browser startup + WAF stalls dominate |
  | Selenium steady-state (cold, no WAF) | ~5 s          | 0.20 case/s       | measured on AI 772309                |
  | HTTP backend, cold, no throttle      | **0.87 s**    | **1.15 case/s**   | one worker, one IP                   |
  | HTTP + `retry-403` single worker     | 3.60 s        | 0.28 case/s       | sweep E, 429 ok / 0 fail, 4 stalls   |
  | **HTTP + 4-shard proxy rotation**    | **0.98 s**    | **1.02 case/s**   | **8.5 h, 0 × HTTP 403 / 429 / 5xx**  |

  Selenium → HTTP is the **5.7× per-request speedup** (0.87 s vs
  5 s) from killing browser startup + DOM-wait. HTTP single →
  HTTP 4-shard is another **~3.6× wall-clock speedup** from
  parallel workers running on disjoint proxy sessions so each
  worker has its own WAF counter. Per-worker rate (0.19 ok/s
  now vs 0.28 ok/s in sweep E) is essentially unchanged —
  rotation doesn't make one worker faster, it just lets you run
  4 of them cooldown-free.

  **Scaling economics.** Per-shard bandwidth: ~42 MB/h =
  ~0.82 BRL/h at 20 BRL/GB ScrapeGW residential. Total cost
  to finish the remaining ~170 k real HCs is **~208 BRL
  regardless of shard count** (bandwidth is per-record, not
  per-shard); only wall-clock scales:

  | shards | wall-clock (remaining ~170 k HCs) | bandwidth cost |
  |--------|-----------------------------------|----------------|
  | 1      | ~253 h (~11 days)                 | ~208 BRL       |
  | 4      | ~63 h (~2.5 days)                 | ~208 BRL       |
  | 16     | ~16 h                             | ~208 BRL       |
  | 32     | ~8 h                              | ~208 BRL       |

  The architecture doesn't care how many shards you run as
  long as each has its own proxy pool; WAF headroom has been
  verified at 4× concurrency over 8.5 h, untested beyond.

  **Next lever (not yet shipped): defer PDF text extraction to
  a second-pass sweep.** Today each scrape fetches 5–10
  andamento PDFs per dense case, which dominates wall clock
  and bandwidth. A fast metadata-only first pass plus a
  surgical "fetch PDFs only when needed" second pass would
  roughly halve both numbers — especially valuable for
  research questions that never read the PDFs.

- **2026-04-18 21:00 UTC — HTTP + proxies vs Selenium: the
  bake-off.** Selenium was retired on 2026-04-17 (spec at
  `docs/superpowers/specs/2026-04-17-selenium-retirement.md`);
  this session gives us the empirical numbers to back the
  decision. HTTP + proxies wins every axis except one:

  | axis                          | Selenium                                       | HTTP + proxies                                  | winner   |
  |-------------------------------|------------------------------------------------|-------------------------------------------------|----------|
  | Per-case wall                 | 5 s cold / 20 s amortised                      | 0.87 s cold / 0.98 s aggregate (this sweep)     | HTTP     |
  | Concurrency                   | 1 browser per machine (~500 MB RAM each)       | trivially parallel, <50 MB per worker           | HTTP     |
  | Full HC backfill wall-clock   | ~9–11 days (per `docs/rate-limits.md`)         | ~2.5 days @ 4 shards, ~16 h @ 16 shards         | HTTP     |
  | Dependency weight             | Chrome + chromedriver version pinning          | `requests` + `beautifulsoup4`, pure Python      | HTTP     |
  | Deployment                    | display server or Xvfb workarounds             | runs anywhere, container-friendly               | HTTP     |
  | Code size                     | 16 extractors (now frozen under `deprecated/`) | 5 small extractors + `http.py` dispatch         | HTTP     |
  | Cost profile                  | compute-dominated (browser RAM/CPU)            | bandwidth-dominated (~4 USD/GB)                 | HTTP     |
  | **Resilience to STF changes** | **survives DOM tweaks** (visually scrapes)     | **breaks if STF adds auth / captcha / SSR**     | Selenium |

  **The one resilience advantage is why Selenium is *frozen*,
  not deleted.** If STF adds JavaScript rendering, a CAPTCHA
  wall on `/processos/detalhe.asp`, or restructures the XHR
  contract (`/processos/abaX.asp` endpoints), the HTTP path
  breaks and we'd need to dust Selenium off. Today those
  endpoints are stable. `deprecated/scraper.py` stays as
  escape-hatch insurance (`uv sync --extra selenium-legacy` to
  reinstall optional deps).

  **Compound effect of HTTP + proxies is bigger than either
  alone.** HTTP alone is 5.7× faster per request but its WAF
  budget per IP is the same as Selenium's — on a sustained
  sweep HTTP burns the 100-proc budget *faster* and stalls on
  cooldown. Proxy rotation resets the per-IP reputation
  counter for free, converting HTTP's per-request win into a
  sustainable sweep win. End-to-end: **~8–10× full-sweep
  wall-clock speedup, same data quality, same schema.**

  **Cost axis shifts compute → bandwidth.** Selenium was free
  per-case (laptop compute) but wall-clock-expensive. HTTP +
  proxies costs real money (~208 BRL to finish HC, projected)
  but the money buys wall-clock back linearly via sharding.
  For research timelines where time matters more than money,
  this is the right trade.

## Decisions

- **2026-04-18 ~08:50 UTC — investigate before resuming (option #1
  of the three offered: investigate / resume-all / resume-3-defer-3).**
  User picked #1. No shards relaunched yet.
- **2026-04-18 ~08:55 UTC — diagnosis: 1 GB prepaid ScrapeGW
  bandwidth exhausted, not WAF.** User confirmation 09:00 UTC.
  All 12 `error`s are `ProxyError: Unable to connect` at ~852 s
  wall_s, clustered in three synchronised waves across all shards
  — the quota hit zero and the provider stopped routing. Zero
  403/429/5xx anywhere. The WAF-shape filter worked; the p95 axis
  caught the quota exhaustion. **No WAF pressure ever materialised
  in the live work.** Blocker to resume is now commercial
  (top up bandwidth), not technical.
- **2026-04-18 20:23 UTC — cron-monitoring run validates the
  steady-state story.** 8.5 h of continuous operation after
  relaunch, 46 ok/min baseline with <±20 % variation per tick,
  zero new permanent errors, 4 benign alert trips all
  self-corrected by the rotator. The rotation-plus-detector
  stack is verifiably doing its job at the design operating
  point. **No WAF pressure in 8.5 h of live dense-territory
  work** (first confirmation the V-sweep lesson generalises past
  ~4 h of continuous load).
- **2026-04-18 20:23 UTC — alert-criterion calibration finding.**
  "≥5 new `approaching_collapse` per 30-min tick" tripped 4 times
  in 12 probes, score 0/4 on real problems. The criterion is
  noise-dominated in dense-territory steady state because
  (a) p95-axis outliers are common with PDF-heavy cases and
  (b) dead-zone fail_rate triggers on correctly-classified
  `filter_skip` rows. Candidate fix (deferred, post-backfill):
  make `CliffDetector.observe` treat `filter_skip=True` fails
  as neutral for the fail_rate axis, and raise the alert
  threshold to ≥15 new approaching_collapse *or* any actual
  new permanent error.

## Open questions

1. **(Resolved — see Decisions)** What fail shape dominated?
   Answer: almost 100 % NoIncidente (correctly filtered) + 12
   ProxyErrors from a ScrapeGW outage.
2. **(Resolved — user confirmation)** What caused the synchronised
   ScrapeGW outage around 06:00–06:30 UTC? Answer: 1 GB prepaid
   bandwidth quota ran out. All 4 shards share the same billing
   account, so all 4 proxy pools went dark at the same second
   when the meter hit zero.
3. **Should CliffDetector's p95 axis distinguish "infrastructure
   outage" from "STF adaptive block"?** Right now a ProxyError
   with `wall_s=852 s` counts the same as an STF block with
   `wall_s=180 s`. Arguably both should stop the sweep (can't
   make progress either way), but the regime name "collapse"
   implies STF, which misled the morning-after read. Fix either
   the regime name or introduce an "infra_outage" regime that
   tells the rotator "rotate proxies aggressively" instead of
   "cool off the STF IP".
4. **Rolling-median wall_s breaker** (carried forward).
5. **(Resolved — 2026-04-18 12:12 UTC)** `filter_skip` / `body_head`
   validated in live sweep. Every NoIncidente record carries
   `{filter_skip: true, body_head: '', http_status: 200, wall_s ≈ 0.5 s}`.
   STF's dead-zone shape is empty-Location redirect, not truncated
   body — `body_head` stays empty, not "listarProcessos.asp?...".
   Future non-empty `body_head` at the same wall_s profile would
   be the soft-block divergence signal.

## Next steps

1. **Commit `docs/current_progress.md`** — this session's
   observations + decisions. Suggested subject:
   `docs: record 8.5h cron-monitoring session + bandwidth economics`.

2. **User decision: quota-wall strategy.** Runway 22 h,
   shard-1 needs 38.7 h → ≈17 h gap.
   - **1.** Reactive: let cron catch the first 407, top up 5 GB
     (100 BRL) then. ~10–15 min lost work. *Default recommendation.*
   - **2.** Preemptive: top up another 5 GB tonight for zero
     interruption, 200 BRL sunk.
   - **3.** Kill shard-1 early, accept partial HC coverage.
     *Not recommended — breaks the research denominator.*

3. **Post-backfill: consolidated `REPORT.md`** merging all 4
   shards' final state + overnight cluster. Same pattern as the
   archived `2026-04-18_0342_sharded-backfill-plus-instrumentation.md`.
   Then archive `runs/active/.../shard-*` dirs.

4. **Post-backfill: reconcile the ~200 k real-HC projection
   against `docs/process-space.md`** (which estimated 25–40 k).
   One `uv run python` session against `data/cases/HC/*.json` +
   update the doc. The 5–8× density surprise is real data worth
   capturing.

5. **Post-backfill: `CliffDetector` noise-reduction** in
   `src/sweeps/shared.py`. Make `filter_skip=True` fails neutral
   for the fail_rate axis; consider raising the p95 threshold
   from ~7 s to ~10 s to match observed dense-territory baseline.
   Small PR + one new test.

6. **Post-backfill: next-class decision** — ADI (7 k cases,
   ~400 MB, 8 BRL) is a rounding-error follow-up. RE (1.5 M
   cases, potentially ~80 GB, ~1 600 BRL) is a budgeting
   discussion. Decide before launching either.

7. **Carried-forward:**
   - Stratified-by-density sharding for next sweep (shard-1
     solo-bottleneck is a fixable problem).
   - Rolling-median `wall_s` breaker (from multiple prior cycles).
   - Selenium retirement phase 2 — spec at
     `docs/superpowers/specs/2026-04-17-selenium-retirement.md`.

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
