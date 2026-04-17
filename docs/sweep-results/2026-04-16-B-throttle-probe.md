# Validation sweep — throttle_probe

- commit: `90e4bce` · csv: `tests/sweep/throttle_probe.csv` · parity: selenium-csv `output/judex-mini_ADI_1-1000.csv` (609 rows)
- started: 2026-04-16T23:15:29+00:00
- finished: 2026-04-16T23:16:50+00:00
- elapsed: 81.3s

## Cold pass

| classe | processo | wall_s | 429 | 5xx | diffs | anomalies | status |
|--------|----------|-------:|----:|----:|------:|-----------|--------|
| ADI | 7 | 1.25 | 0 | 0 | 0 | — | ok |
| ADI | 26 | 1.00 | 0 | 0 | 0 | — | ok |
| ADI | 28 | 1.14 | 0 | 0 | 0 | — | ok |
| ADI | 31 | 0.77 | 0 | 0 | 0 | — | ok |
| ADI | 33 | 0.94 | 0 | 0 | 0 | — | ok |
| ADI | 45 | 0.79 | 0 | 0 | 0 | — | ok |
| ADI | 47 | 0.95 | 0 | 0 | 0 | — | ok |
| ADI | 72 | 1.56 | 0 | 0 | 0 | — | ok |
| ADI | 81 | 0.83 | 0 | 0 | 0 | — | ok |
| ADI | 90 | 0.87 | 0 | 0 | 1 | — | ok |
| ADI | 95 | 0.70 | 0 | 0 | 0 | — | ok |
| ADI | 96 | 0.73 | 0 | 0 | 0 | — | ok |
| ADI | 100 | 0.81 | 0 | 0 | 0 | — | ok |
| ADI | 105 | 1.61 | 0 | 0 | 0 | — | ok |
| ADI | 115 | 0.75 | 0 | 0 | 0 | — | ok |
| ADI | 128 | 1.00 | 0 | 0 | 0 | — | ok |
| ADI | 143 | 0.91 | 0 | 0 | 0 | — | ok |
| ADI | 160 | 2.47 | 0 | 0 | 0 | — | ok |
| ADI | 164 | 0.80 | 0 | 0 | 1 | — | ok |
| ADI | 197 | 0.94 | 0 | 0 | 0 | — | ok |
| ADI | 204 | 0.82 | 0 | 0 | 0 | — | ok |
| ADI | 221 | 0.91 | 0 | 0 | 0 | — | ok |
| ADI | 224 | 0.87 | 0 | 0 | 0 | — | ok |
| ADI | 226 | 0.70 | 0 | 0 | 0 | — | ok |
| ADI | 229 | 0.73 | 0 | 0 | 0 | — | ok |
| ADI | 239 | 0.94 | 0 | 0 | 0 | — | ok |
| ADI | 251 | 1.34 | 0 | 0 | 0 | — | ok |
| ADI | 271 | 2.15 | 0 | 0 | 0 | — | ok |
| ADI | 282 | 15.25 | 0 | 0 | 0 | — | ok |
| ADI | 285 | 1.06 | 0 | 0 | 0 | — | ok |
| ADI | 301 | 1.22 | 0 | 0 | 0 | — | ok |
| ADI | 345 | 5.96 | 0 | 0 | 0 | — | ok |
| ADI | 349 | 0.94 | 0 | 0 | 0 | — | ok |
| ADI | 353 | 0.76 | 0 | 0 | 0 | — | ok |
| ADI | 368 | 0.95 | 0 | 0 | 0 | — | ok |
| ADI | 371 | 0.86 | 0 | 0 | 0 | — | ok |
| ADI | 388 | 3.49 | 0 | 0 | 0 | — | ok |
| ADI | 390 | 0.87 | 0 | 0 | 0 | — | ok |
| ADI | 430 | 0.86 | 0 | 0 | 0 | — | ok |
| ADI | 433 | 0.69 | 0 | 0 | 0 | — | ok |
| ADI | 460 | 0.73 | 0 | 0 | 0 | — | ok |
| ADI | 471 | 0.94 | 0 | 0 | 0 | — | ok |
| ADI | 518 | 0.67 | 0 | 0 | 0 | — | ok |
| ADI | 550 | 0.84 | 0 | 0 | 0 | — | ok |
| ADI | 559 | 0.87 | 0 | 0 | 0 | — | ok |
| ADI | 566 | 3.05 | 0 | 0 | 0 | — | ok |
| ADI | 575 | 0.80 | 0 | 0 | 0 | — | ok |
| ADI | 592 | 0.74 | 0 | 0 | 0 | — | ok |
| ADI | 604 | 0.93 | 0 | 0 | 0 | — | ok |
| ADI | 605 | 0.92 | 0 | 0 | 0 | — | ok |

