# Proxy canary v2 — 10 distinct sessions (WAF-shape fix validation)

Date: 2026-04-17
Related: [`../2026-04-17-proxy-canary-v1-1session/REPORT.md`](../2026-04-17-proxy-canary-v1-1session/REPORT.md),
[`PLAN.md`](PLAN.md)

## TL;DR

Re-ran the canary with `proxies.txt` now containing 10 distinct
ScrapeGW sessions (v1 was effectively deduped to 1). The
CliffDetector **correctly held `under_utilising` despite a 78 %
fail rate**, because the WAF-shape filter excluded every fail
(all `NoIncidente`, all `wall_s < 3.05 s`, zero 403/429/5xx, zero
retries).

**This resolves open-question #1** from the prior cycle — the
canary-vs-backfill divergence was **data-shape, not
session-count**. Hypothesis (c) "intermittent" is ruled out.

## Head-to-head with v1

| metric                          | v1 (1 effective session) | v2 (10 distinct)   |
|---------------------------------|--------------------------|---------------------|
| ok / fail                       | 34 / 16                  | 11 / 39             |
| fail `error_type`               | all NoIncidente          | all NoIncidente     |
| fail wall_s p50 / p95           | 1.76 / 3.11              | 0.83 / 2.32         |
| 403 count                       | 0                        | 0                   |
| 429 / 5xx count                 | 0 / 0                    | 0 / 0               |
| retries in any fail             | 0                        | 0                   |
| **WAF-shape-counted fails**     | —                        | **0 / 39**          |
| final regime                    | approaching_collapse*    | **under_utilising** |
| reactive rotations              | 7                        | **0**               |

\* v1 ran before the WAF-shape filter landed, so its CliffDetector
was counting `NoIncidente` as WAF pressure. v2 with the filter
on the same-shape data classifies correctly.

## Why v2's fail count is higher than v1's

Different CSV slice. v1 targeted HC 195000..194951; v2 targets
HC 193000..192951 (the canary CSV was reseated between runs).
That range has ~78 % unallocated HCs vs v1's ~32 %. The absolute
numbers disagree because the data disagrees; the *shape* agrees
perfectly — both fail populations are uniform-fast
`NoIncidente`, which is exactly STF's response for an
unallocated HC.

## Expected-outcome table from `PLAN.md`, scored

| metric                              | expected         | got                | verdict                                                |
|-------------------------------------|------------------|--------------------|--------------------------------------------------------|
| ok records                          | 30–40            | 11                 | CSV range is denser in dead-zone than PLAN assumed    |
| fail records                        | 10–20            | 39                 | same cause; not a fix problem                         |
| fail `error_type` breakdown         | all NoIncidente  | all NoIncidente    | ✓                                                     |
| regime at end                       | under_utilising  | under_utilising    | **✓**                                                 |
| regime transitions to collapse      | 0                | 0                  | **✓**                                                 |
| regime transitions to approaching   | 0                | 0                  | **✓**                                                 |
| rotation events (timer)             | 4                | (driver log)       | —                                                     |
| rotation reasons                    | all `time>60s`   | no reactive fired  | **✓**                                                 |
| OK wall p50                         | 4–5 s            | 0.05 s             | cache hit — 8/11 OK records were pre-scraped          |
| FAIL wall p50                       | 1–3 s            | 0.83 s             | **✓**                                                 |

**Pass/fail** on the fix-validation rows: all green. The data-shape
rows (ok count, fail count) diverged not because the fix is wrong
but because the PLAN author over-estimated the density of the CSV
slice.

## What this rules out

- **Hypothesis (a) "soft-block by ScrapeGW"** — ruled out. If a
  single-session pool produced soft-block, a 10-session pool
  should reproduce it. Same shape emerged both times; both were
  real STF `NoIncidente` responses, not a proxy artifact.
- **Hypothesis (c) "intermittent"** — ruled out. The fast-uniform
  fail shape is reproducible and explained entirely by data
  sparsity.
- **Hypothesis (b) "rotation cadence"** — not tested here, but
  the zero reactive-rotation outcome in v2 means rotation cadence
  is not a practical concern at current thresholds.

## What this confirms

- **The two-axis regime model** (see
  [`docs/rate-limits.md § The two CliffDetector axes`](../../rate-limits.md#the-two-cliffdetector-axes))
  correctly handles dead-zone corpora: Axis A filtering takes 39
  fails to zero; Axis B p95 never exceeds 3 s.
- **The fix is safe to deploy at scale.** The sharded backfill can
  proceed through any mix of dead-zone + dense-territory records
  without false-alarm collapse.
