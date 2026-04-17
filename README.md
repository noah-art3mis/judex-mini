# judex-mini

Extração automatizada de dados de processos do STF.

Scraper + parser for case metadata at `portal.stf.jus.br/processos/`.
Given a class and a process number (e.g. `HC 135041`), fetches the
process page, parses parties / andamentos / relator / outcome /
linked PDFs, and emits one JSON record per process.

## Instalação

```bash
# instalar wsl (SOMENTE WINDOWS)
wsl --install

# instalar uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# instalar chromedriver (pode demorar) — necessário apenas para o
# backend Selenium legado; o backend HTTP padrão não precisa
sudo apt install chromium-chromedriver

# clonar repositório
git clone https://github.com/noah-art3mis/judex-mini

# baixar dependências
cd judex-mini && uv sync
```

## Uso

```bash
# uso normal
uv run python main.py --classe ADI --processo-inicial 1 --processo-final 2

# abreviado (ver uv run python main.py --help)
uv run python main.py -c AI -i 1234567 -f 1234570

# backend HTTP (padrão para novos casos — ~10× mais rápido)
uv run python main.py --backend http -c HC -i 135041 -f 135041 \
    -o json -d data/output/test --overwrite

# salvar arquivos no desktop do windows
uv run python main.py --output-dir /mnt/c/Users/YourUsername/Desktop/judex-mini
```

Para mais detalhes ver `uv run python main.py --help`. Para alterar
valores (max_retries, webdriver_timeout, etc.), ver `src/config.py`.

## Testes

```bash
# suíte unitária (157 testes, <3s)
uv run pytest tests/unit/

# validação contra fixtures de ground-truth (parity vs. dados
# conferidos à mão em tests/ground_truth/*.json)
PYTHONPATH=. uv run python scripts/validate_ground_truth.py
```

## Where the data lives

Start with **[`docs/data-layout.md`](docs/data-layout.md)** — the
canonical spatial map of stores, keys, and the foreign key from case
JSON to cached PDF text.

TL;DR three stores:

- **Case JSON**: `data/output/**/judex-mini_<CLASSE>_<N>.json` — one record
  per process, schema in `src/data/types.py` (`StfItem` TypedDict).
- **PDF text cache**: `data/pdf/<sha1(url)>.txt.gz` — extracted
  text, URL-keyed. Read via `src.utils.pdf_cache.read(url)`.
- **PDF elements cache**: `data/pdf/<sha1(url)>.elements.json.gz` —
  structured Unstructured element list for OCR-sourced entries only.
  Read via `pdf_cache.read_elements(url)` (returns `None` for
  pypdf-sourced URLs).
- **HTML fragment cache**: `data/html/<CLASSE>_<N>/*.html.gz` —
  per-tab raw HTML; ~60× speedup on re-scrapes.

The foreign key from a case to its PDF text:

```
data/output/.../judex-mini_HC_135041.json
  └── andamentos[17].link                   ← STF portal PDF URL
       └── src.utils.pdf_cache.read(link)   ← extracted text
```

## Architecture

**HTTP is the only first-class scraping backend** (`src/scraper.py`):
replays the XHR requests `/processos/detalhe.asp` and
`/processos/abaX.asp` make. Fetches detalhe + 9 tabs concurrently;
`sessao_virtual` comes from `sistemas.stf.jus.br/repgeral/votacao`
as JSON + PDFs. ~10× faster per process than the original Selenium
path.

The legacy Selenium scraper was frozen at `src/_deprecated/scraper.py`
on 2026-04-17. To install the optional dep:
`uv sync --extra selenium-legacy`. Passing `main.py --backend selenium`
errors with a deprecation message — see
`docs/superpowers/specs/2026-04-17-selenium-retirement.md`.

STF's `/processos/*` is disallowed by `robots.txt` and the WAF
enforces it with 403 bursts (not 429) above a ~100-process
behavioral threshold. `ScraperConfig.retry_403=True` + a 2s
`--throttle-sleep` floor absorb the block cycles transparently.

### Sweep drivers

Two institutional sweep drivers, both with resume / retry-from /
circuit breaker / SIGINT-safe shutdown / atomic state:

- **Process sweep** — `scripts/run_sweep.py` (+ `src/process_store.py`
  + `src/_shared.py`): CSV-driven, one (classe, processo) per row.
  Output at `docs/sweep-results/<date>-<label>/`.
- **PDF sweep** — `scripts/fetch_pdfs.py` (+ `src/pdf_driver.py` +
  `src/pdf_store.py`): walks case JSON, filters by
  `--classe/--impte-contains/--doc-types/--relator-contains`,
  fetches each andamento PDF. Output at
  `docs/pdf-sweeps/<date>-<label>/`.

OCR re-extraction (`scripts/reextract_unstructured.py`) runs as a
sibling of the PDF sweep; uses the Unstructured API's `hi_res`
strategy and writes both the flat text and the structured element
list back to the cache. See [`docs/pdf-sweeps/README.md`](docs/pdf-sweeps/README.md)
for the PDF-sweep directory conventions.

## Documentation index

| File | What it tells you |
|---|---|
| [`docs/data-layout.md`](docs/data-layout.md)         | Spatial map — where every store lives and how they reference each other. **Start here.** |
| [`docs/handoff.md`](docs/handoff.md)                 | Temporal map — what's in flight, what's blocked, what's next. |
| [`docs/perf-bulk-data.md`](docs/perf-bulk-data.md)   | Original investigation — DataJud dead-end, STF portal mechanics, perf claims and caveats. |
| [`docs/sweep-results/`](docs/sweep-results/)         | Per-run artifacts for process sweeps. `2026-04-16-E-full-1k-defaults/SUMMARY.md` is the canonical SUMMARY template. |
| [`docs/pdf-sweeps/README.md`](docs/pdf-sweeps/README.md) | PDF-sweep directory conventions. |
| [`CLAUDE.md`](CLAUDE.md)                             | Agent + contributor gotchas, conventions, "don't break these" list. |

## Key source modules

| Module | Role |
|---|---|
| `src/scraper.py`                                             | HTTP backend orchestrator. `fetch_process` + `scrape_processo_http`. (Was `scraper_http.py` until 2026-04-17.) |
| `src/extraction_http*.py`                                    | Pure-soup parsers for the HTTP path. |
| `src/data/types.py`                                          | `StfItem` TypedDict — the case-JSON schema. |
| `src/utils/pdf_cache.py`                                     | URL-keyed text + elements cache. |
| `src/process_store.py` + `src/_shared.py`                    | Process-sweep state / log / errors + shared primitives. |
| `src/pdf_driver.py` + `src/pdf_store.py`                     | PDF-sweep driver — resumable, circuit-breakered, SIGINT-safe. |
| `src/utils/adaptive_throttle.py` + `src/utils/request_log.py`| Per-host latency-aware delay + per-GET SQLite archive. |
| `scripts/run_sweep.py`                                       | CSV-driven process sweep. |
| `scripts/fetch_pdfs.py`                                      | Generic PDF sweep. |
| `scripts/reextract_unstructured.py`                          | Re-OCR image-only PDFs via the Unstructured API. |

## Dependencies

`selenium` (legacy backend), `requests` + `beautifulsoup4` (HTTP backend),
`tenacity` (retry), `typer` (CLI), `pypdf` (PDF text), `python-dotenv`
(env loading), `unstructured-client` via HTTP (OCR).
