# Handoff — judex-mini

Branch: `experiment/perf-bulk-data`
Status: landed locally, **not yet pushed**. Tip: `acac647` (or newer).
PR: https://github.com/noah-art3mis/edf-mini/pull/new/experiment/perf-bulk-data

This is the *temporal* doc — what's in flight, what's blocked, what's
next. For *conceptual* knowledge (how the portal works, how rate
limits behave, class sizes, perf numbers, where data lives), read:

- [`docs/data-layout.md`](data-layout.md) — where files live + the three stores.
- [`docs/stf-portal.md`](stf-portal.md) — URL flow, auth triad, field→source map.
- [`docs/rate-limits.md`](rate-limits.md) — WAF behavior, validated defaults, robots.txt posture.
- [`docs/process-space.md`](process-space.md) — HC/ADI/RE ceilings + density.
- [`docs/performance.md`](performance.md) — HTTP-vs-Selenium numbers, caching as the real lever.

## Working conventions

- **`analysis/`** — git-ignored scratch for this-session exploration (marimo notebooks, one-off scripts, raw JSON dumps). Safe to fill freely.
- **All non-trivial arithmetic via `uv run python -c`** — never mental math. See `CLAUDE.md § Calculations`. The rate-budget doc (`docs/sweep-results/2026-04-16-D-rate-budget.md`) is the cautionary tale.
- **Sweeps write a directory**, not a file. Layout in [`docs/data-layout.md § Sweep run artifacts`](data-layout.md#sweep-run-artifacts).

## What just landed

- **Selenium retirement (phase 1).** 2026-04-17. 19 files moved to `deprecated/`, `main.py` defaults to `--backend http`, `--backend selenium` errors with a deprecation message, `selenium` moved to the `[selenium-legacy]` opt-in extra. 158/158 unit tests green post-move. Spec: `docs/superpowers/specs/2026-04-17-selenium-retirement.md`.
- **Validation sweeps A–E.** Full writeups under `docs/sweep-results/`. Highlights: C tripped the WAF at process 108 (surfaced the 403-not-429 behavior); D's three pacing probes produced the validated defaults; E ran 429/429 ok with the shipped defaults before being SIGTERM'd to free the WAF for G's density probe.
- **Robust sweep driver.** Append-only `sweep.log.jsonl` + atomic `sweep.state.json` + derived `sweep.errors.jsonl` + `report.md`. Resume, retry-from, signal-safe shutdown, circuit breaker. Shared primitives in `src/sweeps/shared.py`, reused by `src/sweeps/pdf_driver.py`.
- **Validated pacing defaults** (commit `2a2833d`). See [`docs/rate-limits.md § Validated defaults`](rate-limits.md#validated-defaults-commit-2a2833d).
- **HC class-size refresh (2026-04-16 evening).** Ceiling 270,994; ~216k extant. Bimodal density. Full numbers in [`docs/process-space.md`](process-space.md).
- **HC notebook-strand layout (2026-04-17).** Hub-and-strand pattern across five marimo notebooks. Full layout + findings in [`docs/hc-who-wins.md § Notebook layout`](hc-who-wins.md#notebook-layout--investigation-strands-2026-04-17).

## In flight

### Sweep E close-out

Sweep E stopped at 429/1000 via SIGTERM (clean) and is resumable. The
partial is sufficient evidence that the shipped defaults are
production-viable; a 1000-process ceiling datapoint is nice-to-have
but not necessary.

**Check status:** `docs/sweep-results/2026-04-16-E-full-1k-defaults/sweep.state.json`.

**Finish the full 1000** (adds ~34 min wall from a cold WAF):

```bash
PYTHONPATH=. uv run python scripts/run_sweep.py \
    --csv tests/sweep/full_range_adi.csv \
    --label full_1k_defaults \
    --parity-csv output/judex-mini_ADI_1-1000.csv \
    --out docs/sweep-results/2026-04-16-E-full-1k-defaults \
    --resume
```

Then append an E section to the rate-budget write-up comparing to
the 52 min projection and Selenium baseline.

### HC deep dive scoping

User's stated next step: scrape all HCs and take a deep dive. See
[`docs/hc-who-wins.md`](hc-who-wins.md) for the research question and
notebook layout. Decision still open: time-sliced vs sample-first vs
relator-sliced. At the validated defaults a full HC backfill is ~9
days wall time from one IP — see
[`docs/rate-limits.md § Wall-time math at scale`](rate-limits.md#wall-time-math-at-scale).

Practical starting point: **probe sweep on HCs 1..1000** plus
269000..270000 to validate the parser across paper-era and modern
vintages. ~50 min each at validated defaults.

```bash
# CSV for HC 1..1000
uv run python -c "import csv; w=csv.writer(open('tests/sweep/hc_probe_1_1000.csv','w')); w.writerow(['classe','processo']); [w.writerow(['HC',n]) for n in range(1,1001)]"

PYTHONPATH=. uv run python scripts/run_sweep.py \
    --csv tests/sweep/hc_probe_1_1000.csv --label hc_probe_1_1000 --wipe-cache \
    --out docs/sweep-results/<date>-F-hc-probe-1-1000
```

## Next steps, ordered

### 1. Close out sweep E

Resume command above. Append section to rate-budget write-up. Commit.

### 2. Circuit breaker for the sweep driver

Even with retry-403 + pacing, pathological WAF escalation could
cascade. Abort the sweep if error rate crosses X % in a rolling
window of N processes.

Implementation sketch: `collections.deque(maxlen=N)` of recent statuses in
`run_sweep.main`; after each process, if more than X % of the deque is
non-ok, write errors, write state, exit 2 with a clear message.
Tunable via two CLI flags. Minimum viable: N=25, X=50 %. ~15 min of work.

### 3. Scope the HC deep dive

See "In flight" above. Probe HCs 200000..201000 first to measure
completion + rate before a bigger commitment. Ask the user what the
deep dive wants to answer — that shapes what data matters.

### 4. Outcome derivation

`StfItem` has no "winner" / "verdict" field. The data is scattered
and determining the outcome requires:

- Parsing `sessao_virtual[-1].voto_relator` for verdict phrases (`julgo procedente|improcedente|procedente em parte|nego provimento|dou provimento|não conheço`).
- Checking `sessao_virtual[-1].votes` — if `diverge_relator` is empty AND `pedido_vista` is empty or resolved in a later session, the relator's vote is the outcome.
- Checking `andamentos` for `TRANSITADO(A) EM JULGADO` and event names like `JULGADO PROCEDENTE`, `EMBARGOS RECEBIDOS EM PARTE` — the `complemento` field often carries the full decision text.

Worth adding as a derived field during parse (`src/scraping/extraction/sessao.py`)
OR as a post-processing pass. Brazilian legal vocabulary is richer than
the table above (`prejudicado`, `extinto sem resolução de mérito`,
`conversão em diligência`, …), so a first pass will have a meaningful
`unknown` / `pending` tail. Needed by the HC deep dive if it wants
outcome statistics.

### 5. Retry sweep C's 893 blocked processes

Sweep C's `docs/sweep-results/2026-04-16-C-full-1000.md` predates the
robust driver — flat markdown file, no `sweep.errors.jsonl`. So
`--retry-from` can't be pointed at it directly. Two options:

- **Re-run the full range under the new driver** once the posture is chosen. Uses `--resume` to skip the 107 already in cache.
- **Synthesize an errors.jsonl** from the C report's "status=error" rows (one-off script) to feed `--retry-from`.

First is more honest about wall time; second is faster to start.

### 6. Selenium retirement phase 2

Phase 2 (re-capture ground-truth fixtures under HTTP, audit
`deprecated/` self-containment) and phase 3 (CI check that no live
file imports from `src._deprecated`) still pending. Spec in
`docs/superpowers/specs/2026-04-17-selenium-retirement.md`.

### 7. PDF extraction quality

Currently PDFs go through `pypdf.PdfReader.extract_text(extraction_mode="layout")`.
You'll see warnings like `Rotated text discovered. Output will be incomplete.`
— STF stamps signed documents with rotated watermarks and the extractor
drops content around them.

**Unstructured-API OCR path** (`scripts/reextract_unstructured.py`,
2026-04-17) walks `pdf_targets` output, re-downloads cache entries
shorter than `--min-chars`, POSTs to Unstructured's SaaS API with
`strategy=hi_res`, overwrites `data/pdf/<sha1>.txt.gz` when the new
extract is longer. First production run:
`docs/pdf-sweeps/2026-04-17-famous-lawyers-ocr/`.

**Known gap**: the script does *not* route through
`src/sweeps/pdf_driver.run_pdf_sweep` — it runs an inlined loop, so
no `pdfs.state.json` / `pdfs.log.jsonl` / `requests.db` are produced.
Migration is a small follow-up (pass a PDF-+-OCR `FetcherFn` to
`run_pdf_sweep`). See the script's docstring for the full list.

### 8. Pre-existing cleanup (Selenium side)

Surfaced during the dedup review; untouched because Selenium path has
no automated coverage:

- `deprecated/extraction/extract_peticoes.py:28-30`: `data_match` assigned from `bg-font-info` then immediately overwritten by `processo-detalhes`. First match is dead.
- `deprecated/extraction/extract_deslocamentos.py:113-152`: `_clean_extracted_data` looks dead — `_clean_data_fields` is the one called from `_extract_single_deslocamento`. Verify with grep.
- `src/data/types.py:47-78`: commented-out dataclasses. Git remembers; delete.

Not blocking. Safe to defer.

## Known gaps in the `sessao_virtual` port

Worth knowing if you're debugging:

- **Vote categories are partial** — only codes 7/8/9 land in the final `votes` dict. See [`docs/stf-portal.md § sessao_virtual`](stf-portal.md#sessao_virtual--not-from-abasessao).
- **`documentos` values are mixed types**: string with extracted text (success) or original URL (fetch failed). Consumers must check `startswith("https://")`. Re-running the scraper picks up where failures left off via the URL-keyed PDF cache.
- **Tema branch has only one fixture test (tema 1020).** If you see drift there, probe another tema + add a fixture.
- **No Sessão-branch support for "suspended" lists** — if STF ever returns a listaJulgamento mid-suspension with a different JSON shape, `parse_sessao_virtual` will pass through missing fields as empty strings. No known case.

## How to run things

```bash
# Unit tests (48 tests, <3s)
uv run pytest tests/unit/

# Ground-truth validation (HTTP parity against 5 fixtures)
PYTHONPATH=. uv run python scripts/validate_ground_truth.py

# HTTP scrape, one process, with PDFs
uv run python main.py -c ADI -i 2820 -f 2820 -o json -d data/output/test --overwrite

# HTTP scrape without the PDF fetch (faster, documentos stay as URLs)
uv run python main.py --no-fetch-pdfs -c AI -i 772309 -f 772309 -o json -d data/output/test --overwrite

# Wipe caches
rm -rf data  # HTML fragments, sessao JSON, PDF text
```

### Marimo notebooks under `analysis/`

HC analysis lives in five marimo notebooks — see
[`docs/hc-who-wins.md § Notebook layout`](hc-who-wins.md#notebook-layout--investigation-strands-2026-04-17).

```bash
# interactive editor (opens a browser tab, full reactivity):
uv run marimo edit analysis/hc_famous_lawyers.py

# view-only:
uv run marimo run analysis/hc_famous_lawyers.py

# view-only, no auto-open browser — useful when running remotely
# (WSL/SSH/container). Marimo prints a localhost URL; forward the port first.
uv run marimo run --headless analysis/hc_famous_lawyers.py
```

Swap `hc_famous_lawyers.py` for any of `hc_explorer.py`,
`hc_top_volume.py`, `hc_minister_archetypes.py`, `hc_admissibility.py`.

## Running sweeps

```bash
# One-shot sweep over a CSV of (classe, processo) pairs
PYTHONPATH=. uv run python scripts/run_sweep.py \
    --csv tests/sweep/shape_coverage.csv \
    --label my_sweep \
    --parity-dir tests/ground_truth \
    --out docs/sweep-results/<date>-<label>

# Long sweep with WAF-friendly pacing (defaults already safe; override if tuning)
PYTHONPATH=. uv run python scripts/run_sweep.py \
    --csv tests/sweep/full_range_adi.csv \
    --label long_sweep \
    --throttle-sleep 1.0 \
    --parity-csv output/judex-mini_ADI_1-1000.csv \
    --wipe-cache \
    --out docs/sweep-results/<date>-<label>

# Resume a sweep (skip already-ok processes)
PYTHONPATH=. uv run python scripts/run_sweep.py \
    --csv <same-csv> --label <same> --out <same-dir> --resume

# Retry only the failures from a prior sweep
PYTHONPATH=. uv run python scripts/run_sweep.py \
    --retry-from docs/sweep-results/<dir>/sweep.errors.jsonl \
    --label <label>_retry \
    --throttle-sleep 1.0 \
    --out docs/sweep-results/<date>-<label>-retry
```

**Stopping a running sweep cleanly.** The driver installs SIGINT/SIGTERM
handlers (`scripts/run_sweep.py:517-524`). On signal it finishes the
in-flight process, breaks the loop, then writes `sweep.errors.jsonl` +
`report.md` and exits with its normal status code.

```bash
# find the python process
ps -ef | grep run_sweep | grep -v grep

# clean stop (preferred) — finishes the in-flight process, writes all files
kill -TERM <pid>

# or Ctrl-C if the sweep is in the foreground (same SIGINT path)
```

`SIGKILL` (`kill -9`) is a last resort: per-record writes are atomic so
`sweep.log.jsonl` + `sweep.state.json` are always consistent and the
run is resumable via `--resume`, but `sweep.errors.jsonl` and
`report.md` won't be written. A `--resume` run (even one that skips
everything) regenerates both at its end.
