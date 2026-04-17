# CLAUDE.md — judex-mini (project-level)

Scraper + parser for STF (Brazilian Supreme Court) process data. **HTTP is the only first-class backend.** The legacy Selenium implementation was frozen under `deprecated/` on 2026-04-17 (`docs/superpowers/specs/2026-04-17-selenium-retirement.md`); `--backend selenium` now errors out. See `docs/handoff.md` for current task state.

## Read first

1. **`docs/data-layout.md`** — spatial map (the three stores + foreign key).
2. **`docs/stf-portal.md`** — how the portal works (URL flow, auth triad, field→source map).
3. **`docs/rate-limits.md`** — WAF behavior + validated sweep defaults + robots.txt posture question.
4. **`docs/handoff.md`** — what's in flight, blocked, next.
5. **`docs/process-space.md`** / **`docs/performance.md`** — class sizes + perf numbers (on demand).
6. **`docs/sweep-results/`** — per-run artifacts from validation sweeps A–I+.
7. **`docs/superpowers/specs/`** — design specs for major features.

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

- **HTTP backend** (`src/scraping/scraper.py`): replays the XHR requests `/processos/detalhe.asp` and `/processos/abaX.asp` make. Fetches detalhe + 9 tabs concurrently (`_TAB_WORKERS=4`). `sessao_virtual` comes from `sistemas.stf.jus.br/repgeral/votacao` as JSON + PDFs. The only live scraping path. Was `src/scraper_http.py` until 2026-04-17 — renamed once Selenium retirement freed up the canonical name.
- **Selenium backend** (`deprecated/scraper.py`): frozen reference, not imported by live code. To install the optional dep + import it directly: `uv sync --extra selenium-legacy`. See `deprecated/README.md`.
- **Pure-soup extractors** (`src/scraping/extraction/*.py`): five small modules — `extract_classe`, `extract_meio`, `extract_numero_unico`, `extract_publicidade`, `extract_relator` — plus `_shared.py` regex helpers. Imported by `src/scraping/extraction/http.py`. The 16 Selenium-bound extractors moved to `deprecated/extraction/`.
- **HTTP extractors** (`src/scraping/extraction/http.py`, `src/scraping/extraction/sessao.py`): fragment parsers for the HTTP path.
- **Sweep driver** (`scripts/run_sweep.py` + `src/sweeps/process_store.py` + `src/sweeps/shared.py`): CSV-driven, appends to `sweep.log.jsonl`, atomic `sweep.state.json`, derived `sweep.errors.jsonl`. Supports `--resume`, `--retry-from`, `--retry-403`, `--throttle-sleep`, graceful SIGINT/SIGTERM. Circuit breaker, signal handlers and exception classifier live in `src/sweeps/shared.py` and are reused by `src/sweeps/pdf_driver.py`.

## Caches

- `data/html/<CLASSE>_<N>/<tab>.html.gz` — gzipped HTML fragments + `incidente.txt` per process. Gzip-on-write, gzip-on-read.
- `data/html/<CLASSE>_<N>/sessao_oi_<inc>.html.gz`, `sessao_sessaoVirtual_<inc>.html.gz` — sessão JSON cached under the same directory, named as pseudo-tabs.
- `data/pdf/<sha1(url)>.txt.gz` — extracted PDF text, URL-keyed. Hot vs cold = ~60× speed-up.

Wipe everything: `rm -rf data`. Wipe per-process: `rm -rf data/html/<CLASSE>_<N>`.

## Non-obvious gotchas

- **STF serves UTF-8 without declaring a charset.** `requests` defaults to Latin-1 → mojibake. `scraper._decode` sets `r.encoding = "utf-8"` before reading `r.text`. Never bypass.
- **`/processos/*` is disallowed in STF's `robots.txt`.** STF enforces it at the WAF: HTTP **403 Forbidden** (not 429) blocks IPs that exceed a behavioral threshold. The block clears within minutes. `cfg.retry_403=True` (via `ScraperConfig` or `--retry-403`) rides it out with tenacity backoff; `--throttle-sleep <s>` paces proactively. Non-browser UAs (`curl/*`) get permanent 403 — our default Chrome UA is fine.
- **`abaX.asp` endpoints return 403 without three things**: valid `ASPSESSIONID…` + `AWSALB` cookies, `Referer: detalhe.asp?incidente=N`, and `X-Requested-With: XMLHttpRequest`. `requests.Session()` plus those two headers suffices.
- **`extract_partes` has two sources** on `abaPartes.asp`: `#todas-partes` (full, 9 entries for ADI 2820) and `#partes-resumidas` (main parties, 4 entries). HTTP path uses `#partes-resumidas` for parity with Selenium's `#resumo-partes`.
- **Ground-truth fixtures have inconsistent `sessao_virtual` schemas.** HTTP emits the ADI shape (`{metadata, voto_relator, votes, documentos, …}`). `sessao_virtual` is a SKIP field in `scripts/_diff.SKIP_FIELDS` — do not try to diff it.
- **PDF URLs live on `sistemas.stf.jus.br`**, NOT `portal.stf.jus.br`. Separate origin, separate throttle counter.
- **DataJud does not have STF.** `api_publica_stf` returns 404. Don't re-check.
- **`src/scraping/extraction/__init__.py` is intentionally empty.** Keeps the HTTP backend Selenium-free. `import src.scraper` and `import main` both load 0 selenium modules — pinned by `tests/unit/test_http_backend_no_selenium.py`.
- **`data/pdf/<sha1>.txt.gz` is monotonic-by-length, not archival.** `scripts/reextract_unstructured.py` overwrites the pypdf extract when the OCR pass is longer. The prior attempt is lost unless the script is routed through `src/sweeps/pdf_driver.py` (which keeps history in `pdfs.log.jsonl`). Right now it isn't — see the script's "Known gaps" block. Implication: don't trust the on-disk cache as an audit trail of what a given extractor produced at a given time.

