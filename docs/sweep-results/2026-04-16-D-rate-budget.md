# Rate budget measurements — reactive retry vs proactive pacing

Date: 2026-04-16
Spec: `docs/superpowers/specs/2026-04-16-validation-sweep-design.md` (addendum pending)
Runs: `D1-retry403/`, `D2-sleep05/`, `D3-sleep20/`

## Question

Sweep C showed STF's portal WAF blocks with HTTP 403 after ~107 consecutive processes at sequential-with-4-tab-concurrency pace (~12 req/s). The block is behavioral (rate/burst-based), not UA or session scoped, and lifts within minutes. Two routes to survive a long sweep:

- **Reactive** — treat 403 as a retriable throttle signal; tenacity backs off until the block lifts (`--retry-403`).
- **Proactive** — sleep between processes to stay under the threshold (`--throttle-sleep <s>`).

We measured both on disjoint 200-process slices of ADI IDs.

## Setup

| run | slice           | `--throttle-sleep` | `--retry-403` |
|-----|-----------------|-------------------:|:-------------:|
| R1  | ADI 1..200      | 0                  | ✓             |
| R2  | ADI 201..400    | 0.5                | ✗             |
| R3  | ADI 401..600    | 2.0                | ✗             |

Parity source: `output/judex-mini_ADI_1-1000.csv` (Selenium baseline). `--wipe-cache` on every run.

## Results

### R1 — reactive retry (no pacing)

- **199/200 ok, 1 error.** Process ADI 121 hit a 403 on `abaInformacoes.asp` and tenacity retried **72 times over 273 s (~4.5 min)** before exhausting the 10-retry budget per request (counted across ~11 requests in the process).
- Every process after ADI 121 succeeded immediately → the block lifted *during* the retry cycle.
- Ok-process wall: p50 0.67 s, p90 1.00 s, max 8.24 s, sum 163 s.
- Total elapsed ≈ **7.3 min** (163 s of work + 273 s waiting out the block).

Takeaway: **reactive retry works, but a single process can lose its retry budget if the block happens to start at the wrong moment.** One failure is acceptable; a longer per-request retry budget would likely turn it into a success.

### R2 — 0.5 s pacing, no retry

