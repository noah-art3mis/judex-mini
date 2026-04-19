# Current progress — judex-mini

Branch: `main`. Prior cycle archived at
[`docs/progress_archive/2026-04-19_2100_schema-v7-v8-dje-and-warehouse-rebuild.md`](progress_archive/2026-04-19_2100_schema-v7-v8-dje-and-warehouse-rebuild.md)
— schema v7 (`publicacoes_dje` + DJe scraper: listing → detail → RTF,
three pseudo-tabs on `portal.stf.jus.br`), schema v8 (strip inline
Documento text; `peca_cache` is canonical; warehouse builder resolves
text + extractor off `sha1(url)`), `pautas` table added to the
warehouse, full-corpus renormalize (ok=34,816 / needs_rescrape=44,926
structurally-v6-but-content-stale / error=0), HC 2026 PDF bytes sweep
stopped at 6,909/9,306 URLs with zero retries at 2.0 s/req,
`--sleep-throttle` flag deleted, `scripts/` cleanup + `PYTHONPATH=.`
retired, 423 unit tests green.

**Status as of 2026-04-19 evening.** Corpus: 79,742 HC files, every
one `_meta.schema_version = 8`. Warehouse `data/warehouse/judex.duckdb`:
79,742 cases / 268,157 partes / 1,086,647 andamentos / 30,504 documentos
/ 7,463 pautas / 30,387 pdfs, 518 MB, 168 s rebuild. 2026 sub-warehouse
`data/warehouse/judex-2026.duckdb`: 3,098 cases, 8.5 MB, 4.5 s rebuild.
Nothing executing.

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
- [`docs/stf-portal.md`](stf-portal.md) — URL flow, auth triad, field→source map, DJe flow.
- [`docs/rate-limits.md`](rate-limits.md) — WAF behavior, validated defaults, robots.txt posture.
- [`docs/process-space.md`](process-space.md) — HC/ADI/RE ceilings + density.
- [`docs/performance.md`](performance.md) — HTTP-vs-Selenium numbers, caching as the real lever.
- [`docs/warehouse-design.md`](warehouse-design.md) — DuckDB warehouse schema + build pipeline.
- [`docs/data-dictionary.md`](data-dictionary.md) — schema history v1→v8.

## Working conventions

