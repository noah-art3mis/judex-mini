# HC backfill — extension plan (post-S)

Successor to `analysis/hc_backfill_plan.md` (queue exhausted 2026-04-17 with sweep S). This document covers what's left to scrape and why, the calendar correction needed before launching, the prioritised sweep queue, and the post-sweep routine.

## TL;DR

- **9 909 HCs scraped across 11 sweeps** (I–S), spanning data_protocolo years **2016–2024 + 2026**. Parser quality stable across the whole span (see `docs/sweep-results/2026-04-17-backfill-log.md`).
- **Two real gaps**: pre-2016 (zero coverage) and 2025 (1 HC).
- **Calendar is off by 1–2 years for pre-2018 IDs.** Sweeps R and S, plan-labeled 2015 and 2014, both landed in 2016. Recalibrate before launching anything below HC 135 000.
- **Three tracks proposed**: backward extension (era drift), 2025 fill (only year missing in the modern era), recent-year densification (tighter CIs for who-wins). Total wall ≈ 8–14 hours depending on tracks selected.

## Current state (2026-04-17)

### Cohorts on disk

| sweep | HC range          | plan label | actual data_protocolo year | n on disk |
|------:|-------------------|-----------:|---------------------------:|----------:|
| I     | 230000..230999    | 2023       | 2023                       | 884       |
| J     | 243046..244045    | 2024       | 2024                       | 870       |
| K     | 216670..217669    | 2022       | 2022                       | 817       |
| L     | 202782..203781    | 2021       | 2021                       | 829       |
| M     | 187634..188633    | 2020       | 2020                       | 859       |
| N     | 172910..173909    | 2019       | 2019                       | 914       |
| O     | 158709..159708    | 2018       | 2018                       | 945       |
| P     | 148601..149600    | 2017       | **2017**                   | 914       |
| Q     | 143298..144297    | 2016       | **2017**                   | 936       |
| R     | 138706..139705    | 2015       | **2016**                   | 881       |
| S     | 134119..135118    | 2014       | **2016** (spot-checked)    | 935*      |
| H     | last_100          | 2026 smoke | 2026                       | 100       |

\* S not yet replayed into `output/sample/`. 935 ok per `sweep.state.json`.

### Year coverage (data_protocolo, post-S replay)

| year | n on disk (post-S) | gap |
|-----:|-------------------:|-----|
| 2016 | ~1815              | over-covered (R + S both land here) |
| 2017 | ~1850              | over-covered (P + Q both land here) |
| 2018 | 945                | ok |
| 2019 | 914                | ok |
| 2020 | 859                | ok |
| 2021 | 829                | ok |
| 2022 | 817                | ok |
| 2023 | 884                | ok |
| 2024 | 870                | ok |
| 2025 | 1                  | **undersampled** (~15 000 HCs filed in 2025) |
| 2026 | 100                | smoke only, sufficient |
| ≤2015 | 0                 | **uncovered** |

## Calendar correction (do first)

`src.utils.hc_calendar.year_to_id_range` predicts pre-2018 ranges that overshoot reality. Two sweeps mapped to the same actual year (R/2015→2016, S/2014→2016; Q/2016→2017, P/2017→2017). Likely cause: linear interpolation between sparse anchors masks a non-linear filing-rate change in the 2014–2017 STJ→STF transfer regime.

**Fix** (done 2026-04-17): `src/utils/hc_id_to_date.json` now holds **9 897 anchors** (id range 82959..271060), merged from the extended collector output that previously lived in `analysis/hc_id_to_date.json` (since deleted). Re-run `uv run python src/utils/hc_calendar.py` to inspect the year→id table; 2014 resolves to 120926..126076 and 2015 to 126093..132210, both well below HC 138 000. Collector cell lives at the bottom of `src/utils/hc_calendar.py`.

```python
# one-shot recalibration sketch
import json
from pathlib import Path
anchors = []
for d in Path('output/sample').glob('hc_*'):
    for f in d.iterdir():
        c = json.loads(f.read_text())
        c = c[0] if isinstance(c, list) else c
        dp, pid = c.get('data_protocolo'), c.get('processo_id')
        if dp and pid:
            dd, mm, yy = dp.split('/')
            anchors.append({'id': pid, 'date': f'{yy}-{mm}-{dd}'})
# merge into hc_id_to_date.json, dedupe by id
```

## Sweep queue (priority order)

### Track 1 — Pre-2016 backward extension (era drift study)

Goal: cover the era before the 2016 monocratic-dispatch escalation. Tests whether the dominant `nao_conhecido` finding (~68 %) holds across regimes.

Each sweep is **~2 000 IDs wide** (paper-era density was 47–69 % per sweep G), targeting ~1 000 extant HCs per cohort.

Recalibrated 2026-04-17 against 9 886 sample anchors + 9 probes (HC 85k, 90k, 100k–130k at 5k steps). Pre-2017 era is much lower volume (~5k IDs/year vs ~14k modern):