- **30/200 ok, 170 error.** First 403 at ADI 231 (process #31 of R2). R2 started immediately after R1 — the WAF window was still hot.
- All 170 errors were HTTP 403 on `listarProcessos.asp`, fast-failing in ~0.03 s each.
- Total elapsed: ~128 s (mostly the 0.5 s sleep × 199 processes since errors were cheap).

Takeaway: **0.5 s pacing is not enough**, especially when starting with a warm WAF counter. The measurement is also polluted by R1's tail activity — pacing-only cold-start would need a cooldown between runs to measure cleanly.

### R3 — 2.0 s pacing, no retry (after 8-min cooldown)

- **175/200 ok, 25 error. One contiguous error cluster** at processes 106–130 (ADI 506–530); everything before and after succeeded. First error: ADI 506 on `listarProcessos.asp`.
- Block lasted ~25 processes × 2.03 s = **~51 s**, much shorter than R1's 4.5-min stall at 0 pacing.
- Ok-process wall: p50 0.74 s, p90 1.99 s, max 10.84 s, sum 189 s.
- **Total elapsed: 590 s (9.8 min)** for all 200 processes.

Takeaway: **2 s pacing does not prevent the block** — it still fires at roughly the same process count (R3 blocked at process 106 vs sweep C's 108 vs R1's 121). But pacing does change the recovery shape: the block clears in ~1 minute instead of ~4.5 minutes, and the sweep keeps going. STF's WAF appears to use a sliding window that slides forward while we keep pacing — not fully reset, but fast-thawing.

## Comparison table

| run | pacing | retry-403 | ok/200 | first block at | stall duration | total wall |
|-----|-------:|:---------:|-------:|---------------:|---------------:|-----------:|
| sweep C* | 0 | ✗ | 107† / 1000 | process #108   | n/a (fast-fail through end) | 1.9 min |
| R1  | 0     | ✓ | 199    | process #121   | 4.5 min (retry budget)     | 7.3 min |
| R2  | 0.5   | ✗ | 30     | process #31    | n/a (hot start)             | 2.1 min |
| R3  | 2.0   | ✗ | 175    | process #106   | 1.0 min (block cleared)    | 9.8 min |

*sweep C is listed for scale; different slice (ADI 1..1000).
†ADI 1..107 succeeded before sweep C blocked.

## Findings

1. **STF's block threshold is ~100–120 consecutive processes** at 4-tab concurrency, largely independent of pacing. Zero sleep, 0.5 s, and 2 s all tripped somewhere in that window.
2. **Pacing shrinks the block duration.** 0 pacing → 4.5-min stall; 2 s pacing → ~1-min stall. Probably because the WAF's sliding window keeps sliding when we don't flood it.
3. **Reactive retry salvages nearly everything at moderate pacing.** Per-request budget needs to be larger than 10 retries × 30 s max backoff to ride out the 4.5-min stall reliably.
4. **Warm-start pacing is much worse than cold-start pacing.** R2's 30/200 with 0.5 s is not representative of 0.5 s on a fresh IP — it inherited a hot WAF counter from R1.
5. **The `recursos[].id` vs `recursos[].index`** divergence recurs in every parity sweep. Retiring Selenium fixes it.

## Recommendation

For any sweep ≥ 100 processes, use **both**:

```bash
uv run python scripts/run_sweep.py \
    --csv <inputs.csv> \
    --throttle-sleep 2.0 \
    --retry-403 \
    --out <out-dir>
```

Raise the per-request retry budget in `ScraperConfig` (or expose a CLI flag):

```python
# src/config.py
driver_max_retries: int = 20       # was 10
driver_backoff_max: int = 60       # was 30
```

Total max wait per stuck request: ~20 × 60 s ≈ 20 min. Covers the worst observed block (4.5 min) with a 4× safety factor.

Expected shape for a clean 1000-ADI sweep with this config:
- **Wall time**: 2 s × 1000 + work (~1 s × 1000) + 2–3 block cycles × ~1 min = **~52 min**.
- **Completion**: ≥ 99 % (R1 showed 199/200, R3 showed 175/200; combining both mechanisms should lift to near-perfect).
- **Vs Selenium baseline (77.6 min / 609 ok)**: ~33 % faster wall AND higher completion rate.

If throughput matters more than politeness (e.g. one-off backfill, user has legal posture covered):
- Drop `--throttle-sleep` to 0, keep `--retry-403`, accept the stall cycles. R1-style.
- Wall time: ~25–30 min for 1000 processes, with ~5 stalled processes. Plus the circuit breaker (handoff step #2) so runaway blocks can't cascade.

## Circuit breaker — still recommended

R3 showed 25 contiguous errors. Without `--retry-403`, those are lost. Without a circuit breaker, a pathological WAF escalation could produce hundreds. Add:

- Track rolling error rate (last N processes).
- If rate > X %, stop the sweep, write errors.jsonl, exit non-zero with a clear message.
- User retries later with `--retry-from` once the IP cools off.

Minimum viable: N=25, X=50 %. ~15 min of work.

## Data captured

- `docs/sweep-results/2026-04-16-D1-retry403/sweep.{log,state,errors}.jsonl` + `report.md`
- `docs/sweep-results/2026-04-16-D2-sleep05/sweep.{log,state,errors}.jsonl` + `report.md`
- `docs/sweep-results/2026-04-16-D3-sleep20/sweep.{log,state,errors}.jsonl` + `report.md`

## What we already know

- **STF's threshold is not constant.** Sweep C blocked at process 108 (12 req/s, cold). R1 blocked at process 121 (12 req/s, cold). R2 blocked at process 31 (~6 req/s, hot). The absolute rate matters less than the rolling window over recent activity.
- **Block duration is minutes, not seconds.** R1's stall took 4.5 min. Matches the post-sweep-C probe's behavior.
- **Non-browser UAs (`curl/*`) get permanent 403.** Not related to the rate gate.
- **Reactive retry salvages nearly everything** at the cost of unpredictable stall time. Proactive pacing alone is harder to tune and needs cooldown discipline between runs.

## Data captured

- `docs/sweep-results/2026-04-16-D1-retry403/sweep.{log,state,errors}.jsonl`
- `docs/sweep-results/2026-04-16-D2-sleep05/sweep.{log,state,errors}.jsonl`
- Reports auto-generated at `docs/sweep-results/2026-04-16-D*/report.md`
