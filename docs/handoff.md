# Handoff — judex-mini perf/bulk-data work

Branch: `experiment/perf-bulk-data`
Status: landed + pushed; 5 commits ahead of `main`. Tip: `bc1737c`.
PR: https://github.com/noah-art3mis/judex-mini/pull/new/experiment/perf-bulk-data

Start by reading `docs/perf-bulk-data.md` for the full investigation (DataJud dead-end, STF portal mechanics, 5.7×/~20× perf claim with caveats). This note only covers what's unfinished and why.

## The one thing to decide before any more scraping

**STF's `robots.txt` disallows `/processos` for all user agents.** Not illegal (LAI 12.527/2011 makes court data public) but an explicit machine-readable "please don't". Three postures:

1. **Minimum professional floor** — custom `User-Agent` identifying the project with a contact email, `NOTICE.md` explaining LAI basis + LGPD obligations, keep scraping.
2. **Talk to STF first** — Ouvidoria. Brazilian courts sometimes grant whitelisted access. Slow, safe.
3. **Cache-first distribution** — ship as a parser. Users populate `.cache/` themselves; library never sweeps from one IP.

Still unresolved. Blocks Step 4 (larger validation sweep). Does *not* block Step 3 (Selenium retirement) — that's internal cleanup.

## What works today

- `main.py --backend={selenium,http}` — default `selenium`. HTTP path additionally accepts `--fetch-pdfs/--no-fetch-pdfs` (default on).
- `src/scraper_http.py`:
  - `_http_get_with_retry` wraps every GET in tenacity (retries 429/5xx/connection errors via `ScraperConfig`; 4xx non-429 fails fast).
  - `run_scraper_http` mirrors `run_scraper` (same output shape, same missing-retry loop).
  - `scrape_processo_http` fetches detalhe + 9 tabs concurrently, derives `tema` from abaSessao, then hits the repgeral JSON endpoints for `sessao_virtual` and (when `fetch_pdfs=True`) fetches+extracts each Relatório/Voto PDF.
- `src/extraction_http_sessao.py` — pure parsers (`parse_oi_listing`, `parse_sessao_virtual`, `parse_tema`) plus the `extract_sessao_virtual_from_json` orchestrator. Fetchers are dependency-injected for testability.
- `src/utils/pdf_cache.py` — URL-keyed PDF text cache under `.cache/pdf/<sha1>.txt.gz`. ADI 2820 cold ≈ 12.9s → cached ≈ 0.18s.
- `src/data/missing.py` — `check_missing_processes` lives here now (was in `src/scraper.py`). Backend-neutral.
- `src/extraction/__init__.py` is intentionally empty — keeps the HTTP backend Selenium-free on import. `import src.scraper_http` loads 0 selenium modules (pinned by `tests/unit/test_http_backend_no_selenium.py`).
- `tests/unit/` — 27 unit tests covering retry semantics, CLI dispatch, PDF cache, sessao_virtual parsers (oi/sessaoVirtual/tema against captured JSON for ADI 2820 + live tema 1020). `uv run pytest tests/unit/`.
- `scripts/validate_ground_truth.py` — still the source of truth for HTTP parity. 4/5 MATCH; ACO_2652 shows two pre-existing diffs (assuntos drift on the live site, `pautas: null` vs `[]`). `sessao_virtual` is a SKIP field so it doesn't participate — parsers are validated by the unit tests instead.

## Next steps, ordered

### 1. Larger validation sweep

This is what "the user said next" — blocked on picking a shape + the robots.txt posture. Three sizes in increasing footprint:

- **Shape-coverage smoke** (~10–15 min): 2 processes per class across RE / AI / ADI / ACO / MI / HC. Goal: shake out schema surprises (unusual `partes`, Tema branches, missing PDF links). Lowest footprint.
- **Throttle probe** (~30–60 min): 50 consecutive AIs. Goal: measure steady-state throughput + whether 429s appear + cache effectiveness on repeat.
- **Full regression sweep** (~1–3 hr): 20–50 processes mixing classes and sizes per the original plan. Needs the robots.txt posture decided first.

Extend `scripts/validate_ground_truth.py` to pull from a CSV of `(classe, processo)` pairs instead of globbing fixtures; record any field that diverges more than once across the sample.

### 2. Retire the Selenium path

After a sweep passes:

- Delete `src/scraper.py`, `src/utils/driver.py`, `src/utils/get_element.py`.
- Drop `selenium` from `pyproject.toml`.
- In `src/extraction/`: many extractors are still Selenium-bound (`extract_andamentos.py`, `extract_assuntos.py`, `extract_deslocamentos.py`, `extract_peticoes.py`, `extract_recursos.py`, `extract_partes.py` old bs4 path, `extract_primeiro_autor.py`, `extract_sessao_virtual.py`, `extract_orgao_origem.py`, `extract_data_protocolo.py`, `extract_numero_origem.py`, `extract_volumes_folhas_apensos.py`, `extract_origem.py`, `extract_incidente.py`, `extract_badges.py`). Pure-soup ones (`extract_classe.py`, `extract_meio.py`, `extract_numero_unico.py`, `extract_publicidade.py`, `extract_relator.py`) are imported by `src/extraction_http.py` — keep those.
- `src/extraction/__init__.py` is already empty; no further `__init__` cleanup needed.

### 3. 429-aware backoff on sustained sweeps

Tenacity already retries 429; what's missing is **cross-process** slowdown. STF throttles progressively — after the first few 429s you want to lower global concurrency and widen the spacing, not just retry each request harder. Pattern sketch: a shared counter in `scrape_processo_http` that records 429 rate over a rolling window; when it crosses a threshold, insert a sleep between processes in `_scrape_http_batch`. Tune via `ScraperConfig`.

### 4. PDF extraction quality

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
# Unit tests
uv run pytest tests/unit/

# Ground-truth validation (source of truth for HTTP parity)
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

## Files you probably need to touch first

- `src/scraper_http.py` — HTTP orchestrator, `fetch_process`, `scrape_processo_http`, retry helper, PDF/sessão fetcher factories
- `src/extraction_http.py` — fragment parsers (re-exports Selenium pure-soup extractors)
- `src/extraction_http_sessao.py` — sessao_virtual parsers + orchestrator
- `src/utils/pdf_cache.py` — URL-keyed PDF text cache
- `src/data/missing.py` — backend-neutral check_missing_processes
- `src/extraction/_shared.py` — regex patterns + helpers shared by both paths
- `src/utils/html_cache.py` — gzip + incidente cache (also used for sessão JSON)
- `scripts/_diff.py` — shared field-by-field diff
- `main.py` — CLI

## Files that already work; don't break them

- `tests/ground_truth/*.json` — fixtures for `scripts/validate_ground_truth.py`
- `tests/fixtures/sessao_virtual/*.json` — captured JSON for the sessao_virtual unit tests
- `tests/unit/*.py` — 27 tests; run them before every change
- `src/data/types.py` — `StfItem` TypedDict (fixed Optional types; don't make them non-Optional again)
- `src/data/export.py` — write paths for CSV/JSON/JSONL output
