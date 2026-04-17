# Handoff — judex-mini perf/bulk-data work

Branch: `experiment/perf-bulk-data`
Status: landed locally, **not yet pushed**. Tip: `018f26d`. 13 commits ahead of `main`.
PR: https://github.com/noah-art3mis/judex-mini/pull/new/experiment/perf-bulk-data

Start by reading `docs/perf-bulk-data.md` for the original investigation (DataJud dead-end, STF portal mechanics, 5.7×/~20× perf claim with caveats). Then skim `docs/superpowers/specs/2026-04-16-validation-sweep-design.md` for the sweep plan and `docs/sweep-results/` for what actually happened. This note only covers what's unfinished and why.

## What happened since the last handoff

**Validation sweeps A, B, C completed** (`docs/sweep-results/2026-04-16-{A,B,C}-*`):

- **A — shape-coverage smoke (12 processes, 6 classes).** 12/12 pass. No schema surprises; HC class exercised for the first time. One substitution: AI 828 didn't exist on STF → replaced with AI 500000.
- **B — throttle probe (50 ADIs, cold + warm).** 50/50 cold in 81 s, 0 retries. Warm pass p50 0.14 s — the ~60× cache speed-up `docs/perf-bulk-data.md` predicted.
- **C — full ADI 1–1000 sweep.** **STF blocked us at process #108** with HTTP 403 (not 429) from `listarProcessos.asp`. 107 ok; 893 fast-fail 403s. In the pre-ban window: **~0.79 s/process = 9.7× faster than Selenium's 7.65 s/process**. Selenium baseline for the same range: 77.6 min / 609 ok (measured from `extraido` timestamps in `output/judex-mini_ADI_1-1000.csv`). Selenium completed the range because it's 10× slower per process and stayed under the rate gate; HTTP at current posture tripped it.

**Robust sweep state/log machinery landed** (`scripts/sweep_state.py`, commit `018f26d`):

- Every sweep run writes an append-only `sweep.log.jsonl` (fsynced per record) + atomic `sweep.state.json` + derived `sweep.errors.jsonl`. Report at `report.md`.
- `--resume` skips already-ok processes. `--retry-from <errors.jsonl>` re-runs only failures from a prior sweep.
- SIGINT/SIGTERM stop cleanly after the in-flight process. Recovery path rebuilds `sweep.state.json` from the log if it's missing.
- `AttemptRecord` carries structured fields (`error_type`, `http_status`, `error_url`); report tables aggregate errors by bucket + endpoint.
- Opt-in flags: `--retry-403` (`ScraperConfig.retry_403`) treats 403 as a retriable throttle signal via tenacity; `--throttle-sleep <s>` paces between processes.
- **Breaking change**: `run_sweep.py --out` is now a directory, not a markdown file path. Old sweep A/B reports at `docs/sweep-results/2026-04-16-A-shape-coverage.md` are flat files from the pre-state driver; they stay as-is. New sweeps use the directory layout.

**Block-scope probe** (not committed, see conversation log): STF's sweep-C 403 block was session-agnostic and lifted within minutes. Non-browser UAs (`curl/*`) get permanent 403. Browser-shaped UAs all pass — our default Chrome UA is fine. Implication: the block isn't UA/cookie-based; it's rate/behavior-based.

## In-flight at session clear

A rate-budget measurement was started but not completed. Three experiments on disjoint ADI slices:

| run | CSV                                    | flags                   | goal |
|-----|----------------------------------------|-------------------------|------|
| R1  | `tests/sweep/rate_probe_R1.csv` (1–200)   | `--retry-403`            | Is reactive 403 retry practical? |
| R2  | `tests/sweep/rate_probe_R2.csv` (201–400) | `--throttle-sleep 0.5`   | Does ~5 req/s avoid the wall? |
| R3  | `tests/sweep/rate_probe_R3.csv` (401–600) | `--throttle-sleep 2.0`   | Is ~2.5 req/s over-conservative? |

**R1 was launched** to `docs/sweep-results/2026-04-16-D1-retry403/`. State as of this handoff: ~120/200 complete, **zero 403s so far** — which is strange, because sweep C blocked at #108 at comparable request rate earlier the same day. Suggests STF's block threshold has hysteresis we don't yet understand, or the earlier probe (fresh sessions, 4 different UAs) counted against the global window.

**Action for next session**:

