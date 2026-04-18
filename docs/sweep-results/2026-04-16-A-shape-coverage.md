# Validation sweep — shape_coverage

- commit: `d00ce9a` · csv: `tests/sweep/shape_coverage.csv` · parity: gt-dir `tests/ground_truth`
- started: 2026-04-16T23:14:32+00:00
- finished: 2026-04-16T23:14:37+00:00
- elapsed: 4.9s

## Cold pass

| classe | processo | wall_s | 429 | 5xx | diffs | anomalies | status |
|--------|----------|-------:|----:|----:|------:|-----------|--------|
| AI | 772309 | 0.11 | 0 | 0 | 0 | — | ok |
| MI | 12 | 0.10 | 0 | 0 | 0 | — | ok |
| RE | 1234567 | 0.13 | 0 | 0 | 0 | — | ok |
| ACO | 2652 | 0.50 | 0 | 0 | 2 | — | ok |
| ADI | 2820 | 0.53 | 0 | 0 | 0 | — | ok |
| ADI | 4000 | 0.25 | 0 | 0 | 0 | — | ok |
| RE | 1058333 | 0.25 | 0 | 0 | 0 | — | ok |
| AI | 500000 | 1.26 | 0 | 0 | 0 | — | ok |
| ACO | 3000 | 0.17 | 0 | 0 | 0 | — | ok |
| MI | 943 | 0.43 | 0 | 0 | 0 | — | ok |
| HC | 82959 | 0.71 | 0 | 0 | 0 | — | ok |
| HC | 126292 | 0.46 | 0 | 0 | 0 | — | ok |

- completed: **12 ok / 0 fail** of 12
- wall p50 / p90 / max: **0.34s / 1.09s / 1.26s**
- retries: **429×0**, **5xx×0**
- parity diffs (total across 12 processes): **2**
- shape anomalies (total): **0**

## Per-process diffs

### ACO 2652 (ground_truth)

Diffs vs parity source:
```
  assuntos: http=['DIREITO TRIBUTÁRIO | Procedimentos Fiscais | Cadastro de Inadimplentes - CADIN/SPC/SERASA/SIAFI/CAUC'] vs other=['DIREITO TRIBUTÁRIO | Procedimentos Fiscais | Cadastro de Inadimplentes - CADIN']
  pautas: http=[] vs other=None
```

## Recurring divergences

_No field diffs in ≥2 processes._

## Notes

- **Cache state was mixed.** The 5 anchor fixtures were already cached
  from earlier `validate_ground_truth.py` runs; only the 7 curated
  processes exercised the network. The published wall times reflect
  that — the 5 sub-0.2 s anchors are cache-warm, the 7 curated rows
  are cold-fetched. Cold-only p50 ≈ 0.46 s, p90 ≈ 1.26 s, max 1.26 s
  for this sample.
- **AI 828 substituted with AI 500000.** First pick did not exist
  (STF's `listarProcessos.asp` returned 200 without a redirect, which
  is how the portal signals "no such process"). Design doc noted this
  risk; substitution logged here.
- **ACO 2652 diffs are the pre-existing baseline**, documented in
  `docs/current_progress.md` as "assuntos drift on the live site" and
  "pautas: null vs []". Not introduced by this sweep.
- **PDF rotated-text warnings** appeared for MI 943 / HC 82959 /
  HC 126292 — pypdf's layout-mode extractor drops some content when
  signed documents carry rotated watermarks. Tracked as handoff step
  #4. Not a regression.
- **All shape-probe checks passed** (no missing required scalars, no
  list fields with wrong type, no non-string documento values) across
  all 7 curated processes, including the previously-unexercised HC
  class.
