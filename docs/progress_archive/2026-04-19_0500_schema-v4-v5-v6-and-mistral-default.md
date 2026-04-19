# Current progress — judex-mini

Branch: `main`. Tip: `290c99c` (pushed:
`1ae0920` refactor drop-html-field, `290c99c` docs archive + cron
monitoring session). Prior cycle archived at
[`docs/progress_archive/2026-04-18_2030_steady-state-monitoring-plus-economics.md`](progress_archive/2026-04-18_2030_steady-state-monitoring-plus-economics.md)
— 8.5 h cron-monitored backfill, HC density map reconciled, Selenium
bake-off, bandwidth economics.

**Status as of 2026-04-19 ~04:00 UTC: schema bumped twice — v4
(extractor provenance + documentos list) and v5 (andamento link
unified with Documento).** Mistral is now the default OCR provider
everywhere (`reextract_unstructured.py --provider mistral`, Portuguese
CLI `--provedor`); `--force` bypasses the monotonic cache guard so
provider switches actually overwrite. Every ground-truth fixture
(7 canonical + 2 candidates) regenerated from HTML cache as bare-dict
v5. All v4-compat `link_descricao` fallbacks removed from live code —
the renormalizer (`scripts/renormalize_cases.py`) is v4→v5 aware and
bumps existing production JSONs on next run. Prior tier-0 (2026)
smoke test (917/917 filter_skip=True, zero WAF events) and per-case
tar.gz HTML cache migration are still on the runway. Full unit suite
**328 passed** (up from 298 pre-v4).

Prior HC-backfill context: 4-shard full-range backfill (11.6 h this
cycle + 8.5 h prior = 20.1 h) stopped cleanly at 2026-04-18 20:57 UTC.
Final state 54 841 ok / 17 805 fail (12 real fails, 17 793
filter-skip), zero WAF events. Run archived at
`runs/archive/2026-04-17-hc-full-backfill-sharded/`; consolidated
REPORT at [`docs/reports/2026-04-17-hc-full-backfill-sharded.md`](reports/2026-04-17-hc-full-backfill-sharded.md).
Year-priority launcher + gap-CSV generator landed; 8-shard, 80-session
pipeline validated on tier-0.

Single live file covering the **active task's lab notebook**
(plan / expectations / observations / decisions) and the **strategic
state** across work-sessions (what landed, what's in flight, what's
next, known limitations, operational reference). Convention at
`CLAUDE.md § Progress tracking`. Archive to
`docs/progress_archive/YYYY-MM-DD_HHMM_<slug>.md` when the active
task closes out or the file grows past ~500 lines.

For *conceptual* knowledge (how the portal works, how rate limits
behave, class sizes, perf numbers, where data lives), read:

- [`docs/data-layout.md`](data-layout.md) — where files live + the three stores.
- [`docs/stf-portal.md`](stf-portal.md) — URL flow, auth triad, field→source map.
- [`docs/rate-limits.md`](rate-limits.md) — WAF behavior, validated defaults, robots.txt posture.
- [`docs/process-space.md`](process-space.md) — HC/ADI/RE ceilings + density.
- [`docs/performance.md`](performance.md) — HTTP-vs-Selenium numbers, caching as the real lever.

## Working conventions

- **`analysis/`** — git-ignored scratch for this-session exploration (marimo notebooks, one-off scripts, raw JSON dumps). Safe to fill freely.
- **All non-trivial arithmetic via `uv run python -c`** — never mental math. See `CLAUDE.md § Calculations`.
- **Sweeps write a directory**, not a file. Layout in [`docs/data-layout.md § Sweep run artifacts`](data-layout.md#sweep-run-artifacts).

---

# Active task — lab notebook

## Task

**Execute the year-priority gap-sweep successor plan.** The full-range
4-shard backfill was stopped cleanly at 20:44 UTC (12 real fails across
72 646 records, zero WAF events) and archived. The successor plan
(`docs/hc-backfill-extension-plan.md`) switches to one-year-at-a-time,
4-shard-per-year, newest-first, gap-filtered CSVs. 14 tiers queued:
2026 → 2013 (paper era explicitly out of scope). Estimated ~39.5 h
total wall across 109 042 uncaptured IDs. Tier-0 (2026, 917 IDs,
~18 min) is the launcher smoke test.

## Plan

1. **Fire tier-0 (2026) as launcher smoke test.** Validates the
   gap-CSV generator + year-sharded launcher end-to-end. Low-risk:
   917 IDs, ~18 min wall.
2. **Inspect tier-0 output.** Confirm 4 shards spun up on disjoint
   proxy pools, `shards.pids` written, `driver.log` healthy, final
   ok-rate >= 0.8 on the catch-up slice.
3. **Promote tier-0 REPORT** to `docs/reports/`, archive the run,
   then launch tier-1 (2025, ~2.5 h).
4. **Sequential tiers 2 → 13** with cron monitoring between. Each
   tier's gap CSV is regenerated at launch (captures from the
   previous tier shrink the next tier's gap — technically `--resume`
   handles this but gap-filtered CSV is cleaner).
5. **Post-queue: consolidated REPORT across tiers 0–13**, updates to
   `docs/performance.md` / `docs/rate-limits.md`, and next-class
   decision (ADI vs RE) per carried-forward next-steps.

## Expectations / hypotheses

**H1 (expected).** Tier-0 smoke test completes in 15–25 min with
>= 0.8 ok rate, zero 403/429/5xx, and `filter_skip=False` NoIncidente
count in single digits. Gap-CSV generator produces ~5 000–10 000 row
CSVs per modern-era year, rising to ~13 000 for the worst-captured
years (2018, 2019, 2022, 2023, 2024).

**H0 (would falsify).** Tier-0 fails with a script error (gap CSV
malformed, launcher can't find proxy pool, `run_sweep.py` rejects
the CSV), OR ok-rate < 0.5 (suggesting stale `hc_calendar` anchors
sending us to a dead zone), OR a 403/429/5xx class appears (WAF
re-engaging on concentrated ID ranges). Any of these halts the queue
before tier-1.

**H2 (unexpected).** Per-year 4-shard throughput materially exceeds
46 ok/min aggregate because all 4 shards stay in "hot" territory
(no shard stuck in a dead zone like paper-era shard-3 was). Would
suggest future non-HC sweeps can budget tighter walls. Confirmed by
tier-1 or tier-2 wall < 80 % of table estimate.

## Observations

_(append-only log. UTC timestamps.)_

- **2026-04-18 20:30 UTC — session archived, fresh file seeded.**
  Prior 8.5 h cron-monitored session (12:12 → 20:23 UTC) archived
  to `docs/progress_archive/2026-04-18_2030_steady-state-monitoring-plus-economics.md`.
  Carries the full density map / throughput progression / Selenium
  bake-off record. Workers still running at original PIDs
  (4719/4720/4721/4722); cron unchanged.

- **2026-04-18 22:56 UTC — per-bucket capture and scan-coverage
  snapshot** (25 k symmetric buckets). Two complementary views:
  capture = real HCs obtained vs G-probe-estimated real HCs; scan
  = CSV rows attempted (ok + dead-zone fails) of the 25 k-row
  bucket.

  ```
  HC CAPTURE PROGRESS — what we have vs what exists (G-probe estimate)
  ======================================================================================
  bucket              captured / estimated real      progress bar                      %
  --------------------------------------------------------------------------------------
    0,000.. 24,999         5 /  8,266 real            [░░░░░░░░░░░░░░░░░░░░]    0.1%
   25,000.. 49,999       184 / 10,000 real            [░░░░░░░░░░░░░░░░░░░░]    1.8%
   50,000.. 74,999     9,273 / 21,675 real            [████████░░░░░░░░░░░░]   42.8%
   75,000.. 99,999         0 / 21,675 real            [░░░░░░░░░░░░░░░░░░░░]    0.0%
  100,000..124,999     2,895 / 21,675 real            [██░░░░░░░░░░░░░░░░░░]   13.4%
  125,000..149,999    12,997 / 21,675 real            [████████████░░░░░░░░]   60.0%
  150,000..174,999     1,858 / 23,325 real            [█░░░░░░░░░░░░░░░░░░░]    8.0%
  175,000..199,999     7,136 / 23,325 real            [██████░░░░░░░░░░░░░░]   30.6%
  200,000..224,999     4,925 / 23,325 real            [████░░░░░░░░░░░░░░░░]   21.1%
  225,000..249,999     1,750 / 23,325 real            [█░░░░░░░░░░░░░░░░░░░]    7.5%
  250,000..270,999    12,193 / 18,202 real            [█████████████░░░░░░░]   67.0%
  --------------------------------------------------------------------------------------
  ALL (0..270994)     53,216 / 216,468 real           [████░░░░░░░░░░░░░░░░]   24.6%
  ```

  ```
  HC SCAN COVERAGE — CSV rows attempted (ok + dead-zone fails)
  ======================================================================================
  bucket              attempts / 25 k rows    scan bar                                %
  --------------------------------------------------------------------------------------
    0,000.. 24,999         5 / 25,000 rows     [░░░░░░░░░░░░░░░░░░░░]    0.0%
   25,000.. 49,999       327 / 25,000 rows     [░░░░░░░░░░░░░░░░░░░░]    1.3%
   50,000.. 74,999    18,251 / 25,000 rows     [██████████████░░░░░░]   73.0%
   75,000.. 99,999         0 / 25,000 rows     [░░░░░░░░░░░░░░░░░░░░]    0.0%
  100,000..124,999     3,395 / 25,000 rows     [██░░░░░░░░░░░░░░░░░░]   13.6%
  125,000..149,999    14,232 / 25,000 rows     [███████████░░░░░░░░░]   56.9%
  150,000..174,999     1,858 / 25,000 rows     [█░░░░░░░░░░░░░░░░░░░]    7.4%
  175,000..199,999     7,979 / 25,000 rows     [██████░░░░░░░░░░░░░░]   31.9%
  200,000..224,999     5,568 / 25,000 rows     [████░░░░░░░░░░░░░░░░]   22.3%
  225,000..249,999     1,750 / 25,000 rows     [█░░░░░░░░░░░░░░░░░░░]    7.0%
  250,000..270,999    16,908 / 20,995 rows     [████████████████░░░░]   80.5%
  ```

  Capture-vs-scan divergence reveals shard geography:

  - **50k–74k: scan 73 % but capture 43 %** — shard-3 has checked
    73 % of the row range but captured only 43 % of the real cases
    there; the densest lower half of the bucket is still ahead of
    its cursor.
  - **125k–149k: scan 57 %, capture 60 %** — density > prediction
    here, so capture leads scan.
  - **250k–270k: scan 80 %, capture 67 %** — shard-0 has descended
    most of its range; the remaining 20 % scan will yield fewer
    real cases because the top end is "reserved but unfiled"
    numbers (270 995..273 000).
  - **Untouched buckets** (`0k–24k`, `75k–99k`, `25k–49k`) are the
    three shards' forward destinations; at current 0.4 proc/s
    shard-3, the final zone won't get hit for ~50 h.

  **Corrected remaining-HC estimate:** 216 468 − 53 216 =
  **163 252 real HCs to go**, not the ~170 k used in earlier
  rough math. At ~46 ok/min aggregate that's ~59 h of wall clock.
  **Corrected ETA:** ~59 h instead of ~63 h.

