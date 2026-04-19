# Current progress — judex-mini

Branch: `main`. Prior cycle archived at
[`docs/progress_archive/2026-04-19_0500_schema-v4-v5-v6-and-mistral-default.md`](progress_archive/2026-04-19_0500_schema-v4-v5-v6-and-mistral-default.md)
— v4 → v5 → v6 schema cascade (extractor provenance, andamento/documento
link unification, ASCII-snake_case sessão metadata + ISO-only dates
+ `_meta` wrapper + typed `Pauta`), Mistral as default OCR provider,
monotonic-guard bypass under `--force`, fixtures regenerated as
bare-dict v6, v4-compat paths removed, 328 unit tests green.

**Status as of 2026-04-19 ~05:00 UTC: v6 schema shipped; production
case JSONs (57 595 files) not yet renormalized.** Code paths all
emit v6 shape; fixtures are v6; tests are v6; existing on-disk
`data/cases/**/*.json` (mostly v3, some v4/v5) still carry the old
shape. Next fire: `PYTHONPATH=. uv run python
scripts/renormalize_cases.py --workers 8` — a full dry-run sample
classified 1 000/57 595 all `ok` under v4, so the v6 jump should be
equally mechanical. Warehouse build (`scripts/build_warehouse.py`)
is still to be exercised end-to-end against real corpus.

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

Empty — task hasn't been fired yet.

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
2. `scripts/renormalize_cases.py` still has a stale `to_iso` import
   reference (v3-era; removed in v6) — might surface in the dry-run.
   Check before firing and fix if needed.

## Next steps (this task)

1. Smoke-test the renormalizer on a 10-file slice to catch the
   `to_iso` issue cited above (or confirm it's already resolved).
2. Fire the bounded dry-run (--limit 2000).
3. On clean dry-run, move to full dry-run, then live.

---

# Strategic state

## What just landed

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
  subkeys entirely. `SKIP_FIELDS` in `scripts/_diff.py` guards the
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
# Default: pypdf pass + Mistral rescue on short-cached entries
PYTHONPATH=. uv run python scripts/fetch_pdfs.py \
    --out runs/active/<label> --classe HC --impte-contains "<name>"

# OCR-only re-extraction (default provider: mistral)
PYTHONPATH=. uv run python scripts/reextract_unstructured.py \
    --out runs/active/<label> --classe HC \
    --force   # bypass monotonic guard, always overwrite

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
