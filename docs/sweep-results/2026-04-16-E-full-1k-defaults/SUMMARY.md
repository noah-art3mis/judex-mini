# E — full ADI 1..1000 with new defaults (PARTIAL)

**Status**: stopped early at 429/1000 via SIGTERM to free the WAF
counter for the G density probe. Clean shutdown; all state files
complete. Resume with `--resume` to finish the full 1000.

**Date**: 2026-04-16 → 2026-04-17 (commit `4c2a0fd`)
**Configuration**: default sweep profile landed in `2a2833d` —
`ScraperConfig.retry_403=True`, `driver_max_retries=20`,
`driver_backoff_max=60`, `run_sweep.py --throttle-sleep 2.0` default.
**Parity source**: Selenium baseline `output/judex-mini_ADI_1-1000.csv`
(609 rows).

## Headline

**429 / 429 ok** (0 fail, 0 error). The new defaults absorbed 4 WAF
block cycles cleanly with zero error leakage.

| metric | value |
|---|---|
| processes run | 429 / 1000 |
| ok / fail / error | 429 / 0 / 0 |
| wall p50 / p90 / max | 0.74 s / 1.63 s / 90.0 s |
| 403 retries (tenacity) | 24 total across 4 stalls |
| 429 / 5xx retries | 0 / 0 |
| wall clock | 25 min 50 s (01:17:20 → 01:43:10 UTC) |
| **average pace** | **3.60 s / process** |

## Stall cycles (wall > 20 s = retry-403 backoff in action)

| process | wall (s) | implication |
|:--|---:|:--|
| ADI 104 | 64.0 | WAF tripped at ~100 procs; tenacity rode it out |
| ADI 205 | 64.1 | second cycle at ~200 — regular cadence |
| ADI 301 | 64.1 | third cycle |
| ADI 397 | 90.0 | fourth cycle — slightly longer backoff hit |

Pattern: a block roughly every 100 processes, each resolved in ~1
minute of transparent retry. **Consistent with sweep D's finding that
the WAF threshold is ~100–120 processes regardless of pacing.** What
changed with retry-403 on by default: instead of erroring out, the
sweep keeps moving; the stall cycles are now invisible to downstream.

## Projected vs actual

- **Handoff projection**: ~52 min for 1000 ADIs.
- **Measured pace**: 3.60 s/process → **projected 60 min for 1000**,
  slightly over the handoff estimate. Extra ~8 min is the 4× block
  cycles — a lighter day might finish closer to 52 min, a heavier one
  closer to 70 min. Either way, well under Selenium's 77.6 min.
- **HTTP vs Selenium**: at 60 min measured projection, HTTP is
  **~22% faster** end-to-end than Selenium's 77.6 min for the same
  1000 ADIs — less than the original perf claim of 5.7×/~20× from
  `docs/perf-bulk-data.md` because that was measured against the
  single-process hot-cache case, not a full sweep with WAF friction.

## Interpretation

The run **validates the default posture** (retry-403 + 2 s pacing +
20/60 retry budget) as shipped in commit `2a2833d`:

- ✓ Error-free across 429 real-world processes
- ✓ 4 WAF block cycles absorbed with zero leakage
- ✓ Measured pace within 15% of the handoff projection
- ✓ Faster than Selenium end-to-end, without the parity issues Sweep C
  surfaced at 107 processes

The partial result is sufficient evidence that the defaults are
production-viable for long sweeps. A full 1000-process run (via
`--resume`) would add the 1000-datapoint ceiling but the mechanism is
already clearly working.

## Reproducing / resuming

```bash
# resume from 429 → 1000 (skips already-ok)
PYTHONPATH=. uv run python scripts/run_sweep.py \
    --csv tests/sweep/full_range_adi.csv \
    --label full_1k_defaults \
    --parity-csv output/judex-mini_ADI_1-1000.csv \
    --out docs/sweep-results/2026-04-16-E-full-1k-defaults \
    --resume
```
