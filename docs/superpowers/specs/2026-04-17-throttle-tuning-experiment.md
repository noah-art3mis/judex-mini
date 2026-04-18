# Throttle-sleep tuning experiment (doubles as paper-era backfill)

Date: 2026-04-17
Owner: Gustavo Costa
Status: **superseded — never executed.**

## Superseded (2026-04-17, later same day)

`--throttle-sleep` was removed from `scripts/run_sweep.py` before this
experiment ran. The decision was based on:

1. **D-run evidence already pointed here.** R1 (0 s pacing + retry-403)
   got 199/200; R3 (2 s pacing alone) got 175/200. The experiment
   would have re-measured an effect the D data already called in one
   direction.
2. **Proxy rotation landed in the same session.** With `--proxy-pool`
   swapping IPs every ~270 s (below STF's layer-1 window), individual
   per-IP pacing stops having an independent effect — each proxy never
   accumulates enough requests to trip the throttle regardless of sleep.
3. **Scope hygiene.** Keeping a CLI flag whose measured benefit is
   "mostly redundant with retry-403 and proxy rotation" violates the
   project's no-backcompat-shim convention. Simpler to remove the knob
   than tune it.

The experiment spec is preserved here as a record of the design
reasoning; the trial slices (HC 105001..110200) remain available for
future experiments if a different throttle-related question emerges.
Historical V-sweep data in `docs/rate-limits.md § Two-layer model`
stands as the last word on per-process pacing for the portal.

---

## Original spec (retained for reference)


## Context

`docs/rate-limits.md` established the two-layer WAF model (sweep V,
2026-04-17): pacing fights layer 1 only; layer 2 (per-IP reputation)
is the structural ceiling. The D-runs (2026-04-16) measured three
points on the throttle-sleep curve but were diagnostic, not an
optimisation study — the shipped default (`--throttle-sleep 2.0`)
was picked for stall-duration shape, not throughput.

The question this experiment answers: **does
`--throttle-sleep` at the 2.0 s default actually improve completion
time vs. `--throttle-sleep 0 --retry-403`, or is it dead weight we
inherited from D-era thinking?**

The D data hinted at the answer (R1 at 0 s pacing got 199/200; R3 at
2 s got 175/200 — but retry-403 was on for R1 and off for R3, so
they're not comparable on the throttle axis). We want a clean
apples-to-apples measurement.

### Design constraint: zero-waste trials

Every trial slice must be **real backfill work from
`tests/sweep/hc_all_desc.csv`**, not a throwaway probe. JSONs written
during trials persist into `data/output/hc_experiment/` and count as
backfill progress. Net cost vs. letting the live sweep do it: only
the cooldown gaps between trials (~3–4 h of wall-clock), in exchange
for a measured answer.

## Hypothesis

**H0 (null):** at `--retry-403` enabled, throttle-sleep ∈ {0, 2.0}
produce indistinguishable `wall_time_total` for 200-HC paper-era
slices after cooldowns are normalised.

**H1:** throttle 0 is at least 20 % faster than throttle 2 on
`wall_time_total` with no degradation in `ok / 200`.

**H2 (the D-era worry):** throttle 0 is faster per-process but incurs
at least one long tenacity stall (>3 min) that makes total wall time
worse than throttle 2.

Outcome classifications:
- H1 supported → flip `ScraperConfig.throttle_sleep` default to 0.
- H2 supported → keep the 2.0 s default; document the reasoning with
  fresh numbers.
- H0 not rejected → pick 0 on simplicity grounds (fewer knobs).

## Design

**Factor:** `throttle_sleep ∈ {0.0, 2.0}` (single factor, two levels).
**Covariates pinned:** `retry_403=True`, `driver_max_retries=20`,
`driver_backoff_max=60` — the validated defaults; we are tuning
*only* the proactive-pacing knob.

**Replicates:** 3 per level (6 trials total).

**Trial unit:** one 200-HC slice, disjoint from every other trial and
from prior experimental sweeps (V/U/T at 118k/123k/128k).

**Order:** blocked alternation `T0, T2, T0, T2, T0, T2`. Layer-2
drift during the experiment is then absorbed symmetrically — if 0 s
builds reputation faster, each 0-trial is followed by 2-trial with a
full cooldown to drain. Also protects against any monotonic
time-of-day trend on STF's end.

**Cooldown:** **45 min no-STF-traffic between every trial** + **60
min cold-start** before trial 1 (after the live sweep is SIGTERM'd
and drained). This is the layer-2 drain budget from
`docs/rate-limits.md § Cooldown recommendations`.

**Isolation from live sweep:** the live HC backfill
(`docs/sweep-results/2026-04-17-hc-full-backfill/`) MUST be paused
via `pkill -TERM -f run_sweep.*hc_full_backfill` before trial 1.
Resume after trial 6 finishes. The driver is `--resume`-safe. Live
sweep is currently in the 269k range; experiment slices are in the
105k–110k range; zero slice overlap for weeks of live-sweep progress.

### Trial slices (fixed, paper-era, disjoint)

| trial | slice label | HC range          | throttle | cooldown before |
|------:|:------------|:------------------|---------:|----------------:|
| 1     | A-T0        | HC 105001..105200 | 0.0 s    | 60 min          |
| 2     | B-T2        | HC 106001..106200 | 2.0 s    | 45 min          |
| 3     | C-T0        | HC 107001..107200 | 0.0 s    | 45 min          |
| 4     | D-T2        | HC 108001..108200 | 2.0 s    | 45 min          |
| 5     | E-T0        | HC 109001..109200 | 0.0 s    | 45 min          |
| 6     | F-T2        | HC 110001..110200 | 2.0 s    | 45 min          |

All six slices are pre-2013 paper-era, 1000 HCs apart (no slice-to-slice
bleedover through the WAF's sliding window), and none have been
touched by prior experimental sweeps or by the live backfill.

### Per-trial CSV + output layout

For each trial `X-T{0,2}`, the driver writes to:

```
docs/sweep-results/2026-04-17-throttle-tuning/X-T{0,2}/
  sweep.log.jsonl
  sweep.state.json
  sweep.errors.jsonl   # derived after trial
  report.md            # derived after trial
  driver.log           # captured stdout
data/output/hc_experiment/judex-mini_HC_<N>.json  # per-process JSONs, shared across trials
```

A one-off CSV per trial is derived by `scripts/build_throttle_trial_csvs.py`
(new, ~15 lines) that slices `hc_all_desc.csv` to the 200-row range.

## Metrics

Primary:
- **`wall_time_total`** per trial (seconds from first GET to last
  state write). The thing we actually care about.

Secondary (from `sweep.log.jsonl`):
- **`ok / 200`** — completeness. Expected ~195–200 on both arms.
- **`p50, p95 wall_s`** per process — distribution shape, catches
  layer-1 vs layer-2 engagement.
- **WAF cycle count** — number of contiguous 403 bursts (derived by
  scanning `sweep.log.jsonl` for `error_type=waf_block` sequences,
  or by clustering `wall_s > 20 s` processes).
- **Max single-process wall_s** — the H2 tail-risk signal.
- **Net new JSONs in `data/output/hc_experiment/`** — backfill yield.

Derived analysis:
- Paired comparison **`wall_time_total(T0) vs wall_time_total(T2)`**
  across the three matched pairs `(A,B), (C,D), (E,F)`.
- Effect-size estimate **Δ = mean(T2) − mean(T0)** with trial-to-trial
  noise as SD. 3 pairs is underpowered for p-values; we're looking
  for directional evidence and magnitude, not significance.

## Budget

| phase                           | duration | notes |
|---------------------------------|---------:|-------|
| SIGTERM live sweep + cooldown   | 60 min   | `pkill -TERM` + wait |
| Trial 1 (A-T0, 200 HCs @ 0 s)   | ~25 min  | expected 0.6 s/proc + WAF stalls; H2 says more |
| Cooldown                        | 45 min   |  |
| Trial 2 (B-T2, 200 HCs @ 2 s)   | ~45 min  | 2.0 s × 200 = 400 s floor + work |
| Cooldown                        | 45 min   |  |
| Trial 3 (C-T0)                  | ~25 min  |  |
| Cooldown                        | 45 min   |  |
| Trial 4 (D-T2)                  | ~45 min  |  |
| Cooldown                        | 45 min   |  |
| Trial 5 (E-T0)                  | ~25 min  |  |
| Cooldown                        | 45 min   |  |
| Trial 6 (F-T2)                  | ~45 min  |  |
| Analysis + report               | 30 min   | post-hoc script over all six `sweep.log.jsonl` |
| Resume live sweep               | 0 min    | `--resume` on the original command |
| **Total**                       | **~8 h** | can run unattended with `run_in_background` |

Net backfill yield: **~1 200 HCs** written to `data/output/hc_experiment/`.
Net live-sweep time lost: ~8 h → ~2 000 HCs *would have* been
scraped → experiment steals ~800 HCs of progress.

## Implementation sketch

Three small artifacts, all new:

**1. `scripts/build_throttle_trial_csvs.py`** (~30 lines). Slices
`tests/sweep/hc_all_desc.csv` into the six per-trial CSVs under
`tests/sweep/throttle_trials/`. Idempotent.

**2. `scripts/run_throttle_experiment.sh`** (~60 lines, bash). Loops
over a hardcoded schedule array `[(label, csv, throttle,
cooldown_s), …]`, running each trial with:

```bash
PYTHONPATH=. uv run python scripts/run_sweep.py \
    --csv tests/sweep/throttle_trials/${label}.csv \
    --label throttle_${label} \
    --out docs/sweep-results/2026-04-17-throttle-tuning/${label} \
    --items-dir data/output/hc_experiment \
    --throttle-sleep ${throttle} \
    > docs/sweep-results/2026-04-17-throttle-tuning/${label}/driver.log 2>&1
```

Between trials: `sleep ${cooldown_s}` (pure wall-clock, no STF
requests). Prints progress header before each trial. On SIGINT,
sends SIGTERM to the running trial (driver is already
SIGTERM-safe) and exits cleanly — the experiment is
`--resume`-compatible at the trial level.

**3. `scripts/analyse_throttle_experiment.py`** (~80 lines). Reads
all six `sweep.log.jsonl` files, computes the metrics above, writes
a Markdown report to `docs/sweep-results/2026-04-17-throttle-tuning/REPORT.md`
with the paired comparison table, distribution histograms (as inline
ASCII), and a recommended default.

No changes to `src/scraping/` or `src/sweeps/` — the experiment uses
existing `--throttle-sleep` CLI flag and state-file format.

## Dependencies

- Live sweep paused before trial 1 (manual `pkill -TERM`).
- `--items-dir` flag must accept a new directory (already does, used
  by sweeps T/U/V/Z).
- Disk: ~1 200 new HC JSONs × ~40 KB ≈ **50 MB** under
  `data/output/hc_experiment/`.
- No new Python dependencies.

## Risks & mitigations

- **Layer-2 drift during the experiment** — mitigated by the blocked
  alternating order (every T0 is followed by T2 and vice versa) and
  45 min cooldowns.
- **Experiment slices happen to land in an easy/hard corner of the
  WAF's internal state** — 3 replicates per arm reduces but doesn't
  eliminate this. If all three T0 trials hit anomalous WAF state, we
  re-run the affected arm after an overnight cold reset.
- **Live sweep's accumulated layer-2 pressure taints trial 1** —
  mitigated by 60 min pre-experiment cooldown (longer than the 45 min
  inter-trial default). If trial 1 shows anomalously long stalls vs
  trials 3 and 5, we discount it and use 5 trials for analysis.
- **Experiment runs overnight unattended and crashes silently** —
  driver already writes `sweep.state.json` atomically; `pgrep -f
  run_throttle_experiment` plus `ls -lt docs/sweep-results/2026-04-17-throttle-tuning/`
  tells you where it stopped. The shell wrapper logs each trial's
  start/end timestamp to a top-level `experiment.log`.
- **WAF gets significantly angrier at us during the experiment than
  during historical sweeps** — abort condition: if any trial
  produces `ok < 180 / 200`, stop the experiment, cool down overnight,
  re-plan. Conservative (~10 % failure rate is the floor for
  V-era paper sweeps).

## Non-goals

- **Not** tuning `driver_max_retries` or `driver_backoff_max` —
  those stay at validated defaults.
- **Not** testing throttle values other than 0 and 2.0 — a 5-point
  grid would need 15 trials (~20 h) and the D-data already covers
  the shape. Two-level design answers the actual question.
- **Not** validating the H2 tail-risk beyond max-wall_s — if H2
  fires, the follow-up is a dedicated tail-distribution study, not
  an extension of this experiment.
- **Not** measuring proxy rotation — separate spec. This experiment
  pins the single-IP case as a baseline.
- **Not** updating ground-truth fixtures or running parity checks
  — the experiment validates *throughput*, not correctness; parser
  quality is pinned by existing fixtures + pytest.

## Follow-ups (out of scope here)

1. If H1 is supported, flip `ScraperConfig.throttle_sleep` default in
   `src/config.py` and update `docs/rate-limits.md § Validated defaults`
   with the new numbers. ~15 min.
2. Regardless of outcome, a **rolling-median circuit breaker** on
   recent `wall_s` values is still needed — see
   `docs/current_progress.md §3`. Orthogonal to this experiment; the data
   collected here will inform the threshold.
3. **Proxy rotation experiment** — separate spec, layered on top of
   whatever throttle default this experiment picks.

## Approval checklist

Before running:
- [ ] Spec reviewed by owner.
- [ ] Live sweep is in a state where a ~8 h pause is acceptable.
- [ ] `data/output/hc_experiment/` directory is empty or contains
      only prior experiment output (no contamination with other
      sweeps).
- [ ] Disk space verified (~50 MB free under `data/output/`).
- [ ] `scripts/build_throttle_trial_csvs.py` and
      `scripts/run_throttle_experiment.sh` reviewed and committed
      before the first trial fires.
