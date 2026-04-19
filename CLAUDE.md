# CLAUDE.md — judex-mini (project-level)

Scraper + parser for STF (Brazilian Supreme Court) process data. **HTTP is the only first-class backend.** The legacy Selenium implementation was frozen under `deprecated/` on 2026-04-17; `--backend selenium` now errors out.

## When to read what

| Open this doc when… | File |
|---|---|
| Starting a session / resuming work | [`docs/current_progress.md`](docs/current_progress.md) — active-task lab notebook + strategic state. Living file; template and archive convention live inside it. |
| You need to know where a file lives (cases, caches, runs, exports) | [`docs/data-layout.md`](docs/data-layout.md) — spatial map of every store and every key. |
| Writing new scraping code or debugging a 403 | [`docs/stf-portal.md`](docs/stf-portal.md) — URL flow, auth triad, UTF-8 quirk, field→source map. |
| Tuning request pacing, retries, or proxy rotation | [`docs/rate-limits.md`](docs/rate-limits.md) — WAF behavior (403-not-429), validated defaults, cross-sweep cooldowns. |
| **Before launching a sweep from a Claude Code session** | [`docs/agent-sweeps.md`](docs/agent-sweeps.md) — context-window pitfalls + detached-sweep pattern. |
| Estimating cost / coverage of a backfill | [`docs/process-space.md`](docs/process-space.md) — class sizes + density probes. |
| A perf number doesn't match your extrapolation | [`docs/performance.md`](docs/performance.md) — cold numbers + why caching is the real lever. |
| Writing a notebook or cross-case SQL query | [`docs/warehouse-design.md`](docs/warehouse-design.md) — DuckDB schema + build pipeline. |
| Writing a PDF sweep | [`docs/peca-sweep-conventions.md`](docs/peca-sweep-conventions.md). |
| You want to see how a prior experiment turned out | [`docs/reports/`](docs/reports/) — promoted narratives from validation sweeps. |
| You want to understand how a major feature was designed | [`docs/superpowers/specs/`](docs/superpowers/specs/). |

## Runtime

Python project managed with **`uv`**. **Never** run bare `python`, `pip`, or `pytest`:

```bash
uv run pytest tests/unit/
uv run python main.py ...
uv add <pkg>
```

Scripts import `src.*` directly — no `PYTHONPATH=.` needed. The repo
is an editable install (hatchling `packages = ["src"]` in pyproject);
`uv sync` puts `src` on the venv's import path. Pytest picks up the
`scripts/` directory via `[tool.pytest.ini_options] pythonpath = ["."]`
in pyproject, so tests that `from scripts.run_sweep import ...` also
work with no env var.

```bash
uv run python scripts/validate_ground_truth.py
uv run python scripts/run_sweep.py ...
```

## CLI (`judex`)

User-facing surface lives in `src/cli.py` (Typer app, registered via
`[project.scripts] judex = "src.cli:app"` in pyproject). `uv sync`
installs the `judex` console entry; commands below also work as
`uv run judex …`. Each subcommand is a thin Typer wrapper that
rebuilds argv and calls the `main()` of an argparse-based script in
`scripts/` — so the same sweep can be launched detached
(`nohup uv run python scripts/baixar_pecas.py …`) without Typer in
the picture.

| Command              | Source                        | What it does                                                                                            |
|----------------------|-------------------------------|---------------------------------------------------------------------------------------------------------|
| `varrer-processos`   | `scripts/run_sweep.py`        | Case JSON scrape (the WAF-hot half). Range / CSV / retry modes; `--proxy-pool`; `--items-dir`.          |
| `baixar-pecas`       | `scripts/baixar_pecas.py`     | PDF bytes download. `--proxy-pool`; sharded mode via `--shards N --proxy-pool-dir D`.                    |
| `extrair-pecas`      | `scripts/extrair_pecas.py`    | PDF text extraction from cached bytes (zero HTTP). `--provedor {pypdf\|mistral\|chandra\|unstructured}`. |
| `exportar`           | (in-CLI)                      | Export the five HC Marimo notebooks to standalone interactive HTML.                                      |
| `validar-gabarito`   | `scripts/validate_ground_truth.py` | Diff the scraper's output against hand-verified `tests/ground_truth/*.json`.                        |
| `sondar-densidade`   | `scripts/class_density_probe.py` | Stratified density probe of process-id space per STF class (HC, ADI, RE, …).                         |

Help on any command: `uv run judex <command> --help`. Source of truth
for flag names / defaults is `src/cli.py` (Typer decorators) + the
underlying script's argparse.

**Sharded sweeps.** For >1000-target sweeps with proxy rotation:
`uv run judex baixar-pecas --csv X.csv --saida out/ --shards 8
--proxy-pool-dir config/ --retomar --nao-perguntar`. Partitions the
CSV range-wise, picks `proxies.{a..h}.txt` from `--proxy-pool-dir`,
detaches N children, writes `out/shards.pids`. Monitor with
`pgrep -af baixar_pecas` or read each `out/shard-<letter>/pdfs.state.json`.
`xargs -a out/shards.pids kill -TERM` stops cleanly. The launcher lives
in `src/sweeps/shard_launcher.py`; the older shell equivalent for
`run_sweep` is `scripts/launch_hc_backfill_sharded.sh`.