- **`analysis/`** — git-ignored scratch for this-session exploration (marimo notebooks, one-off scripts, raw JSON dumps). Safe to fill freely.
- **All non-trivial arithmetic via `uv run python -c`** — never mental math. See `CLAUDE.md § Calculations`.
- **Sweeps write a directory**, not a file. Layout in [`docs/data-layout.md § Sweep run artifacts`](data-layout.md#sweep-run-artifacts).

---

# Active task — lab notebook

*No active task. Populate this section when a new cycle starts:*

## Task

*(one-paragraph description of the goal)*

## Plan

*(numbered steps — include bail-out conditions)*

## Expectations / hypotheses

*(H1 / H0 / H2 framing — what would confirm, what would falsify, what would surprise)*

## Observations

*(timestamped log — newest at the bottom; record the actual commands run and the actual numbers seen)*

## Decisions

*(load-bearing choices worth remembering)*

## Open questions

*(numbered; strike through when resolved — don't delete, so the archive preserves the reasoning trail)*

## Next steps

*(ordered; each step should be re-entrant after a session crash)*

---

# Strategic state

## What just landed (most recent cycle — full detail in the archive)

- **Schema v8 — strip inline Documento text, cache becomes canonical**
  (2026-04-19). Every `Documento` slot carries `text=None` +
  `extractor=None` on disk; warehouse builder resolves text + extractor
  off `sha1(url)` against `data/cache/pdf/`. DJe `decisoes[].texto`
  (HTML) retained as cache-free fast path — it is content-equal to the
  stripped RTF per explicit comparison on HC 158802. E2E verified on a
  fresh scrape of HC 158802: 22 Documento slots, all pointer-only,
  cache still holds 24.5 KB of extracted text.
- **Schema v7 — `publicacoes_dje` + DJe scraper** (2026-04-19).
  Three-layer flow on `portal.stf.jus.br`: `listarDiarioJustica.asp`
  → `verDiarioProcesso.asp` (per entry) → `verDecisao.asp?texto=<id>`
  (RTF per decisão). HTML cache gained two pseudo-tab keys
  (`dje_listing`, `dje_detail_<sha1[:16]>`). Gated on `fetch_dje=True`.
  HC 158802 ground truth now carries 6 publications / 7 decisões /
  24.5 KB of RTF text as the canonical DJe regression fixture.
- **Warehouse `pautas` table shipped** (2026-04-19 ~14:05). 7,463 rows
  across 6,737 distinct cases (8.5 % of corpus); top types
  `PAUTA PUBLICADA NO DJE - 1ª/2ª TURMA`. Builder fully v6+-aware;
  warehouse shrank 722 → 518 MB on rebuild (DuckDB recompaction).
- **Full-corpus renormalize** (2026-04-19 ~09:48). Two code fixes
  (optional-tabs relaxation in renormalizer + `primeiro_autor`
  re-derivation in `reshape_to_v6`) + full-mode pass → ok=34,816
  (2.75× prior run); needs_rescrape=44,926; 0 errors. On the
  re-extracted slice: "E OUTRO" sentinel 22 % → 0 %, multi-IMPTE 3 %
  → 26 %, pautas populated on 18.7 % of cases.
- **Overnight HC backfill tiers 0–3** (2026-04-19 01:17 → 06:12). 22,147
  net-new HC cases born v6 across years 2026/2025/2024/2023. Tier-2
  shard-6 collapsed early (1,282 IDs ungrabbed in 2024); monitor
  over-fires on completed-tier shards (150 false positives, needs
  active-tier scoping before reuse).
- **HC 2026 PDF bytes sweep** (2026-04-19 13:00 → 20:09 UTC). Stopped
  manually at **6,909 / 9,306 URLs (74.2 %)**, 0 fail, 0 retries at
  2.0 s/req. Coverage 2,307 / 3,099 cases touched; 918 M characters
  written to `cache/pdfs/*.bytes.gz`. Resume via `baixar-pecas ... --retomar`.
- **`--sleep-throttle` flag deleted** (2026-04-19 17:15). Zero retries
  across 6,909 requests at 2.0 s validated the value as policy, not a
  knob. Hardcoded `_THROTTLE_SLEEP_S = 2.0` in `src/sweeps/peca_cli.py`;
  `run_download_sweep` keeps the kwarg for test-injection only.
- **PDF pipeline split into `baixar-pecas` + `extrair-pecas`**
  (2026-04-19). WAF-bound bytes fetch separated from the zero-HTTP
  extractor chain. Provider switch no longer re-hits STF.
- **`scripts/` cleanup + `PYTHONPATH=.` retired** (2026-04-19). Three
  underscore helpers promoted to library code; five one-shots deleted.
  Hatchling editable install makes `src/` importable without the env
  var. `CLAUDE.md § Runtime` updated.

## In flight

Nothing executing. Working-tree state to resolve before the next cycle:

- **`src/analysis/lawyer_canonical.py` + `tests/unit/test_lawyer_canonical.py`**
  — untracked. Looks like a start on TODO item *"check if new author
  info changes anything"*. Not yet committed.
- **Uncommitted modifications** to `CLAUDE.md`, `README.md`, `TODO.md`,
  `docs/hc-who-wins.md`, `scripts/baixar_pecas.py`, `src/cli.py`,
  `src/sweeps/download_driver.py`, `tests/unit/test_download_driver.py`.
  The three last likely correspond to the `--sleep-throttle` deletion
  already logged as landed (tests green) — worth a quick `git diff` to
  confirm before committing.

## Backlog — ordered

Carried over from the archived cycle's "Analytical readiness" section
+ `TODO.md`.

### Analyses (TODO item 1)

1. Check whether new author info (untruncated `#todas-partes` +
   re-derived `primeiro_autor`) changes outcome distributions.
   `src/analysis/lawyer_canonical.py` is the in-flight start.
2. Segmentation by year / government.
3. Segmentation `primeiro_autor` × `autores` (does the head author
   dominate the roster, or is it a thin signal?).
4. Check golden-example candidates.
5. Confirm DJes in ground-truth examples.

### Warehouse

1. **DJe warehouse flatten.** `publicacoes_dje` ships in v7/v8 but the
   warehouse builder has no `_flatten_publicacoes_dje`. Parallel to the
   `pautas` gap closed 2026-04-19 ~14:05. TODO item 4.
2. **Add `content_version` column to `cases`.** Derived at flatten
   time from `reshape_to_v8` provenance (e.g.
   `all(nome NOT LIKE '%E OUTRO%')` AND
   `len(pautas) > 0 OR session_count == 0`). Lets analyses filter to
   the clean slice without `LIKE` heuristics.
3. **Rename `pdfs` table → `pecas`.** Semantically it holds all peças
   (PDF + RTF), not only PDFs. Queue for the next full rebuild.
4. **Decide on `data_protocolo_iso` redundancy** under v8 (ISO-only
   dates make it a no-cost alias). Lean toward drop.

### Data recovery

1. **Clear the 44,926 rescrape cliff.** Root cause: 78.5 % (35,254)
   have flat-directory HTML cache that `html_cache.read` doesn't open.
   Preferred path: (c) permanent fall-back in `html_cache.read` for
   flat-dir + (b) targeted sweep on the residual 9,671 (~20 min).
   Drops "E OUTRO" partes count from 9,877 toward zero and populates
   pautas on the recovered slice.
2. **Rewrite notebooks → md reports.** TODO item *"change notebooks to
   not have info that can go stale; write those to md reports instead"*.

### Operational hygiene

- **Bytes-cache suffix rename** `<sha1>.pdf.gz` → `<sha1>.bytes.gz`.
  Full playbook in the Reference section below; safe to run now that
  no `baixar-pecas`/`extrair-pecas` process is live.
- **Fix `scripts/monitor_overnight.sh`** — scope stale-shard alerts to
  the currently-active tier (150 false positives overnight).
- **Index `{processo_id → path}` in `peca_targets.py`** — ~2 min of
  `rglob` CPU before the first HTTP on a 79k-file tree.
- **`peca_targets.py` target-filter gap** — drops 372 RTF URLs
  (`downloadTexto.asp?ext=RTF`), doesn't walk `sessao_virtual.documentos`.
  One change fixes both.

### Scraper optimization (not blocking)

Ordered by ROI from the 2026-04-19 request-footprint audit. Portal-
bucket savings per case (the WAF-bound counter):

1. **Delete `abaDecisoes.asp` fetch** (free; −1 GET; no downstream reader).
2. **Class-gate `abaRecursos.asp`** (skip on HC/AI by default; −1 GET, ~1.8 s wall).
3. **Audit + gate `abaDeslocamentos.asp`** (needs warehouse-usage check first).
4. **Class-gate `abaPautas` / `abaPeticoes`** on monocratic classes.

Lean "fast sweep" floor: 8 GETs/case vs today's 12 on the no-DJe path.

## Known limitations

- **Denominator composition + right-censoring** — HC density maps
  reflect the 2013 → 2026 tiers in scope. Paper-era (pre-2013)
  explicitly out of scope. See `docs/hc-who-wins.md § Sampling`.
- **Stale-cache content residue** in the warehouse. 44,926 cases are
  structurally v8 but content-stale (partes truncated at `#partes-
  resumidas`, pautas empty). 9,877 partes rows carry the
  `'%E OUTRO%'` sentinel; 16,153 cases have NULL `outcome_verdict`.
  Author-based analyses over the full corpus must filter or the fake
  "E OUTRO" author over-counts 9,877 times. Clears via the "rescrape
  cliff" backlog item.

## Known gaps

- **`sessao_virtual` ground-truth parity** — live code emits the ADI
  shape; older HC fixtures sometimes lacked `metadata` subkeys
  entirely. `SKIP_FIELDS` in `src/sweeps/diff_harness.py` guards the
  diff harness against this.
- **PDF enrichment status tracking** — no persisted field answers
  "has this case been through PDF enrichment?" Derivable from
  `extractor` slots; a `scripts/pdf_enrichment_status.py` rollup was
  proposed but not landed.

---

# Reference — how to run things

```bash
# Unit tests (~6 s, 423 tests)
uv run pytest tests/unit/

# Ground-truth validation (HTTP parity against 7 fixtures + 2 candidates)
uv run python scripts/validate_ground_truth.py

# HTTP scrape, one process, with PDFs
uv run python -c "from src.scraping.scraper import scrape_processo_http; print(scrape_processo_http('HC', 128377, fetch_pdfs=False))"

# Wipe all regenerable caches (case JSONs under data/cases/ survive)
rm -rf data/cache/pdf data/cache/html
```

## Renormalize production JSONs to the current schema

```bash
# Dry run — quantify needs_rescrape + error
uv run python scripts/renormalize_cases.py --dry-run --workers 4

# Live
uv run python scripts/renormalize_cases.py --workers 8

# Scoped to one classe
uv run python scripts/renormalize_cases.py --classe HC --workers 4
```

## Running sweeps

```bash
# One-shot sweep over a CSV of (classe, processo) pairs
uv run python scripts/run_sweep.py \
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

**When + how to execute the fix.** Now that no `baixar-pecas` /
`extrair-pecas` process is live (`pgrep -af 'baixar_pecas|extrair_pecas'`
returns empty), the constraint that blocked the rename is gone:

```bash
# 1) migration: mv <sha1>.pdf.gz → <sha1>.bytes.gz across data/cache/pdf/
#    write scripts/migrate_peca_cache_bytes.py first; walk the tree,
#    rename atomically. Estimated ~36k files.
uv run python scripts/migrate_peca_cache_bytes.py --dry-run   # verify count
uv run python scripts/migrate_peca_cache_bytes.py             # execute

# 2) deploy the constant change
#    edit src/utils/peca_cache.py:71  "pdf.gz" → "bytes.gz"
#    grep tests for any hardcoded `.pdf.gz` expectations (few)

# 3) verify
uv run pytest tests/unit/                                     # 423 expected
uv run python scripts/validate_ground_truth.py                # 0 diffs expected
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

## PDF sweeps + OCR

```bash
# 1) Download bytes (WAF-bound; runs once per URL)
uv run python scripts/baixar_pecas.py \
    --classe HC --impte-contem "<name>" \
    --saida runs/active/<label>-bytes --nao-perguntar

# 2) Extract text via chosen provider (zero HTTP; local cache)
uv run python scripts/extrair_pecas.py \
    --classe HC --impte-contem "<name>" \
    --provedor mistral --forcar \
    --saida runs/active/<label>-mistral --nao-perguntar

# Re-extract same URLs with a different provider — no re-download
uv run python scripts/extrair_pecas.py \
    --classe HC --impte-contem "<name>" \
    --provedor chandra \
    --saida runs/active/<label>-chandra --nao-perguntar
```

## Warehouse

```bash
# Full rebuild (~168 s on 79k-case corpus)
uv run python scripts/build_warehouse.py
# → data/warehouse/judex.duckdb

# Year-scoped rebuild (HC only; fast iteration — ~4.5 s for 2026)
uv run python scripts/build_warehouse.py --year 2026 --classe HC
# → data/warehouse/judex-2026.duckdb
```

## Marimo notebooks / judex CLI hub

```bash
uv run marimo edit analysis/<name>.py
uv run judex --help
```
