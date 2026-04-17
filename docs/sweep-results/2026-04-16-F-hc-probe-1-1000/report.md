# Validation sweep — hc_probe_1_1000

- commit: `4c2a0fd` · csv: `tests/sweep/hc_probe_1_1000.csv` · parity: none
- started: 2026-04-17T01:43:52+00:00
- finished: 2026-04-17T01:45:29+00:00
- elapsed: 96.4s

## Cold pass

| classe | processo | wall_s | 429 | 5xx | diffs | anomalies | status |
|--------|----------|-------:|----:|----:|------:|-----------|--------|
| HC | 1 | 0.28 | 0 | 0 | 0 | — | fail |
| HC | 2 | 0.08 | 0 | 0 | 0 | — | fail |
| HC | 3 | 0.09 | 0 | 0 | 0 | — | fail |
| HC | 4 | 0.14 | 0 | 0 | 0 | — | fail |
| HC | 5 | 0.10 | 0 | 0 | 0 | — | fail |
| HC | 6 | 0.11 | 0 | 0 | 0 | — | fail |
| HC | 7 | 0.15 | 0 | 0 | 0 | — | fail |
| HC | 8 | 0.12 | 0 | 0 | 0 | — | fail |
| HC | 9 | 0.18 | 0 | 0 | 0 | — | fail |
| HC | 10 | 0.08 | 0 | 0 | 0 | — | fail |
| HC | 11 | 0.09 | 0 | 0 | 0 | — | fail |
| HC | 12 | 0.08 | 0 | 0 | 0 | — | fail |
| HC | 13 | 0.11 | 0 | 0 | 0 | — | fail |
| HC | 14 | 0.08 | 0 | 0 | 0 | — | fail |
| HC | 15 | 0.12 | 0 | 0 | 0 | — | fail |
| HC | 16 | 0.12 | 0 | 0 | 0 | — | fail |
| HC | 17 | 0.09 | 0 | 0 | 0 | — | fail |
| HC | 18 | 0.10 | 0 | 0 | 0 | — | fail |
| HC | 19 | 0.08 | 0 | 0 | 0 | — | fail |
| HC | 20 | 0.08 | 0 | 0 | 0 | — | fail |
| HC | 21 | 0.08 | 0 | 0 | 0 | — | fail |
| HC | 22 | 0.11 | 0 | 0 | 0 | — | fail |
| HC | 23 | 0.08 | 0 | 0 | 0 | — | fail |
| HC | 24 | 0.08 | 0 | 0 | 0 | — | fail |
| HC | 25 | 0.12 | 0 | 0 | 0 | — | fail |
| HC | 26 | 0.09 | 0 | 0 | 0 | — | fail |
| HC | 27 | 0.08 | 0 | 0 | 0 | — | fail |
| HC | 28 | 0.11 | 0 | 0 | 0 | — | fail |
| HC | 29 | 0.90 | 0 | 0 | 0 | — | ok |
| HC | 30 | 0.68 | 0 | 0 | 0 | — | ok |
| HC | 31 | 0.14 | 0 | 0 | 0 | — | fail |
| HC | 32 | 0.13 | 0 | 0 | 0 | — | fail |
| HC | 33 | 0.11 | 0 | 0 | 0 | — | fail |
| HC | 34 | 0.14 | 0 | 0 | 0 | — | fail |
| HC | 35 | 0.14 | 0 | 0 | 0 | — | fail |
| HC | 36 | 0.12 | 0 | 0 | 0 | — | fail |
| HC | 37 | 0.12 | 0 | 0 | 0 | — | fail |
| HC | 38 | 0.84 | 0 | 0 | 0 | — | ok |
| HC | 39 | 0.13 | 0 | 0 | 0 | — | fail |
| HC | 40 | 0.57 | 0 | 0 | 0 | — | ok |
| HC | 41 | 0.09 | 0 | 0 | 0 | — | fail |
| HC | 42 | 0.11 | 0 | 0 | 0 | — | fail |
| HC | 43 | 0.08 | 0 | 0 | 0 | — | fail |
| HC | 44 | 0.73 | 0 | 0 | 0 | — | ok |

- completed: **5 ok / 39 fail** of 44
- wall p50 / p90 / max: **0.73s / 0.92s / 0.90s**
- retries: **429×0**, **5xx×0**
- parity diffs (total across 44 processes): **0**
- shape anomalies (total): **0**

## Errors breakdown

| error_type | http_status | count |
|------------|------------:|------:|
| NoIncidente | - | 39 |

## Per-process diffs

_No diffs or anomalies on any process._

## Recurring divergences

_No field diffs in ≥2 processes._