- **2026-04-18 23:10 UTC — empirical date range per 25 k bucket
  + sequentiality check.** Scanned 53 922 captured HC case JSONs
  for `data_protocolo`, bucketed by `processo_id`, compared
  against `src.utils.hc_calendar.id_to_date` estimates.

  | bucket              | n      | earliest    | median      | latest      |
  |---------------------|--------|-------------|-------------|-------------|
  |   0k..  24,999      | 0      | (untouched) | (untouched) | (untouched) |
  |  25k..  49,999      | 240    | 1969-01-07  | 1972-03-02  | 1979-04-26  |
  |  50k..  74,999      | 9 273  | ~1979*      | 1981-04-24  | 2000-06-12  |
  |  75k..  99,999      | 0      | (untouched) | (untouched) | (untouched) |
  | 100k..124,999       | 3 455  | 2013-06-06  | 2014-06-15  | 2014-10-27  |
  | 125k..149,999       | 12 997 | 2014-10-27  | 2015-12-22  | 2017-10-26  |
  | 150k..174,999       | 1 859  | 2017-11-07  | 2018-07-17  | 2019-08-02  |
  | 175k..199,999       | 7 172  | 2019-12-19  | 2020-12-22  | 2021-04-05  |
  | 200k..224,999       | 4 927  | 2021-04-05  | 2021-06-04  | 2023-02-01  |
  | **225k..249,999**   | 1 753  | **2023-07-03** | 2023-08-07 | **2024-10-03** |
  | **250k..270,999**   | 12 246 | **2025-05-09** | 2025-10-16 | **2026-04-17** |

  *The `50k..74,999` bucket has one record dated `0198-02-26` —
  STF data-entry typo (missing leading `1` on `1998`). Earliest
  real filing in the bucket is ~1979.

  **Priority ranking for newest-first sharding** (Bolsonaro + Lula-3
  era at top):

  1. **250k..270,999** — 2025-05 → 2026-04 — *last 12 months*
  2. **225k..249,999** — 2023-07 → 2024-10 — *prior 18 months*
  3. **200k..224,999** — 2021-04 → 2023-02
  4. **175k..199,999** — 2019-12 → 2021-04
  5. **150k..174,999** — 2017-11 → 2019-08
  6. **125k..149,999** — 2014-10 → 2017-10
  7. **100k..124,999** — 2013-06 → 2014-10

  **Sequentiality finding.** HC numbers are **98.2 % monotonic**
  in time. Sliding-window check over 53 922 pairs (window size
  100): 1.78 % of comparisons are out-of-order (later HC number
  with earlier `data_protocolo` than a recent neighbour). The
  inversions are structural — STF occasionally assigns numbers
  ahead of filing (reservas, distribuição em lote) and sometimes
  backdates. Safe to use HC-id as a **year-level temporal proxy**;
  unsafe at day-level resolution.

  **hc_calendar anchor drift.** The pre-computed anchors in
  `src/utils/hc_id_to_date.json` (9 897 anchors) estimate the
  bucket midpoints ~6–18 months off the empirical median. Low
  priority refresh post-backfill: rebuild the anchor file from
  the completed corpus's (processo_id, data_protocolo) pairs —
  the 50 k+ captured HCs give a much tighter anchor set than the
  original build used.

  **Data-quality filter candidate** for downstream analysis:
  `year < 1950 → flag as suspect` (catches the 0198 typo class).

