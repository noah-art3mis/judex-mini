# CLAUDE.md — judex-mini (project-level)

Scraper + parser for STF (Brazilian Supreme Court) process data. **HTTP is the only first-class backend.** The legacy Selenium implementation was frozen under `deprecated/` on 2026-04-17; `--backend selenium` now errors out.

## When to read what

| Open this doc when… | File |
|---|---|
| Starting a session / resuming work | [`docs/current_progress.md`](docs/current_progress.md) — active-task lab notebook + strategic state. Living file; template and archive convention live inside it. |
| You need to know where a file lives (cases, caches, runs, exports) | [`docs/data-layout.md`](docs/data-layout.md) — spatial map of every store and every key. |
| Writing new scraping code or debugging a 403 | [`docs/stf-portal.md`](docs/stf-portal.md) — URL flow, auth triad, UTF-8 quirk, field→source map. |
| A field-wide data regression just showed up (e.g. 0% populated) | [`docs/system-changes.md`](docs/system-changes.md) — STF-side migrations timeline (DJe → digital.stf, Selenium retirement, schema v1→v8, known gaps). |
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
uv sync --extra analysis                    # one-time: pulls core + analysis extras
uv run pytest tests/unit/
uv run python main.py ...
uv add <pkg>
```

Scripts import `judex.*` directly — no `PYTHONPATH=.` needed. The repo
is an editable install (hatchling `packages = ["judex"]` in pyproject);
`uv sync` puts `judex` on the venv's import path. The `--extra analysis`
flag is needed for tests because `judex/analysis/stats.py` pulls scipy
transitively through hdbscan / umap-learn / seaborn. Pytest picks up the
`scripts/` directory via `[tool.pytest.ini_options] pythonpath = ["."]`
in pyproject, so tests that `from scripts.run_sweep import ...` also
work with no env var.

```bash
uv run python scripts/validate_ground_truth.py
uv run python scripts/run_sweep.py ...
```

## CLI (`judex`)

User-facing surface lives in `judex/cli.py` (Typer app, registered via
`[project.scripts] judex = "judex.cli:app"` in pyproject). `uv sync`
installs the `judex` console entry; commands below also work as
`uv run judex …`. Each subcommand is a thin Typer wrapper that
rebuilds argv and calls the `main()` of an argparse-based script in
`scripts/` — so the same sweep can be launched detached
(`nohup uv run python scripts/baixar_pecas.py …`) without Typer in
the picture.

| Command                | Source                             | What it does                                                                                            |
|------------------------|------------------------------------|---------------------------------------------------------------------------------------------------------|
| `varrer-processos`     | `scripts/run_sweep.py`             | Case JSON scrape (the WAF-hot half). Range / CSV / retry modes; `--proxy-pool FILE`; `--items-dir`; sharded mode via `--shards N --proxy-pool FILE` (round-robin split into N pools at launch). |
| `baixar-pecas`         | `scripts/baixar_pecas.py`          | PDF bytes download. `--proxy-pool FILE`; sharded mode via `--shards N --proxy-pool FILE`.               |
| `extrair-pecas`        | `scripts/extrair_pecas.py`         | PDF text extraction from cached bytes (zero HTTP). `--provedor {pypdf\|mistral\|chandra\|unstructured}`.|
| `atualizar-warehouse`  | `scripts/build_warehouse.py`       | Rebuild `data/warehouse/judex.duckdb` from case JSONs + PDF cache. Full-rebuild, atomic swap, zero HTTP.|
| `exportar`             | (in-CLI)                           | Export the five HC Marimo notebooks to standalone interactive HTML.                                     |
| `validar-gabarito`     | `scripts/validate_ground_truth.py` | Diff the scraper's output against hand-verified `tests/ground_truth/*.json`.                            |
| `sondar-densidade`     | `scripts/class_density_probe.py`   | Stratified density probe of process-id space per STF class (HC, ADI, RE, …).                            |

Help on any command: `uv run judex <command> --help`. Source of truth
for flag names / defaults is `judex/cli.py` (Typer decorators) + the
underlying script's argparse.

**Sharded sweeps.** For >1000-target sweeps with proxy rotation, both
scrape layers support `--shards N --proxy-pool FILE` — one flat file
of proxy URLs (one per line, `#`-comments + blank lines ignored).
The launcher round-robin-splits the file into N per-shard pools at
`<saida>/proxies/proxies.{a..p}.txt` and detaches one child per
shard.

```bash
# Case JSON (WAF-hot)
uv run judex varrer-processos --csv X.csv --saida out/ --rotulo hc_q2 \
    --shards 8 --proxy-pool config/proxies --retomar

# PDF bytes (sistemas.stf.jus.br)
uv run judex baixar-pecas --csv X.csv --saida out/ --shards 8 \
    --proxy-pool config/proxies --retomar --nao-perguntar
```

Partitions the CSV (interleave by default), splits the proxy file,
spawns N children (per-shard label `<rotulo>_shard_<letter>` for
`varrer-processos`; per-shard dir only for `baixar-pecas`), writes
`out/shards.pids`. Monitor with `uv run judex probe --out-root out/`
or `pgrep -af <rotulo>_shard_` (varrer) / `pgrep -af baixar_pecas`
(baixar), or read each `out/shard-<letter>/sweep.state.json` /
`.../pdfs.state.json`. `xargs -a out/shards.pids kill -TERM` stops
cleanly. Both launchers live in `judex/sweeps/shard_launcher.py`
(`launch_sharded_sweep` / `launch_sharded_download`). The CLI path is
preferred for new sharded sweeps; `scripts/launch_hc_backfill_sharded.sh`
is still valid when you need to **pre-seed each shard's
`sweep.state.json` from an archived monolithic sweep** (to avoid
re-fetching already-`ok` cases) — the CLI doesn't do that seeding step.

## Testing

```bash
uv run pytest tests/unit/                               # ~12 s, 475 tests — run before every change
uv run python scripts/validate_ground_truth.py         # parity vs. hand-verified JSON
```

## Non-obvious gotchas

These prevent a cold agent from taking the wrong action. Everything else is findable.

- **STF serves UTF-8 without declaring a charset.** `requests` defaults to Latin-1 → mojibake. `scraper._decode` sets `r.encoding = "utf-8"` before reading `r.text`. Never bypass.
- **`/processos/*` is WAF-throttled with HTTP 403 (not 429).** The block clears within minutes. `cfg.retry_403=True` rides it out with tenacity backoff. Non-browser UAs (`curl/*`) get permanent 403. Process-level pacing doesn't drain the per-IP reputation counter; use `--proxy-pool` rotation instead of `--throttle-sleep`.
- **`abaX.asp` endpoints need all three**: `ASPSESSIONID…` + `AWSALB` cookies, `Referer: detalhe.asp?incidente=N`, and `X-Requested-With: XMLHttpRequest`. Otherwise 403.
- **`extract_partes` reads `#todas-partes`**, not `#partes-resumidas` (which collapses multi-lawyer IMPTE entries and drops PROC on HC).
- **Use `judex.analysis.lawyer_canonical` for any ADV/IMPTE name work; don't roll your own regex in a notebook.** The raw `partes[].nome` column is a minefield: OAB parentheticals (`(12345/SP)`, `(12345/SP) E OUTRO(A/S)`), portal sentinels meaning "same as previous row" (`O MESMO`, `OS MESMOS`, typos like `O MESM0`, `IO MESMO`, ~3k phantom IMPTE rows if not filtered), accent-missing institutional variants (`DEFENSORIA PUBLICA DA UNIAO` — 4.7k rows — slips past any `DEFENSORIA PÚBLICA` prefix check), non-parenthetical OAB forms (`OAB/SP 148022`, `OAB-PE 48215`), law firms / unions / federations that are not individual lawyers, and courts-as-parties. `canonical_lawyer(nome)` returns `(key, oab_codes)` with tail/paren/sentinel handling; `classify(nome)` returns `LawyerEntry(kind, key, oab_codes)` with `kind ∈ {sentinel, placeholder, pro_se, institutional, juridical, court, with_oab, bare}`. Tests in `tests/unit/test_lawyer_canonical.py` pin every real-data edge case surfaced by a full-corpus stress test. Sample callers: `analysis/hc_judge_lawyer_network.py`, `analysis/hc_top_volume.py`.
- **PDF URLs live on `sistemas.stf.jus.br`**, not `portal.stf.jus.br`. Separate origin, separate throttle counter.
- **The PDF cache is a four-file quartet keyed on `sha1(url)`.** `<sha1>.pdf.gz` = raw bytes (written by `baixar-pecas`), `<sha1>.txt.gz` = extracted text, `<sha1>.elements.json.gz` = provider elements, `<sha1>.extractor` = provider label sidecar (written by `extrair-pecas`). Re-runs are controlled by the sidecar (`--provedor` match → skip; `--forcar` → overwrite). No monotonic-by-length guard: provider is the quality axis.
- **`varrer-pdfs` is split into two commands.** `baixar-pecas` is the only path that talks to STF (WAF-bound; throttle, proxy pool, circuit breaker all live here). `extrair-pecas --provedor {pypdf|mistral|chandra|unstructured}` reads cached bytes and writes text — zero HTTP, no throttle, no breaker. Switch providers / re-OCR a tier without re-downloading. See `docs/superpowers/specs/2026-04-19-varrer-pdfs-ocr-knob.md` for the spec.
- **Corpus is uniformly v8 on disk (as of 2026-04-19).** `SCHEMA_VERSION = 8` in `judex/data/types.py`; every file under `data/cases/HC/` carries `_meta.schema_version = 8` and dict-shaped (or `None`) `outcome`. The renormalizer (`scripts/renormalize_cases.py`) has been run full-corpus twice — bare-string `outcome` no longer exists in production data. The warehouse builder's `_unpack_outcome` and the pre-v8 inline-text fallback in `_flatten_documentos` are retained as legacy-tolerant guards for cold checkouts / old backups, not because current data needs them. See [`docs/data-dictionary.md § Schema history`](docs/data-dictionary.md#schema-history) for the v1→v8 changelog.
- **`judex/scraping/extraction/__init__.py` is intentionally empty** to keep the HTTP backend Selenium-free. Pinned by `tests/unit/test_http_backend_no_selenium.py`.
- **DataJud does not have STF.** `api_publica_stf` returns 404. Don't re-check.
- **`sessao_virtual[].documentos` entries with `url=None` are capture gaps, not inline-text documents.** Every `Relatório` / `Voto` row *is* a URL-linked PDF — a null URL means the scrape didn't capture the link (older scrape versions, or the link wasn't live yet on STF). Consequence: a year-scoped warehouse's `pdfs` table count reflects *captured URLs*, not the total PDF population for that year. If a `--year 2026` warehouse comes out with `pdfs=0`, investigate the scraper's link-capture path before assuming those cases genuinely have no PDFs.

## Don't break these

- `tests/ground_truth/*.json` — 5 hand-verified cases; source of truth for `validate_ground_truth.py`.
- `tests/fixtures/sessao_virtual/*.json` — captured JSON for the sessao_virtual unit tests.
- `tests/unit/*.py` — run before every change.
- `judex/data/types.py` — `StfItem` TypedDict. Fields are Optional for a reason; don't make them non-Optional again.
- `judex/sweeps/process_store.py` + `judex/sweeps/peca_store.py` — atomic write contracts are load-bearing; don't add non-atomic state updates.

## Conventions

- **No backwards-compat shims.** Change the call sites + tests.
- **Always use code for non-trivial arithmetic** — `uv run python -c "..."`. Never mental math; numbers get quoted downstream.
- **Keep files focused.** `scraper.py` past ~600 lines → split by concern.
- **Extractor tests diff against captured fixtures**, not hand-built dicts. Pattern: `tests/fixtures/<feature>/<case>.json`.
- **Sweeps write a directory**, not a single file. `<out>/report.md`, `<out>/sweep.log.jsonl`, etc.
- **Measure before optimising.** Cold perf numbers don't extrapolate to sweep scale (WAF ceiling dominates).
