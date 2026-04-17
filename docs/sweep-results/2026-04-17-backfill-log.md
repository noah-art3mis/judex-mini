# HC year-backfill — autonomous session log

Narrative record of the unattended multi-sweep backfill kicked off on
2026-04-17. Plan at `analysis/hc_backfill_plan.md`. Health-gate rules
documented there; this file interprets what happened.

## Context at start

- Sweep H (smoke, 100 HCs near the top) had landed earlier: 100/100
  ok, validated the pipeline. 67 % pending (fresh filings), 0
  concedidos — parser sanity, not deep-dive data.
- Sweep I (HC 230000..230999, 2023 vintage) was running when the
  autonomous mode was enabled.
- Criteria for "works well" before auto-proceeding to the next sweep:
  ok rate ≥ 90 % of non-404 responses, no circuit-breaker abort,
  wall ≤ 3× baseline, non-degenerate outcome distribution.

## What happened, in order

Each sweep covers 1000 contiguous HC ids centered on the year's
midpoint (from `analysis/hc_calendar.year_to_id_range`). Parser quality
was 100 % in every sweep — all failures are clean 404s from sparse HC
numbering, not parser bugs.

| # | year | range          | ok    | fails | WAF | wall     | notes |
|--:|-----:|----------------|------:|------:|----:|---------:|-------|
| I | 2023 | 230000..230999 |   883 |   117 |   1 | 55.3 min | first completed post-smoke |
| J | 2024 | 243046..244045 |   867 |   133 |   1 | 53.8 min | clean |
| K | 2022 | 216670..217669 |   817 |   183 |   1 | 54.5 min | lowest density so far |
| L | 2021 | 202782..203781 |   828 |   172 |   4 | 53.8 min | WAF pressure picking up |
| M | 2020 | 187634..188633 |   859 |   141 |   5 | 54.9 min | stable |
| N | 2019 | 172910..173909 |   913 |    87 |   5 | 56.5 min | density climbing |
| O | 2018 | 158709..159708 |   945 |    55 |  10 | 57.5 min | WAF ×10, all absorbed |
| P | 2017 | 148601..149600 |   914 |    86 |   9 | 55.7 min | clean |
| Q | 2016 | 143298..144297 |   936 |    64 |   9 | 57.0 min | clean |
| R | 2015 | 138706..139705 |   881 |   119 |   6 | 54.2 min | actually 2016 vintage |
| S | 2014 | 134119..135118 |   935 |    65 |   2 | 57.2 min | actually 2016 vintage |

Every completed sweep cleared all health gates. Zero hard errors
across all nine sweeps totalling ~8k HCs — `status=error` count is 0
everywhere; 5xx counts 0–7 per sweep, each absorbed by tenacity retries.

## Infrastructure behaviour

Three observations worth recording for the next iteration:

1. **Wall time is remarkably stable** at 54–58 min per 1000-HC sweep.
   That converges on ~3.3 s/process end-to-end — slightly under the
   handoff's 3.6 s projection.
2. **WAF cycles cluster by sweep** but do not accumulate across
   sweeps: each sweep sees 1–10 retry-403 cycles (up from sweep I's
   single cycle to sweep O's ten), but each block clears within
   ~60–90 s and the next sweep starts with a cold counter. Rate-
   budget defaults (`retry_403=True`, 2 s pacing, max 20 attempts)
   are holding up.
3. **Post-sweep cache-replay is the bottleneck between runs.** The
   sweep driver writes state / log / errors / report but *not* per-
   process JSONs. Each sweep needs a cache-hot replay pass (~30 s
   for ~900 HCs) to populate `output/sample/<label>/` so the
   notebook can load it. Open TODO in `docs/hc-who-wins.md` § "Open
   TODOs". Replay was caught once writing 0 files (state-schema
   mismatch after a driver update) and re-run with the corrected
   flat-keys layout.

## Data inventory

- **8070 HCs** currently loaded under `output/sample/hc_<range>/`,
  across 9 year-cohorts + sweep H (top 100) + 7 one-off samples.
- **993 id→date anchors** in `analysis/hc_id_to_date.json`, spanning
  2003-03-31 .. 2026-04-16. The 2023 slice alone contributed 883
  anchors so the calendar's interpolation is now dense through the
  post-2014 era.
- **Disk usage**: rough estimate ~3–4 GB under `.cache/html/` for
  9 × 1000 process caches; ~1–2 GB under `output/sample/`.

## Outcome distribution so far (n=8070)

This is the first dataset large enough to make the who-wins question
answerable.

| outcome             |    n | share |
|---------------------|-----:|------:|
| `nao_conhecido`     | 5476 | 67.9% |
| `denegado`          |  824 | 10.2% |
| None (pending)      |  655 |  8.1% |
| `nao_provido`       |  393 |  4.9% |
| `prejudicado`       |  384 |  4.8% |
| `concedido`         |  274 |  3.4% |
| `concedido_parcial` |   38 |  0.5% |
| `provido`           |   26 |  0.3% |

Reads:

- **Procedural rejection dominates** (`nao_conhecido` = nearly 68 %).
  STF's HC practice is monocratic: most petitions are dispatched via
  *nego seguimento* before merits are reached.
- **True wins** (`concedido` + `concedido_parcial`) = **312 cases,
  3.9 % overall.** At the handoff's quoted 5–10 % historical range,
  we're on the low end. That fits with a time-distributed sample
  across years where monocratic dispatch has been increasing.
- **`denegado` + `nao_provido` = 15.1 %** — merits-level losses. Plus
  `prejudicado` 4.8 % (mooted cases).
- **Pending = 8.1 %** — lower than the raw count suggests because the
  top-100 sweep H (67 % pending on fresh IDs) is diluted out by the
  matured samples.

## Who-wins analysis is now unblocked

With 312 wins across ~8k decided cases, the impetrante and relator
aggregations will have enough mass for:
- top-5 to top-10 repeat-player impetrantes with non-degenerate CIs
- all ~15 relators at ≥ 100 cases each
- stratification by year (8 cohorts) to detect era drift
- orgao_origem and assunto controls (variety should be real in the
  matured samples, unlike sweep H where 100/100 were direct STF
  filings)

The marimo notebook at `analysis/hc_explorer.py` loads everything
under `output/sample/` automatically; opening it now will pick up all
8070 HCs and render the existing who-wins + affinity-heatmap cells
against real data.

## What's next

- Original queue (I–S) **complete**. Successor plan at
  `docs/hc-backfill-extension-plan.md`.
- Calendar discrepancy discovered post-S: plan-labeled "2014/2015"
  sweeps both landed in 2016. Calendar recalibrated against
  9 886 (id, data_protocolo) anchors from existing samples + 9
  pre-2016 probes (HC 85 000..130 000 at 5 000-step intervals).
- **Sweep Z (2025 fill, HC 258 105..259 104)** launched 2026-04-17
  in background after recalibration. First sweep under the
  extension plan; only modern-era year missing.
- After Z: launch sweep T (2015, HC 128 651..129 650) per
  extension plan Track 1.
- When all planned sweeps finish, the handoff doc and
  `docs/hc-who-wins.md` should get their "status: completed" update
  and the notebook's bar charts should have their screenshots
  captured for the write-up.
