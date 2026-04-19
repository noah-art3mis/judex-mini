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

---

# Strategic state

## What just landed

- **`scripts/` cleanup + `PYTHONPATH=.` retired** (2026-04-19).
  Three underscore helpers promoted to library code: `_diff.py` →
  `src/sweeps/diff_harness.py`, `_pdf_cli.py` → `src/sweeps/pdf_cli.py`,
  `_filters.py` → `src/utils/filters.py`. Five one-shots deleted (git
  preserves): `migrate_html_cache_to_tar.py`, `class_density_probe.py`,
  `ocr_bakeoff.py`, `replay_sample_jsons.py`, `launch_hc_backfill.sh`
  (superseded by sharded variant). Callers updated in `run_sweep.py`,
  `validate_ground_truth.py`, `baixar_pdfs.py`, `extrair_pdfs.py`, and
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
- **PDF pipeline split into `baixar-pdfs` + `extrair-pdfs`**
  (2026-04-19). `varrer-pdfs`, `scripts/fetch_pdfs.py`, and
  `scripts/reextract_unstructured.py` retired — replaced by two
  independent commands. `baixar-pdfs` is the only WAF-bound path;
  writes raw bytes to `data/cache/pdf/<sha1>.pdf.gz`. `extrair-pdfs
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

## PDF sweeps + OCR

```bash
# 1) Download bytes (WAF-bound; runs once per URL)
PYTHONPATH=. uv run python scripts/baixar_pdfs.py \
    --classe HC --impte-contem "<name>" \
    --saida runs/active/<label>-bytes --nao-perguntar

# 2) Extract text via chosen provider (zero HTTP; local cache)
PYTHONPATH=. uv run python scripts/extrair_pdfs.py \
    --classe HC --impte-contem "<name>" \
    --provedor mistral --forcar \
    --saida runs/active/<label>-mistral --nao-perguntar

# Re-extract same URLs with a different provider — no re-download
PYTHONPATH=. uv run python scripts/extrair_pdfs.py \
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