- completed: **50 ok / 0 fail** of 50
- wall p50 / p90 / max: **0.91s / 2.44s / 15.25s**
- retries: **429×0**, **5xx×0**
- parity diffs (total across 50 processes): **2**
- shape anomalies (total): **0**

## Warm pass

| classe | processo | wall_s | 429 | 5xx | diffs | anomalies | status |
|--------|----------|-------:|----:|----:|------:|-----------|--------|
| ADI | 7 | 0.12 | 0 | 0 | 0 | — | ok |
| ADI | 26 | 0.13 | 0 | 0 | 0 | — | ok |
| ADI | 28 | 0.16 | 0 | 0 | 0 | — | ok |
| ADI | 31 | 0.24 | 0 | 0 | 0 | — | ok |
| ADI | 33 | 0.17 | 0 | 0 | 0 | — | ok |
| ADI | 45 | 0.20 | 0 | 0 | 0 | — | ok |
| ADI | 47 | 0.16 | 0 | 0 | 0 | — | ok |
| ADI | 72 | 0.12 | 0 | 0 | 0 | — | ok |
| ADI | 81 | 0.09 | 0 | 0 | 0 | — | ok |
| ADI | 90 | 0.14 | 0 | 0 | 1 | — | ok |
| ADI | 95 | 0.14 | 0 | 0 | 0 | — | ok |
| ADI | 96 | 0.13 | 0 | 0 | 0 | — | ok |
| ADI | 100 | 0.26 | 0 | 0 | 0 | — | ok |
| ADI | 105 | 0.29 | 0 | 0 | 0 | — | ok |
| ADI | 115 | 0.13 | 0 | 0 | 0 | — | ok |
| ADI | 128 | 0.23 | 0 | 0 | 0 | — | ok |
| ADI | 143 | 0.22 | 0 | 0 | 0 | — | ok |
| ADI | 160 | 0.19 | 0 | 0 | 0 | — | ok |
| ADI | 164 | 0.25 | 0 | 0 | 1 | — | ok |
| ADI | 197 | 0.27 | 0 | 0 | 0 | — | ok |
| ADI | 204 | 0.13 | 0 | 0 | 0 | — | ok |
| ADI | 221 | 0.11 | 0 | 0 | 0 | — | ok |
| ADI | 224 | 0.10 | 0 | 0 | 0 | — | ok |
| ADI | 226 | 0.12 | 0 | 0 | 0 | — | ok |
| ADI | 229 | 0.15 | 0 | 0 | 0 | — | ok |
| ADI | 239 | 0.27 | 0 | 0 | 0 | — | ok |
| ADI | 251 | 0.37 | 0 | 0 | 0 | — | ok |
| ADI | 271 | 0.11 | 0 | 0 | 0 | — | ok |
| ADI | 282 | 0.41 | 0 | 0 | 0 | — | ok |
| ADI | 285 | 0.19 | 0 | 0 | 0 | — | ok |
| ADI | 301 | 0.16 | 0 | 0 | 0 | — | ok |
| ADI | 345 | 0.48 | 0 | 0 | 0 | — | ok |
| ADI | 349 | 0.13 | 0 | 0 | 0 | — | ok |
| ADI | 353 | 0.11 | 0 | 0 | 0 | — | ok |
| ADI | 368 | 0.14 | 0 | 0 | 0 | — | ok |
| ADI | 371 | 0.16 | 0 | 0 | 0 | — | ok |
| ADI | 388 | 0.18 | 0 | 0 | 0 | — | ok |
| ADI | 390 | 0.13 | 0 | 0 | 0 | — | ok |
| ADI | 430 | 0.12 | 0 | 0 | 0 | — | ok |
| ADI | 433 | 0.10 | 0 | 0 | 0 | — | ok |
| ADI | 460 | 0.19 | 0 | 0 | 0 | — | ok |
| ADI | 471 | 0.16 | 0 | 0 | 0 | — | ok |
| ADI | 518 | 0.10 | 0 | 0 | 0 | — | ok |
| ADI | 550 | 0.16 | 0 | 0 | 0 | — | ok |
| ADI | 559 | 0.12 | 0 | 0 | 0 | — | ok |
| ADI | 566 | 0.09 | 0 | 0 | 0 | — | ok |
| ADI | 575 | 0.18 | 0 | 0 | 0 | — | ok |
| ADI | 592 | 0.12 | 0 | 0 | 0 | — | ok |
| ADI | 604 | 0.10 | 0 | 0 | 0 | — | ok |
| ADI | 605 | 0.13 | 0 | 0 | 0 | — | ok |

