# Current progress — judex-mini

Branch: `main`. Prior cycle archived at
[`docs/progress_archive/2026-04-19_0500_schema-v4-v5-v6-and-mistral-default.md`](progress_archive/2026-04-19_0500_schema-v4-v5-v6-and-mistral-default.md)
— v4 → v5 → v6 schema cascade (extractor provenance, andamento/documento
link unification, ASCII-snake_case sessão metadata + ISO-only dates
+ `_meta` wrapper + typed `Pauta`), Mistral as default OCR provider,
monotonic-guard bypass under `--force`, fixtures regenerated as
bare-dict v6, v4-compat paths removed, 328 unit tests green.

**Status as of 2026-04-19 ~00:55 UTC: v6 schema shipped; production
migration is 22 % complete.** Live renormalize (`--classe HC
--workers 8`, detached) ran 6.75 min wall and produced
`ok=12669 / needs_rescrape=44926 / error=0` over 57 595 files. The
12 669 migrated cases are v6 on disk (`_meta` slot populated;
andamento uses `index` + ISO `data`; no `data_iso` sibling). The
44 926 in the rescrape bucket have incomplete HTML cache —
concentrated in older-scrape files (mostly v2 list-wrapped shape
on disk) whose tab set didn't include `abaPautas` / sessao JSON
when they were first cached. Rescrape CSV at
`runs/active/renormalize_needs_rescrape.csv`. Warehouse build
(`scripts/build_warehouse.py`) is still to be exercised end-to-end
against the migrated slice.

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
- [`docs/warehouse-design.md`](warehouse-design.md) — DuckDB warehouse schema + build pipeline.

## Working conventions