## Testing

```bash
uv run pytest tests/unit/                               # fast, <3 s — run before every change
uv run python scripts/validate_ground_truth.py         # parity vs. hand-verified JSON
```

## Non-obvious gotchas

These prevent a cold agent from taking the wrong action. Everything else is findable.

- **STF serves UTF-8 without declaring a charset.** `requests` defaults to Latin-1 → mojibake. `scraper._decode` sets `r.encoding = "utf-8"` before reading `r.text`. Never bypass.
- **`/processos/*` is WAF-throttled with HTTP 403 (not 429).** The block clears within minutes. `cfg.retry_403=True` rides it out with tenacity backoff. Non-browser UAs (`curl/*`) get permanent 403. Process-level pacing doesn't drain the per-IP reputation counter; use `--proxy-pool` rotation instead of `--throttle-sleep`.
- **`abaX.asp` endpoints need all three**: `ASPSESSIONID…` + `AWSALB` cookies, `Referer: detalhe.asp?incidente=N`, and `X-Requested-With: XMLHttpRequest`. Otherwise 403.
- **`extract_partes` reads `#todas-partes`**, not `#partes-resumidas` (which collapses multi-lawyer IMPTE entries and drops PROC on HC).
- **PDF URLs live on `sistemas.stf.jus.br`**, not `portal.stf.jus.br`. Separate origin, separate throttle counter.
- **The PDF cache is a four-file quartet keyed on `sha1(url)`.** `<sha1>.pdf.gz` = raw bytes (written by `baixar-pecas`), `<sha1>.txt.gz` = extracted text, `<sha1>.elements.json.gz` = provider elements, `<sha1>.extractor` = provider label sidecar (written by `extrair-pecas`). Re-runs are controlled by the sidecar (`--provedor` match → skip; `--forcar` → overwrite). No monotonic-by-length guard: provider is the quality axis.
- **`varrer-pdfs` is split into two commands.** `baixar-pecas` is the only path that talks to STF (WAF-bound; throttle, proxy pool, circuit breaker all live here). `extrair-pecas --provedor {pypdf|mistral|chandra|unstructured}` reads cached bytes and writes text — zero HTTP, no throttle, no breaker. Switch providers / re-OCR a tier without re-downloading. See `docs/superpowers/specs/2026-04-19-varrer-pdfs-ocr-knob.md` for the spec.
- **Corpus is uniformly v8 on disk (as of 2026-04-19).** `SCHEMA_VERSION = 8` in `src/data/types.py`; every file under `data/cases/HC/` carries `_meta.schema_version = 8` and dict-shaped (or `None`) `outcome`. The renormalizer (`scripts/renormalize_cases.py`) has been run full-corpus twice — bare-string `outcome` no longer exists in production data. The warehouse builder's `_unpack_outcome` and the pre-v8 inline-text fallback in `_flatten_documentos` are retained as legacy-tolerant guards for cold checkouts / old backups, not because current data needs them. See [`docs/data-dictionary.md § Schema history`](docs/data-dictionary.md#schema-history) for the v1→v8 changelog.
- **`src/scraping/extraction/__init__.py` is intentionally empty** to keep the HTTP backend Selenium-free. Pinned by `tests/unit/test_http_backend_no_selenium.py`.
- **DataJud does not have STF.** `api_publica_stf` returns 404. Don't re-check.
- **`sessao_virtual[].documentos` entries with `url=None` are capture gaps, not inline-text documents.** Every `Relatório` / `Voto` row *is* a URL-linked PDF — a null URL means the scrape didn't capture the link (older scrape versions, or the link wasn't live yet on STF). Consequence: a year-scoped warehouse's `pdfs` table count reflects *captured URLs*, not the total PDF population for that year. If a `--year 2026` warehouse comes out with `pdfs=0`, investigate the scraper's link-capture path before assuming those cases genuinely have no PDFs.

## Don't break these

- `tests/ground_truth/*.json` — 5 hand-verified cases; source of truth for `validate_ground_truth.py`.
- `tests/fixtures/sessao_virtual/*.json` — captured JSON for the sessao_virtual unit tests.
- `tests/unit/*.py` — run before every change.
- `src/data/types.py` — `StfItem` TypedDict. Fields are Optional for a reason; don't make them non-Optional again.
- `src/sweeps/process_store.py` + `src/sweeps/peca_store.py` — atomic write contracts are load-bearing; don't add non-atomic state updates.

## Conventions

- **No backwards-compat shims.** Change the call sites + tests.
- **Always use code for non-trivial arithmetic** — `uv run python -c "..."`. Never mental math; numbers get quoted downstream.
- **Keep files focused.** `scraper.py` past ~600 lines → split by concern.
- **Extractor tests diff against captured fixtures**, not hand-built dicts. Pattern: `tests/fixtures/<feature>/<case>.json`.
- **Sweeps write a directory**, not a single file. `<out>/report.md`, `<out>/sweep.log.jsonl`, etc.
- **Measure before optimising.** Cold perf numbers don't extrapolate to sweep scale (WAF ceiling dominates).