1. Check `docs/sweep-results/2026-04-16-D1-retry403/sweep.state.json` for final counts. If completed cleanly, R1's zero-403 result is the finding: at this point in time STF tolerated 200 sequential processes with no pacing.
2. Run R2 and R3 back-to-back. Commands:
   ```bash
   PYTHONPATH=. uv run python scripts/run_sweep.py \
       --csv tests/sweep/rate_probe_R2.csv --label rate_probe_R2_sleep05 \
       --wipe-cache --throttle-sleep 0.5 \
       --parity-csv output/judex-mini_ADI_1-1000.csv \
       --out docs/sweep-results/2026-04-16-D2-sleep05
   PYTHONPATH=. uv run python scripts/run_sweep.py \
       --csv tests/sweep/rate_probe_R3.csv --label rate_probe_R3_sleep20 \
       --wipe-cache --throttle-sleep 2.0 \
       --parity-csv output/judex-mini_ADI_1-1000.csv \
       --out docs/sweep-results/2026-04-16-D3-sleep20
   ```
3. Write `docs/sweep-results/2026-04-16-D-rate-budget.md` comparing all three.

Open TaskList at session start has the three experiments pending under IDs 12/13/14/15.

## The one thing still to decide

**STF's `robots.txt` disallows `/processos` for all user agents.** Sweep C made this real: the WAF enforces it with a 403 block at ~107 consecutive processes (but R1 contradicted this — threshold isn't constant). Three postures (unchanged from the previous handoff):

1. **Minimum professional floor** — custom `User-Agent` identifying the project with a contact email, `NOTICE.md` explaining LAI basis + LGPD obligations, keep scraping with adaptive pacing.
2. **Talk to STF first** — Ouvidoria. Brazilian courts sometimes grant whitelisted access. Slow, safe.
3. **Cache-first distribution** — ship as a parser. Users populate `.cache/` themselves; library never sweeps from one IP.

Still unresolved. No longer blocks the *mechanics* of long sweeps (`--retry-403` + `--throttle-sleep` + `--retry-from` handle it), only the posture question. Doesn't block Selenium retirement either (still internal cleanup).

## What works today

- `main.py --backend={selenium,http}` — default `selenium`. HTTP path additionally accepts `--fetch-pdfs/--no-fetch-pdfs` (default on).
- `src/scraper_http.py`:
  - `_http_get_with_retry` wraps every GET in tenacity (retries 429/5xx/connection errors via `ScraperConfig`; 4xx non-429 fails fast; `cfg.retry_403=True` adds 403 to the retriable set).
  - `run_scraper_http` mirrors `run_scraper` (same output shape, same missing-retry loop).
  - `scrape_processo_http` fetches detalhe + 9 tabs concurrently, derives `tema` from abaSessao, then hits the repgeral JSON endpoints for `sessao_virtual` and (when `fetch_pdfs=True`) fetches+extracts each Relatório/Voto PDF.
- `src/extraction_http_sessao.py` — pure parsers (`parse_oi_listing`, `parse_sessao_virtual`, `parse_tema`) plus the `extract_sessao_virtual_from_json` orchestrator. Fetchers are dependency-injected for testability.
- `src/utils/pdf_cache.py` — URL-keyed PDF text cache under `.cache/pdf/<sha1>.txt.gz`. ADI 2820 cold ≈ 12.9s → cached ≈ 0.18s.
- `src/data/missing.py` — `check_missing_processes` lives here now (was in `src/scraper.py`). Backend-neutral.
- `src/extraction/__init__.py` is intentionally empty — keeps the HTTP backend Selenium-free on import. `import src.scraper_http` loads 0 selenium modules (pinned by `tests/unit/test_http_backend_no_selenium.py`).
- `tests/unit/` — **48 unit tests** covering retry semantics (incl. 403 opt-in), CLI dispatch, PDF cache, sessao_virtual parsers, sweep state recovery + atomic writes, CSV parsing, exception classification. `uv run pytest tests/unit/`.
- `scripts/validate_ground_truth.py` — still the source of truth for HTTP parity. 4/5 MATCH; ACO_2652 shows two pre-existing diffs (assuntos drift on the live site, `pautas: null` vs `[]`). `sessao_virtual` is a SKIP field so it doesn't participate — parsers are validated by the unit tests instead.
- `scripts/run_sweep.py` + `scripts/sweep_state.py` — CSV-driven sweep driver with append-only log, atomic state, resume, retry-from, structured errors, 403 retry, throttle sleep. See the "Running sweeps" section below.

## Next steps, ordered

### 1. Finish the rate-budget experiments

Three sweeps queued in `tests/sweep/rate_probe_R{1,2,3}.csv` (ADI 1..200, 201..400, 401..600). R1 launched before this handoff with `--retry-403` and no pacing — check `docs/sweep-results/2026-04-16-D1-retry403/sweep.state.json` for the result. **R2 (0.5 s sleep) and R3 (2.0 s sleep) still need to run.** Exact commands in the "In-flight" section above.

After all three finish: write `docs/sweep-results/2026-04-16-D-rate-budget.md` comparing wall time, 403 rate, stall patterns. The verdict tells us whether reactive retry (zero tuning) or proactive pacing (predictable pace) is the right default.

### 2. Circuit breaker for the sweep driver