- **`analysis/`** — git-ignored scratch for this-session exploration (marimo notebooks, one-off scripts, raw JSON dumps). Safe to fill freely.
- **All non-trivial arithmetic via `uv run python -c`** — never mental math. See `CLAUDE.md § Calculations`.
- **Sweeps write a directory**, not a file. Layout in [`docs/data-layout.md § Sweep run artifacts`](data-layout.md#sweep-run-artifacts).

---

# Active task — lab notebook

## Task

**Renormalize the 57 595-file production corpus to schema v6.** The
schema cascade (v3 → v4 → v5 → v6) shipped in the prior cycle
without touching on-disk data. The live code now emits v6; the
warehouse build expects v6-friendly inputs; the renormalizer is
v6-aware via the current extractors. This task drives the bulk
migration.

## Plan

1. **Dry-run sample** — `--dry-run --workers 4 --limit 2000` to
   surface any systematic parse error introduced by the v6 changes
   (metadata key rename, ISO-only dates, `_meta` wrapper). Walk
   prints every 500 files; ~3 min at 4 workers.
2. **Full dry-run** — drop `--limit`, same cadence. ~30 min at 4
   workers. Goal: quantify `needs_rescrape` (incomplete HTML cache)
   and `error` counts before any write.
3. **Live migration** — drop `--dry-run`; writes atomically per file.
   `--resume`-safe via the `already_current` short-circuit. Expected
   wall ~2 h at 4 workers / ~1 h at 8.
4. **Post-migration audit** — sample 10 v6 files: confirm `_meta`
   slot exists with `schema_version=6`, andamento link carries
   `{tipo, url, text, extractor}`, sessão metadata keys are
   ASCII-snake_case, every date field is ISO-8601. Build the
   warehouse end-to-end against the migrated corpus.
5. **Clean up older-version tolerance** (separate PR). Once the
   audit confirms all data is v6, drop the v1/v2/v3 branches in
   `_normalize_documentos` and the pre-v6 fallbacks in
   `_flatten_case`. Keep the renormalizer itself version-tolerant.

## Expectations / hypotheses

- **H1** (expected): >95 % of files classify as `ok` in dry-run;
  `needs_rescrape` stays <5 %; `error` count is zero or a
  single-digit systematic issue. The v3 → v4 migration on the same
  corpus was clean; v4 → v5 → v6 are more conservative changes.
- **H0** (null, would falsify): a systemic `error` pattern shows up
  on an entire classe or year range. Would suggest a regression in
  an extractor the renormalizer re-runs.
- **H2** (unexpected): the `needs_rescrape` count is large (say,
  10 k+). Would imply the HTML cache has gone stale in some
  systematic way we hadn't tracked — not a v6 issue but something
  the migration would surface. Recovery: feed the rescrape CSV
  through `run_sweep.py` before the live migration.

## Observations

- **2026-04-19 — smoke-run clean.**
  `PYTHONPATH=. uv run python scripts/renormalize_cases.py --dry-run --workers 4 --limit 10`
  → 10/10 `ok`, 0 error, 0 needs_rescrape, 0.3 s wall (31 files/s).
- **2026-04-19 — bounded dry-run clean.**
  `PYTHONPATH=. uv run python scripts/renormalize_cases.py --dry-run --workers 8 --limit 2000`
  → 2000/2000 `ok`, 0 error, 0 needs_rescrape, 76.1 s wall (26 files/s
  stable after ramp-up). Throughput is I/O-bound, not CPU — 8-workers
  plateaued near 4-workers. Naive full-corpus ETA: **~37 min at 8
  workers** (57 595 / 26 f/s, computed via `uv run python -c`).
- **Open question 2 resolved.** The stale `to_iso` import in
  `scripts/renormalize_cases.py` is already gone (removed when the
  renormalizer was updated to emit the v6 shape). Grep confirms no
  `to_iso` import in the file.
- **2026-04-19 — corpus is HC-only.** `data/cases/` has one subdir:
  `HC` (57 595 files). The "57 595-file production corpus" figure
  and `--classe HC` count are identical — step 5 ("remaining
  classes") is a no-op at current corpus size.
- **2026-04-19 — live migration launched.** Detached:
  `nohup bash -c 'PYTHONPATH=. uv run python scripts/renormalize_cases.py
  --classe HC --workers 8 > runs/active/renormalize-hc.log 2>&1' & disown`.
  Driver PID in `runs/active/renormalize-hc.pid` (inner nohup'd
  bash; python worker tree lives as children). First 1000 files at
  27 f/s, 100 % `ok`. ETA ~36 min. Reconnect recipe:
  `pgrep -af renormalize_cases` to verify alive;
  `tail -f runs/active/renormalize-hc.log` for progress;
  `xargs -a runs/active/renormalize-hc.pid kill -TERM` for graceful
  stop (driver installs SIGTERM handlers and writes
  `needs_rescrape.csv` before exit).
- **2026-04-19 — live migration finished in 6.75 min.** Final tally:
  `ok=12669  needs_rescrape=44926  error=0`. Wall 405.2 s at 142 f/s
  (much faster than the 26 f/s dry-run projection because
  `needs_rescrape` short-circuits before the extractor chain — only
  the 12 669 `ok` paths did the full rebuild; those ran at roughly
  the projected rate). Rescrape CSV written to
  `runs/active/renormalize_needs_rescrape.csv` (44 926 rows, 439 KB).
  **H2 confirmed**: 78 % of the corpus has incomplete HTML cache.
  Dry-run `ok=2000` was misleading — lex-sorted iteration put
  recently-scraped (fully-cached) files first; stale-cache files are
  concentrated in the tail of the ordering.
- **2026-04-19 — v6 shape verified on migrated file.**
  `HC_118201-118201`: `_meta={schema_version:6, status_http:200,
  extraido:...}` at slot 0, no top-level `schema_version`, andamento
  has `index` + ISO `data` + no `data_iso` sibling. Migration is
  structurally correct on the files that ran through it.
- **2026-04-19 — legacy-shape files persist.** Sampled
  `HC_134348-134348` (in rescrape CSV): still the v2 list-wrapped
  shape (a dict inside a 1-element list). Untouched by this pass.
  The renormalizer's `_load_existing` can unwrap that shape; the
  blocker was missing HTML fragments, not JSON shape.
- **2026-04-19 01:17 → 06:12 — overnight chain (tiers 0→3) finished
  cleanly.** 4h 55min wall, matches the ~5h estimate. Wrapper at
  `scripts/overnight_t0123.sh`, chain pid was 197540, cron monitor
  cleaned up post-completion. Per-tier tally:

  | tier | year | CSV | ok | fail | wall | notes |
  |---|---|---|---|---|---|---|
  | 0 | 2026 |    917 |     0 |   917 |  ~2 min | all filter_skip (future-IDs); expected |
  | 1 | 2025 |  4,555 | 1,744 | 2,811 | ~46 min | 38% ok rate — mid-range filter_skip density |
  | 2 | 2024 | 13,609 | 10,361 | 1,966 | ~125 min | **shard-6 collapsed early at 02:40** (only 419/1701 records); 1,282 IDs ungrabbed in that slice |
  | 3 | 2023 | 11,825 | 10,042 | 1,783 | ~117 min | 85% ok rate |

  **Net-new captures: 22,147 HC cases**, all born v6. Aggregate
  throughput across the run: ~78 ok/min real-capture (below the
  92 ok/min projection but within ballpark). WAF behaved: only
  1 `collapse` regime hit (shard-6 of t2), a handful of
  `approaching_collapse` and `l2_engaged` hits in t2/t3. No
  cross-tier WAF carryover.
- **Two issues surfaced for later, neither blocking:**
  - **Tier-2 shard-6 ungrabbed slice** (~1,282 IDs in 2024 range
    `~239,271..240,972`). Tomorrow's `generate_hc_year_gap_csv.py
    --year 2024` regen will surface them automatically — they're
    not on disk so they re-enter the gap.
  - **Monitor false-positive bug.** `scripts/monitor_overnight.sh`
    flagged "stale workers" on completed-tier shards (e.g. tier-0
    shards alerting through the night even though they exited at
    01:19). The stale check should be scoped to only the
    currently-active tier (the one whose `shards.pids` the
    wrapper is currently waiting on). 150 false positives total
    overnight; zero actionable alerts. The chain itself worked,
    but the monitor needs a fix before reuse.
- **2026-04-19 ~09:00 — Phase 3 morning audit complete.**
  - **Anchor refresh.** `src/utils/hc_id_to_date.json` regenerated
    from every on-disk HC case: 9,897 → **79,742 anchors**, id
    range 82,959..271,060 → 48,933..271,139, date range 2003..2026
    → 1971..2026. File grew 581KB → 4.6MB; load time 577ms (one-shot
    at import). Backup at `…hc_id_to_date.json.bak-2026-04-19`.
    Tightening of `year_to_id_range()` is modest (~93 IDs at year
    boundaries) since modern years were already well-anchored;
    big wins in paper-era extrapolation. Probably worth a
    by-month subsample later to keep the file lean.
  - **20-file v6 audit on new captures** — 20/20 clean
    (`_meta.schema_version=6`, andamento link well-formed dict,
    ISO `data_protocolo`).
  - **Warehouse builder rewrite landed.** Original `_bulk_insert`
    used `executemany` parameter-binding, which choked at 15+ min
    on the full 79k corpus and never completed. Four-fix sequence:
    (1) Arrow registration bulk insert (~40-50× speedup); (2)
    schema-aware INTEGER coercion (corpus has occasional
    string-shaped numerics); (3) VARCHAR / VARCHAR[] coercion
    (`numero_origem` was `[int]` in some rows, `[str]` in others);
    (4) **streamed PDF rows + eager row-list clearing** so peak
    RAM is one table at a time, not all five stacked (PDFs alone
    decompress to ~1 GB; WSL2 only has 2.3 GB available). New
    capability: `--year YYYY --classe HC` for fast iteration
    sub-warehouses (uses `hc_calendar.year_to_id_range`).
  - **Full warehouse built** at `data/warehouse/judex.duckdb` —
    722 MB, 79,742 cases / 268,157 partes / **1,086,647 andamentos** /
    30,504 documentos / 30,387 pdfs, **wall 184.6s** (was 15+ min
    and killed). Phase 1F sanity SQL all green: 100% v6, 0 NULL
    `data_protocolo` (HC), 0 andamento link inconsistencies,
    plausible outcome distribution (58% nao_conhecido, 10%
    denegado, 3% concedido).
  - **2026 sub-warehouse** at `data/warehouse/judex-2026.duckdb` —
    262 MB, 3,098 cases, built in 21.9s. Fast iteration target
    for analyses scoped to one year.
  - **Year coverage after tonight** (HC): 2026=3,099, **2025=13,365,
    2024=10,827, 2023=11,099** (last two grew ~12× from tonight),
    2022=1,160 ← **next big gap (tier-4)**, 2021=7,423, then
    declining through 2013 (511) plus paper-era stragglers. Stray
    `2000: 1` outlier worth a one-line investigation later.
- **Caveat on warehouse "100% v6".** The warehouse reports v6 for
  every case because `_flatten_case` injects `schema_version=6`
  into its output dict — it's a *structural* soundness signal, not
  a *data completeness* one. The 44,926 stale-cache files made it
  into the warehouse with whatever fields their incomplete HTML
  cache could yield (tab fragments missing → empty
  `andamentos`/`documentos`/`pautas` slots for those rows). If a
  cross-case query mysteriously misses andamentos for a chunk of
  older HCs, that's the explanation, not a v6 regression.
- **2026-04-19 ~09:30 — second renormalize pass, with two fixes.**
  Complaint from TODO: old data still used truncated
  `#partes-resumidas` authors + stale `primeiro_autor`; pautas
  empty. Two code changes shipped (+11 unit tests, 391 suite green,
  ground-truth 0 diffs):
  - `scripts/renormalize_cases.py`: split `TABS` into
    `_REQUIRED_TABS` (detalhe, informacoes, partes, andamentos,
    sessao) and `_OPTIONAL_TABS` (decisoes, deslocamentos, peticoes,
    recursos, pautas). Missing optional → `""` placeholder
    (extractors no-op on empty); missing required → still
    `needs_rescrape`. Prior strict all-or-nothing `_read_all_cached`
    was punting cases to rescrape just because their cache predated
    `abaPautas`/`abaDecisoes` (added in commit 1241d22).
  - `src/data/reshape.py`: `reshape_to_v6` now re-derives
    `primeiro_autor` via `extract_primeiro_autor(partes)`. Derived
    value wins; stale falls back to existing when partes has no
    matching `AUTHOR_PARTY_TIPOS` prefix.
- **2026-04-19 ~09:31 — shape-only pass, whole corpus.**
  `uv run python scripts/renormalize_cases.py --mode shape-only
  --force --workers 4` → **79,742 files in 84.2 s, 947 f/s,
  0 error, 0 needs_rescrape.** All files now structurally v6.
  But shape-only can't fix content drift: on-disk partes lists
  were still `#partes-resumidas`-collapsed for ~95 % of HC files.
- **2026-04-19 ~09:33 → 09:48 — full-mode pass, whole corpus.**
  `uv run python scripts/renormalize_cases.py --force --workers 8`
  → **ok=34,816 / needs_rescrape=44,926 / error=0, wall 886.2 s
  (90 f/s aggregate, ~37 f/s real-extraction rate).** Significant
  uplift: prior pass was ok=12,669; today's is ok=34,816 (**2.75×
  improvement**) due to the optional-tabs relaxation letting cases
  whose caches predated `abaPautas`/`abaDecisoes` rebuild from
  what's actually present.
- **Content uplift on the re-extracted slice** (5000-file sample,
  split by bucket):

  |                        | Re-extracted (n=2228) | Still truncated (n=2772) |
  |------------------------|:---------------------:|:------------------------:|
  | `"E OUTRO"` sentinel   | **0.0 %**             | 21.8 %                   |
  | Multi-IMPTE present    | **25.9 %**            | 3.0 %                    |
  | PROC entry present     | 10.5 %                | 1.2 %                    |
  | `pautas` populated     | **18.7 %**            | 0 %                      |

  "E OUTRO" sentinel dropped from 21.8 % → 0 % on re-extracted
  files; multi-IMPTE presence jumped 3 % → 26 % (≈9× more full
  lawyer rosters surfaced); pautas now populated in 18.7 % of
  re-extracted HCs (was 0 % — field was empty until v6 added
  `extract_pautas`). These are the concrete payoffs of the
  `#todas-partes` + typed-pauta + re-derivation work.
- **2026-04-19 ~09:50 — root cause of the 44,926 rescrape cliff.**
  **78.5 % (35,254 files) have a flat-directory HTML cache** —
  the pre-tar.gz format (`HC_N/abaXxx.html.gz` per-tab files)
  that `html_cache.read` doesn't open. Only 21.5 % (9,671) have
  no cache at all. The renormalizer's `_read_all_cached` assumes
  tar.gz; it predates (or missed) the cache-format migration.
  Three recovery options:
  - **A (fast)**: one-shot converter flat-dir → tar.gz for the
    35,254 recoverable cases, then re-run renormalizer. Zero
    HTTP, ~5 min wall estimated.
  - **B (thorough)**: `run_sweep.py --csv
    runs/active/renormalize_needs_rescrape.csv` — refresh HTML +
    handles the 9,671 no-cache tail in one pass. ~90 min WAF-bound.
  - **C (permanent)**: teach `html_cache.read` to fall back to
    flat-dir when tar.gz absent (~20 LOC). Covers any future
    flat-dir cache that slips in too.
- **2026-04-19 ~09:55 — warehouse rebuilt post-migration.**
  `uv run python scripts/build_warehouse.py` →
  `data/warehouse/judex.duckdb`, **722 MB, 117.6 s, 79,742 cases
  / 268,157 partes / 1,086,647 andamentos / 30,504 documentos
  / 30,387 pdfs.** Warehouse now reflects the re-extracted slice
  with untruncated partes + populated pautas. Same caveat as
  before: 56 % of rows still carry the pre-migration truncated
  content because they're in the rescrape bucket. A
  `reextracted_at` / `content_version` column would let analyses
  filter to the clean slice; not yet added.
- **2026-04-19 ~10:00 — HC 2026 PDF bytes sweep launched.**
  `scripts/baixar_pecas.py --csv runs/active/2026-04-19-hc-2026-pdfs/targets.csv`
  against the 3,098 HC 2026 cases surfaced via
  `judex-2026.duckdb`. 9,306 distinct PDF URLs from
  `andamentos.link_url`, ~10 h wall at `--sleep-throttle 2.0`.
  Detached per `docs/agent-sweeps.md`; pid in `baixar.pid`.
  Progress at 3.5 h in: 3,404 ok / 0 fail, one absorbed 403.
  **Note on target resolution**: `_find_case_file` in
  `peca_targets.py` does one `rglob` per CSV row over the full
  79k-file `data/cases/HC` tree — ~2 min of pure CPU before the
  first HTTP. Worth indexing `{processo_id → path}` once per root.
- **2026-04-19 — document-universe audit (the prompt was
  "are there other PDFs associated with a case").** Scope
  clarified and written to
  [`docs/stf-portal.md § Document sources`](stf-portal.md#document-sources--the-full-universe-of-pdfs--rtfs--voto-html):
  - Exactly two URL-bearing surfaces per case:
    `andamentos[].link.url` (PDF + RTF) and
    `sessao_virtual[].documentos[].url` (voto PDFs, two
    hosts). Nothing else — verified against the warehouse
    tables and every `aba*.html.gz` tab.
  - **Corrected an earlier misreading.** I'd said sessão-virtual
    votos from `sistemas.stf.jus.br/repgeral/votacao?texto=<id>`
    were HTML-text (no OCR). Wrong: a direct probe shows **both**
    sistemas (`octet-stream`, `%PDF-1.6`) and
    digital.stf.jus.br (`application/pdf`, `%PDF-1.7`) return
    binary PDFs. Ground-truth `text` fields are populated because
    an OCR step already ran during capture — not because the
    endpoint serves text.
  - **Stale-JSON gap surfaced on 2026 corpus.** All 1,302
    `sessao_virtual.documentos[].url` entries across the 625
    2026 HCs are null in the production JSON. Running the current
    `parse_sessao_virtual` on the *cached JSON* populates them
    immediately (tested on HC 270392 and HC 128377). So this is
    a re-extraction gap — the JSONs were written under an older
    `_build_documentos` — not a scraper bug. Fix is local CPU,
    zero STF traffic.
  - **Known target-filter gap.** `peca_targets.py`'s
    `_iter_case_pdf_targets` filters on `url.lower().endswith(".pdf")`,
    which silently drops the 372 `DECISÃO DE JULGAMENTO` RTF URLs
    (`downloadTexto.asp?ext=RTF`) — and misses sessão-virtual
    documentos entirely (never walked). Two targeted fixes land
    both in one change.
- **2026-04-19 ~13:45 — warehouse-vs-JSON benchmark.**
  `analysis/warehouse_benchmark.py` runs the same analyst query
  (per-year case count, andamento count, distinct `primeiro_autor`)
  two ways, each in its own subprocess so `getrusage` peaks are
  independent.

  |                        | warehouse    | JSON walk    | ratio |
  |------------------------|--------------|--------------|-------|
  | wall                   | **0.157 s**  | **39.41 s**  | **251× faster** |
  | peak RSS               | 103.8 MB     | 56.9 MB      | warehouse heavier (DuckDB engine baseline) |
  | filesystem bytes read  | ~tens of MB  | 7.36 GB      | ~100× less I/O |
  | on-disk footprint      | 722 MB       | 3.8 GB       | **5.3× more compact** |

  Head/tail rows match exactly on both paths (e.g. `[2026, 3099,
  35682, 2862]`). Warehouse wins by two orders of magnitude on wall
  and I/O; loses ~47 MB on peak RSS (DuckDB engine baseline vs a
  small Python dict). JSON mode is parse-bound (51 % CPU, 7.4 GB of
  filesystem reads for 79,742 files). Investment validated: any
  analyst query that touches >1 field per case amortises the
  warehouse instantly.
- **2026-04-19 ~13:45 — v6 representation audit on `judex.duckdb`.**
  Fit of `src/warehouse/builder.py` against the current v6 schema:
  - ✅ `_meta` slot → `cases.*` siblings (`schema_version`,
    `status_http`, `extraido`); reads both `_meta.*` and pre-v6
    top-level via `.get(…, item.get(…))`.
  - ✅ `outcome` dict exploded into four columns
    (`outcome_verdict/_source/_source_index/_date_iso`) via
    `_unpack_outcome`; tolerates bare-string v3 outcomes still on
    disk.
  - ✅ v5+ andamento `link` dict exploded into
    `link_tipo/_url/_url_sha1/_text/_extractor`; sha1 precomputed
    for joining to `pdfs`.
  - ✅ `sessao_virtual[].documentos` positional PK
    `(session_idx, doc_seq)` preserves v4 duplicates; v1/v2/v3
    shapes handled by `_normalize_documentos`.
  - ❌ **`pautas` is not represented.** v6 added typed `Pauta` via
    `extract_pautas`; builder has zero pauta logic (`grep -c pauta
    src/warehouse/builder.py` → 0). 18.7 % of the re-extracted
    slice has populated pautas — all invisible to SQL today.
  - ⚠️ **Content-stale residue** (probed on full warehouse):
    **9,877 partes rows** carry the `LIKE '%E OUTRO%'` truncation
    sentinel, **92 cases** have zero partes, **16,153 cases** have
    NULL `outcome_verdict`. All three are the 44,926 stale-cache
    rescrape cliff leaking in — structurally v6, content stale.
    Author-based analyses on the full corpus will over-count a fake
    author 9,877 times unless filtered.
  - ⚠️ **PDF join skew.** `documentos` → `pdfs` joins
    **13,075 / 30,504 rows** (42 %) via `url_sha1`;
    `andamentos.link_url_sha1` → `pdfs` joins only **167 / 240,995
    rows** (0.07 %). Documentos are well-populated (session voto
    PDFs); andamento-linked PDFs were never bulk-downloaded until
    today's `baixar-pecas` run (PID 574055).
- **2026-04-19 ~14:05 — `pautas` table shipped in builder, both
  warehouses rebuilt.** Added `pautas` schema + `_flatten_pautas` +
  insert call + manifest column (`n_pautas`) in
  `src/warehouse/builder.py`. `BuildSummary` and the CLI grew a
  `n_pautas` field. TDD: 2 new tests (v6 flatten + absent/empty
  tolerance) + 1 updated manifest assertion; 395 / 395 unit tests
  green. Rebuilds:

  | warehouse           | cases  | partes  | andamentos | documentos | **pautas** | pdfs   | wall   | size     |
  |---------------------|-------:|--------:|-----------:|-----------:|-----------:|-------:|--------|----------|
  | `judex.duckdb`      | 79,742 | 268,157 | 1,086,647  | 30,504     | **7,463**  | 30,387 | 168 s  | 517.8 MB |
  | `judex-2026.duckdb` |  3,098 |   9,645 |    35,681  |  1,302     |       0    |      0 |   4.5 s |   8.5 MB |

  **Pautas sanity**: 7,463 rows across 6,737 distinct cases (8.5 %
  of the corpus); date range 2016-04-12 → 2026-04-09; 0 NULL
  `data_iso`. Top types: `PAUTA PUBLICADA NO DJE - 1ª TURMA`
  (4,235), `2ª TURMA` (3,045), `PLENÁRIO` (82), `INCLUÍDO NA LISTA
  DE JULGAMENTO` (55). 2026 sub-warehouse has 0 pautas — new
  filings, too early for session scheduling.

  **Full warehouse shrank 722 → 518 MB** (28 % smaller). No data
  lost (fact-table counts identical). Likely DuckDB recompacted on
  the atomic swap.
- **2026-04-19 ~14:05 — PDF tracking gap confirmed.** Cache
  inventory at rebuild time: 5,401 `.pdf.gz` (bytes-only), 30,387
  `.txt.gz` (text-extracted). Warehouse's `_iter_pdf_rows` globs
  only `.txt.gz`, so it tracks **30,387 / 35,788 = 84.9 %** of
  on-disk PDF artifacts. The 5,401 gap is today's in-flight
  `baixar-pecas` output that hasn't been through `extrair-pdfs`
  yet. Join counts unchanged vs pre-rebuild: `andamentos` → `pdfs`
  167; `documentos` → `pdfs` 13,075. To close the gap: after the
  downloader finishes (~5 h more), run `extrair-pdfs --classe HC
  --provedor mistral` over the 2026 scope, then rebuild. That step
  turns `.pdf.gz` into `.txt.gz` + `.extractor` sidecar, which the
  next builder pass ingests.

## Re-extraction status — what's v6, what isn't

The schema cascade (v3→v4→v5→v6 + andamento link unified +
extractor provenance + `_meta` wrap + ISO-only dates + typed
`Pauta`) changed enough surface area that **every cached case
needs the extractor chain re-run** for the on-disk JSON to reflect
the current code. State of that re-extraction:

| Bucket | Count | Re-extracted? | What still needs to happen |
|---|---|---|---|
| Renormalized to v6 (full-mode, today's second pass)   | **34,816** | ✅ done — extractor chain re-ran on cached HTML 2026-04-19 09:48; `#todas-partes` partes + typed pauta + re-derived `primeiro_autor` | nothing |
| Shape-only migrated only                              | **44,926** | ⚠️ structure-v6 but content-stale — `_meta` slot + ISO dates + dict-shaped outcome in place, but partes are still `#partes-resumidas`-truncated and pautas are empty | depends on recovery path (see below) |
| **Rescrape cliff — flat-directory HTML cache on disk** | **35,254** | ❌ recoverable locally: cache exists in pre-tar.gz per-tab format, renormalizer doesn't read it | one-shot flat-dir→tar.gz converter + re-run renormalizer (~5 min, zero HTTP) OR fall-back reader in `html_cache.read` |
| **Rescrape cliff — no cache at all**                   | **9,671**  | ❌ genuinely absent: never scraped-with-cache or cache deleted | `run_sweep.py --csv runs/active/renormalize_needs_rescrape.csv` — WAF-bound, ~90 min |
| New captures from 2026-04-19 overnight (tiers 0–3)    | 22,147 net-new HC cases | ✅ born v6 (current scraper writes v6 directly) | nothing |

**The 2026-04-19 overnight did NOT touch the 44,926 stale-cache
bucket** — those IDs were already on disk (just stale-shape) so
the year-gap CSV generator excluded them. They remain on the
explicit rescrape backlog (open question 3). Revised recovery
path after today's root-cause analysis (2026-04-19 ~09:50):
35,254 have flat-directory cache recoverable locally (~5 min
with a format-converter one-shot); only 9,671 truly need an
HTTP rescrape (~20 min at the smaller count).

## Decisions

- **Run renormalize from a detached process** (`nohup … & disown`)
  since it'll span an hour+ and the Claude Code window might die.
  `shards.pids` pattern doesn't apply (single-process parallelism via
  `ProcessPoolExecutor` inside the script), but the durable state
  still lives in atomic per-file writes — reconnecting from a fresh
  window reads the tally by counting files matching `schema_version`
  in the JSON.

## Open questions

1. Should the v6 warehouse build drop the `data_protocolo_iso`
   column as redundant (now that `data_protocolo` is ISO)? Or keep
   as a no-cost alias? Lean toward drop to avoid two-names-one-value
   rot.
2. ~~`scripts/renormalize_cases.py` still has a stale `to_iso`
   import reference~~ — resolved; grep confirms absence.
3. **Clear the 44 926 rescrape cliff — which path?** Root cause
   (2026-04-19 ~09:50): **78.5 % (35,254) have flat-directory
   HTML cache locally**, unread by the renormalizer; only 21.5 %
   (9,671) truly lack cache. Three options:
   (a) stop here — 34,816 v6-content files (44 % of corpus) is
   enough to validate the warehouse end-to-end; defer until
   analyses demand broader coverage;
   (b) **flat-dir → tar.gz converter** (zero HTTP) + re-run
   renormalizer on the 35,254 — clears the biggest slice cheaply;
   follow with targeted sweep on the residual 9,671;
   (c) **permanent fix in `html_cache.read`**: fall back to
   flat-dir when tar.gz absent, ~20 LOC. Makes the renormalizer
   idempotent across both formats without a one-shot migration.
   Preference: (c) + (b) residual sweep. Not yet decided.
4. **Strategy retrospective**: a principled v5→v6 migration could
   have been JSON-only (10× faster) for ~90 % of the diff (key
   renames + `_meta` wrap + date-format change), with HTML only
   needed for `extract_pautas` — one fragment, not eleven. Worth
   capturing as a design pattern for the next schema bump.

## Next steps (this task)

Smoke-run + bounded dry-run landed clean (see Observations). Plan
below is the **agreed process** if the session dies between steps —
reconnect from a fresh window, read this file, resume from whichever
step hasn't been marked done in the Observations log.

1. ~~Smoke-run (10 files).~~ Done 2026-04-19, clean.
2. ~~Bounded dry-run (2000 files, 8 workers).~~ Done 2026-04-19, clean.
3. **Skip full dry-run.** Justification: H1 held strongly on 2000-file
   sample (0 error / 0 needs_rescrape); renormalizer's atomic-write
   contract (`tmp + os.replace`) + `--resume`-safe `already_current`
   short-circuit mean the blast radius of any surprise is "re-run
   with `--force`", not data loss.
4. **Live — HC first.** `--classe HC --workers 8` (~55 k files, ~35
   min at 26 f/s). HC is the biggest class; any systematic edge case
   surfaces here. Fire detached:

   ```bash
   nohup PYTHONPATH=. uv run python scripts/renormalize_cases.py \
       --classe HC --workers 8 \
       > runs/active/renormalize-hc.log 2>&1 & disown
   echo $! > runs/active/renormalize-hc.pid
   ```

   On reconnect from a crashed window: `pgrep -af renormalize_cases`
   to verify alive; `tail -f runs/active/renormalize-hc.log` for
   progress; `wc -l` on `runs/active/renormalize_needs_rescrape.csv`
   for rescrape count (written on exit only).

5. **Live — remaining classes.** `--workers 8` with no `--classe`
   filter, after step 4 completes. Remaining ~2.6 k files; ~2 min.
   `--resume`-safe: already-v6 HC files short-circuit via
   `_meta.schema_version == 6` check.
6. **Post-migration audit.** Sample 10 v6 files across classes:
   confirm `_meta` slot, `_meta.schema_version == 6`, andamento link
   is `{tipo, url, text, extractor}`, sessão metadata keys are ASCII
   snake_case, every date field is ISO-8601. Spot-check one HC + one
   ACO + one RE.
7. **Warehouse end-to-end.**
   `PYTHONPATH=. uv run python scripts/build_warehouse.py` → exercise
   all 5 tables + manifest against the migrated corpus. Expected
   wall a few minutes; full-rebuild by design.
8. **Drop older-version tolerance** (separate PR). Delete v1/v2/v3
   branches in `_normalize_documentos` and pre-v6 fallbacks in
   `_flatten_case` / `_flatten_andamentos` once step 6 confirms all
   data is v6.

## Analytical readiness — actions after 2026-04-19 ~13:45 audit

Ordered by urgency. Items 1–2 are hands-off ("do nothing yet"); 3–5
are the real backlog this audit surfaces.

1. **Hold on warehouse rebuilds while `baixar-pecas` (PID 574055)
   runs.** ~5 h remaining at 0.27 tgt/s. Concurrent `.pdf.gz`
   writes + a warehouse read of the PDF cache is fine in principle
   (builder streams), but a rebuild now captures a half-populated
   state. Rebuild once the run finishes (~19:35 local).
2. **Then rebuild `judex-2026.duckdb` (fast, ~22 s) and
   `judex.duckdb` (~2 min).** Validate the andamento→pdfs join
   climbs from 167 → the expected ~3 k-row level for 2026 HC.
3. **Add a `pautas` flatten to the builder.** Small, self-contained:
   - schema SQL: `CREATE TABLE pautas (classe, processo_id, seq,
     data_iso, tipo, descricao, julgador, link_url, link_url_sha1)
     PRIMARY KEY (classe, processo_id, seq)`;
   - new `_flatten_pautas(item: dict) -> list[dict]` alongside
     `_flatten_andamentos` (pautas share the same `link` dict shape
     post-v6);
   - `_bulk_insert(con, "pautas", pautas_rows); pautas_rows.clear()`
     in `build()`.
   Unlocks session-level + pauta-facet analyses and brings the
   18.7 % of re-extracted cases with populated pautas into SQL.
4. **Clear the rescrape cliff — open question 3 option (c).**
   Flat-dir fallback in `html_cache.read` (~20 LOC) + re-run
   `renormalize_cases.py --force --workers 8`. Recovers 35,254 of
   the 44,926 stale-cache cases locally (zero HTTP, ~15 min wall).
   Residual 9,671 go through `run_sweep.py --csv
   runs/active/renormalize_needs_rescrape.csv` afterwards (~90 min
   WAF-bound). Drops the "E OUTRO" partes count from 9,877 toward
   zero and populates pautas on the recovered slice.
5. **Add `content_version` (or `reextracted_at`) to `cases`.** One
   column at flatten time, derived from `reshape_to_v6` provenance
   (e.g. whether `partes` came from `#todas-partes` vs stale — a
   reasonable proxy: `all(nome NOT LIKE '%E OUTRO%' for nome in
   partes)` AND `len(pautas) > 0 OR session_count == 0`). Lets
   analyses `WHERE content_version >= 2` without `LIKE` heuristics.
   Fold in alongside step 3.

Additional housekeeping surfaced en route (not blocking analyses,
recorded for triage):

- **`_find_case_file` in `peca_targets.py` rglob-per-row** — ~2 min
  of pure CPU before the first HTTP on the 2026 sweep launch.
  Index once (`{processo_id: path}`) at CSV ingest.
- **`peca_targets.py` target-filter gap** — drops 372 RTF URLs
  (`downloadTexto.asp?ext=RTF`), doesn't walk `sessao_virtual
  documentos`. Both fixed in one change.
- **Stale `sessao_virtual.documentos[].url` in 2026 corpus** —
  all 1,302 URLs null on disk; re-running `parse_sessao_virtual`
  on cached JSON populates them. Re-extraction gap, not a scraper
  bug. Folds into step 4's renormalizer re-run.
- **Open question 1** (drop `data_protocolo_iso` as redundant under
  v6) — no new info; still punted.

## Request-footprint audit (2026-04-19 ~afternoon)

Ad-hoc count of every HTTP GET made per case under the current HTTP
backend. Goal was to find cuts that buy WAF headroom so we can
push the scrape rate harder without tripping 403s. Source: walk of
`src/scraping/scraper.py` + extractors + `docs/stf-portal.md`
field→source map.

**Per-case baseline.** Small case (AI-style, `fetch_dje=False`,
no sessão virtual) = **12 GETs**: 11 on `portal.stf.jus.br` + 1 on
`sistemas.stf.jus.br`. Medium HC with DJe + sessão virtual ≈
**30–40 GETs first run, ~15 with cache**. Three independent WAF
buckets (`portal`, `sistemas`, `digital`) — interleaving across
origins already paces the per-IP reputation counter; the per-case
token budget that matters is **portal-bucket only**.

Portal-bucket GETs (the WAF-bound ones):

| # | Endpoint                              | Populates                          | Verdict                           |
|---|---------------------------------------|------------------------------------|-----------------------------------|
| 1 | `listarProcessos.asp` (302)           | `incidente`                        | Keep — entry point                |
| 2 | `detalhe.asp`                         | cookies + base metadata            | Keep — cookies needed for abaX    |
| 3 | `abaInformacoes.asp`                  | `assuntos`, `origem`, …            | Keep                              |
| 4 | `abaPartes.asp`                       | `partes`, `primeiro_autor`         | Keep                              |
| 5 | `abaAndamentos.asp?imprimir=`         | `andamentos[]` (+ PDF URLs)        | Keep                              |
| 6 | `abaDeslocamentos.asp`                | `deslocamentos`                    | **Candidate cut** — low use       |
| 7 | `abaSessao.asp?tema=`                 | `tema` id (regex)                  | Keep (gates sistemas `tema=`)     |
| 8 | `abaDecisoes.asp`                     | **nothing — fetched, not parsed**  | **CUT** — pure waste (~57 B stub) |
| 9 | `abaPautas.asp`                       | `pautas`                           | Keep (v7 just wired parsing)      |
| 10| `abaPeticoes.asp`                     | `peticoes`                         | Keep (class-gate candidate)       |
| 11| `abaRecursos.asp`                     | `recursos`                         | **Candidate skip** — ~1.8 s, usually empty on HC/AI |
| 15| `dje/listarDiarioJustica.asp`         | `publicacoes_dje[]` listing        | Conditional (`fetch_dje`) — already gated |
| 16+| `dje/verDiarioProcesso.asp`          | DJe entry detail                   | Keep if DJe on                    |
| 17+| `dje/verDecisao.asp?texto=`          | RTF decision body                  | Keep if DJe on                    |

Sistemas-bucket (separate WAF counter, not the bottleneck):
`repgeral/votacao?tema=` (conditional), `?oi=` (always), `?sessaoVirtual=` (1 per OI).

**Redundancy findings.** No data overlap between tabs —
`abaInformacoes` and `detalhe` both mention `assuntos` but at
different granularity. The three PDF sources (andamento links,
sessão-virtual documentos, DJe RTF) are disjoint, all needed. The
real waste is **`abaDecisoes.asp`: always fetched, never parsed**
(the Selenium path dropped it and the HTTP port kept the fetch).
Secondary: `abaRecursos.asp` is slow and usually empty on HC/AI.

**Optimization ladder** (portal-bucket savings per case):

1. **Delete `abaDecisoes.asp` fetch.** Free. −1 GET. No downstream reader.
2. **Class-gate `abaRecursos.asp`** (skip on HC/AI by default). −1 GET + ~1.8 s wall on typical cases.
3. **Audit + gate `abaDeslocamentos.asp`.** −1 GET. Needs warehouse-usage check first.
4. **Class-gate `abaPautas` / `abaPeticoes`** on monocratic classes. −1–2 GETs situationally.

Lean "fast sweep" floor: **7 portal GETs + 1 sistemas GET = 8 total**
per case (vs today's 12 on the no-DJe path). ~33 % fewer requests,
and more importantly **−3 portal-bucket tokens** where the WAF
actually lives.

**Decision:** ship #1 (delete `abaDecisoes.asp`) as a standalone
chore commit — zero risk. #2 and #3 wait on a usage audit (notebook
+ warehouse grep for `deslocamentos` / `recursos` reads). Don't
pipeline these into the v6 renormalize; they're scraper-side, not
data-side.

**Followups (not yet opened as issues):**
- audit `recursos` / `deslocamentos` downstream usage in
  `notebooks/`, `src/warehouse/`, and the warehouse DuckDB schema.
- measure portal-bucket `ceil` under current WAF by holding other
  origins constant — needed to quantify how much faster the fast
  sweep actually runs.

---

# Strategic state

## What just landed

- **Schema v8 — strip inline Documento text, cache becomes canonical** (2026-04-19).
  Every `Documento` slot (`andamentos[].link`, `sessao_virtual[].documentos[]`,
  `publicacoes_dje[].decisoes[].rtf`) now carries `text=None` and
  `extractor=None` on disk. `peca_cache` (`data/cache/pdf/<sha1(url)>.{txt.gz,extractor}`)
  is the single source of truth — the `Documento` docstring's claim
  ("struct is a pointer, not a payload") is finally accurate. Fetchers
  (`_make_pdf_fetcher`, `resolve_documentos`, `_resolve_publicacoes_dje`)
  still download + extract every URL for the cache-warming side
  effect but discard the returned text. Warehouse builder gained
  `_resolve_text` + `_resolve_extractor` (keyed on `sha1(url)` against
  `pdf_cache_root`, cache-first with inline pre-v8 fallback) so
  `andamentos.link_text` / `documentos.text` / `.extractor` columns
  stay populated uniformly across v6–v8 cases. `reshape_to_v8`
  (renamed from `reshape_to_v7`) strips inline text on migration;
  idempotent. `PublicacaoDJe.decisoes[].texto` (HTML-extracted) is
  retained as the DJe fast-path — content-equal to the stripped RTF
  per the earlier finding, no information lost. The DJe `texto` is
  the only per-Documento-like inline text surviving v8; everything
  else is pointer-only. 412 unit tests green (+2 new v8 warehouse
  resolver tests covering JSON-null cache-resolve and cache-wins-
  over-stale-inline). E2E validated on HC 158802: 22 Documento slots
  on a fresh scrape, all pointer-only; cache still holds 24.5 KB of
  extracted text. Docs: `data-dictionary.md § v8`; `Documento`
  docstring rewritten.
- **Schema v7 — `publicacoes_dje` field + DJe scraper** (2026-04-19).
  New top-level `publicacoes_dje: List[PublicacaoDJe]` on every case.
  Three HTTP layers (same `portal.stf.jus.br` WAF bucket as the tabs):
  `listarDiarioJustica.asp` → `verDiarioProcesso.asp` (per entry) →
  `verDecisao.asp?texto=<id>` (RTF per decisão). `parse_dje_listing`
  + `parse_dje_detail` in `src/scraping/extraction/dje.py` are pure;
  orchestration in `scraper.py` (`_make_dje_*_fetcher` + `_resolve_publicacoes_dje`)
  gates on `fetch_dje=True` kwarg. `DecisaoDJe.kind` ∈ `{decisao,
  ementa}` — EMENTA is a decisao-shaped `<p>+<a>` block on the
  Acórdão-section variant, discriminated by `"EMENTA:"` prefix.
  HTML cache picks up two pseudo-tab keys: `dje_listing` and
  `dje_detail_<sha1[:16]>`. RTFs flow through the existing
  `peca_cache`. Renormalizer seeds `[]` on pre-v7 corpus; shape-only
  mode plus tolerant cache-rebuild (`_rebuild_publicacoes_dje` skips
  entries whose detail HTML isn't cached). All 7 ground-truth
  fixtures bumped to v7 via `reshape_to_v7`; `publicacoes_dje` added
  to `SKIP_FIELDS` (reverse-chrono list grows at head, not tail, so
  the existing `_diff_growing_list` tail-append semantics don't fit).
  HC 158802 ground truth now carries the real 6-entry populated
  data (+24.5 KB inline RTF text) as the canonical DJe regression
  fixture. 407 unit tests green. E2E validated on HC 158802: 6
  publicações, 7 decisões, 24.5 KB of RTF text; cache-warm re-scrape
  0.29 s. Docs: `stf-portal.md § DJe flow`, `data-dictionary.md § v7`,
  `data-layout.md` pseudo-tab entries.
- **Side-effect bug fix: `peca_utils.extract_document_text` UA** (2026-04-19).
  Bare `requests.get()` was sending `python-requests/*` → STF's WAF
  permanently 403s non-browser UAs (per `docs/stf-portal.md` gotcha).
  `sistemas.stf.jus.br` and `digital.stf.jus.br` happened to be more
  permissive so the bug was silent until the DJe RTFs (served from
  `portal.stf.jus.br/servicos/dje/`) hit it. Fixed by passing a
  Chrome UA. Probably unsticks an unknown count of prior
  silent-failure PDF/RTF downloads on portal-host andamento links.
  No test coverage was pinning this; adding one would need a
  fixture capture of the 403 behavior, which I didn't chase.
- **Finding: DJe HTML `texto` ≡ RTF `rtf.text` (content-equal)** (2026-04-19).
  Every one of HC 158802's 7 decisão blocks is character-identical
  between `decisoes[].texto` (HTML-extracted, single-paragraph
  join) and `decisoes[].rtf.text` (RTF, paragraph-preserving) after
  whitespace normalization (`re.sub(r'\s+', ' ', s.replace('\xa0',
  ' '))`). Raw-length deltas (e.g. 18066 vs 18091 on the DJ 127
  monocratic) are purely `\n`-vs-` ` and `\xa0`-vs-`  `. Implication
  for the upcoming v8 strip: the DJe RTF is redundant with its
  HTML sibling — unlike `andamentos[].link.text` (full PDF body,
  no HTML sibling). V8 plan narrowed: strip `rtf.text` +
  `andamentos[].link.text`/`sessao_virtual[].documentos[].text`
  (all PDF-linked); KEEP DJe `decisoes[].texto` as the cache-free
  fast path. Does not generalize to `andamentos` / sessao_virtual
  documentos — those remain PDF-canonical with no HTML fallback.
- **`scripts/` cleanup + `PYTHONPATH=.` retired** (2026-04-19).
  Three underscore helpers promoted to library code: `_diff.py` →
  `src/sweeps/diff_harness.py`, `_pdf_cli.py` → `src/sweeps/peca_cli.py`,
  `_filters.py` → `src/utils/filters.py`. Five one-shots deleted (git
  preserves): `migrate_html_cache_to_tar.py`, `class_density_probe.py`,
  `ocr_bakeoff.py`, `replay_sample_jsons.py`, `launch_hc_backfill.sh`
  (superseded by sharded variant). Callers updated in `run_sweep.py`,
  `validate_ground_truth.py`, `baixar_pecas.py`, `extrair_pecas.py`, and
  `tests/unit/test_pdf_cli.py`; doc refs in `stf-portal.md`,
  `data-dictionary.md`, and the 2026-04-17 spec repointed. With no
  `from scripts.*` imports remaining in `scripts/*.py`, the hatchling
  editable install (`packages = ["src"]`, already in pyproject) is
  sufficient — `PYTHONPATH=.` is no longer required for scripts or
  pytest. `CLAUDE.md § Runtime` updated. 391 unit tests green;
  `scripts/renormalize_cases.py` left in place pending the TODO-listed
  pautas-crash fix.
- **Phase 3 morning audit — full v6 warehouse online** (2026-04-19
  ~09:00). Anchor file refreshed (9.9k → 79.7k anchors; date range
  now 1971..2026). Warehouse builder rewritten end-to-end: Arrow
  bulk insert + schema-aware INTEGER/VARCHAR/VARCHAR[] coercion +
  streamed PDFs + eager memory release + new `--year` filter
  (HC-only). Full warehouse built in **3:05 wall**
  (`data/warehouse/judex.duckdb`, 722 MB, 79,742 cases / 1.08 M
  andamentos), versus the original `executemany` path that was
  killed at 15+ min and never completed. Year-scoped 2026
  sub-warehouse built in 21.9s (`judex-2026.duckdb`, 262 MB).
  Phase 1F sanity SQL all green. See active-task Observations
  for full breakdown + the "Re-extraction status" caveat about
  structural-vs-data v6.
- **Overnight HC backfill, tiers 0–3** (2026-04-19 01:17 → 06:12).
  `scripts/overnight_t0123.sh` chained four `launch_hc_year_sharded.sh`
  invocations sequentially via `tail --pid` blocking. **22,147
  net-new HC cases** captured, all born v6. Tier-2 shard-6
  collapsed early (1,282 IDs ungrabbed in 2024 range, will
  re-surface in next gap-CSV regen). `scripts/monitor_overnight.sh`
  + `13,43 * * * *` crontab worked end-to-end but stale-shard
  alert logic over-fires on completed-tier shards (150 false
  positives overnight); needs scoping to active-tier-only before
  reuse.
- **PDF pipeline split into `baixar-pecas` + `extrair-pecas`**
  (2026-04-19). `varrer-pdfs`, `scripts/fetch_pdfs.py`, and
  `scripts/reextract_unstructured.py` retired — replaced by two
  independent commands. `baixar-pecas` is the only WAF-bound path;
  writes raw bytes to `data/cache/pdf/<sha1>.pdf.gz`. `extrair-pecas
  --provedor {pypdf|mistral|chandra|unstructured}` reads those bytes
  locally — zero HTTP, no throttle, no circuit breaker — and writes
  text + `.extractor` sidecar. Switch providers or re-OCR without
  re-hitting STF. Sidecar-match skip replaces the retired
  monotonic-by-length guard. Pypdf now a first-class `OCRProvider`
  (`src/scraping/ocr/pypdf.py`); `estimate_wall` added to the
  dispatcher for the preview block. Drivers +363 unit tests green,
  up from 333 pre-split. Spec:
  [`docs/superpowers/specs/2026-04-19-varrer-pdfs-ocr-knob.md`](superpowers/specs/2026-04-19-varrer-pdfs-ocr-knob.md).
- **Schema v6 — broad cleanup sweep** (2026-04-19 ~04:30 UTC via
  external edit, documented in `src/data/types.py`). Reduces schema
  variance: ASCII snake_case metadata keys, ISO-only dates (no raw
  DD/MM/YYYY + `*_iso` pair), `_meta: ScrapeMeta` slot for
  scrape-provenance (`schema_version`/`status_http`/`extraido`),
  `index_num`/`id` → `index`, `Recurso.data` → `Recurso.tipo`,
  typed `Pauta`, non-Optional `incidente`. StfItem top-level is now
  pure domain data. `extract_andamentos` split into reusable
  `_parse_andamento_item` shared with new `extract_pautas`.
- **Schema v5 — andamento link unified with Documento**
  (2026-04-19 ~04:00 UTC). `Andamento.link` carries `{tipo, url,
  text, extractor}` or None; `link_descricao` sibling is gone.
  Option 2 for href-less edge case: `{tipo: "...", url: null, ...}`.
  Downstream consumers + help text + ground-truth fixtures all
  migrated; v4-compat `link_descricao` fallback removed.
- **Schema v4 — extractor provenance** (2026-04-19 ~03:30 UTC).
  `extractor: Optional[str]` on every `Documento`. `<sha1>.extractor`
  plain-text sidecar alongside `<sha1>.txt.gz` +
  `<sha1>.elements.json.gz`. sessao_virtual documentos dict → list
  preserving duplicate `tipo` (option b). `extract_document_text`,
  `_make_pdf_fetcher`, `resolve_documentos`, `_cache_only_pdf_fetcher`
  all return `(text, extractor)`.
- **Mistral as default OCR provider everywhere** (2026-04-19).
  `scripts/reextract_unstructured.py` generalised to dispatch
  through `src.scraping.ocr.extract_pdf`; `--provider` flag, default
  mistral. Portuguese CLI `--provedor` + per-provider `*_API_KEY`
  check. `--force` now bypasses the monotonic cache guard —
  unconditional overwrite of text + elements + sidecar. Prior guard
  bug fixed (was clobbering the sidecar with `extractor=unchanged`
  on no-improvement runs).
- **3-way OCR bakeoff results** (earlier). Mistral wins on speed
  (12×), cost (10×), and semantic preservation vs Unstructured.
  Chandra preserves semantics but 15 % shorter output.
- **HTML cache migrated to per-case tar.gz** (prior cycle). 58 %
  on-disk reduction, 12× inode reduction; migration script at
  `scripts/migrate_html_cache_to_tar.py`.
- **DuckDB warehouse implemented** at `src/warehouse/builder.py` +
  entrypoint `scripts/build_warehouse.py`. Five tables (`cases`,
  `partes`, `andamentos`, `documentos`, `pdfs`) + `manifest`. Full
  schema tolerance v1..v6 via `_flatten_case` + `_flatten_documentos`.
- **Tier-0 (2026) HC backfill smoke test passed** (2026-04-18).
  8-shard year-priority pipeline validated, 917/917 filter_skip,
  zero WAF events. Tier-1 (2025) queued.
- **4-shard HC backfill archived**. Final: 54 841 ok / 12 real fails
  across 72 646 records over 11.6 h. Corpus 55 354 HCs.
- **Detached-sweep pattern documented** in `CLAUDE.md § Surviving
  session death`.
- **Proxy pool at 80 sessions across 8 files** (`proxies.{a..h}.txt`).

## In flight

Nothing executing. Four strands paused at clean handoff points:

- **Schema v6 migration — code shipped, data not yet renormalized.**
  See active-task section above. Blocks the warehouse build
  end-to-end audit.
- **HC backfill — tier-0 complete, tier-1 queued.** Tier-0 ran
  clean; run dir at `runs/active/2026-04-18-hc-2026/` awaiting
  archival; tier-1 (2025) next fire. 109 042 total gap IDs across
  tiers 0–13.
- **Storage migration — 50 cases tar'd, 55 k still legacy.**
  `scripts/migrate_html_cache_to_tar.py` is ready; full migration
  ~30 s one-shot.
- **Warehouse end-to-end** — builder + tests shipped, but never run
  against the real corpus. Gated on v6 migration.

## Next steps, ordered

### Schema v6 migration (blocks everything that reads case JSONs in bulk)

1. **Smoke-run** — `--limit 10 --dry-run` to catch import/symbol
   errors (see open question 2 in active task).
2. **Bounded dry-run** — `--limit 2000`.
3. **Full dry-run** — no limit.
4. **Live migration** — `--workers 8`.
5. **Post-migration audit + warehouse build** — exercise
   `scripts/build_warehouse.py` against the migrated corpus;
   sanity-check the 5 tables + manifest.
6. **Drop older-version tolerance** in `_normalize_documentos` and
   `_flatten_case` (separate PR).

### HC-backfill strand

1. Archive tier-0, fire tier-1 (2025, ~2.5 h at 8-shard).
2. Sequential tiers 2 → 13 with cron monitoring between.
3. Consolidated post-queue REPORT at
   `docs/reports/<date>-hc-year-priority-tiers-0-13.md`.
4. Doc amendments (rate-limits, performance, hc-who-wins).

### Storage-migration strand

1. Full tar.gz migration pass (drop `--keep-dirs`; ~30 s at current
   55 k-case scale).
2. Update `CLAUDE.md § Caches` if the layout summary still mentions
   per-tab `.html.gz`.

### Long-running carryovers

- Decide on `data_protocolo_iso` column redundancy under v6 (active
  task open question 1).
- Re-run `docs/hc-who-wins.md` sample-size math against the final
  HC corpus.

## Known limitations

- **Denominator composition + right-censoring** — HC density maps
  reflect the 2013 → 2026 tiers in scope. Paper-era (pre-2013)
  explicitly out of scope. See `docs/hc-who-wins.md § Sampling`.

## Known gaps

- **`sessao_virtual` ground-truth parity** — the live code emits the
  ADI shape; older HC fixtures sometimes lacked the `metadata`
  subkeys entirely. `SKIP_FIELDS` in `src/sweeps/diff_harness.py` guards the
  diff harness against this.
- **PDF enrichment status tracking** — no persisted field answers
  "has this case been through PDF enrichment?" Derivable from
  `extractor` slots; a `scripts/pdf_enrichment_status.py` rollup
  script was proposed but not landed.

---

# Reference — how to run things

```bash
# Unit tests (~6 s, 328 tests)
uv run pytest tests/unit/

# Ground-truth validation (HTTP parity against 7 fixtures + 2 candidates)
PYTHONPATH=. uv run python scripts/validate_ground_truth.py

# HTTP scrape, one process, with PDFs
PYTHONPATH=. uv run python -c "from src.scraping.scraper import scrape_processo_http; print(scrape_processo_http('HC', 128377, fetch_pdfs=False))"

# Wipe all regenerable caches (case JSONs under data/cases/ survive)
rm -rf data/cache/pdf data/cache/html
```

## Renormalize production JSONs to the current schema

```bash
# Dry run — quantify needs_rescrape + error
PYTHONPATH=. uv run python scripts/renormalize_cases.py --dry-run --workers 4

# Live
PYTHONPATH=. uv run python scripts/renormalize_cases.py --workers 8

# Scoped to one classe
PYTHONPATH=. uv run python scripts/renormalize_cases.py --classe HC --workers 4
```

## Running sweeps

```bash
# One-shot sweep over a CSV of (classe, processo) pairs
PYTHONPATH=. uv run python scripts/run_sweep.py \
    --out runs/active/$(date +%Y-%m-%d)-<label> \
    --csv tests/sweep/<label>.csv

# Sharded backfill (8 shards on disjoint proxy pools)
nohup ./scripts/launch_hc_year_sharded.sh 2025 \
    > runs/active/2026-04-XX-hc-2025/launcher-stdout.log 2>&1 & disown

# Stop all shards cleanly
xargs -a runs/active/<label>/shards.pids kill -TERM
```

## Data model — how pecas tie to cases

**A "peça" is any downloadable case document, regardless of format.**
Today that's PDFs (the majority — `downloadPeca.asp?ext=.pdf` plus
voto PDFs from `sistemas.stf.jus.br/repgeral/` and
`digital.stf.jus.br/…/conteudo.pdf`) and RTFs (`DECISÃO DE
JULGAMENTO` via `downloadTexto.asp?ext=RTF`). Future formats land in
the same cache + warehouse with no code change; format dispatch lives
in `peca_utils.extract_document_text`, which detects magic bytes
(`%PDF`, `{\rtf`) and routes to pypdf or striprtf.

Three hops from a case to its extracted text, all deterministic:

```text
data/cases/HC/judex-mini_HC_270392-270392.json                  ← the case record
  └── andamentos[i].link.url                                    ← portal.stf.jus.br URL
       └── sha1(url) = "295772cbd5…"                            ← cache key (format-neutral)
            ├── data/cache/pdf/295772cbd5….pdf.gz               ← raw bytes  (baixar-pecas)
            ├── data/cache/pdf/295772cbd5….txt.gz               ← extracted text (extrair-pecas)
            ├── data/cache/pdf/295772cbd5….elements.json.gz     ← PDF-OCR structure list (optional)
            └── data/cache/pdf/295772cbd5….extractor            ← "pypdf_plain" | "mistral" | "chandra"
                                                                   | "unstructured" | "rtf"   ← truth about format
```

**Key properties:**

- **URL-keyed, not case-keyed.** Two cases citing the same peça share
  **one** cache entry and **one** warehouse `pdfs` row. Counting
  pecas-per-case needs walking `andamentos[].link.url` per case.
- **Filename `.pdf.gz` is historical** — the bytes file may contain
  RTF octets (from `downloadTexto.asp`) because we kept the legacy
  extension when we renamed modules (`pdf → peca`) to avoid breaking
  the in-flight sweep. The `.extractor` sidecar is the source of
  truth for format: `"rtf"` → RTF bytes, any pypdf/mistral/chandra
  label → PDF bytes. Ditto `.elements.json.gz` — only PDF-OCR
  providers emit one, so its presence implies PDF.
- **The quartet is re-entrant.** Re-running `extrair-pecas` with a
  new `--provedor` reads the bytes off disk (no STF traffic) and
  overwrites `.txt.gz` + `.extractor`. Switching providers is a
  local operation; the bytes never change.

Access surfaces:

- **Python, case-centric**: `peca_cache.read(url)` / `has_bytes(url)` /
  `read_extractor(url)` — hashes the URL internally, you never touch
  sha1. One call per `andamentos[i].link.url`.
- **SQL, cross-case**: warehouse `pdfs` table joins to `andamentos`
  on `sha1 = link_url_sha1` (pre-computed at build time). The table
  is named `pdfs` today but semantically holds all peças — a follow-up
  rename (`pdfs → pecas`) is on TODO for the next warehouse rebuild.

### Known wart: bytes-file suffix `.pdf.gz` lies (queued fix)

**What the wart is.** `peca_cache._bytes_path` hardcodes the bytes-
cache filename to `<sha1>.pdf.gz`:

```python
# src/utils/peca_cache.py:70
def _bytes_path(url: str) -> Path:
    return CACHE_ROOT / f"{_hash(url)}.pdf.gz"
```

There is no format branch, no content sniff. Every URL's bytes land
in `<sha1>.pdf.gz`, whether the body is PDF or RTF octets. After the
RTF-first-class filter shipped (2026-04-19 commit `6ac64e9`), RTF
andamento URLs (`downloadTexto.asp?ext=RTF`, ~372 per-year on HC)
will start writing their bytes into `.pdf.gz`-named files too. The
filename stops being accurate; the `.extractor` sidecar (`"rtf"` vs
`"pypdf_plain"` / `"mistral"` / …) is the actual source of truth
about format.

**Why the data is still safe.** Binary formats are self-describing
in their first few bytes. `peca_utils.detect_file_type()` dispatches
on magic bytes (`%PDF` → pdf; `{\rtf` → rtf) and has never trusted
the filename. Three independent recovery paths for any cache entry:

1. Magic-byte sniff on the decompressed bytes (ground truth).
2. `.extractor` sidecar (fast; requires extraction to have run).
3. Warehouse `pdfs.extractor` column (same as path 2, bulk-scope).

So the lie is a *readability* wart, not a *correctness* one. Nothing
in production reads the filename as authoritative. A cold reader
glancing at `data/cache/pdf/` gets misled; code does not.

**Why it wasn't fixed in the `pdf→peca` rename.** The in-flight HC
2026 sweep (pid 574055, ~5.5 h in at the time of the rename) holds
`_bytes_path` in its in-memory module copy. Changing the constant
on disk mid-sweep splits the cache across two naming conventions
(old process keeps writing `.pdf.gz`; new processes look at
`.bytes.gz`), which would break `has_bytes(url)` on every URL
written post-change.

**When + how to execute the fix.** After the sweep exits
(`pgrep -af 'baixar_pecas|extrair_pecas'` returns empty):

```bash
# 1) migration: mv <sha1>.pdf.gz → <sha1>.bytes.gz across data/cache/pdf/
#    write scripts/migrate_peca_cache_bytes.py first; walk the tree,
#    rename atomically. Estimated ~36k files (30,387 pre-existing
#    + whatever this sweep added, ~9,306 on full completion).
uv run python scripts/migrate_peca_cache_bytes.py --dry-run   # verify count
uv run python scripts/migrate_peca_cache_bytes.py             # execute

# 2) deploy the constant change
#    edit src/utils/peca_cache.py:71  "pdf.gz" → "bytes.gz"
#    grep tests for any hardcoded `.pdf.gz` expectations (few)

# 3) verify
uv run pytest tests/unit/                                     # 393 expected
uv run python scripts/validate_ground_truth.py                # 0 diffs expected
# spot-check: a known URL from the 2026 sweep should still resolve
uv run python -c "from src.utils import peca_cache; print(peca_cache.has_bytes('https://portal.stf.jus.br/processos/downloadPeca.asp?id=15386152898&ext=.pdf'))"

# 4) rebuild warehouse — pdfs.cache_path column embeds the old filename
uv run python scripts/build_warehouse.py --year 2026
uv run python scripts/build_warehouse.py                      # full corpus

# 5) commit
#    chore(cache): rename bytes-cache suffix .pdf.gz → .bytes.gz
```

**Suffix choice.** `.bytes.gz` — literal, format-neutral, contrasts
cleanly with `.txt.gz` (the derived text). Rejected alternatives:
`.peca.gz` (not a known extension; extra cognitive load), `.raw.gz`
(too generic), `.blob.gz` (opaque).

**Tracked in TODO.md** under "Document-universe follow-ups" (the
"sweep artifact filenames + cache-sidecar extension" entry). Queue:
after HC 2026 download sweep completes (~21:00 local on 2026-04-19
per the 16 URLs/min extrapolation).

## PDF sweeps + OCR

```bash
# 1) Download bytes (WAF-bound; runs once per URL)
PYTHONPATH=. uv run python scripts/baixar_pecas.py \
    --classe HC --impte-contem "<name>" \
    --saida runs/active/<label>-bytes --nao-perguntar

# 2) Extract text via chosen provider (zero HTTP; local cache)
PYTHONPATH=. uv run python scripts/extrair_pecas.py \
    --classe HC --impte-contem "<name>" \
    --provedor mistral --forcar \
    --saida runs/active/<label>-mistral --nao-perguntar

# Re-extract same URLs with a different provider — no re-download
PYTHONPATH=. uv run python scripts/extrair_pecas.py \
    --classe HC --impte-contem "<name>" \
    --provedor chandra \
    --saida runs/active/<label>-chandra --nao-perguntar

# Provider bakeoff
PYTHONPATH=. uv run python scripts/ocr_bakeoff.py \
    --out runs/active/<label> --providers mistral,chandra --limit 55
```

## Warehouse

```bash
PYTHONPATH=. uv run python scripts/build_warehouse.py
# → data/warehouse/judex.duckdb
```

## Marimo notebooks / judex CLI hub

```bash
uv run marimo edit analysis/<name>.py
uv run judex --help
```