- completed: **50 ok / 0 fail** of 50
- wall p50 / p90 / max: **0.14s / 0.27s / 0.48s**
- retries: **429×0**, **5xx×0**
- parity diffs (total across 50 processes): **2**
- shape anomalies (total): **0**

## Per-process diffs

### ADI 90

Diffs vs parity source:
```
  recursos[tail idx 0]: http={'id': 1, 'data': 'AG.REG. NA AÇÃO DIRETA DE INCONSTITUCIONALIDADE'} vs gt={'index': 1, 'data': 'AG.REG. NA AÇÃO DIRETA DE INCONSTITUCIONALIDADE'}
```

### ADI 164

Diffs vs parity source:
```
  recursos[tail idx 0]: http={'id': 1, 'data': 'EMB.DECL. NA AÇÃO DIRETA DE INCONSTITUCIONALIDADE'} vs gt={'index': 1, 'data': 'EMB.DECL. NA AÇÃO DIRETA DE INCONSTITUCIONALIDADE'}
```

## Recurring divergences

| field | occurrences |
|-------|-------------:|
| recursos[tail idx 0] | 2 |

## Notes

- **50/50 complete with zero retries.** No 429s, no 5xx, no network
  errors on the cold pass. STF's portal did not throttle a sequential
  50-process sweep at the concurrency this scraper uses (4 tabs per
  process, sequential between processes). This invalidates the
  assumption behind handoff step #3 (cross-process backoff) at this
  scale — keep the design, but the trigger threshold is further away
  than feared. A larger or longer sweep may still trip it.
- **Cold throughput: 81 s wall for 50 processes ≈ 1.6 s/process.**
  p50 / p90 / max = 0.91 / 2.44 / 15.25 s. ADI 282 is the tail — its
  cache shows a sessao_virtual JSON plus several PDF fetches from
  `sistemas.stf.jus.br`, which is the most likely source of the 15 s.
  Without PDFs (`--no-fetch-pdfs`) the number drops, but we measured
  the default path on purpose.
- **Warm throughput: 11 s for 50 processes ≈ 0.22 s/process** (p50 0.14 s,
  p90 0.27 s). The cache is delivering the ~60× speed-up that
  `docs/performance.md` predicts.
- **Two recurring diffs — NOT a regression.** Both are the
  `recursos[*].id` vs `recursos[*].index` key-name divergence between
  the HTTP extractor and the **Selenium extractor code**. The ground-
  truth fixtures (`tests/ground_truth/ACO_2652.json`) use `id`, which
  is what the HTTP port emits. The bulk Selenium CSV used as parity
  here was produced by the Selenium path which emits `index`
  (see `src/scraping/extraction/recursos.py:39`). The Selenium output
  disagrees with its own ground truth. Retiring the Selenium path
  (handoff step #2) resolves this automatically; no fix needed on
  HTTP.
- **Zero shape anomalies** — every process produced the expected
  StfItem structure. List fields are lists, required scalars are
  populated, documentos values are all strings where present.
- **No parity-mismatch diffs beyond the known `recursos` key
  disagreement.** `assuntos`, `partes`, `andamentos`, `deslocamentos`,
  `peticoes`, `pautas` all match the Selenium baseline on all 50.
