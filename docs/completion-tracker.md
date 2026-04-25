# Per-year completion tracker (HC)

Reference table for HC corpus coverage: cases scraped, PDF bytes
downloaded, and text extracted — per case-protocolo year. Last
refreshed **2026-04-24** (post-2025 substantive sweep, post-extraction,
post-warehouse rebuild).

## Status legend

- ✅ ≥95% content-fresh / landed
- 🔄 actively in flight
- 🟡 partial / older scrape, content-stale
- ❌ not started or sparse-on-disk

## Sources

- **cases** — warehouse `cases` row count grouped by
  `year(data_protocolo_iso)` (cases with NULL protocolo dates — ~200
  for 2017 — don't appear in the per-year count but do exist on disk).
- **peças (bytes)** — join of `pdfs_substantive` view's `sha1` column
  against the set of `<sha1>.pdf.gz` filenames in `data/cache/pdf/`.
  This measures what the scraper has actually downloaded.
- **peças (text)** — join of the same `sha1` column against
  `<sha1>.txt.gz` filenames. This measures what's usable for
  content-level analysis (can include pre-split-era legacy extractions
  whose bytes are no longer on disk — see § Cache integrity caveat).
- **denominator** — the `pdfs_substantive` view: tier-A (DECISÃO
  MONOCRÁTICA, INTEIRO TEOR DO ACÓRDÃO, MANIFESTAÇÃO DA PGR, and
  sessão-virtual Voto/Relatório) plus tier-B (DESPACHO). Tier-C
  boilerplate (certidões, despachos ordinatórios) is not counted.

## Table

| year | width  | cases  | peças (bytes)            | peças (text)              | tier-A bytes      | tier-A URLs |
|-----:|-------:|-------:|--------------------------|---------------------------|-------------------|------------:|
| 2026 |  4,001 |  3,099 | 🟡 3,722 / 5,078 = 73%   | 🟡 1,315 / 5,078 = 26%   | 🟡 3,319 / 4,670 = 71%  |     4,670 |
| 2025 | 16,200 | 13,365 | ✅ 16,685 / 24,414 = 68% | ✅ 23,735 / 24,414 = 97% | ✅ 16,492 / 24,174 = 68% |    24,174 |
| 2024 | 14,387 | 12,014 | ❌ 526 / 23,298 = 2%     | 🟡 6,720 / 23,298 = 29% (documentos only) | ❌ 382 / 21,680 = 2%   |    21,680 |
| 2023 | 12,644 | 11,129 | ❌ 73 / 22,831 = 0.3%    | 🟡 6,471 / 22,831 = 28% (documentos only) | ❌ 69 / 21,186 = 0.3%  |    21,186 |
| 2022 | 13,057 |  1,160 | ❌ 5 / 2,017 = 0.2%      | ❌ 116 / 2,017 = 6%      | ❌ 5 / 1,652 = 0.3%      |     1,652 |
| 2021 | 14,508 |  7,423 | ❌ 61 / 11,605 = 0.5%    | ❌ 104 / 11,605 = 1%     | ❌ 59 / 10,252 = 0.6%    |    10,252 |
| 2020 | 15,754 |  4,207 | ❌ 41 / 6,775 = 0.6%     | ❌ 65 / 6,775 = 1%       | ❌ 39 / 5,687 = 0.7%     |     5,687 |
| 2019 | 14,352 |    914 | ❌ 4 / 2,245 = 0.2%      | ❌ 26 / 2,245 = 1%       | ❌ 4 / 1,527 = 0.3%      |     1,527 |
| 2018 | 13,969 |    945 | ❌ 6 / 1,756 = 0.3%      | ❌ 16 / 1,756 = 1%       | ❌ 6 / 1,348 = 0.4%      |     1,348 |
| 2017 | 12,604 |  1,852 | ❌ 15 / 3,273 = 0.5%     | ❌ 26 / 3,273 = 1%       | ❌ 12 / 2,829 = 0.4%     |     2,829 |
| 2016 |  7,049 |  4,582 | ❌ 57 / 8,700 = 0.7%     | ❌ 364 / 8,700 = 4%      | ❌ 53 / 7,415 = 0.7%     |     7,415 |
| 2015 |  6,319 |  5,584 | ❌ 89 / 10,712 = 0.8%    | ❌ 371 / 10,712 = 3%     | ❌ 82 / 9,406 = 0.9%     |     9,406 |
| 2014 |  5,338 |  4,342 | ❌ 35 / 8,463 = 0.4%     | ❌ 131 / 8,463 = 2%      | ❌ 31 / 7,135 = 0.4%     |     7,135 |

`width` is the STF-side case-id-space width for HC that year (from
`docs/process-space.md`); `cases` is what's on disk in the warehouse.

## Cache integrity caveat

The four-file cache quartet (`.pdf.gz` / `.txt.gz` /
`.elements.json.gz` / `.extractor`) is not internally consistent:

| file              |   count |
|-------------------|--------:|
| `.pdf.gz`         |  48,050 |
| `.txt.gz`         |  49,406 |
| `.extractor`      |  31,410 |
| `.elements.json.gz` |    34 |

**17,954** sha1s have both `.pdf.gz` and `.txt.gz` (up from 11,214
pre-extraction). **30,096** have bytes only; **31,452** have text
only. The text-only population is pre-`baixar-pecas`/`extrair-pecas`-
split legacy: an older pipeline extracted text on-the-fly during
download without persisting bytes. Functionally usable content =
bytes ∪ text = 79,502 distinct sha1s, larger than either file count
alone. When deciding whether to re-fetch, prefer the union (text is
still usable for analysis even with bytes gone).

This is why the tracker splits "peças (bytes)" from "peças (text)":
bytes is what the in-flight sweep is moving; text is what analysis
can read.

## Mid-sweep filter change (2026-04-23) and resume (2026-04-24)

Commit `e7ce6af` (2026-04-23) made `--apenas-substantivas` the
default for `baixar-pecas` / `extrair-pecas`, dropping tier-C tipos
from every sweep. The 2025 sweep launched 2026-04-22 11:54 BRT
against the full-tipos target list (`50,526 PDFs`); we paused it,
landed the filter, and resumed under the new default at
2026-04-24 09:32 BRT. The resume targeted 17,590 substantive URLs,
of which 10,431 were already cached and 7,159 were fetched fresh
in 5h 14m wall-clock with **zero failures** at 0.93 tgt/s sustained
on a single direct IP. 2025 substantive bytes coverage went from
**39% → 69%**.

## Cumulative cache (2026-04-24, post-sweep + post-extraction)

- 48,050 `.pdf.gz` files (+7,159 from today's substantive sweep)
- 49,406 `.txt.gz` files (+6,740 from today's `extrair-pecas
  --provedor pypdf`; 419 corrupt-bytes parse failures — pre-existing
  data-quality tail, not today's sweep)
- 5.9 GB total in `data/cache/pdf/`
- Warehouse `n_pdfs` manifest now 49,406 (was 42,666); `built_at`
  2026-04-24 22:50, rebuild wall-clock 309.7s, commit `e7ce6af`.

## Backfill priority queue

Ordered by coverage gap, not by size — HC 2022 is small but the
biggest near-zero-coverage hole in the 2017–2022 backfill gap.

1. **2022** (~11,900 missing cases, near-zero coverage) — single
   arm-B-sized sweep, ~25 min at 16-shard fresh-pool.
2. **2019, 2018, 2017** (~37k missing cases combined) — three
   sequential year sweeps; would close the 2017–2022 hole.
3. **2023 / 2024 peça sweeps** — each year has ~21k tier-A URLs with
   ≤2% bytes coverage. Separate WAF counter on `sistemas.stf.jus.br`
   allows 16 shards safely; refresh proxies before launch (H6).
4. **2025 peça sweep cleanup** — bytes coverage now at 69% / tier-A
   at 68%. The remaining ~30% is URLs the original pre-filter sweep
   marked failed/skipped before pausing; need a `--retentar-de`
   pass to close fully.
5. **2021, 2020, 2016, 2015, 2014 case re-scrapes** (mixed-coverage,
   content-stale) — `--full-range` re-scrapes, smaller marginal value
   than the missing-year sweeps; defer until 2017–2022 closes.
6. **Pre-2014** (paper-era, ≤47% density per
   `docs/process-space.md`) — not a near-term priority; lower yield
   per request.

**Recently completed:**
- ✅ **2025 peça sweep main pass** (2026-04-24): 7,159 new tier-A/B
  PDFs landed in 5h 14m at 0.93 tgt/s, 0 failures, direct-IP. Took
  2025 substantive bytes coverage from 39% → 68%.
- ✅ **2025 `extrair-pecas --provedor pypdf`** (2026-04-24): 6,740
  new `.txt.gz` files extracted in ~6 min. 2025 substantive text
  coverage is now 97%.
- ✅ **Warehouse builder streaming refactor** (2026-04-24): replaced
  the list-accumulation scan (peaked at ~11 GB total-vm and
  OOM-killed on WSL2) with a chunked stream that flushes every 5,000
  cases into DuckDB. Full HC corpus rebuild now fits in <1 GB RAM
  and completes in ~5 min. Regression guard:
  `tests/unit/test_build_warehouse.py::test_chunked_scan_preserves_counts_and_rates`.

## How to refresh this table

```bash
uv run --no-project python <<'PY'
import os, duckdb
base = 'data/cache/pdf'
pdf_sha1s = {n[:-7] for n in os.listdir(base) if n.endswith('.pdf.gz')}
txt_sha1s = {n[:-7] for n in os.listdir(base) if n.endswith('.txt.gz')}

c = duckdb.connect('data/warehouse/judex.duckdb', read_only=True)
c.execute('CREATE TEMP TABLE disk_bytes (sha1 VARCHAR)')
c.executemany('INSERT INTO disk_bytes VALUES (?)', [(s,) for s in pdf_sha1s])
c.execute('CREATE TEMP TABLE disk_txt (sha1 VARCHAR)')
c.executemany('INSERT INTO disk_txt VALUES (?)', [(s,) for s in txt_sha1s])

rows = c.execute("""
WITH y AS (
  SELECT processo_id, year(data_protocolo_iso) AS ano
    FROM cases WHERE classe='HC' AND data_protocolo_iso IS NOT NULL
)
SELECT y.ano,
       COUNT(*) AS subst_urls,
       SUM(CASE WHEN db.sha1 IS NOT NULL THEN 1 ELSE 0 END) AS bytes_landed,
       SUM(CASE WHEN dt.sha1 IS NOT NULL THEN 1 ELSE 0 END) AS text_extracted,
       SUM(CASE WHEN s.tier = 'A' THEN 1 ELSE 0 END) AS tier_a,
       SUM(CASE WHEN s.tier = 'A' AND db.sha1 IS NOT NULL THEN 1 ELSE 0 END) AS tier_a_bytes
  FROM y
  JOIN pdfs_substantive s USING (processo_id)
  LEFT JOIN disk_bytes db ON db.sha1 = s.sha1
  LEFT JOIN disk_txt dt ON dt.sha1 = s.sha1
 WHERE s.classe = 'HC'
 GROUP BY y.ano ORDER BY y.ano DESC
""").fetchall()
for r in rows:
    print(r)
PY
```
