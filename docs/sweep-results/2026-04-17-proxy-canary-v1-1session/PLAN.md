# Proxy canary re-run — CliffDetector WAF-shape fix validation

Date: 2026-04-17
Owner: Gustavo Costa + Claude Opus 4.7
Status: **queued** — will run after the WAF-shape fix commits.

## Context

The first proxy canary (same output dir, now overwritten) ran with
the original CliffDetector, which counted *any* `status != "ok"` as
a fail. HC 195000..194951 contains ~30 % non-existent HCs
(`NoIncidente` fast fails — STF returns a response but no
`incidente` is extractable, because the number isn't in the portal's
database). The detector read corpus sparsity as WAF pressure,
escalated to `approaching_collapse`, and fired **7 panic rotations
at 4–5 s intervals** at the end of the run before tripping
`collapse`.

Post-mortem findings (`docs/current_progress.md § WAF-detection + proxy-rotation`):

- **Proxy path was healthy:** 34 successful scrapes via ScrapeGW,
  real parsed STF responses at p50 = 4.5 s.
- **Fails were fast:** p50 = 1.76 s, max = 3.11 s. WAF-absorbed
  retries take 60–180 s; nothing in the log matches that.
- **Zero 403s** in the entire run. The "collapse" was a false alarm
  from a misspecified signal.

Two code fixes land before this rerun:

1. **CliffDetector WAF-shape filter** — a fail only counts toward
   the regime if `wall_s > 15` OR `http_status in {403, 429, 5xx}`
   OR `retries` non-empty. Fast `NoIncidente` fails don't count.
2. **30 s floor on reactive rotation** — regime-driven rotations
   (approaching_collapse → rotate) can't fire more often than every
   30 s, preventing panic-drain of the pool.

## Hypothesis

**H1 (expected):** After the fix, scraping HC 195000..194951 with
proxy rotation will produce:

- **~34 ok / ~16 fail** — same sparsity as before (data reality,
  not a bug to fix)
- **Regime stays in `under_utilising` or `healthy` throughout** —
  fast fails no longer count as WAF signal; p95 wall_s stays ~10 s
  so p95 axis stays quiet
- **Zero `approaching_collapse` or `collapse` regime transitions**
- **4 rotations total**, all on the 60 s timer — no reactive
  rotations
- **Wall time ~240 s** (50 records × ~4.8 s/record; proxy latency
  dominates)
- **Exit code 1** (because fails > 0, but *not* because of collapse)

**H0 (null — would falsify the fix):**

- Regime still transitions to `approaching_collapse` or `collapse`
- Rotation events > 5 in the run

**H2 (unexpected but possible):**

- Regime *correctly* detects real WAF pressure that the first
  canary masked with false alarms. Previously we couldn't
  distinguish "WAF issue" from "sparsity issue"; now we can. If
  regime genuinely crosses `l2_engaged` based on p95 latency, we
  have a real signal worth investigating.

## Plan

1. **Commit the WAF-shape fix** (CliffDetector + rotation rate-limit).
2. **Rerun canary** with identical config to the first one:
   ```bash
   PYTHONPATH=. uv run python scripts/run_sweep.py \
       --csv tests/sweep/canary_50.csv \
       --label proxy_canary \
       --out docs/sweep-results/2026-04-17-proxy-canary \
       --items-dir data/output/proxy_canary \
       --proxy-pool proxies.txt \
       --proxy-rotate-seconds 60 \
       --proxy-cooldown-minutes 2
   ```
   Notably **no `--throttle-sleep`** — that flag is gone.
3. **Check results against expected outcomes** (below).
4. **Write `REPORT.md`** sibling doc documenting actual vs. expected.

## Expected-outcome table

| metric                              | expected        | falsifies fix if     |
|-------------------------------------|-----------------|----------------------|
| ok records                          | 30–40           | < 20                 |
| fail records                        | 10–20           | > 30                 |
| fail `error_type` breakdown         | all NoIncidente | any 403-shape        |
| regime at end of sweep              | under_utilising | approaching_collapse |
| regime transitions to collapse      | 0               | ≥ 1                  |
| regime transitions to approaching   | 0               | ≥ 1                  |
| rotation events                     | 4               | > 6                  |
| rotation reasons                    | all `time>60s`  | any `approaching_collapse` |
| wall time (total)                   | 200–300 s       | > 400 s              |
| OK wall p50                         | 4–5 s           | > 10 s               |
| FAIL wall p50                       | 1–3 s           | > 10 s               |
| credentials in driver.log           | 0 occurrences   | any                  |
| credentials in sweep.log.jsonl      | 0 occurrences   | any                  |

## Interpretation rules

- **All expected rows match** → fix validated, CliffDetector correctly
  distinguishes WAF signals from data sparsity. Ship with confidence.
- **H2 fires** (regime crosses `l2_engaged` via real p95 latency) →
  genuine WAF engagement; investigate ScrapeGW exit-IP rotation
  frequency + WAF interactions. Not a failure of the fix.
- **Falsification criteria fire** → fix is wrong; revert or
  recalibrate thresholds.

## Budget

Canary wall time: ~4 min. Human review: ~5 min. Total: ~10 min.
No proxy bandwidth concern (50 records × ~70 KB = ~3.5 MB).