## Don't break these

- `tests/ground_truth/*.json` — 5 fixtures; the source of truth for `validate_ground_truth.py`.
- `tests/fixtures/sessao_virtual/*.json` — captured JSON for the sessao_virtual unit tests.
- `tests/unit/*.py` — 48 tests; run them before every change. `uv run pytest tests/unit/`.
- `src/data/types.py` — `StfItem` TypedDict. Fields are Optional for a reason; don't make them non-Optional again.
- `src/data/export.py` — write paths for CSV/JSON/JSONL output.
- `src/sweeps/process_store.py` — atomic write contracts are load-bearing; don't add non-atomic state updates. `src/sweeps/pdf_store.py` mirrors the same contracts for URL-keyed PDF sweeps.

## Calculations

**Always use code** (`uv run python -c "..."` or equivalent) for non-trivial arithmetic. Never mental math, especially in docs and reports where incorrect numbers get quoted downstream. Inherited from user-level `~/.claude/CLAUDE.md § Arithmetic`, repeated here because the rate-budget doc (`docs/sweep-results/2026-04-16-D-rate-budget.md`) was the case where forgetting it bit us.

## Conventions (project-specific)

- **No backwards-compat shims.** Change the call sites + tests. See user-level `CLAUDE.md`.
- **Keep files focused.** When `scraper.py` grows past ~600 lines, split by concern — `fetch_process`, PDF fetchers, sessão orchestration already have their own modules. (`http_session.py` was carved off in this exact way; see `src/scraping/http_session.py`.)
- **Extractor tests should diff against captured fixtures**, not hand-built dicts. Pattern: `tests/fixtures/<feature>/<case>.json`.
- **Sweeps write everything to a directory**, not a single file. `<out>/report.md`, `<out>/sweep.log.jsonl`, etc.
- **Measure before optimising.** The perf numbers in `docs/performance.md` apply to cold single-process requests; at sweep scale the WAF ceiling (`docs/rate-limits.md`) dominates and the naive extrapolation doesn't hold. Check `docs/sweep-results/` for the latest reality.

## Testing

```bash
# suíte unitária (fast — <3 s, run before every change)
uv run pytest tests/unit/

# ground-truth parity vs. hand-verified JSON in tests/ground_truth/
PYTHONPATH=. uv run python scripts/validate_ground_truth.py
```

Fixtures:
- `tests/ground_truth/*.json` — 5 hand-verified cases; the source of truth for `validate_ground_truth.py`.
- `tests/fixtures/sessao_virtual/*.json` — captured JSON for the sessão_virtual unit tests.
- `tests/unit/test_http_backend_no_selenium.py` — pins that the HTTP path loads 0 Selenium modules.

## Where the data lives

See [`docs/data-layout.md`](docs/data-layout.md) for the canonical spatial
map. Three stores + the foreign key between them:

- **Case JSON** — `data/output/**/judex-mini_<CLASSE>_<N>.json`, one record per process, schema in `src/data/types.py` (`StfItem` TypedDict).
- **PDF text cache** — `data/pdf/<sha1(url)>.txt.gz`, URL-keyed. Read via `src.utils.pdf_cache.read(url)`.
- **PDF elements cache** — `data/pdf/<sha1(url)>.elements.json.gz`, structured Unstructured element list for OCR-sourced entries only. Read via `pdf_cache.read_elements(url)` — returns `None` for pypdf-sourced URLs.
- **HTML fragment cache** — `data/html/<CLASSE>_<N>/*.html.gz`, per-tab raw HTML; ~60× speedup on re-scrapes.

