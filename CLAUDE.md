# CLAUDE.md — judex-mini (project-level)

Scraper + parser for STF (Brazilian Supreme Court) process data. Two backends live side-by-side: **Selenium** (legacy, being retired) and **HTTP** (default target, faster). See `docs/handoff.md` for current task state.

## Read first

1. **`docs/handoff.md`** — what's in flight, what's blocked, what's next.
2. **`docs/perf-bulk-data.md`** — original investigation (DataJud dead-end, STF mechanics, 5.7× / ~20× perf claim).
3. **`docs/sweep-results/`** — results from validation sweeps A, B, C, and whatever's in flight under `D*`.
4. **`docs/superpowers/specs/`** — design specs for major features (sweep driver, rate-budget experiments).

## Runtime

Python project managed with **`uv`**. **Never** run bare `python`, `pip`, or `pytest` — always:

```bash
uv run pytest tests/unit/
uv run python main.py ...
uv add <pkg>             # adds to pyproject
```

Tests live under `tests/unit/` (48 fast tests, <3 s). Fixtures under `tests/ground_truth/` and `tests/fixtures/`. Run them before every change.

Many scripts need `PYTHONPATH=.` because they import `src.*` and `scripts.*`:
```bash
PYTHONPATH=. uv run python scripts/validate_ground_truth.py
PYTHONPATH=. uv run python scripts/run_sweep.py ...
```

## Scraping architecture

- **HTTP backend** (`src/scraper_http.py`): replays the XHR requests `/processos/detalhe.asp` and `/processos/abaX.asp` make. Fetches detalhe + 9 tabs concurrently (`_TAB_WORKERS=4`). `sessao_virtual` comes from `sistemas.stf.jus.br/repgeral/votacao` as JSON + PDFs.
- **Selenium backend** (`src/scraper.py`): the legacy path. Slower; still the default for `main.py`. To be retired (handoff step 4).
- **Shared extractors** (`src/extraction/*.py`): some are pure-soup (class/meio/numero_unico/publicidade/relator) and imported by both; the rest are Selenium-bound and being replaced.
- **HTTP extractors** (`src/extraction_http.py`, `src/extraction_http_sessao.py`): fragment parsers for the HTTP path.
- **Sweep driver** (`scripts/run_sweep.py` + `src/process_store.py` + `src/_shared.py`): CSV-driven, appends to `sweep.log.jsonl`, atomic `sweep.state.json`, derived `sweep.errors.jsonl`. Supports `--resume`, `--retry-from`, `--retry-403`, `--throttle-sleep`, graceful SIGINT/SIGTERM. Circuit breaker, signal handlers and exception classifier live in `src/_shared.py` and are reused by `src/pdf_driver.py`.

## Caches

- `.cache/html/<CLASSE>_<N>/<tab>.html.gz` — gzipped HTML fragments + `incidente.txt` per process. Gzip-on-write, gzip-on-read.
- `.cache/html/<CLASSE>_<N>/sessao_oi_<inc>.html.gz`, `sessao_sessaoVirtual_<inc>.html.gz` — sessão JSON cached under the same directory, named as pseudo-tabs.
- `.cache/pdf/<sha1(url)>.txt.gz` — extracted PDF text, URL-keyed. Hot vs cold = ~60× speed-up.

Wipe everything: `rm -rf .cache`. Wipe per-process: `rm -rf .cache/html/<CLASSE>_<N>`.

## Non-obvious gotchas

