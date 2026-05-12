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

Snapshot date: **2026-05-12** (post chain-delta re-run + HC 2020
outlier recovery + warehouse rebuild).

| year | width  | cases  | peças (bytes)              | peças (text)               | tier-A bytes               | tier-A URLs |
|-----:|-------:|-------:|----------------------------|----------------------------|----------------------------|------------:|
| 2026 |  4,001 |  3,099 | ✅ 4,701 / 4,711 = 99.8%   | ✅ 4,711 / 4,711 = 100%    | ✅ 4,660 / 4,670 = 99.8%   |     4,670 |
| 2025 | 16,200 | 13,365 | ✅ 24,365 / 24,488 = 99.5% | ✅ 24,210 / 24,488 = 98.9% | ✅ 24,176 / 24,298 = 99.5% |    24,298 |
| 2024 | 14,387 | 12,014 | ✅ 21,885 / 21,904 = 99.9% | ✅ 21,889 / 21,904 = 99.9% | ✅ 21,661 / 21,680 = 99.9% |    21,680 |
| 2023 | 12,644 | 11,129 | 🟡 14,456 / 21,453 = 67%   | ✅ 20,781 / 21,453 = 97%   | 🟡 14,231 / 21,186 = 67%   |    21,186 |
| 2022 | 13,057 | 10,824 | ✅ 20,208 / 20,209 = 99.99%| ✅ 20,208 / 20,209 = 99.99%| ✅ 20,013 / 20,013 = 100%  |    20,013 |
| 2021 | 14,508 |  9,305 | ✅ 13,886 / 14,455 = 96.1% | ✅ 13,914 / 14,455 = 96.3% | ✅ 13,614 / 14,067 = 96.8% |    14,067 |
| 2020 | 15,754 |  4,493 | 🟡 2,609 / 7,751 = 33.7%   | ❌ 1,448 / 7,751 = 18.7%   | 🟡 2,072 / 6,663 = 31.1%   |     6,663 |
| 2019 | 14,352 |    914 | ❌ 4 / 2,245 = 0.2%        | ❌ 26 / 2,245 = 1%         | ❌ 4 / 1,527 = 0.3%        |     1,527 |
| 2018 | 13,969 |    945 | ❌ 6 / 1,756 = 0.3%        | ❌ 16 / 1,756 = 1%         | ❌ 6 / 1,348 = 0.4%        |     1,348 |
| 2017 | 12,604 |  1,852 | ❌ 15 / 3,273 = 0.5%       | ❌ 26 / 3,273 = 1%         | ❌ 12 / 2,829 = 0.4%       |     2,829 |
| 2016 |  7,049 |  4,582 | ❌ 57 / 8,700 = 0.7%       | ❌ 364 / 8,700 = 4%        | ❌ 53 / 7,415 = 0.7%       |     7,415 |
| 2015 |  6,319 |  5,584 | ❌ 89 / 10,712 = 0.8%      | ❌ 371 / 10,712 = 3%       | ❌ 82 / 9,406 = 0.9%       |     9,406 |
| 2014 |  5,338 |  4,342 | ❌ 35 / 8,463 = 0.4%       | ❌ 131 / 8,463 = 2%        | ❌ 31 / 7,135 = 0.4%       |     7,135 |
| 2013 | (legacy fragment) |    511 | ❌ 3 / 1,279 = 0.2%   | ❌ 17 / 1,279 = 1%         | ❌ 3 / 930 = 0.3%          |       930 |

`width` is the STF-side case-id-space width for HC that year (from
`docs/process-space.md`); `cases` is what's on disk in the warehouse.

**2026-05-12 movements** (vs prior snapshot): HC 2024 text 80% → 99.9%
(anomaly closed by the delta re-run + warehouse rebuild, no targeted
retry needed). HC 2021 bytes/text 0.5%/1% → 96.1%/96.3% (chain v2 +
delta re-run). HC 2020 partial bump from outlier recovery (3 cached +
1 newly-refetched outlier OCR'd via local Tesseract; 4 lost — 3 orphan
URLs from the May 5-11 corpus deletion + 1 persistent STF-empty).
HC 2026 bytes 73% → 99.8% (incremental sweeps + recuperar drains).
HC 2025 / 2023 / 2022 essentially unchanged. **2013 is a new row** —
sparse legacy fragment of cases whose `data_protocolo_iso` fell in
2013 (likely re-distributed or re-classified cases); not a target.

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
uv run judex executar --csv <year-cases.csv> --retomar --prever
```

`--prever` exits before any HTTP and prints a deduped, cache-aware
forecast (PDFs to fetch, OCR cost, wall-time estimate) — the runner's
actual workload, not the warehouse's URL count.

## Backfill priority queue

Ordered by **case-JSON-walk fetch tail** (the runner's real-work
estimate), not by warehouse "% missing" (over-counts; see § drift).

The **2026 → 2021 ladder is now closed for peças** (all six years
≥96% on text after the 2026-05-12 chain-delta re-run + HC 2024
delta-driven anomaly closure). Remaining priorities are the older
case-id-space gaps and the lingering HC 2023 bytes-coverage hole.

1. **2023 bytes second pass** — text is 97% but bytes are only 67%
   (14,456 / 21,453). Likely just URL count drift between the bytes
   sweep and the most recent warehouse rebuild — a targeted
   `judex executar --csv` over the affected cases (or a
   `baixar-pecas` follow-up) should close the gap cheaply. Cost is
   small; this was *not* on the queue pre-2026-05-12 because the
   table snapshot from 2026-04-30 showed 70% as steady-state.
2. **2019, 2018, 2017 cases** — ~37k missing cases combined; three
   sequential year sweeps; closes the 2017–2022 hole. Followed by
   the matching peça sweeps (~13–15k URLs each, same shape as
   2024/2023/2022).
3. **2020 cases** — 4,493 / 15,754 widths on disk; ~11,300 missing.
   Outlier residual closed 2026-05-12 (4/8 oversized PDFs recovered
   via local Tesseract; 4 lost — see `current_progress.md` § Resolved
   2026-05-12). The real 2020 backfill is a fresh year-of-HC sweep,
   not residual recovery.
4. **2016, 2015, 2014 case re-scrapes** (mixed-coverage,
   content-stale) — `--full-range` re-scrapes, smaller marginal value
   than the missing-year sweeps; defer until 2017–2020 closes.
5. **Pre-2014** (paper-era, ≤47% density per
   `docs/process-space.md`) — not a near-term priority; lower yield
   per request. The 511 cases that surfaced in 2013 today are a
   legacy-fragment artifact, not a target.

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
