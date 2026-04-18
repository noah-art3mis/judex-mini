# Validation sweep — proxy_canary

- commit: `f5497d4` · csv: `tests/sweep/canary_50.csv` · parity: none
- started: 2026-04-18T01:27:16+00:00
- finished: 2026-04-18T01:28:35+00:00
- elapsed: 78.6s

## Cold pass

| classe | processo | wall_s | 429 | 5xx | diffs | anomalies | status |
|--------|----------|-------:|----:|----:|------:|-----------|--------|
| HC | 193000 | 2.46 | 0 | 0 | 0 | — | fail |
| HC | 192999 | 0.64 | 0 | 0 | 0 | — | fail |
| HC | 192998 | 0.65 | 0 | 0 | 0 | — | fail |
| HC | 192997 | 0.58 | 0 | 0 | 0 | — | fail |
| HC | 192996 | 6.47 | 0 | 0 | 0 | — | ok |
| HC | 192995 | 3.15 | 0 | 0 | 0 | — | ok |
| HC | 192994 | 3.88 | 0 | 0 | 0 | — | ok |
| HC | 192993 | 0.59 | 0 | 0 | 0 | — | fail |
| HC | 192992 | 0.81 | 0 | 0 | 0 | — | fail |
| HC | 192991 | 0.62 | 0 | 0 | 0 | — | fail |
| HC | 192990 | 0.60 | 0 | 0 | 0 | — | fail |
| HC | 192989 | 0.57 | 0 | 0 | 0 | — | fail |
| HC | 192988 | 0.59 | 0 | 0 | 0 | — | fail |
| HC | 192987 | 0.57 | 0 | 0 | 0 | — | fail |
| HC | 192986 | 0.58 | 0 | 0 | 0 | — | fail |
| HC | 192985 | 0.57 | 0 | 0 | 0 | — | fail |
| HC | 192984 | 0.96 | 0 | 0 | 0 | — | fail |
| HC | 192983 | 0.61 | 0 | 0 | 0 | — | fail |
| HC | 192982 | 0.59 | 0 | 0 | 0 | — | fail |
| HC | 192981 | 0.57 | 0 | 0 | 0 | — | fail |
| HC | 192980 | 0.60 | 0 | 0 | 0 | — | fail |
| HC | 192979 | 0.62 | 0 | 0 | 0 | — | fail |
| HC | 192978 | 0.57 | 0 | 0 | 0 | — | fail |
| HC | 192977 | 0.57 | 0 | 0 | 0 | — | fail |
| HC | 192976 | 0.47 | 0 | 0 | 0 | — | fail |
| HC | 192975 | 0.47 | 0 | 0 | 0 | — | fail |
| HC | 192974 | 0.62 | 0 | 0 | 0 | — | fail |
| HC | 192973 | 0.65 | 0 | 0 | 0 | — | fail |
| HC | 192972 | 0.58 | 0 | 0 | 0 | — | fail |
| HC | 192971 | 0.58 | 0 | 0 | 0 | — | fail |
| HC | 192970 | 0.57 | 0 | 0 | 0 | — | fail |
| HC | 192969 | 0.79 | 0 | 0 | 0 | — | fail |
| HC | 192968 | 0.58 | 0 | 0 | 0 | — | fail |
| HC | 192967 | 0.58 | 0 | 0 | 0 | — | fail |
| HC | 192966 | 0.67 | 0 | 0 | 0 | — | fail |
| HC | 192965 | 0.57 | 0 | 0 | 0 | — | fail |
| HC | 192964 | 0.57 | 0 | 0 | 0 | — | fail |
| HC | 192963 | 0.57 | 0 | 0 | 0 | — | fail |
| HC | 192962 | 0.81 | 0 | 0 | 0 | — | fail |
| HC | 192961 | 0.56 | 0 | 0 | 0 | — | fail |
| HC | 192960 | 0.60 | 0 | 0 | 0 | — | fail |
| HC | 192959 | 0.56 | 0 | 0 | 0 | — | fail |
| HC | 192958 | 2.98 | 0 | 0 | 0 | — | ok |
| HC | 192957 | 3.22 | 0 | 0 | 0 | — | ok |
| HC | 192956 | 3.86 | 0 | 0 | 0 | — | ok |
| HC | 192955 | 3.25 | 0 | 0 | 0 | — | ok |
| HC | 192954 | 3.20 | 0 | 0 | 0 | — | ok |
| HC | 192953 | 3.94 | 0 | 0 | 0 | — | ok |
| HC | 192952 | 12.35 | 0 | 0 | 0 | — | ok |
| HC | 192951 | 6.15 | 0 | 0 | 0 | — | ok |

- completed: **11 ok / 39 fail** of 50
- wall p50 / p90 / max: **3.86s / 11.17s / 12.35s**
- retries: **429×0**, **5xx×0**
- parity diffs (total across 50 processes): **0**
- shape anomalies (total): **0**

## Errors breakdown

| error_type | http_status | count |
|------------|------------:|------:|
| NoIncidente | - | 39 |

## Per-process diffs

_No diffs or anomalies on any process._

## Recurring divergences

_No field diffs in ≥2 processes._