- **2026-04-18 23:20 UTC — year-level granularity check + capture
  histogram.** `data_protocolo` is DD/MM/YYYY so year bucketing is
  trivial. Full per-year count (1950+ filter, n = 54 048):

  ```
   year       n     HC id range in year           capture bar
  -----------------------------------------------------------------------
   1965       1     53,315..53,315                [░]
   1968       1     59,260..59,260                [░]
   1969       1     49,591..49,591                [░]
   1971      58     49,517..49,711                [░]
   1972     646     49,622..51,050                [██]
   1973     740     50,016..53,546                [███]
   1974     597     50,737..55,432                [██]
   1975     586     53,166..55,325                [██]
   1976     454     53,385..66,859 (spread 13k)   [█]
   1977     462     55,125..56,314                [██]
   1978     419     55,615..56,837                [█]
   1979     402     49,962..59,043 (spread  9k)   [█]
   1980     422     57,566..60,235                [█]
   1981     391     54,564..64,933 (spread 10k)   [█]
   1982     365     59,193..61,572                [█]
   1983     483     60,547..62,047                [██]
   1984     604     51,916..64,402 (spread 12k)   [██]
   1985     460     59,946..63,703                [██]
   1986     510     62,207..64,962                [██]
   1987     477     64,503..65,912                [██]
   1988     612     63,107..67,192                [██]
   1989     441     61,071..67,888                [█]
   1990     359     67,760..68,250                [█]
   1992..2000      <15/yr — capture gap at shard-2/3 boundary
   2001..2012       0 — untouched (shard-2 territory, cursor at 121k)
   2013     511     118,201..118,839              [██]
   2014   3,955     121,513..126,119              [█████████████████]
   2015   5,584     126,120..132,438              [████████████████████████]
   2016   4,582     132,439..139,705              [███████████████████]
   2017   1,852     139,487..150,000              [████████]
   2018     945     158,709..159,708              [████]
   2019     914     172,910..180,000              [███]
   2020   3,889     187,634..196,281              [████████████████]
   2021   7,423     196,282..210,000              [████████████████████████████████]
   2022     817     216,670..217,669              [███]
   2023     884     224,531..230,999              [███]
   2024     870     238,695..246,930              [███]
   2025   9,184     255,998..267,137              [████████████████████████████████████████]
   2026   3,099     267,138..271,139              [█████████████]
  -----------------------------------------------------------------------
  TOTAL 54,048 captured HCs, year 1965 → 2026
  ```

  **Coverage interpretation:**
  - **1971–1990 well-sampled** (shard-3 HC 50k–68k territory,
    ~400–800/yr captured each).
  - **1991–2000 very sparse** (1–14/yr) — these HCs live around
    HC 68k–75k, the boundary between shard-3 and shard-2;
    neither has fully descended through yet.
  - **2001–2012 empty** — HC 75k–118k is shard-2's untouched tail
    (cursor currently at 121k).
  - **2013–2026 well-sampled** — shards 0/1/2 have been in this
    range the entire session.

  **Interesting year effects:**
  - **Per-year HC-id spread decouples from time pre-1990**: 9k–13k
    HC range per year (paper era numbering was non-sequential).
    Post-2013: 1k–10k range per year. Matches the 98.2 %
    monotonicity finding — modern-era nearly perfect, paper-era
    less so.
  - **2021 spike to 7 423 captured** is real, not artifact —
    COVID-era prisoner-release HC wave.
  - **2022–2024 low counts (~850/yr each)** are partly a capture
    gap (shard-0 is descending toward 2022 — HC 216 670 ≈
    mid-2022 — and hasn't finished there yet) and partly real
    normalisation after the 2021 spike.
  - **2025 peak** (9 184) is shard-0's bucket 250k–270k = one full
    year of current filing rate (~9–11k real HCs/yr).

  **Year checkpoints for shard-2 descent:** as shard-2 crosses
  HC 118k → 75k, expect 1991→2012 populate. Concretely:
  - shard-2 at HC 118k → 2012 fills in
  - shard-2 at HC 100k → 2009–2011
  - shard-2 at HC  90k → 2006–2008
  - shard-2 at HC  80k → 2002–2005
  - shard-2 at HC  75k → 1999–2001

  Useful signal for tracking shard-2's contribution to the
  year-level corpus.

- **2026-04-18 20:44 UTC — SIGTERM'd the 4-shard backfill** at user
  go. All 4 uv parents (4680/4688/4694/4704) and Python workers
  (4719–4722) exited cleanly within 5 s. Final state **54 841 ok /
  17 805 fail / 72 646 processed** over 11.6 h of continuous load.
  Inspection: **12 real fails** (filter_skip=False NoIncidente);
  17 793 benign filter-skips. **Zero HTTP 403/429/5xx** across the
  full 11.6 h. Real-fail rate 0.016 % — lowest on record for this
  codebase. Capture set on disk: 55 354 HCs, range 48 933 → 271 139.

- **2026-04-18 20:45 UTC — year-priority scripts landed.**
  `scripts/generate_hc_year_gap_csv.py` (2.5 KB, 5 unit tests in
  `tests/unit/test_generate_hc_year_gap_csv.py`) + `scripts/launch_hc_year_sharded.sh`
  (executable). Full unit suite green at **246 passed**. Smoke-verified
  on 2026: gap CSV has 917 rows, descending 271 048 → 266 464.

- **2026-04-18 20:57 UTC — consolidated REPORT + archive.** Archived
  run directory moved to `runs/archive/2026-04-17-hc-full-backfill-sharded/`.
  REPORT promoted to [`docs/reports/2026-04-17-hc-full-backfill-sharded.md`](reports/2026-04-17-hc-full-backfill-sharded.md).
  Key claim to absorb downstream: **20.1 h of continuous 4-shard +
  42-session load** (8.5 h prior + 11.6 h this cycle) with zero WAF
  events. Promotes "rotation > throttle" from confirmed-under-4h to
  confirmed-under-20h; `docs/rate-limits.md` amendment queued.

- **2026-04-18 21:00 UTC — 8-shard pivot.** User added 44 new
  proxies; split + rebalanced across `proxies.{a..h}.txt` at
  **10 each = 80 active sessions**, with 4 extras in
  `config/proxies.reserve.txt`. Launcher updated to iterate 8 pools.

- **2026-04-18 21:07 → 21:09 UTC — tier-0 (2026) smoke test
  SUCCESS.** Run dir `runs/active/2026-04-18-hc-2026/`, 8 shards on
  disjoint pools (a–h, 10 proxies each), 917 rows split
  114–115/shard. All shards wrote `report.md` and exited cleanly.
  **917/917 fails, all NoIncidente filter_skip=True**, zero 403/429/5xx.
  Interpretation: **2026 is fully captured** — the 917 "gap" IDs
  are legitimately reserved-but-unfiled HC numbers. Wall clock
  ~2 min for 917 records = ~460 recs/min aggregate (fast because
  fails are cheap at ~0.8 s each).

  End-to-end pipeline validated: gap-CSV generator → shard_csv →
  launch_hc_year_sharded → 8 detached nohup workers → atomic state
  → clean exit + `report.md`. No new captures (2026 already at
  100 % of real HCs), but the infrastructure works.

  **8-shard throughput anchor pending tier-1** — tier-0 used
  fast-fail paths. Tier-1 (2025, 6 857 gap with real-HC density
  ~56 %) will give a real ok-rate anchor for the remaining queue.

- **2026-04-19 00:22 UTC — five-buttons audit** (DJe, Jurisprudência,
  Peças, Push, Imprimir). Traced every button's real handler through
  the processo-bundle JS + inline `<script>` on `detalhe.asp`, then
  probed each endpoint against HC 158802 (incidente 5494703). Findings:

  | Button | Real endpoint | Scrapable from HTTP? | New data vs. current schema |
  |---|---|---|---|
  | **DJe** | `/servicos/dje/listarDiarioJustica.asp?tipoPesquisaDJ=AP&classe=<C>&numero=<N>` (inline `<script>`, l.637 of `detalhe`) | yes, 200 OK | byte-for-byte identical to `andamentos[i].complemento` + `.link` — but see open question |
  | **Jurisprudência** | `jurisprudencia.stf.jus.br/pages/search?classeNumeroIncidente=...&base=acordaos` (bundle) | **no** — AWS WAF JS challenge (HTTP 202 + `AwsWafIntegration.getToken()`) | structured **ementa** + órgão + relator + data-julgamento — possibly worth extracting from acórdão PDFs we already have |
  | **Peças** | `redir.stf.jus.br/estfvisualizadorpub/.../ConsultarProcessoEletronico.jsf?seqobjetoincidente=<inc>` (bundle) | **no** — same AWS WAF JS challenge; and the help-page branch fires for all HCs (because `peca="P"` + `meio="E"` → `"S" != s && "E" == o`) | n/a for HC; `peca` flag in detalhe is 45 694 P / 432 S / 1 RE in our cache |
  | **Push** | `/processos/push` subscription form (bundle) | gated on CPF + email | not a data source |
  | **Imprimir** | `verImpressao.asp?imprimir=true&incidente=<inc>` (plain `<a>`) | yes, 14.8 KB | **none** — tab shells are empty; inline JS fires the same 9 `abaX.asp` XHRs client-side. Strictly worse than our path (adds 1 shell request, removes none) |

  **DJe redundancy check on HC 158802** — the DJe-button summary has
  6 rows (DJ Nr 204 / 137 / 99 / 78 / 127 / 126). For each row,
  `abreDetalheDiarioProcesso(...)` calls `verDiarioProcesso.asp` which
  returns "Decisão: A Turma, por maioria, deu provimento ao agravo
  regimental, para cassar a liminar deferida, nos termos do voto do
  Ministro Edson Fachin…" — **identical string** to
  `andamentos[29/05/2020].complemento` ("AGRAVO REGIMENTAL PROVIDO").
  DJe's "Download do documento (RTF)" link corresponds to the same
  `downloadTexto.asp?id=5097474&ext=RTF` already in `andamento.link`.

  **Imprimir shell shape** — confirmed empty by section-length probe:
  `#partes`, `#andamentos`, `#informacoes`, `#decisoes`,
  `#deslocamentos`, `#peticoes`, `#recursos`, `#pautas`,
  `#sessao-virtual` all returned 0 chars. Inline jQuery script:

  ```js
  $.get('abaPartes.asp?incidente=5494703', function(resposta) { ... });
  $('#andamentos').load('abaAndamentos.asp?incidente=5494703&imprimir=true');
  $.get('abaInformacoes.asp?incidente=5494703', ...);
  $('#decisoes').load('abaDecisoes.asp?incidente=5494703');
  // ... same 9 abaX.asp fetches we already fire in src/scraping/scraper.py::fetch_process
  ```

  **AWS WAF origin wall** — both external STF apps (`estfvisualizadorpub`,
  `jurisprudencia.stf.jus.br`) return the signature 202 + empty body +
  `AwsWafIntegration` snippet. Structurally un-scrapable from our
  `requests`-based backend.

  **Two findings left open, not closed** (see § Open questions):

  - **DJe RTF utility** — the `downloadTexto.asp?ext=RTF` payload is
    already in `andamento[i].link.url`, but RTFs are **plain text
    wrapped in markup** (we `striprtf.rtf_to_text` them in
    `src/utils/pdf_utils.py:72`) with zero OCR risk, whereas some
    andamento links route to `downloadPeca.asp?ext=.pdf` that go
    through pypdf / Unstructured OCR. Not fully convinced the RTF
    side-channel is "useless" — plausible it would cleanly replace
    scanned-peça extraction on acts where STF publishes both. Needs
    a probe: enumerate andamentos where both a peça-PDF and a
    matching DJe RTF exist, diff the extracted text.

  - **Jurisprudência ementa** — the only genuinely-new field any of
    the five buttons exposes is the **isolated ementa** from
    `jurisprudencia.stf.jus.br`. Already inside every acórdão PDF
    we download, but buried in prose with relatório + votos. AWS WAF
    blocks the jurisprudência origin, but the same field could be
    parsed out of cached acórdão PDFs (`E M E N T A` … `A C Ó R D Ã O`
    delimiters are stable). ~30-line extractor in
    `src/scraping/extraction/ementa.py` at zero extra network cost.
    Worth doing if downstream analysis wants the citeable summary
    separated from the voting narrative.

- **2026-04-19 00:40 UTC — RTF extraction was silently broken;
  landed the one-line fix.** Tracing the "DJe RTF might not be
  useless" open question turned up a real production bug in
  `src/utils/pdf_utils.py`:

  ```python
  import striprtf                          # broken: no top-level attr
  plain_text = striprtf.rtf_to_text(...)   # AttributeError, caught silently
  ```

  The correct import is `from striprtf.striprtf import rtf_to_text`.
  The `try/except Exception: return None` at line 80 swallowed the
  `AttributeError`; pdf_cache only persists when `text is not None`,
  so no garbage cached — just every RTF URL silently returning None
  on every scrape, forever, self-reinforcing cache miss.

  **Scope of the bug**:
  - `sessao_virtual[*].documentos` RTF entries — silently `text: None`
    where they should have held clean prose. Fetched fresh on every
    scrape because cache-miss-on-None.
  - `andamentos[i].link.text` — structurally `None` regardless, because
    `src/scraping/extraction/tables.py:65` leaves it None pending a
    promised "OCR/pypdf enrichment pass" that never landed. The RTF
    bug is moot for andamentos today (nothing calls extract on them),
    but becomes load-bearing if we ever wire up the enrichment pass.

  **Landed changes**:
  - `src/utils/pdf_utils.py`: fix import (`from striprtf.striprtf
    import rtf_to_text`), switch content decode from `utf-8` to
    `latin-1` (STF escapes accents as `\'c7\'c3` hex pairs that
    need byte-preserving decode, not utf-8 which maps them to the
    replacement character).
  - `tests/unit/test_pdf_utils_rtf.py`: two behavioral tests —
    extract-preserves-accents (`FALSIFICAÇÃO`, `PÚBLICO`, `decisão`)
    and magic-byte detection routes to RTF path.

  **Verification**: end-to-end round-trip against the HC 129840 AgR
  ementa (user-supplied RTF, 6 584 bytes raw) → 1 870 chars clean
  Portuguese prose, all 6 numbered clauses intact, every accent
  preserved. Full unit suite at **262 passed** (was 260).

  **No schema change triggered.** Every slot this fix populates
  (`sessao_virtual[*].documentos.text`, `andamentos[i].link.text`)
  already exists as `Optional[str]`. The v3 schema shipped the
  structure for carrying extracted text; the extractor being broken
  just meant those slots carried `None` when they could have carried
  prose. Fixture rebuild may be queued for cases with RTF entries in
  `sessao_virtual[*].documentos` (ADI 2820 primary candidate) —
  offline renormalizer rerun, no behavior change needed.

  **What this resolves**: the earlier open question "DJe RTF utility —
  not fully convinced it's useless" closes in the affirmative. The
  RTF channel is the jurisprudência ementa on a non-WAF-walled
  origin, and the only reason we thought it was useless was that our
  extractor had been silently discarding every byte. For the 5-row
  HC 129840 DJe listing the user inspected (DJ 162/164/98/116/**133**),
  the `Acórdãos 1ª Turma` row on DJ 133 maps to the "PUBLICADO ACÓRDÃO,
  DJE" andamento whose `downloadTexto.asp?...&ext=RTF` link now
  extracts cleanly.

- **2026-04-19 ~01:30 UTC — OCR backend economics + alternatives
  survey.** User asked whether to consider Chandra / Surya / other
  OCR backends, and how much it would cost to OCR all relevant PDFs.
  Scope narrowed to three live alternatives + the incumbent.

  **Inventory (measured against `data/cases/HC/`, 55 354 captured HCs):**

  | filter | PDFs |
  |---|---:|
  | famous-lawyer + 3 doc types (current research preset) |     354 |
  | famous-lawyer, any doc type                            |     752 |
  | all HC + 3 key doc types (any lawyer)                  |  64 603 |
  | all HC PDF links                                       | 153 272 |
  | already cached as text (16 982 entries)                |   ↑ subset |

  Cached-text size distribution: 3 essentially empty (`<200` chars),
  2 013 short (`200–1k`), 6 952 medium (`1k–5k`), 5 886 long
  (`5k–20k`), 2 128 very long (`>20k`). The "real OCR-upgrade
  candidates" inside the cached set is roughly the **<1k bucket
  (~2 016 PDFs)** plus a fraction of the 1k–5k tier — well below
  the 16 982 nominal.

  **Incumbent baseline (measured, `docs/reports/2026-04-17-famous-lawyers-ocr.md`):**
  - Unstructured `hi_res` at $10 / 1k pg.
  - 55 candidates → **34 improved (62 %)**, 19 unchanged
    (genuine-short orders), 2 transient WAF empty-body.
  - Total chars on improved set: 73 720 → **489 419 (6.6×)**.
  - Wall: ~21 min for 55 PDFs ≈ **23 s/PDF end-to-end**.
  - Total Unstructured spend across all three historical runs
    (famous-lawyers + top-volume + minister-archetypes ≈ 88 PDFs ×
    ~5 pg avg) is **~$4–5**. Forward-looking decision, not a
    sunk-cost migration.

  **The four backends at April-2026 prices (computed via `python -c`):**

  | backend | $ / 1k pg | source |
  |---|---:|---|
  | Unstructured `hi_res` (current) | $10.00 | unstructured.io/pricing |
  | Mistral OCR 3 batch             |  $1.00 | mistral.ai/news/mistral-ocr-3 |
  | Datalab Chandra hosted          | ~$3.00 | community report; Datalab pricing not public |
  | Chandra on Modal H100           | ~$0.55 | $3.95/hr ÷ 2 pg/s observed throughput |

  **Cost per tier (~5 pg/PDF blended avg for Brazilian legal docs):**

  | tier | pages | Unstructured | Mistral batch | Chandra hosted | Modal Chandra |
  |---|---:|---:|---:|---:|---:|
  | famous-lawyer (354)         |   1 770 |  $17.70 |   $1.77 |    $5.31 |   $0.97 |
  | HC + key docs (64 603)      | 323 015 |   $3 230 |    $323 |     $969 |    $178 |
  | all HC (153 272)            | 766 360 |   $7 663 |    $766 |   $2 299 |    $421 |

  Unstructured is **5×–18× more expensive** than the cheapest
  alternative across every tier.

  **Quality bench:** Chandra-2 reports **95.2 % accuracy on
  Portuguese** (best of the four). Mistral OCR 3 has no public PT
  benchmark but is generally competitive. Both should match or
  exceed the 6.6× char lift Unstructured `hi_res` produced; needs
  empirical re-run on the same 55-PDF famous-lawyer set before
  committing to a >5k-PDF sweep.

  **Lock-in points** (the only real reason to hesitate):
  1. `src/utils/pdf_cache.py::write_elements` expects Unstructured's
     typed element list (`Title` / `NarrativeText` / `Table` etc.).
     33 `.elements.json.gz` files exist on disk. Translator shim is
     ~10 lines, but downstream consumers may want the typology.
  2. `scripts/reextract_unstructured.py::_concat_elements` joins on
     `el["text"]`. Trivial to re-target.
  3. Wall-time profile shifts: Unstructured was 23 s/PDF measured;
     Modal Chandra single-H100 sync is ~2.5 s/PDF (5 pg @ 2 pg/s);
     Mistral batch returns asynchronously over ~24 h. Sync vs batch
     changes how `pdf_driver.run_pdf_sweep` paces.

  **Decision rule (drafted, not yet committed):**
  - **≤ ~1k PDFs** (e.g. famous-lawyer preset, $18 on Unstructured):
    keep Unstructured. Migration engineering exceeds savings.
  - **~5k–~64k PDFs** (HC + key doc types tier, $3 230 on
    Unstructured): switch to **Mistral batch** (~$323, ~½ day
    integration). Modal saves another ~$145 but costs an extra day —
    only worth it for recurring re-runs.
  - **All-HC + recurring sweeps** (~150 k+, $7 663 on Unstructured):
    **Modal Chandra** wins decisively — 18× cost ratio, plus highest
    PT quality, plus reusable inference infra for future workloads.
    Worth the 1–2 day setup.

  **Pre-migration validation gate:** re-run the famous-lawyer 55-PDF
  set through the chosen alternative; confirm ≥ 6.6× char lift on
  the same rescuable subset; spot-check 5 acórdãos manually. ~1 h
  of work; prevents a ~$300 bad bulk sweep.

- **2026-04-19 ~02:30 UTC — HTML cache layout migration +
  DuckDB warehouse sketch.** Orthogonal to the HC-backfill strand;
  triggered by a user-led Q&A on storage costs. Three deliverables:

  **1) HTML cache migrated from per-tab `.html.gz` to per-case
  `.tar.gz`.** Root cause: 559 540 gzipped fragments averaging
  2.7 KB each were paying 4 KB of ext4 block padding per inode →
  **1.85 GB wasted to padding** (57 % of the cache's on-disk
  footprint). Per-case tar.gz collapses ~10 fragments per case into
  one archive. Measured result on a 50-case sample: **12× inode
  reduction, 58 % on-disk footprint reduction** (3.2 MB → 1.4 MB,
  matched benchmark prediction exactly). Extrapolated to current
  55 354 cases: ~1.9 GB reclaimed. At full-HC (350 k) projection:
  ~20 GB reclaimed + 10× reduction in B2 backup object count.

  **Decision point in the design:** tar-of-gz (per-member gzip,
  random-access reads) was measured against tar.gz-of-plain (outer
  gzip, cross-tab compression). Benchmark on 50 real cases:
  tar-of-gz apparent=2.04 MB (worse, tar headers dominate at 3 KB
  members); tar.gz-of-plain apparent=1.28 MB, one-tab read 0.84 ms
  (vs 0.25 ms for tar-of-gz, still well within budget). **Picked
  tar.gz-of-plain** — gzip's 32 KB sliding window exploits cross-tab
  redundancy for 30 KB-per-case payloads, read pattern is
  "all-tabs-of-a-case" dominant anyway.

  **Atomicity tightened as a side effect.** Pre-refactor, a crash
  mid-scrape could leave a case with partial tabs cached (7/10 on
  disk, 3/10 missing), which `--resume` would treat as "present" for
  the tabs it found and mix fresh re-scrapes for the missing ones.
  Post-refactor, `scrape_processo_http` accumulates writes into a
  `_CacheBuf` dataclass and flushes once per case via tempfile +
  `os.replace` — every case is either fully cached or absent. This
  is the same atomicity contract `src/sweeps/process_store.py` has
  held for sweep state.

  **Landed:**
  - `src/utils/html_cache.py` rewritten: API is now `read`,
    `read_incidente`, `has_case`, `write_case` (batch). Old per-tab
    `write` + `write_incidente` removed (no backcompat shims per
    project convention).
  - `src/scraping/scraper.py`: `_CacheBuf` dataclass, threaded
    through `fetch_process` + `_make_sessao_fetcher`; single flush
    in `scrape_processo_http` gated by `cache_buf.dirty` (no-op
    rewrites skipped when all tabs are cache hits, so mtime-based
    backup diffs stay stable).
  - `scripts/run_sweep.py::_wipe_html_caches` updated to rm the
    tar.gz (with legacy-dir fallback for partial migration states).
  - `scripts/migrate_html_cache_to_tar.py` — idempotent migration
    with `--dry-run`, `--keep-dirs`, `--classe`, `--limit` flags.
    Verifies round-trip per case (reads every member through the
    new API vs source) before deletion.
  - `tests/unit/test_html_cache.py` — 9 new tests covering
    read/has_case on empty, write_case round-trips, missing-tab
    returns None, variable-suffix sessao tabs, replace semantics,
    UTF-8 content, archive format, no-leftover-tempfiles.
  - Full unit suite: **298 passed** (was 262).

  **Dry-run executed on 20 cases (0.5 s); keep-dirs migration
  executed on 50 cases (1.5 s)** as smoke test. Round-trip verified
  end-to-end on ACO 2652 (all 13 members: detalhe + 9 tabs + 3
  variable-suffix sessao entries, every byte intact). 54 304 cases
  still on the legacy layout, ~49 new tar.gz sit alongside the
  source directories for belt-and-suspenders.

  **2) DuckDB warehouse design sketched at
  [`docs/warehouse-design.md`](warehouse-design.md).** Design-only,
  no code. Five tables (`cases`, `partes`, `andamentos`,
  `documentos`, `pdfs`) + `manifest`, full-rebuild pipeline
  (`scripts/build_warehouse.py`, not written), single `.duckdb`
  file at `data/warehouse/judex.duckdb`. Scraper stays primary;
  warehouse is derived and rebuildable. Manual refresh cadence for
  v1; post-sweep trigger queued for v2. Expected build time: ~2–3
  min at current scale, ~15–20 min at 350 k-HC scale.

  **3) `data/cache/html/` changed shape.** The data-layout doc
  (`docs/data-layout.md`) still references `html_cache` by module
  name (not path), so the module boundary holds; a one-line update
  to the file-path example is queued (see Next steps).

- **2026-04-19 ~03:00 UTC — 3-way OCR bakeoff on 5-PDF validation
  slice.** Pre-migration gate from Open question 7. Candidate pool
  shrank from the original 55 to 5 because `pdf_cache` is
  monotonic-by-length — the 2026-04-17 Unstructured rescue
  overwrote 34 of the 55 shorts. All 5 cached baselines are 0 chars
  on disk (prior extraction never persisted). Harness
  (`scripts/ocr_bakeoff.py`) extended to save full text per
  provider at `<out>/texts/<url_key>.<provider>.txt` + inline
  800-char samples in `report.md` — prior version threw text away
  at `preview[:200]`, making quality comparison impossible. Run at
  `runs/active/2026-04-19-ocr-bakeoff/`, 15 provider calls, zero
  failures.

  **Three-provider scorecard** (5 PDFs, ~75 pg total):

  | axis                           | Unstructured                    | Mistral                  | Chandra               |
  |---|---|---|---|
  | total chars                    | 137 934                         | 138 418                  | 118 156 (–15 %)       |
  | total wall                     | 193 s                           | **16 s (12× vs U)**      | 79 s (2.4× vs U)      |
  | $ / 1 k pg (list)              | $10                             | **$1 batch / $2 sync**   | ~$3                   |
  | accent preservation `ç ã ó`    | occasional loss                 | clean                    | clean                 |
  | `§` paragraph sign             | **OCR'd as digit `8`**          | preserved                | preserved             |
  | Roman numerals `(i)(ii)(iii)`  | **collapsed to `(1)`**          | preserved                | preserved             |
  | Table label→value pairing      | **broken (split blocks)**       | clean markdown tables    | HTML-in-markdown      |
  | Wrapped-ementa word order      | **reordered (semantic break)**  | correct                  | correct               |
  | Output format                  | plain text + typed elements     | markdown (`#`, tables)   | markdown + `<b>` HTML |

  **Concrete defect** from HC 252.920 ementa (48 KB acórdão,
  Toron/Tofic/Tranchesi), first 2 KB `diff -u unstructured mistral`:

  - Unstructured: `"FRAUDE À E CRIMINOSA. ALEGADA LICITAÇÃO ORGANIZAÇÃO"`
  - Mistral:      `"FRAUDE À LICITAÇÃO E ORGANIZAÇÃO CRIMINOSA"`

  Column un-weaving: the two-column wrapped ementa is read
  column-by-column without reassembly. Another inversion on the
  same page: Unstructured `"NÃO CONSTOU COMO DIRETA OU INVESTIGADO,
  SEJA INDIRETAMENTE"` vs Mistral `"NÃO CONSTOU COMO INVESTIGADO,
  SEJA DIRETA OU INDIRETAMENTE"` — meaning inverted. Plus `§→8`
  (`"art. 2º, 8 4º, II"` vs `"art. 2º, § 4º, II"`) and
  `(i)(ii)(iii)→(1)(1)(1)` in the same PDF.

  **Cost-by-scale** (using list prices, Mistral batch):

  | tier                         | pages   | Unstructured | Mistral batch | savings |
  |---|---:|---:|---:|---:|
  | famous-lawyer (354)          |   1 770 |    $17.70    |      $1.77    |   –$16  |
  | HC + key docs (64 603)       | 323 015 |   $3 230     |    $323       |  –$2 907 |
  | all HC (153 272)             | 766 360 |   $7 663     |    $766       |  –$6 897 |

  **Gate passed on a different axis than planned.** Original gate
  was "≥ 6.6× char lift vs cached baseline on rescuable subset" —
  inapplicable here because cached is 0 chars across all 5
  candidates. Real gate passed: **cross-provider semantic fidelity**.
  Unstructured's defects are *algorithmic* (column un-weaving,
  vocabulary fallbacks) so they recur across the corpus, not a
  5-PDF fluke.

  **Harness changes landed** (`scripts/ocr_bakeoff.py`):
  `_run_provider` now returns full text (was discarding it at
  `preview[:200]`); main loop writes `texts/<url_key>.<provider>.txt`
  + `texts/<url_key>.cached.txt` per candidate; `_write_report`
  gains "Side-by-side samples" section. Full OCR unit suite still
  27/27 green.

## Decisions

- **2026-04-19 ~03:00 UTC — migrate OCR default from Unstructured
  to Mistral sync.** Bakeoff run surfaces the trigger on a different
  axis than the original char-lift gate: **cross-provider semantic
  fidelity**. Unstructured has systemic, reproducible defects on
  acórdão text (column un-weaving of wrapped ementas, `§`→`8` glyph
  fallback, `(i)(ii)(iii)→(1)(1)(1)` Roman-numeral collapse, broken
  label→value table pairing) that Mistral does not. Mistral is
  simultaneously 12× faster and 10× cheaper. Chandra is 2.4× faster
  + 3× cheaper than Unstructured but ships 15 % shorter output with
  HTML-in-markdown hybrid formatting that needs downstream stripping.
  Plan: rename `scripts/reextract_unstructured.py` → `reextract_ocr.py`,
  thin it over `src.scraping.ocr.extract_pdf`, default
  `--provider mistral`. Keep `--provider unstructured/chandra` as
  comparison flags. Batch vs sync call TBD based on throughput
  tolerance. See observation 2026-04-19 ~03:00 UTC.

- **2026-04-18 20:30 UTC — archive the monitoring session, keep
  running.** The active task evolved from "diagnose the overnight
  collapse and decide resume" to "ride the steady-state backfill."

- **2026-04-18 20:40 UTC — supersede the per-year single-worker
  `hc-backfill-extension-plan.md` with a year-priority 4-shard
  structure.** Year-priority sequential, newest-first, 4-shard per
  year, gap-filtered CSVs (IDs not already on disk). Paper era
  (pre-2013) explicitly out of scope.

- **2026-04-18 20:42 UTC — gap-sweep, not full-year + `--resume`.**
  Gap CSV (derived by filtering year range against `data/cases/HC/`)
  saves ~30 % of wall and sidesteps the state-aggregation step that
  full-year-plus-resume would need. Also skips paper era entirely
  per user call.

- **2026-04-18 20:42 UTC — 2026 catch-up as tier 0.** Small sweep
  (~917 IDs, ~18 min at 4-shard) doubles as the launcher smoke test.

- **2026-04-18 20:43 UTC — delay SIGTERM until launcher ready.**
  Superseded at 20:44 when user said "stop the current runs" —
  launcher landed shortly after, so the delay was de facto < 20 min.

- **2026-04-18 21:00 UTC — 8-shard per year.** With 80 sessions
  across 8 disjoint pools (a–h), run 8 shards per tier instead of 4.
  Wall expected to halve; validated empirically on tier 0.

- **2026-04-18 — ground-truth fixtures rebuilt to v3 offline.** All
  7 fixtures (`tests/ground_truth/*.json`) re-extracted via
  `scripts.renormalize_cases._rebuild_item` against the cached HTML
  fragments — purely offline, no network. Now carry full v3 shape:
  `schema_version=3`, top-level `url`, `data_protocolo_iso`,
  `status_http` (was `status`), `OutcomeInfo` dict (was bare
  string), `data_iso` companion on every nested date field.
  Fixture content is now canonically v3; `validate_ground_truth.py`
  diffs cleanly. Unit suite stays green at 260 passed. No separate
  migration script needed — reused the renormalizer's inline
  rebuilder in a one-off Python invocation.

- **2026-04-18 — keep pypdf `extraction_mode="plain"` as PDF default.**
  Earlier turn of the day switched from `layout` to `plain` after
  observing letter-spaced title artifacts (`O S   ENHOR   M   INISTRO`)
  in a voto/relatório extraction. Three-way comparison notebook
  (`analysis/pdf_extractor_compare.py`, pypdf layout / pypdf plain /
  Unstructured hi_res) later surfaced a counter-example on ACO 2652's
  Certidão de Trânsito: plain mode reverses label/value on structured
  tables (`: ESTADO DE SERGIPE\nAUTOR(A/S)`) because PDF content-stream
  order ≠ visual order. Layout mode renders the table correctly.
  **Decision: keep plain**, on the grounds that long documents
  (voto, relatório, decisão monocrática, acórdão) dominate the corpus
  and are pure prose — where plain wins unambiguously. Short
  table-heavy docs (certidões, despachos) degrade but their downstream
  consumers are small (date regexes don't care about word order;
  party names come from `abaPartes.asp`, not PDF text). Post-processing
  layout to recover clean prose is *technically* easier than fixing
  plain's table inversion — all layout fixes are ≤5-line regexes,
  table inversion needs semantic heuristics — but the engineering cost
  outweighs the marginal quality gain at current priorities.
  **Escape hatch:** `scripts/reextract_unstructured.py --force` on
  doc-types where structure matters (EMENTA, CERTIDÃO, ATA) remains
  available; the notebook is a diagnostic entry point for deciding
  whether to run it on a given URL cluster.

## Open questions

1. **CliffDetector noise-reduction** — make `filter_skip=True`
   fails neutral for the fail_rate axis; consider raising the p95
   threshold from ~7 s to ~10 s to match observed dense-territory
   baseline. (Queued for post-backfill.)
2. **Rolling-median wall_s breaker** — secondary safety net for
   V-style patterns the p95 axis misses. (Carried forward.)
3. **Quota-wall decision** — reactive vs preemptive top-up.
   Pending user call when the first 407 lands or before bedtime,
   whichever comes first.
4. **Scale beyond 4 shards?** — WAF headroom verified at 4× over
   8.5 h, untested at 8× or 16×. The arithmetic suggests it works
   (per-shard WAF counter is independent), but empirically unverified.
5. **DJe RTF vs. PDF-OCR for same-act text** — when an andamento
   has a `downloadPeca.asp?ext=.pdf` link that goes through pypdf /
   Unstructured OCR, does STF also publish the same act via DJe as
   a `downloadTexto.asp?ext=RTF`? If yes, substituting RTF for PDF
   on those cases would cut OCR risk to zero. Requires a probe over
   the andamentos corpus matching peça-PDFs with contemporaneous
   DJe RTFs. Caveat: RTF is typically only the ementa + dispositivo,
   so it'd be a lossy substitution for full-acórdão use cases — but
   plausibly a *complementary* field, not a replacement.
6. **Structured ementa extraction from cached acórdão PDFs** — the
   jurisprudência button exposes ementa as a clean string, but the
   origin is AWS-WAF-blocked. The same field exists in every
   `downloadPeca.asp?ext=.pdf` we already cache, between the
   `E M E N T A` and `A C Ó R D Ã O` / `R E L A T Ó R I O` headers.
   ~30-line parser would give us the citeable summary as a separate
   `StfItem` field without any extra network calls. Worth doing if
   downstream analysis (e.g. `docs/hc-who-wins.md` argument-mining)
   needs the legal-theses summary separately from voting narrative.
7. ~~**OCR backend migration trigger**~~ **Closed 2026-04-19
   ~03:00 UTC.** Validation-gate bakeoff
   (`runs/active/2026-04-19-ocr-bakeoff/`) fired the trigger on
   semantic-fidelity grounds, not cost. Unstructured has systemic
   defects Mistral does not; Mistral is also 12× faster and 10×
   cheaper. Decision: migrate to Mistral sync — see 2026-04-19
   ~03:00 UTC observation + decision. Chandra held as comparison
   backend; cost-based migration thresholds from the original
   economics survey (2026-04-19 ~01:30 UTC) retained as reference
   for any future provider evaluation.

## Next steps

1. **Hands-off cron monitoring.** Nothing to do unless alert fires.
2. **Quota-wall strategy (user decision).** Three options surfaced
   in archived file § Decisions — default is reactive top-up.
3. **Post-backfill consolidated REPORT.md** merging all 4 shards'
   final state. Template: archived cycle's observation log.
4. **Post-backfill: reconcile `docs/process-space.md`** — HC
   ceiling numbers there are stale (doc says 25–40 k real HCs;
   G-probe + this sweep confirm ~216 k). One `uv run python`
   session against `data/cases/HC/*.json`.
5. **Post-backfill: `CliffDetector` noise-reduction PR** in
   `src/sweeps/shared.py` — one-liner + one new test.
6. **Post-backfill: next-class decision** — ADI (~400 MB, 8 BRL,
   rounding error) vs RE (~80 GB, ~1 600 BRL, real budgeting call).
7. **Carried-forward:**
   - Stratified-by-density sharding for next sweep (shard-1
     solo-bottleneck is fixable).
   - Rolling-median `wall_s` breaker.
   - Selenium retirement phase 2 — re-capture ground-truth
     fixtures under HTTP + audit `deprecated/` self-containment.
     Spec at `docs/superpowers/specs/2026-04-17-selenium-retirement.md`.
   - ✅ **OCR provider abstraction module** — landed
     (`src/scraping/ocr/{base,dispatch,unstructured,mistral,chandra}.py`).
     27 unit tests. `extract_pdf(bytes, config)` is the single entry.
   - ✅ **Pre-migration validation bakeoff** — ran 2026-04-19
     ~03:00 UTC, see observation + decision. Harness
     (`scripts/ocr_bakeoff.py`) extended to persist full text per
     `(url, provider)` + inline 800-char samples in `report.md`.
   - **Switch OCR default to Mistral** — rename
     `scripts/reextract_unstructured.py` → `reextract_ocr.py`,
     thin wrapper over `src.scraping.ocr.extract_pdf`, default
     `--provider mistral`, keep `--provider unstructured/chandra`
     as comparison flags. Short follow-up per the migration decision.
   - **88-PDF Mistral re-run vs prior Unstructured corpus** —
     ~$0.20 batch, ~1 min wall. Diff against existing extracts and
     confirm the column-un-weaving / `§→8` / `(i)→(1)` defect
     classes are uniformly absent. Cheap sanity before any bulk
     sweep (HC + key-doc-types tier = 64 k PDFs, $323 on Mistral
     batch).
   - **Promote bakeoff report** to
     `docs/reports/2026-04-19-ocr-bakeoff.md` (convention per
     CLAUDE.md § Running sweeps), archive
     `runs/active/2026-04-19-ocr-bakeoff/`.

---

# Strategic state

## What just landed

- **Schema v5 — andamento link unified with Documento** (2026-04-19
  ~04:00 UTC). `Andamento.link` now carries `{tipo, url, text,
  extractor}` or None; the v4 sibling field `Andamento.link_descricao`
  is gone, the anchor label lives in `link.tipo`. Shape is identical
  to `sessao_virtual[*].documentos[*]` — one `Documento` TypedDict
  drives both slots. Option 2 chosen for the href-less edge case:
  anchors with visible text but no `href` materialise as
  `{tipo: "...", url: null, text: null, extractor: null}` rather than
  dropping the label. Warehouse table column renamed `link_descricao`
  → `link_tipo`. Downstream consumers (`src/warehouse/builder.py`,
  `src/sweeps/pdf_targets.py`, `scripts/ocr_bakeoff.py`) read
  `link.tipo` directly with no fallback — pre-v5 case JSONs must be
  renormalized first. `scripts/renormalize_cases.py` handles the jump
  naturally (re-runs the current `extract_andamentos` against cached
  HTML). All 7 ground-truth fixtures + 2 candidates regenerated from
  cache as bare-dict v5 with 0 content diffs. 328 unit tests green
  (+1 new href-less edge-case test).
- **Schema v4 — extractor provenance on every extracted text**
  (2026-04-19 ~03:30 UTC). New `extractor: Optional[str]` slot on
  both `AndamentoLink` and `Documento`. Open-set label
  (`"rtf" / "pypdf_plain" / "pypdf_layout" / "unstructured" /
  "mistral" / "chandra"`) persisted via a `<sha1>.extractor` plain-text
  sidecar alongside `<sha1>.txt.gz` + `<sha1>.elements.json.gz`.
  `sessao_virtual[*].documentos` restructured from dict-keyed-by-tipo
  to list-of-Documento — option (b) of the v4 design: duplicate
  `tipo` values survive (the v3 dict silently dropped second votes
  from the same session). `_build_documentos`, `resolve_documentos`,
  `_make_pdf_fetcher`, `_cache_only_pdf_fetcher`, `extract_document_text`
  all return `(text, extractor)`. Warehouse flattener handles all
  v1-v4 documento shapes transparently. `pdf_cache.write(url, text,
  extractor=...)` — passing `extractor=None` is non-destructive, so
  pre-v4 callers can re-write text without clobbering a known label.
- **`reextract_unstructured.py` generalised to an OCR dispatcher**
  (2026-04-19). `--provider mistral|unstructured|chandra`, default
  **`mistral`**. Routes through `src.scraping.ocr.extract_pdf` — one
  OCRConfig per run, provider-specific knobs (`--strategy`, `--mode`,
  `--batch`) stay inert for providers that don't use them. Monotonic
  guard now bypassed under `--force`: unconditional cache overwrite
  with new provider output + extractor sidecar + elements cache. When
  guard triggers (non-force, new ≤ old), the fetcher returns
  `(None, provider, "unchanged")` so the driver skips `pdf_cache.write`
  entirely — the prior behaviour rewrote the same text with
  `extractor="unchanged"` clobbering the real sidecar label, which
  was a latent bug surfaced by the v4 sidecar contract. Portuguese
  CLI `src/cli.py varrer-pdfs` gains `--provedor` flag + per-provider
  `*_API_KEY` env-var check (MISTRAL_API_KEY is the new default
  gate for the rescue pass).
- **3-way OCR bakeoff, Mistral chosen as new default**
  (2026-04-19 ~03:00 UTC). 5-PDF validation slice from the
  famous-lawyer set at `runs/active/2026-04-19-ocr-bakeoff/`;
  15 provider calls, zero failures. Unstructured ships **systemic
  defects on acórdão text** (column un-weaving of two-column
  ementas → semantic garble, `§`→digit `8`, Roman numerals
  `(i)(ii)(iii)`→`(1)(1)(1)`, broken label→value table pairing)
  that Mistral does not. Mistral is **12× faster + 10× cheaper**
  on the same 75 pages. Chandra preserves semantics but ships
  15 % shorter output + HTML-in-markdown hybrid. Harness
  (`scripts/ocr_bakeoff.py`) extended to persist full text per
  provider and inline 800-char side-by-side in `report.md` — prior
  version threw text away at `preview[:200]`. Open question 7
  closed. `scripts/reextract_unstructured.py` now generalised and
  defaults to `--provider mistral` (see next-two entries above).
- **HTML cache migrated to per-case tar.gz** (2026-04-19 session).
  `src/utils/html_cache.py` rewritten with batched `write_case` API;
  `src/scraping/scraper.py` refactored to accumulate via `_CacheBuf`
  dataclass and flush once per case (atomic tempfile + rename).
  Measured 58 % on-disk reduction / 12× inode reduction on a 50-case
  sample; ~1.9 GB reclaimed at current 55 k-case scale. Per-case
  atomicity tightened as a side effect (no more partial-cache
  `--resume` edge case). Migration script at
  `scripts/migrate_html_cache_to_tar.py` (idempotent,
  round-trip-verified, `--dry-run` / `--keep-dirs` / `--classe`
  flags). 9 new unit tests; full suite **298 passed**. Only ~50 tars
  written so far (keep-dirs smoke test) — full migration is a queued
  next step.
- **DuckDB warehouse design** sketched at
  [`docs/warehouse-design.md`](warehouse-design.md) — five tables
  (`cases`, `partes`, `andamentos`, `documentos`, `pdfs`) +
  `manifest`, single `.duckdb` file, full-rebuild pipeline, manual
  refresh cadence. No code yet.
- **Tier-0 (2026) launcher smoke test passed** (2026-04-18 21:07 →
  21:09 UTC). 8 shards on disjoint proxy pools, 917 rows, 917/917
  filter_skip=True NoIncidente (confirms 2026 fully captured), zero
  WAF events. `runs/active/2026-04-18-hc-2026/` not yet archived,
  tier-1 not yet fired.
- **4-shard HC backfill stopped cleanly + archived** at
  `runs/archive/2026-04-17-hc-full-backfill-sharded/`. Consolidated
  REPORT at [`docs/reports/2026-04-17-hc-full-backfill-sharded.md`](reports/2026-04-17-hc-full-backfill-sharded.md).
  Final: 54 841 ok / 12 real fails across 72 646 records over 11.6 h,
  zero WAF events. Corpus on disk: 55 354 HCs (49 k → 271 k).
- **Year-priority gap-sweep successor plan** at
  [`docs/hc-backfill-extension-plan.md`](hc-backfill-extension-plan.md).
  14 tiers (2026 → 2013), 109 042 IDs total gap, ~20 h projected
  wall at 8-shard / ~39.5 h at 4-shard baseline. Paper era out of
  scope.
- **Gap-CSV generator + year-sharded launcher** — `scripts/generate_hc_year_gap_csv.py`
  (+ 5 unit tests) and `scripts/launch_hc_year_sharded.sh`. Full
  unit suite green at 246 passed.
- **Detached-sweep pattern documented** in `CLAUDE.md § Surviving
  session death` — four-pillar recipe (`nohup … & disown`,
  `shards.pids`, atomic state, cron monitor) + reconnection workflow.
- **Proxy pool doubled to 80 sessions across 8 files** (`proxies.{a..h}.txt`).
  User added 44 new proxies on 2026-04-18; split + rebalanced into
  e/f/g/h at 11 each.
- **Raw `html` field dropped from `StfItem`** (`1ae0920`). All 6
  ground-truth fixtures updated in lockstep. Shrinks case JSONs by
  ~50–200 KB each.
- **Cron-monitored 8.5 h backfill session** (archived). Empirical
  confirmation that HTTP + 4-shard proxy rotation sustains
  ~1 rec/s aggregate with zero WAF pressure.
- **HC density map reconciled** (archived). G-probe (Apr 16)
  extrapolation of ~216 k real HCs is accurate.
- **Selenium-vs-HTTP-with-proxies bake-off** (archived). HTTP wins
  every axis except resilience-to-STF-changes.
- **`filter_skip` + `body_head` instrumentation** (`c463f14`) and
  unified CLI `judex` hub (`04b852a`) — pre-session.

## In flight

Nothing actively executing. Three strands paused at clean handoff points:

- **Schema migration v3/v4 → v5 — code shipped, data not yet
  renormalized.** Fixtures are all v5; production case JSONs under
  `data/cases/**/*.json` are still pre-v5 (mostly v3 based on the
  earlier dry-run sample of 1000/57 595 all classified `ok` under
  v4). Next fire: `PYTHONPATH=. uv run python
  scripts/renormalize_cases.py --workers 8`. Renormalizer is
  v4→v5-aware (re-runs current `extract_andamentos` which emits the
  unified link shape); cache entries without the `<sha1>.extractor`
  sidecar back-fill as `extractor: null` — the agreed lossy default.
  Estimated wall at 10 files/s sequential → ~1.5 h with 8 workers.
- **HC backfill — tier-0 complete, tier-1 queued.** Tier-0 ran
  clean (917/917 filter_skip=True, zero WAF events), confirming the
  8-shard year-priority pipeline. Run dir at
  `runs/active/2026-04-18-hc-2026/` awaiting archival; tier-1 (2025)
  is the next fire. 109 042 total gap IDs across tiers 0–13;
  tier-0's 917 filter_skips don't dent the remaining ~108 k.
- **Storage migration — 50 cases tar'd, 55 k still legacy.**
  `scripts/migrate_html_cache_to_tar.py` is ready; the keep-dirs
  smoke test wrote ~49 sibling tars but source dirs remain. Full
  migration is a ~30 s one-shot at current cache size.

## Next steps, ordered

### HC-backfill strand

1. **Archive tier-0 run** — `git mv runs/active/2026-04-18-hc-2026
   runs/archive/2026-04-18-hc-2026` + promote a short report to
   `docs/reports/2026-04-18-hc-2026-tier-0.md` (one paragraph; the
   signal was "pipeline healthy," not "lots of captures").
2. **Launch tier-1 (2025)** —
   `nohup ./scripts/launch_hc_year_sharded.sh 2025 > runs/active/2026-04-19-hc-2025/launcher-stdout.log 2>&1 & disown`.
   Regenerate the gap CSV at launch so any captures since the
   backfill shrink it. This is the first tier where 8-shard
   aggregate throughput gets a real anchor (~56 % real-HC density
   expected in 2025's 6 857-row gap).
3. **Sequential tiers 2 → 13** with cron monitoring between
   (schedule via `/schedule`, `13,43 * * * *` cadence as before).
4. **Consolidated post-queue REPORT** at
   `docs/reports/<date>-hc-year-priority-tiers-0-13.md`.
5. **Doc amendments** post-queue:
   - `docs/rate-limits.md` — promote rotation > throttle to
     confirmed-under-20h; add 8-shard-80-session empirical result.
   - `docs/performance.md` — add 8-shard aggregate throughput.
   - `docs/process-space.md` — already accurate; no change needed.
   - `docs/hc-who-wins.md` — re-check sample-size math against
     final corpus.

### Schema migration v5 strand (independent, blocks warehouse build)

1. **Full dry-run** — `PYTHONPATH=. uv run python
   scripts/renormalize_cases.py --dry-run --workers 4` to surface any
   `needs_rescrape` (incomplete HTML cache) or parse errors across the
   full 57 595-file corpus before committing any writes. Walk prints
   every 500 files; ~30 min at single-thread. Partial-sample dry run
   earlier today classified 1 000/57 595 all `ok` so nothing
   structural is expected to explode.
2. **Live migration** — drop `--dry-run`; same invocation. Writes
   atomically per file (tmp + `os.replace`); `--resume` implicit via
   the `already_current` short-circuit, so a killed run re-enters
   cleanly. Elapsed estimate ~2 h at 4 workers; 1 h at 8. Follow-on
   CSV at `runs/active/renormalize_needs_rescrape.csv` for cases
   whose HTML cache fell out during the pipeline migrations.
3. **Post-migration audit** — sanity-check a sampled v5 file carries
   `{tipo, url, text, extractor}` on both andamento links and
   documento entries; run the warehouse build end-to-end. Drop the
   `_normalize_documentos` version-tolerance for v1/v2/v3 shapes
   once we're confident all data is v5 (separate PR).

### Storage-migration strand (independent of backfill tiers)

6. **Run the full HTML cache migration** —
   `PYTHONPATH=. uv run python scripts/migrate_html_cache_to_tar.py --keep-dirs`
   first (full-corpus verification, ~30 s), then once a spot-check
   passes, the same command without `--keep-dirs` to reclaim the
   ~1.9 GB. Do not run this while a sweep is writing to the cache —
   the migration and the scraper both touch `data/cache/html/`.
   Tier-1 should be fully completed and archived before the
   migration, OR the migration can precede tier-1 entirely (it's
   faster than tier-1 will be). Recommend: **migrate before tier-1**
   — smaller blast radius if anything unexpected surfaces.
7. **Update `docs/data-layout.md`** to reflect the per-case
   tar.gz layout (one-line change to the HTML-cache example;
   module reference at line 102 remains accurate).
8. **Update `CLAUDE.md § Caches`** — the "one gzipped HTML
   fragment per tab" description is now stale. Change to "one
   tar.gz per case, containing plain-HTML members + incidente.txt."
9. **Implement `scripts/build_warehouse.py`** per the design at
   [`docs/warehouse-design.md`](warehouse-design.md). v1 is
   full-rebuild, manual trigger, ~2–3 min at current scale.
   Dependencies: `uv add duckdb`. Suggested TDD pattern: fixture
   case-JSON → `build_warehouse([fixture_dir])` → query the
   resulting `.duckdb` and assert row counts, nested-field
   correctness. Ship once tier-1 lands so the first real build
   includes the 2025 gap-fill.
10. **DuckDB warehouse v2 (deferred)** — post-sweep auto-refresh
    trigger from `run_sweep.py`'s cleanup phase. Only if manual
    refresh becomes tedious; don't build preemptively.

### Long-running carryovers

11. `CliffDetector` noise-reduction PR.
12. Next-class decision (ADI then RE, or RE directly).

## Known limitation — denominator composition and right-censoring

Preserved across cycles. Under FGV's §b rule (the project default —
see [`docs/hc-who-wins.md § Research question`](hc-who-wins.md#research-question)),
our `fav_pct` denominator is the set of cases with a recognized
terminating verdict. Pending cases excluded. Real costs for
mixed-vintage corpora: selection bias via processing speed,
right-censoring thrown away, denominator shrinkage on fresh data,
parser-gap pollution, temporal incomparability. Mitigations (not
yet implemented): split `None` into `pending` vs `parser_gap`,
report %-pending alongside every `fav_pct`, sensitivity analysis
via bracketing, Kaplan-Meier win curves on mature vintages.

## Known gaps in the `sessao_virtual` port

- **Vote categories are partial** — only codes 7/8/9 land in the final `votes` dict. See [`docs/stf-portal.md § sessao_virtual`](stf-portal.md#sessao_virtual--not-from-abasessao).
- **`documentos` values are mixed types**: string with extracted text (success) or original URL (fetch failed). Consumers must check `startswith("https://")`.
- **Tema branch has only one fixture test (tema 1020).** If you see drift there, probe another tema + add a fixture.

## Doc amendments queued (for post-backfill)

All four amendments landed 2026-04-18 alongside the v3 fixture
rebuild. Status:

- **`docs/process-space.md`** — no amendment needed (doc was
  already accurate on HC ~216 k).
- ✅ **`docs/rate-limits.md`** — updated § `4-shard proxy-rotation
  validation (2026-04-18)` with the 20.1 h combined-session
  results (54 841 ok / 72 646 processed, real-fail 0.016 %, zero
  WAF events) and promoted "rotation > throttle" to confirmed
  under 20 h. Noted the 8-shard pivot as pending validation.
- ✅ **`docs/performance.md`** — updated the 4-shard row
  annotation to reference 20.1 h cumulative load + real-fail
  rate; updated the "IP rotation is canonical" bullet to the
  same cumulative duration.
- ✅ **`docs/hc-who-wins.md`** — Full-HC-backfill bullet
  upgraded: 2.5 days at 4-shard promoted from math to empirically
  validated over 20.1 h; added 8-shard (~1.3 days) projection;
  noted the ~55 k on-disk capture status and year-priority
  gap-sweep queue. Sample-size estimates do not presume the
  old density ceiling — 216 k is the current anchor.

---

# Reference — how to run things

```bash
# Unit tests (226 tests, <5 s)
uv run pytest tests/unit/

# Ground-truth validation (HTTP parity against 6 fixtures)
PYTHONPATH=. uv run python scripts/validate_ground_truth.py

# HTTP scrape, one process, with PDFs
uv run judex coletar -c ADI -i 2820 -f 2820 -o json -d data/cases/ADI --sobrescrever

# Wipe all regenerable caches (safe; HC case JSONs under data/cases/ survive)
rm -rf data/cache
```

## Running sweeps

```bash
# One-shot sweep over a CSV of (classe, processo) pairs
PYTHONPATH=. uv run python scripts/run_sweep.py \
    --csv tests/sweep/shape_coverage.csv \
    --label my_sweep \
    --parity-dir tests/ground_truth \
    --out runs/active/<date>-<label>

# Long sweep with proxy rotation
PYTHONPATH=. uv run python scripts/run_sweep.py \
    --csv tests/sweep/<input>.csv \
    --label long_sweep \
    --proxy-pool config/proxies.a.txt \
    --out runs/active/<date>-<label>

# Resume (skip already-ok processes)
PYTHONPATH=. uv run python scripts/run_sweep.py \
    --csv <same-csv> --label <same> --out <same-dir> --resume
```

**Stopping a running sweep cleanly.**

```bash
ps -ef | grep run_sweep | grep -v grep           # find the pid
kill -TERM <pid>                                 # clean stop
# or: pkill -TERM -f "run_sweep.*<label>"
```

## Live sharded-sweep probe

```bash
PYTHONPATH=. uv run python scripts/probe_sharded.py \
    --out-root runs/active/2026-04-17-hc-full-backfill-sharded

grep -cH "\[rotate\]" \
    runs/active/2026-04-17-hc-full-backfill-sharded/shard-*/driver.log

pgrep -af "run_sweep.*hc_full_backfill_shard"
```

## Launching sharded sweeps

```bash
# Shard a CSV into N range-partitions
PYTHONPATH=. uv run python scripts/shard_csv.py \
    --csv tests/sweep/<input>.csv \
    --shards 4 --out-dir tests/sweep/shards/

# Launch N concurrent backfill shards
nohup ./scripts/launch_hc_backfill_sharded.sh \
    > runs/active/<dir>/launcher-stdout.log 2>&1 & disown

# Stop all shards cleanly
xargs -a runs/active/<dir>/shards.pids kill -TERM
```

## Marimo notebooks / judex CLI hub

```bash
uv run judex --help
uv run judex exportar --apenas hc_famous_lawyers
uv run marimo edit analysis/hc_famous_lawyers.py
```