Current `--retry-403` retries per-request with tenacity; per-process can spend ~2.5 min per request × 10 requests = 25 min in worst case if blocks cluster. Should add: abort the sweep if error rate crosses X % in a rolling window of N processes. Also stops the "cascade of 5-min waits" scenario.

Implementation sketch: maintain a `collections.deque(maxlen=N)` of recent statuses in `run_sweep.main`; after each process, if more than X % of the deque is non-ok, write errors, write state, exit with status 2 and a clear message. Tunable via two CLI flags. ~15 min of work.

### 3. Retry sweep C's 893 blocked processes

Sweep C's `docs/sweep-results/2026-04-16-C-full-1000.md` predates the robust driver — it wrote a flat markdown file, no `sweep.errors.jsonl`. So `--retry-from` can't be pointed at it directly. Two options:

- **Re-run the full range under the new driver** once the rate-budget posture is chosen. Uses `--resume` to skip the 107 already in cache.
- **Synthesise an errors.jsonl** from the C report's "status=error" rows (one-off script) to feed `--retry-from`.

Either works. The first is more honest about wall time; the second is faster to start.

### 4. Retire the Selenium path

After the measurement settles:

- Delete `src/scraper.py`, `src/utils/driver.py`, `src/utils/get_element.py`.
- Drop `selenium` from `pyproject.toml`.
- In `src/extraction/`: many extractors are still Selenium-bound (`extract_andamentos.py`, `extract_assuntos.py`, `extract_deslocamentos.py`, `extract_peticoes.py`, `extract_recursos.py`, `extract_partes.py` old bs4 path, `extract_primeiro_autor.py`, `extract_sessao_virtual.py`, `extract_orgao_origem.py`, `extract_data_protocolo.py`, `extract_numero_origem.py`, `extract_volumes_folhas_apensos.py`, `extract_origem.py`, `extract_incidente.py`, `extract_badges.py`). Pure-soup ones (`extract_classe.py`, `extract_meio.py`, `extract_numero_unico.py`, `extract_publicidade.py`, `extract_relator.py`) are imported by `src/extraction_http.py` — keep those.
- **Surfaced during sweeps**: `src/extraction/extract_recursos.py:39` emits `{"index": …}` but the ground-truth fixtures and HTTP extractor emit `{"id": …}`. This is a real Selenium-side inconsistency (see sweep B/C diffs). Deleting the Selenium path resolves it.
- `src/extraction/__init__.py` is already empty; no further `__init__` cleanup needed.

### 5. PDF extraction quality

Currently PDFs go through `pypdf.PdfReader.extract_text(extraction_mode="layout")`. You'll see warnings like `Rotated text discovered. Output will be incomplete.` — these are real: STF often stamps signed documents with rotated watermarks and the extractor drops content around them. Two options: (a) fall back to default mode on rotation, (b) use `pdfminer.six` or OCR for the problem documents. Worth investigating if downstream analysis needs the full text.

### 5. Pre-existing bugs in the Selenium side

Surfaced during the dedup review; untouched because the Selenium path has no automated coverage:

- `src/extraction/extract_peticoes.py:28-30`: `data_match` is assigned from `bg-font-info` on line 28, then immediately overwritten by `processo-detalhes` on line 30. The first match is dead.
- `src/extraction/extract_deslocamentos.py:113-152`: `_clean_extracted_data` looks dead — `_clean_data_fields` is the one called from `_extract_single_deslocamento`. Verify with grep.
- `src/data/types.py:47-78`: commented-out dataclasses. Git remembers; delete.

Not blocking. Clean up if you're already in those files. Safe to defer until Step 2 deletes these files anyway.

## Gaps in the sessao_virtual port

Worth knowing if you're debugging:

- **Vote categories are partial**: only `tipoVoto.codigo` 7 (diverge), 8 (acompanha-divergência), 9 (acompanha) land in the final `votes` dict. Codes 3 (impedido), 10 (acompanha-ressalva), 11 (suspeito), 13 (acompanha-ressalva-ministro) drop out for parity with the Selenium extractor's 5-category DOM scrape. If downstream needs these, extend `_VOTE_CATEGORY` in `src/extraction_http_sessao.py`.
- **documentos values are mixed types**: string containing extracted text (success) or the original URL (fetch failed). Consumers must check `startswith("https://")` to tell. Re-running the scraper picks up where failures left off via the URL-keyed PDF cache.
- **Tema branch has only one fixture test (tema 1020)**. If you see drift there, probe another tema + add a fixture.
- **No Sessão-branch support for "suspended" lists** — if STF ever returns a listaJulgamento mid-suspension with a different JSON shape, `parse_sessao_virtual` will pass through missing fields as empty strings. No known case.

## Non-obvious things (kept from previous handoff, still true)

