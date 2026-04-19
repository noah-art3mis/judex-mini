# HC full backfill — 4-shard proxy-rotated sweep

- **Dates:** 2026-04-17 (first launch) → 2026-04-18 20:44 UTC (SIGTERM)
- **Commits:** `00eabd7` at stop-time (started at earlier commit, several land-without-restart across cycles)
- **Label:** `hc_full_backfill_shard_{0..3}`
- **Out:** `runs/archive/2026-04-17-hc-full-backfill-sharded/shard-{0..3}/`
- **Status:** Stopped cleanly via SIGTERM to supersede with the year-priority gap-sweep plan (`docs/hc-backfill-extension-plan.md`). Not a failure.

## TL;DR

4 shards × 4 disjoint proxy pools (`proxies.{a,b,c,d}.txt`, 42 sessions total) processed **72 646 records** over the most-recent **11.6 h continuous run** (the prior cycle's 8.5 h is archived separately at [`docs/progress_archive/2026-04-18_2030_steady-state-monitoring-plus-economics.md`](../progress_archive/2026-04-18_2030_steady-state-monitoring-plus-economics.md)). Net result on the HC corpus:

- **55 354 HCs on disk** post-stop (range 48 933 → 271 139); up from ~1 000 at the start of this multi-day effort.
- **54 841 ok / 17 805 fail** this run, of which only **12 are "real" fails** (filter_skip=False NoIncidente) — the other 17 793 are reserved-but-unfiled or dead-zone HC numbers, flagged benign by `filter_skip` (commit `c463f14`).
- **Zero HTTP 403 / 429 / 5xx.** The 4-shard disjoint-proxy-pool design held cleanly across both cycles (8.5 h prior + 11.6 h this).
- Regime detector fired `approaching_collapse` 321 times globally but rotator self-corrected within 1 tick each — never entered `collapse`.

## Per-shard headline

| shard | total recs | ok     | filter-skip fail | real fail | ID range (floor) | proxy pool | wall (s) |
|------:|-----------:|-------:|-----------------:|----------:|------------------|------------|---------:|
|     0 |     20 001 | 15 158 |          ~4 839  |         4 | 216 670          | a (10 IPs) |   41 676 |
|     1 |     17 874 | 16 218 |          ~1 652  |         4 | 138 722          | b (10 IPs) |   41 674 |
|     2 |     15 444 | 13 628 |          ~1 813  |         3 | 121 057          | c (12 IPs) |   41 672 |
|     3 |     19 327 |  9 837 |          ~9 489  |         1 | 29               | d (10 IPs) |   41 673 |
| **Σ** | **72 646** | **54 841** |  **~17 793**   |    **12** | 29..273 000      | 42 IPs     |  ~41 674 |

Shard-3's 9 489 filter-skip fails are the paper-era dead zone (HCs 1..~49 000 mostly don't exist) — the 9 837 ok it captured spans 1971–1990 at ~400–800/year. Not retried by the successor plan.

## Real-fail rate (the number that matters)

**12 / 72 646 = 0.016 %** real-fail rate. Lowest on record for this codebase. By comparison, early sweeps (A–E) sat at 0.3–2 % real fails before the proxy-pool-rotation work landed.

All 12 real fails are `NoIncidente` with `filter_skip=False` — i.e. HCs the filter thought *should* exist but the detalhe page returned empty on. Candidates for a one-off retry pass; not a sweep-level concern.

## WAF posture

Empirically validated a full **20.1 h of continuous 4-shard load** (8.5 h prior cycle + 11.6 h this) with zero HTTP 403, zero 429, zero 5xx. Promotes the "rotation > throttle" hypothesis (`docs/reports/2026-04-17-V-throttle-zero.md`) from *confirmed-under-4h* to *confirmed-under-20h*.

Implications for future sweeps, to be absorbed into `docs/rate-limits.md`:

- At 4-shard + 42 sessions scale, the per-IP WAF counter does not accumulate to saturation even at 11.6 h continuous load.
- `--throttle-sleep` remains unnecessary. Proxy rotation is load-bearing.
- The 30-90 min between-sweep cooldown guidance in `docs/rate-limits.md § Two-layer model` is conservative; 20 h continuous has been fine. Revisit after the year-priority plan's tier-by-tier cadence has more data.

## Throughput

- **Aggregate: ~46 ok/min** at steady state across all 4 shards (11.6 h × 60 × 4 shards ÷ 54 841 ok ≈ 46/min).
- **Per-shard: ~0.19 ok/s** — unchanged from single-worker baseline (`docs/performance.md`). Rotation enables parallelism; it does not speed up individual fetches.
- End-to-end corpus speed-up vs. single-IP baseline: **~8–10×** wall-clock, with linear bandwidth cost.

## Why stopped (superseded)

The 4-shard full-range design produces uneven per-year capture because each shard descends through its own contiguous ID slab. Concretely, the capture histogram at [`current_progress.md#per-year-capture-histogram`](../current_progress.md) showed:

- **2001–2012: empty** — shard-2's untouched tail (stopped at HC 121 057).
- **1991–2000: very sparse** (1–14/yr captured).
- **Modern era 2013–2026: well-sampled** but uneven (2021 at 7 560 captured, 2022 at 817).

The **year-priority gap-sweep** successor (`docs/hc-backfill-extension-plan.md`) switches to one-year-at-a-time, 4-shard per year, newest-first, with each year's CSV filtered to uncaptured IDs only. Tiers 0–13 (2026 → 2013) cover the modern era in ~39.5 h at the same 46 ok/min. Paper era explicitly out of scope.

## Artifacts (archived)

- `shard-{0..3}/report.md` — full per-record cold-pass tables (0.5–0.8 MB each).
- `shard-{0..3}/sweep.state.json` — terminal per-record state (~6 MB each).
- `shard-{0..3}/sweep.log.jsonl` — append-only log (~6 MB each).
- `shard-{0..3}/sweep.errors.jsonl` — classified fails (17 805 rows total).
- `shard-{0..3}/driver.log` — stdout of each worker.
- `launcher.log`, `launcher-*-*.log` — launch + relaunch traces.
- `shards.pids` — captured parent PIDs at stop time (`4680 / 4688 / 4694 / 4704`).

## Next

Year-priority gap-sweep tier 0 (2026 catch-up, ~917 IDs, ~18 min estimated wall). Launcher: `scripts/launch_hc_year_sharded.sh 2026`. Plan at `docs/hc-backfill-extension-plan.md`.