- **STF serves UTF-8 without declaring a charset.** `requests` defaults to Latin-1 → mojibake. `scraper_http._decode` sets `r.encoding = "utf-8"` before reading `r.text`. Never bypass.
- **`/processos/*` is disallowed in STF's `robots.txt`.** STF enforces it at the WAF: HTTP **403 Forbidden** (not 429) blocks IPs that exceed a behavioral threshold. The block clears within minutes. `cfg.retry_403=True` (via `ScraperConfig` or `--retry-403`) rides it out with tenacity backoff; `--throttle-sleep <s>` paces proactively. Non-browser UAs (`curl/*`) get permanent 403 — our default Chrome UA is fine.
- **`abaX.asp` endpoints return 403 without three things**: valid `ASPSESSIONID…` + `AWSALB` cookies, `Referer: detalhe.asp?incidente=N`, and `X-Requested-With: XMLHttpRequest`. `requests.Session()` plus those two headers suffices.
- **`extract_partes` has two sources** on `abaPartes.asp`: `#todas-partes` (full, 9 entries for ADI 2820) and `#partes-resumidas` (main parties, 4 entries). HTTP path uses `#partes-resumidas` for parity with Selenium's `#resumo-partes`.
- **Ground-truth fixtures have inconsistent `sessao_virtual` schemas.** HTTP emits the ADI shape (`{metadata, voto_relator, votes, documentos, …}`). `sessao_virtual` is a SKIP field in `scripts/_diff.SKIP_FIELDS` — do not try to diff it.
- **PDF URLs live on `sistemas.stf.jus.br`**, NOT `portal.stf.jus.br`. Separate origin, separate throttle counter.
- **DataJud does not have STF.** `api_publica_stf` returns 404. Don't re-check.
- **`src/extraction/__init__.py` is intentionally empty.** Keeps the HTTP backend Selenium-free. `import src.scraper_http` loads 0 selenium modules — pinned by `tests/unit/test_http_backend_no_selenium.py`.
- **`recursos[].id` vs `recursos[].index`**: HTTP emits `id` (matches ground truth), Selenium code emits `index` (doesn't). Surfaced by sweeps B and C. Fix = retire Selenium.
- **`.cache/pdf/<sha1>.txt.gz` is monotonic-by-length, not archival.** `scripts/reextract_unstructured.py` overwrites the pypdf extract when the OCR pass is longer. The prior attempt is lost unless the script is routed through `src/pdf_driver.py` (which keeps history in `pdfs.log.jsonl`). Right now it isn't — see the script's "Known gaps" block. Implication: don't trust the on-disk cache as an audit trail of what a given extractor produced at a given time.

## Don't break these

- `tests/ground_truth/*.json` — 5 fixtures; the source of truth for `validate_ground_truth.py`.
- `tests/fixtures/sessao_virtual/*.json` — captured JSON for the sessao_virtual unit tests.
- `tests/unit/*.py` — 48 tests; run them before every change. `uv run pytest tests/unit/`.
- `src/data/types.py` — `StfItem` TypedDict. Fields are Optional for a reason; don't make them non-Optional again.
- `src/data/export.py` — write paths for CSV/JSON/JSONL output.
- `src/process_store.py` — atomic write contracts are load-bearing; don't add non-atomic state updates. `src/pdf_store.py` mirrors the same contracts for URL-keyed PDF sweeps.

## Calculations

**Always use code** (`uv run python -c "..."` or equivalent) for non-trivial arithmetic. Never mental math, especially in docs and reports where incorrect numbers get quoted downstream. Inherited from user-level `~/.claude/CLAUDE.md § Arithmetic`, repeated here because the rate-budget doc (`docs/sweep-results/2026-04-16-D-rate-budget.md`) was the case where forgetting it bit us.

## Conventions (project-specific)

- **No backwards-compat shims.** Change the call sites + tests. See user-level `CLAUDE.md`.
- **Keep files focused.** When `scraper_http.py` grows past ~600 lines, split by concern — `fetch_process`, PDF fetchers, sessão orchestration already have their own modules.
- **Extractor tests should diff against captured fixtures**, not hand-built dicts. Pattern: `tests/fixtures/<feature>/<case>.json`.
- **Sweeps write everything to a directory**, not a single file. `<out>/report.md`, `<out>/sweep.log.jsonl`, etc.
- **Measure before optimising.** The perf claim in `docs/perf-bulk-data.md` has caveats; sweep C showed a new constraint (STF's WAF threshold) that invalidated the naive extrapolation. Check `docs/sweep-results/` for the latest reality.