Foreign key from a case to its PDF text:

```
data/output/.../judex-mini_HC_135041.json
  └── andamentos[17].link                   ← STF portal PDF URL
       └── src.utils.pdf_cache.read(link)   ← extracted text
```

## Sweep drivers

Two institutional sweep drivers, both resume / retry-from / circuit-breaker / SIGINT-safe / atomic-state:

- **Process sweep** — `scripts/run_sweep.py` + `src/sweeps/process_store.py` + `src/sweeps/shared.py`. CSV-driven, one `(classe, processo)` per row. Output at `docs/sweep-results/<date>-<label>/`.
- **PDF sweep** — `scripts/fetch_pdfs.py` + `src/sweeps/pdf_driver.py` + `src/sweeps/pdf_store.py`. Walks case JSON, filters by `--classe / --impte-contains / --doc-types / --relator-contains`, fetches each andamento PDF. Output at `docs/pdf-sweeps/<date>-<label>/`.

OCR re-extraction (`scripts/reextract_unstructured.py`) runs as a sibling of the PDF sweep; Unstructured API `hi_res` strategy, writes both flat text and structured element list back to the cache. See [`docs/pdf-sweeps/README.md`](docs/pdf-sweeps/README.md) for directory conventions.

## Key source modules

| Module | Role |
|---|---|
| `src/scraping/scraper.py`                                       | HTTP backend orchestrator — `fetch_process` + `scrape_processo_http`. |
| `src/scraping/http_session.py`                                  | Session builder: cookies, headers, `X-Requested-With`, UA. |
| `src/scraping/extraction/*.py`                                  | Pure-soup fragment parsers for the HTTP path. |
| `src/data/types.py`                                             | `StfItem` TypedDict — the case-JSON schema. |
| `src/data/export.py`                                            | CSV / JSON / JSONL write paths. |
| `src/utils/pdf_cache.py`                                        | URL-keyed text + elements cache. |
| `src/utils/adaptive_throttle.py` + `src/utils/request_log.py`   | Per-host latency-aware delay + per-GET SQLite archive. |
| `src/sweeps/process_store.py` + `src/sweeps/shared.py`          | Process-sweep state / log / errors + shared primitives (circuit breaker, signal handlers, exception classifier). |
| `src/sweeps/pdf_driver.py` + `src/sweeps/pdf_store.py`          | PDF-sweep driver — resumable, circuit-breakered, SIGINT-safe. |
| `scripts/run_sweep.py`                                          | CSV-driven process sweep entry. |
| `scripts/fetch_pdfs.py`                                         | Generic PDF sweep entry. |
| `scripts/reextract_unstructured.py`                             | Re-OCR image-only PDFs via the Unstructured API. |

## Documentation index

| File | What it tells you |
|---|---|
| [`README.md`](README.md)                                 | End-user getting-started guide (Portuguese). Install → first run → troubleshooting. |
| [`docs/data-layout.md`](docs/data-layout.md)             | Spatial map — every store, every key, every cross-reference. **Start here.** |
| [`docs/stf-portal.md`](docs/stf-portal.md)               | How the STF portal works — URL flow, auth triad, UTF-8 quirk, field→source map, DataJud dead-end. |
| [`docs/rate-limits.md`](docs/rate-limits.md)             | WAF behavior (403-not-429), empirical thresholds, validated defaults, robots.txt posture question. |
| [`docs/process-space.md`](docs/process-space.md)         | HC / ADI / RE ceilings + density-probe numbers + methodology. |
| [`docs/performance.md`](docs/performance.md)             | HTTP-vs-Selenium measured numbers; caching is the real lever. |
| [`docs/handoff.md`](docs/handoff.md)                     | Temporal map — what just landed, in flight, next steps. |
| [`docs/hc-who-wins.md`](docs/hc-who-wins.md)             | HC deep-dive research question + notebook-strand layout + findings. |
| [`docs/sweep-results/`](docs/sweep-results/)             | Per-run artifacts for process sweeps. `2026-04-16-E-full-1k-defaults/SUMMARY.md` is the canonical SUMMARY template. |
| [`docs/pdf-sweeps/README.md`](docs/pdf-sweeps/README.md) | PDF-sweep directory conventions. |
| [`docs/superpowers/specs/`](docs/superpowers/specs/)     | Design specs for major features (sweep driver, rate-budget experiments, Selenium retirement). |

## Dependencies

`requests` + `beautifulsoup4` (HTTP backend), `tenacity` (retry), `typer` (CLI), `pypdf` (PDF text), `python-dotenv` (env loading), `unstructured-client` via HTTP (OCR). `selenium` is an optional extra (`uv sync --extra selenium-legacy`) gated behind the frozen `deprecated/` backend.