- **The `abaX.asp` endpoints return 403 without three things**: valid session cookie (`ASPSESSIONID…` + `AWSALB`), `Referer: detalhe.asp?incidente=N`, and `X-Requested-With: XMLHttpRequest`. `requests.Session()` plus the two headers suffices.
- **STF serves UTF-8 without declaring a charset.** `requests` defaults to Latin-1 → mojibake. `scraper_http._decode` handles it; never bypass.
- **`extract_partes` has two possible sources** on `abaPartes.asp`: `#todas-partes` (full, 9 entries for ADI 2820) and `#partes-resumidas` (main parties, 4 entries). The HTTP path uses `#partes-resumidas` for parity with Selenium's `#resumo-partes`.
- **Ground-truth fixtures have inconsistent `sessao_virtual` schemas** across files (MI/RE/AI use `{data,tipo,numero,relator,status,participantes}`; ACO_2652 uses `{lista,relator,orgao_julgador,voto_texto,…}`; ADI_2820_reread uses `{metadata,voto_relator,votes,documentos,julgamento_item_titulo}`). The HTTP port emits the ADI schema — that's what the current code commits to.
- **PDF URLs live on `sistemas.stf.jus.br`, not `portal.stf.jus.br`.** Separate origin, separate throttle counter. Interleaving PDF fetches between tab fetches naturally slows the portal hit rate.
- **DataJud does not have STF.** `api_publica_stf` returns 404. Other tribunals work with the same public API key. Don't re-check.

## How to run things

```bash
# Unit tests (48 tests, <3s)
uv run pytest tests/unit/

# Ground-truth validation (HTTP parity against 5 fixtures)
PYTHONPATH=. uv run python scripts/validate_ground_truth.py

# HTTP scrape, one process, with PDFs
uv run python main.py --backend http -c ADI -i 2820 -f 2820 -o json -d output/test --overwrite

# HTTP scrape without the PDF fetch (faster, documentos stay as URLs)
uv run python main.py --backend http --no-fetch-pdfs -c AI -i 772309 -f 772309 -o json -d output/test --overwrite

# Selenium scrape (unchanged default path)
uv run python main.py -c AI -i 772309 -f 772309 -o json -d output/test --overwrite

# Wipe caches
rm -rf .cache  # HTML fragments, sessao JSON, PDF text
```

## Running sweeps

```bash
# One-shot sweep over a CSV of (classe, processo) pairs
PYTHONPATH=. uv run python scripts/run_sweep.py \
    --csv tests/sweep/shape_coverage.csv \
    --label my_sweep \
    --parity-dir tests/ground_truth \
    --out docs/sweep-results/<date>-<label>

# Long sweep with WAF-friendly pacing
PYTHONPATH=. uv run python scripts/run_sweep.py \
    --csv tests/sweep/full_range_adi.csv \
    --label long_sweep \
    --throttle-sleep 1.0 \
    --retry-403 \
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
    --retry-403 --throttle-sleep 1.0 \
    --out docs/sweep-results/<date>-<label>-retry
```

Sweep output directory layout:
```
<out>/
    sweep.log.jsonl      append-only, one JSON line per attempt
    sweep.state.json     compacted state, atomic rewrite
    sweep.errors.jsonl   derived from state (non-ok only)
    report.md            human-readable summary
```

## Files you probably need to touch first

- `src/scraper_http.py` — HTTP orchestrator, `fetch_process`, `scrape_processo_http`, retry helper (incl. 403 opt-in), PDF/sessão fetcher factories
- `src/config.py` — `ScraperConfig` including `retry_403` flag
- `src/extraction_http.py` — fragment parsers (re-exports Selenium pure-soup extractors)
- `src/extraction_http_sessao.py` — sessao_virtual parsers + orchestrator
- `src/utils/pdf_cache.py` — URL-keyed PDF text cache
- `src/data/missing.py` — backend-neutral check_missing_processes
- `src/extraction/_shared.py` — regex patterns + helpers shared by both paths
- `src/utils/html_cache.py` — gzip + incidente cache (also used for sessão JSON)
- `scripts/_diff.py` — shared field-by-field diff
- `scripts/run_sweep.py` — CSV-driven sweep driver (state/log/errors + resume/retry-from/signal handling)
- `scripts/sweep_state.py` — append-only log + atomic compacted state (independent of run_sweep, reusable)
- `main.py` — CLI

## Files that already work; don't break them

- `tests/ground_truth/*.json` — fixtures for `scripts/validate_ground_truth.py`
- `tests/fixtures/sessao_virtual/*.json` — captured JSON for the sessao_virtual unit tests
- `tests/unit/*.py` — 27 tests; run them before every change
- `src/data/types.py` — `StfItem` TypedDict (fixed Optional types; don't make them non-Optional again)
- `src/data/export.py` — write paths for CSV/JSON/JSONL output
