# Per-year completion tracker (HC)

Reference table for HC corpus coverage: cases scraped, PDF bytes
downloaded, and text extracted — per case-protocolo year. Last
refreshed **2026-04-30** (post HC 2024 + 2023 + 2022 peça backfill +
warehouse rebuild on the new memory-capped builder). Counters drawn
from `data/raw/pecas/` + `data/derived/pecas-texto/` (post `f4b5604`
data reorg).

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

| year | width  | cases  | peças (bytes)             | peças (text)              | tier-A bytes              | tier-A URLs |
|-----:|-------:|-------:|---------------------------|---------------------------|---------------------------|------------:|
| 2026 |  4,001 |  3,099 | 🟡 3,722 / 5,078 = 73%    | 🟡 1,315 / 5,078 = 26%    | 🟡 3,319 / 4,670 = 71%    |     4,670 |
| 2025 | 16,200 | 13,365 | ✅ 16,926 / 24,414 = 69%  | ✅ 23,735 / 24,414 = 97%  | ✅ 16,686 / 24,174 = 69%  |    24,174 |
| 2024 | 14,387 | 12,014 | ✅ 15,598 / 22,267 = 70%  | 🟡 17,843 / 22,267 = 80%  | ✅ 15,011 / 21,680 = 69%  |    21,680 |
| 2023 | 12,644 | 11,129 | ✅ 15,044 / 21,458 = 70%  | ✅ 20,767 / 21,458 = 97%  | ✅ 14,772 / 21,186 = 70%  |    21,186 |
| 2022 | 13,057 | 10,824 | ✅ 14,591 / 20,224 = 72%  | ✅ 20,068 / 20,224 = 99%  | ✅ 14,380 / 20,013 = 72%  |    20,013 |
| 2021 | 14,508 |  7,562 | ❌ 61 / 11,894 = 0.5%     | ❌ 132 / 11,894 = 1%      | ❌ 59 / 10,443 = 0.6%     |    10,443 |
| 2020 | 15,754 |  4,208 | ❌ 41 / 6,791 = 0.6%      | ❌ 65 / 6,791 = 1%        | ❌ 39 / 5,701 = 0.7%      |     5,701 |
| 2019 | 14,352 |    914 | ❌ 4 / 2,245 = 0.2%       | ❌ 26 / 2,245 = 1%        | ❌ 4 / 1,527 = 0.3%       |     1,527 |
| 2018 | 13,969 |    945 | ❌ 6 / 1,756 = 0.3%       | ❌ 16 / 1,756 = 1%        | ❌ 6 / 1,348 = 0.4%       |     1,348 |
| 2017 | 12,604 |  1,852 | ❌ 15 / 3,273 = 0.5%      | ❌ 26 / 3,273 = 1%        | ❌ 12 / 2,829 = 0.4%      |     2,829 |
| 2016 |  7,049 |  4,582 | ❌ 57 / 8,700 = 0.7%      | ❌ 364 / 8,700 = 4%       | ❌ 53 / 7,415 = 0.7%      |     7,415 |
| 2015 |  6,319 |  5,584 | ❌ 89 / 10,712 = 0.8%     | ❌ 371 / 10,712 = 3%      | ❌ 82 / 9,406 = 0.9%      |     9,406 |
| 2014 |  5,338 |  4,342 | ❌ 35 / 8,463 = 0.4%      | ❌ 131 / 8,463 = 2%       | ❌ 31 / 7,135 = 0.4%      |     7,135 |

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

## Cumulative cache (2026-04-30, post HC 2022 extract close-out)

- 94,091 `.pdf.gz` files (+15,007 from HC 2022 baixar-pecas, +15,482
  from HC 2024, +15,318 from HC 2023 across the four-day cycle).
- 105,821 `.txt.gz` files (+14,865 from HC 2022 extract; matches the
  `extrair-pecas` report ok count exactly).
- Warehouse `pdfs` row count 105,821; built_at 2026-04-30 17:45 BRT,
  rebuild wall-clock 530s on the memory-capped builder
  (`SET memory_limit='800MB'` + `_CHUNK_SIZE=1500`), 90,763 cases,
  3.02 GB on disk. The previous default (5000-case chunks, no
  DuckDB memory cap) OOM-killed on this dataset once the `.txt.gz`
  cache passed ~100k files — text payload in `andamentos.link_text`
  + Arrow conversion peak crossed the WSL2 3.8 GB ceiling.

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

The **2025 → 2022 ladder is now closed for peças** (all four years
≥97% on text via direct-IP overnight sweeps). Remaining priorities
are the older case-id-space gaps and HC 2024's 80% text plateau.

1. **2024 extract second pass** — text coverage is 80% (17,843 /
   22,267) vs the 97–99% achieved on 2023 and 2022. Investigate
   why ~3k 2024 PDFs didn't extract cleanly (provider failures,
   RTF mistypes, scanned originals?). Likely a focused
   `extrair-pecas --csv` retry on 2024 with a different provider
   tier (chandra / mistral) covers the gap; cost is small. See
   `runs/active/2026-04-27-*` for the original extract artifacts.
2. **2019, 2018, 2017 cases** — ~37k missing cases combined; three
   sequential year sweeps; closes the 2017–2022 hole. Followed by
   the matching peça sweeps (~13–15k URLs each, same shape as
   2024/2023/2022).
3. **2021 cases** — 7,562 / 14,508 widths on disk; ~6,950 missing.
   Single sweep at 16-shard fresh-pool; once cases land, peça
   sweep follows.
4. **2020 cases** — 4,208 / 15,754 widths on disk; ~11,500 missing.
   Same shape as 2021.
5. **2016, 2015, 2014 case re-scrapes** (mixed-coverage,
   content-stale) — `--full-range` re-scrapes, smaller marginal value
   than the missing-year sweeps; defer until 2017–2021 closes.
6. **Pre-2014** (paper-era, ≤47% density per
   `docs/process-space.md`) — not a near-term priority; lower yield
   per request.

**Recently completed:**
- ✅ **HC 2022 peça sweep direct-IP** (2026-04-30 00:21 → 13:15 BRT,
  ~13h overnight + tail closeout): main pass landed **15,007 fresh
  PDFs** (15,007 ok + 7 cached, 0 fails) on a single direct IP.
  Same shape as HC 2024 / HC 2023 — direct-IP held WAF reputation
  cleanly all night with no SSL-EOF tail-storm intervention needed.
  Took 2022 substantive bytes coverage from **0% → 72%**.
- ✅ **HC 2022 `extrair-pecas --provedor pypdf`** (2026-04-30 14:48 →
  16:17 BRT, 1h28m): 14,865 ok / 142 unknown_type / 133 no_bytes /
  7 cached out of 15,147 targets. 98.1% extraction rate. Took 2022
  substantive text coverage from **26% → 99%** — closes the
  2025–2022 four-year ladder.
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
