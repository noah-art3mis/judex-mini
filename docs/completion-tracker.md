# Per-year completion tracker (HC)

Reference table for HC corpus coverage: cases scraped, PDF bytes
downloaded, and text extracted — per case-protocolo year. Last
refreshed **2026-04-26** (post-2025 retry sweep direct-IP,
post-warehouse rebuild). Counters now drawn from `data/raw/pecas/`
(post `f4b5604` data reorg).

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
  against the set of `<sha1>.pdf.gz` filenames in `data/raw/pecas + data/derived/pecas-texto/`.
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
| 2025 | 16,200 | 13,365 | ✅ 16,926 / 24,414 = 69% | ✅ 23,735 / 24,414 = 97% | ✅ 16,686 / 24,174 = 69% |    24,174 |
| 2024 | 14,387 | 12,014 | ❌ 526 / 23,298 = 2%     | 🟡 6,720 / 23,298 = 29% (documentos only) | ❌ 382 / 21,680 = 2%   |    21,680 |
| 2023 | 12,644 | 11,129 | ❌ 73 / 22,831 = 0.3%    | 🟡 6,471 / 22,831 = 28% (documentos only) | ❌ 73 / 21,186 = 0.3%  |    21,186 |
| 2022 | 13,057 |  1,160 | ❌ 5 / 21,693 = 0.0%     | ❌ 5,628 / 21,693 = 26%  | ❌ 5 / 20,013 = 0.0%     |    20,013 |
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

## Cumulative cache (2026-04-26, post 2025-retry direct-IP)

- 48,284 `.pdf.gz` files (+234 from today's HC 2025 retry direct-IP)
- 64,606 `.txt.gz` files (extrair-pecas backfill in flight; corpus-wide)
- ~6.0 GB in `data/raw/pecas/`; text in `data/derived/pecas-texto/`
- Warehouse `pdfs` row count 64,606; built_at 2026-04-26, rebuild
  wall-clock 286.0s, 90,762 cases.

## Warehouse-vs-case-JSON drift (caveat for reading this table)

The "% bytes" columns above join warehouse URL rows against unique
on-disk sha1s — a many-to-one relationship, since `sessao_virtual[]`
fan-out duplicates URL→sha1 references in `pdfs_substantive`. The
warehouse view is correct as a corpus-quality metric ("do the cases
have known PDFs?") but **overstates the operational fetch tail** of
a sweep, because the runner dedupes by sha1 before issuing requests.

Tonight's HC 2025 retry made the drift visible: warehouse said
"7,488 substantive URLs missing"; case-JSON-walk dry-run said
"234 URLs to fetch"; the runner closed the job in 12 min on direct
IP with **0 failures and 234 fresh fetches landed**. A 33× over-count.

For sweep planning, the canonical "real fetch tail" estimate is:

```bash
uv run judex baixar-pecas --csv <year-cases.csv> --apenas-substantivas \
    --retomar --dry-run --nao-perguntar 2>&1 | grep -E "targets|disco|baixar"
```

Look at the "**a baixar:**" line — that's the deduped, cache-aware
URL count the runner would actually issue.

## Backfill priority queue

Ordered by **case-JSON-walk fetch tail** (the runner's real-work
estimate), not by warehouse "% missing" (over-counts; see § drift).

1. **2024 peça sweep** — case-JSON walk: **15,482 fresh URLs to
   fetch** (verified 2026-04-26 dry-run). ~13h direct-IP at 2s/req,
   or ~1–2h sharded with refreshed proxies.
2. **2023 peça sweep** — case-JSON walk: **15,318 fresh URLs**.
   Same shape as 2024.
3. **2022 cases** — only 1,160 / 13,057 case widths on disk;
   ~11,900 missing cases. Single sweep, ~25 min at 16-shard
   fresh-pool. Once cases land, 2022 peça population becomes
   enumerable.
4. **2019, 2018, 2017 cases** — ~37k missing cases combined; three
   sequential year sweeps; closes the 2017–2022 hole.
5. **2021, 2020, 2016, 2015, 2014 case re-scrapes** (mixed-coverage,
   content-stale) — `--full-range` re-scrapes, smaller marginal value
   than the missing-year sweeps; defer until 2017–2022 closes.
6. **Pre-2014** (paper-era, ≤47% density per
   `docs/process-space.md`) — not a near-term priority; lower yield
   per request.

**Recently completed:**
- ✅ **HC 2025 retry direct-IP** (2026-04-26): 234 new tier-A bytes
  landed in ~12 min monolithic on direct IP, **0 failures**. Closed
  the residual gap from the 2026-04-22/24 substantive resume. The
  pre-rebuild warehouse said "7,488 missing" — the runner's
  case-JSON walk said "234 to fetch", and the bytes confirmed.
  Lesson pinned: warehouse over-counts; use `--dry-run` for ops
  estimates.
- ❌ **HC 2025 retry sharded sweep** (2026-04-26, 2h10m, killed):
  16-shard fresh-pool launch against `config/proxies` (last
  refreshed 5 days prior). Every fresh-fetch attempt failed with
  `407 Proxy Authentication Required`; 144 ProxyError records
  in 2h, **zero new bytes landed**. Killed via `pkill -KILL -f
  baixar_pecas` (SIGTERM not respected — workers stuck in tenacity
  retry loop). Lesson: a 5-day-old proxy file should always be
  re-validated against a 1-URL `curl --proxy <one-line>` smoke
  test before fanning out to N shards. The 2h10m of wasted
  wall-clock would have caught the 407 in 30s. Forensic record
  preserved at `runs/active/2026-04-26-hc-pecas-2025-retry/`.
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
PDF_DIR = 'data/raw/pecas'
TXT_DIR = 'data/derived/pecas-texto'
pdf_sha1s = {n[:-7] for n in os.listdir(PDF_DIR) if n.endswith('.pdf.gz')}
txt_sha1s = {n[:-7] for n in os.listdir(TXT_DIR) if n.endswith('.txt.gz')}

c = duckdb.connect('data/derived/warehouse/judex.duckdb', read_only=True)
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