| sweep | target year | ID range (1000 IDs)  | wall   | priority |
|------:|------------:|----------------------|-------:|----------|
| T     | 2015        | 128 651..129 650     | ~60 m  | high — first paper-era cohort |
| U     | 2014        | 123 001..124 000     | ~60 m  | high |
| V     | 2013        | 118 201..119 200     | ~60 m  | medium |
| W     | 2012        | 113 648..114 647     | ~60 m  | medium |
| X     | 2011        | 108 917..109 916     | ~60 m  | low |
| Y     | 2010        | 104 123..105 122     | ~60 m  | low |
| (further back: 2009 ≈ HC 99 500, 2006 ≈ HC 90 000, 2004 ≈ HC 85 000 — pre-electronic, optional) |

Density at HC 100 000–130 000 was 9/10 in the probe (only HC 95 000 was 404). Should comfortably land ≥ 600 extant per 1000-ID sweep; if density drops below 50 % at lower IDs, widen to 2 000 IDs.

**Stop criterion**: if outcome distribution within a year drifts < 5 % from the adjacent year, declare era stable and stop pre-emptively.

### Track 2 — 2025 fill (only modern-era year missing)

Goal: parity with the 2016–2024 cohorts. Currently 1 HC of an estimated 15 000 filed in 2025.

| sweep | target year | ID range             | wall  | priority |
|------:|------------:|----------------------|------:|----------|
| Z     | 2025        | 258 105..259 104     | ~60 m | **highest — launched 2026-04-17** |

Only sweep that's strictly necessary for cohort completeness in the modern era.

### Track 3 — Recent-year densification (tighter CIs)

Goal: increase per-year mass for the lawyer × relator crosstabs (currently ≥3 merits decisions cells empty out everyone but Defensorias). Each sweep adds a second 1 000-ID slice at a different offset within the same year.

| sweep | year | offset | est ID range |
|------:|-----:|-------:|--------------|
| AA    | 2023 | +6 mo   | ~234 500..235 499 |
| BB    | 2024 | +6 mo   | ~248 000..248 999 |
| CC    | 2022 | +6 mo   | ~221 000..221 999 |

Only useful if Track 1's era drift is small enough that we want to push for statistical power on the modern data instead. **Decide after Tracks 1 + 2.**

## Wall-time budget

| track | sweeps | est wall  | notes |
|-------|-------:|----------:|-------|
| 1     | 4–6    | 7.5–14 h  | T+U+V+W minimum; X, Y optional |
| 2     | 1      | ~1 h      | 2025 fill |
| 3     | 0–3    | 0–3 h     | only if track 1 says modern era is the right place to densify |

Per-sweep wall has been remarkably stable at 54–58 min for dense (post-2017) eras, ~110 min projected for paper-era (2× ID coverage at same per-process throughput).

## Health gates (unchanged from previous plan)

Checked on each sweep's `sweep.state.json` before launching the next:

- `ok / total >= 0.85` (relaxed from 0.90 — paper-era density is bimodal, lower 404 thresholds expected)
- no circuit-breaker abort (state status != "aborted")
- wall <= 3× the in-flight reference (~ 60 min for dense eras, ~ 110 min for paper)
- outcome distribution non-degenerate (not all-404, not all-pending)
- **new**: `data_protocolo` year of ≥80 % of ok cases falls within target year ± 1

Last gate guards against another calendar-mismatch surprise; if it fires, halt and re-probe before retrying.

## Post-sweep routine (per sweep)

1. **Read** `docs/sweep-results/<date>-<label>/sweep.state.json`.
2. **Check health gates** above. If any fail → halt and surface numbers; don't proceed.
3. **Replay cache-hot** into `output/sample/<label>/judex-mini_HC_<n>-<n>.json` (chunk size 1 in `main.py` would write each as its own file; see existing replay invocation in backfill log).
4. **Extend** `src/utils/hc_id_to_date.json` with the new (id, data_protocolo) anchors.
5. **Recalibrate** `src/utils/hc_calendar.py` after every 2 sweeps in Track 1 (since each new cohort tightens the interpolation in the paper era).
6. **Append** a row to `docs/sweep-results/2026-04-17-backfill-log.md` with sweep, range, ok/fail, WAF cycles, wall.
7. **Launch** next queued sweep in the background.

## Decision points (when to stop)

- **Three consecutive sweeps with ok % < 85** → halt, investigate WAF posture (may require rotating IPs via `--proxy-pool` or extending retry budget).
- **Outcome distribution drift across an era < 5 %** → diminishing analytical returns, declare done.
- **Hard cap**: 20 sweeps total in this extension (currently 1 done = S; budget for 19 more). Forces re-evaluation if scope creeps.

## What this plan does NOT cover

- **Other classes** (RHC, AP, MS). Marquee criminal-bar lawyers are more likely to appear in RHC/AP than HC; if the lawyer×relator analysis stalls on volume, scope an RHC sweep separately. Density probe at `scripts/class_density_probe.py`.
- **PDF re-extraction quality**. Some 2016-era HCs had documentos with rotated-watermark artefacts (see handoff § PDF extraction quality). Out of scope here.
- **Robots.txt posture**. Still unresolved; sweeps continue under the current adaptive-pacing arrangement.

## Files to update when this plan is done

- `docs/handoff.md` § "Next major goal" — mark the HC backfill as completed across the planned eras.
- `docs/hc-who-wins.md` — incorporate era-drift findings (or note their absence) in the writeup.
- ~~`analysis/hc_backfill_plan.md` — supersede with a one-line pointer to this file.~~ Done 2026-04-17: file deleted; this doc is the canonical successor.
