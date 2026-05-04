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
| Pricing a sweep in money + wall time (year-of-HC, OCR, direct-IP vs proxy) | [`docs/cost-estimates.md`](docs/cost-estimates.md) — per-unit anchors, per-pass tables, override env vars. |
| Forecasting a specific sweep before launch (single direct-IP vs 16 shards) | `judex debug {varrer-processos,baixar-pecas,extrair-pecas} --prever` — exits with a real-anchored cost+wall table; math in [`judex/utils/cost.py`](judex/utils/cost.py). |
| Checking on a live or completed run (rate, regime, cliff diagnosis) | `judex probe --out-root <dir>` (sharded, live `--watch` mode) / `judex analisar-regimes <run_dir>` (mono+sharded, post-hoc regime trajectory; `--json` for jq). Both in [`judex/cli.py`](judex/cli.py). |
| Checking per-year HC coverage (cases / peça bytes / text) or picking the next backfill target | [`docs/completion-tracker.md`](docs/completion-tracker.md) — per-year table, cache-integrity caveat, backfill priority queue. |
| A perf number doesn't match your extrapolation | [`docs/performance.md`](docs/performance.md) — cold numbers + why caching is the real lever. |
| A sweep finished with a residual (errored / empty / unallocated / lost rows) | **Per-row recipe** — `from judex.sweeps.error_triage import recovery_recipe` returns `Recipe(action, summary, command_hint)`. **Multi-step scenarios** + the `judex limpar` gap — [`docs/recovery-patterns.md`](docs/recovery-patterns.md). The classifier + `RECOVERY_RECIPES` table are pinned by `tests/unit/test_error_triage.py`; the doc is interpretation, the code is SOT. |
| Writing a notebook or cross-case SQL query | [`docs/warehouse-design.md`](docs/warehouse-design.md) — DuckDB schema + build pipeline. |
| Writing a PDF sweep | [`docs/peca-sweep-conventions.md`](docs/peca-sweep-conventions.md) — sweep input semantics, output layout. **Tier definitions / fail-open policy**: module docstring of [`judex/sweeps/peca_classification.py`](judex/sweeps/peca_classification.py); the doc surface in [`docs/peca-tipo-classification.md`](docs/peca-tipo-classification.md) is just the warehouse view + CLI semantics. Empirical row counts / median chars: [`docs/reports/2026-04-23-peca-tipo-tier-validation.md`](docs/reports/2026-04-23-peca-tipo-tier-validation.md). |
| Doing the "who-wins HC" analysis (research question, lit review, validation) | [`docs/hc-who-wins.md`](docs/hc-who-wins.md) — single consolidated doc with §1 Scope and plan / §2 Literature review / §3 Validation. The three pre-2026-05-03 sub-files (`-lit-review`, `-validation`) were merged here; cross-links use intra-doc anchors. |
| You want to see how a prior experiment turned out OR find the dated empirical snapshot backing a code constant | [`docs/reports/`](docs/reports/) — promoted narratives from validation sweeps **and** date-stamped artefacts that back module constants (e.g. peça-tipo tier counts, HTTP-vs-Selenium bench, OCR bakeoff). |
| You want to understand how a major feature was designed | [`docs/superpowers/specs/`](docs/superpowers/specs/). |
| Standing up infra (cloud OCR provider, proxy pool, fresh WSL host) | [`docs/setup-fly.md`](docs/setup-fly.md), [`docs/setup-modal.md`](docs/setup-modal.md), [`docs/setup-runpod.md`](docs/setup-runpod.md), [`docs/setup-proxies.md`](docs/setup-proxies.md), [`docs/setup-wsl.md`](docs/setup-wsl.md) — operational setup; the *why* lives in the linked code SOTs (provider docstrings, `fly/README.md`, `rate-limits.md`). |

**Code-as-SOT pattern.** Several routing rows above point at code first
and Markdown second. That's deliberate — when a fact lives in *both*
the doc and a Python constant/function, the Markdown drifts and the
code stays honest (tests pin it). For these specifically:

- **Per-row recovery recipes** → `recovery_recipe()` /
  `RECOVERY_RECIPES` in `judex/sweeps/error_triage.py`. Don't read a
  Markdown table to decide what to do with one errors.jsonl row;
  import the function.
- **Peça tier classification + fold/fail-open contract** → module
  docstring of `judex/sweeps/peca_classification.py`. The empirical
  row counts that backed the assignments live in `docs/reports/` so
  they don't pollute the live module.
- **Cost anchors / re-anchoring rule** → module docstring of
  `judex/utils/cost.py`. The doc (`cost-estimates.md`) carries the
  *interpretation* (year-of-HC tables, OCR bakeoff trade-offs, BRL
  policy) but the constants and rate-source functions are in code.
- **Lawyer canonicalisation** → `judex.analysis.lawyer_canonical`
  (already in the gotchas below).

When proposing a new doc, ask first: "could this be a docstring or a
docstring + a `docs/reports/` snapshot?" If yes, do that instead.

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
uv run judex executar -c HC -i 250920 -f 267137 --saida runs/active/<label>/
```

**Local-OCR system deps (only if using `--provedor tesseract`):**
the `ocr-local` extra pulls `pytesseract`/`pdf2image`/`pillow` into the
venv but those are thin wrappers — they need the system binaries
**Tesseract + the Portuguese language pack + Poppler**. On WSL/Linux:

```bash
sudo apt-get install -y tesseract-ocr tesseract-ocr-por poppler-utils
uv sync --extra ocr-local
```

On macOS: `brew install tesseract tesseract-lang poppler`. `tesseract`
runs Tesseract locally (in-process, no network); `tesseract_modal` is
the Modal-hosted variant for production-scale sweeps that need to fan
out beyond what the local host can parallelise (Modal's containers +
its ~10-shard concurrency cap). Same engine + Portuguese language
pack, same quality. See
[`docs/reports/2026-04-30-ocr-bakeoff.md`](docs/reports/2026-04-30-ocr-bakeoff.md)
for cost/quality tradeoffs.

## CLI (`judex`)

User-facing surface lives in `judex/cli.py` (Typer app, registered via
`[project.scripts] judex = "judex.cli:app"` in pyproject). `uv sync`
installs the `judex` console entry; commands below also work as
`uv run judex …`. Each subcommand is a thin Typer wrapper that calls
the matching `run_X(**kwargs)` library function in `judex/sweeps/`
directly — detached invocation is `nohup uv run judex <command> …`.

**Top-level surface is the everyday operator path: `executar` → `acompanhar` → `relatar`, plus `limpar` for residual recovery and `atualizar-warehouse` / `relatorio-diario` for downstream artefacts.** Everything else lives under `judex debug` — inspection / validation / comparison / export / backup utilities. The canonical primary path is `judex executar` ([ADR-0005](docs/adr/0005-unified-pipeline.md)); reach for `judex debug …` only when the task isn't part of the everyday loop. The pre-`executar` legacy three-command chain (`varrer-processos`, `baixar-pecas`, `extrair-pecas`) and its `coletar` orchestrator were removed from the CLI surface; the library code remains in `judex/sweeps/` for `pick_provider` and shared helpers used by the unified pipeline. Recoverable on the `archive/iteration-2-three-command-chain` branch (local + `origin`) if needed.

| Command                       | Source                                | What it does                                                                                            |
|-------------------------------|---------------------------------------|---------------------------------------------------------------------------------------------------------|
| `executar`                    | `judex/pipeline/runner.py`            | **Primary path.** Single-process unified pipeline (portal/sistemas/ocr Pools) over a (classe, range). One log + one state file + one PID. Sharded mode via `--shards N --proxy-pool FILE`. ADR-0005. |
| `atualizar <classe>`          | (in-CLI, calls `run_pipeline`)        | Manual incremental: find max processo_id on disk, probe forward via `discover_new_numeros` until N consecutive unallocated_pid (default 20), scrape only the live discoveries end-to-end. Required positional `<classe>`. Auto-stops at STF's leading edge — no margin guesswork. Idempotent. |
| `acompanhar`                  | (in-CLI)                              | Tail-with-auto-detection live monitor for monolithic + sharded runs.                                    |
| `relatar`                     | (in-CLI)                              | Consolidate a finished `executar` run into a single report.                                             |
| `limpar`                      | `judex/sweeps/limpar.py`              | One-command residual recovery for finished `judex executar` runs.                                        |
| `atualizar-warehouse`         | `judex/sweeps/build_warehouse.py`     | Rebuild `data/derived/warehouse/judex.duckdb` from `data/source/processos/` + `data/derived/pecas-texto/`. Full-rebuild, atomic swap, zero HTTP.|
| `debug probe`                 | (in-CLI)                              | Live-progress table for sharded runs (predates `executar`'s nested state).                              |
| `debug analisar-regimes`      | (in-CLI)                              | Post-hoc regime trajectory reconstruction from a sweep log (cliff / SSL-EOF detection).                  |
| `debug providers`             | (in-CLI, `judex/scraping/ocr/dispatch.py`) | OCR provider comparison table at a given workload size — sorted by cost, sourced from each provider's `SPEC`. |
| `debug exportar`              | (in-CLI)                              | Export the five HC Marimo notebooks to standalone interactive HTML.                                     |
| `debug fazer-backup`          | (in-CLI, `judex/backup.py`)           | Bundle `data/source/processos` + `data/raw/pecas` + `data/derived/pecas-texto` into a single Windows-openable `.zip`. ZIP64, atomic write. |
| `debug validar-gabarito`      | `scripts/validate_ground_truth.py`    | Diff the scraper's output against hand-verified `tests/ground_truth/*.json`.                            |
| `debug relatorio-diario`      | (in-CLI)                              | Daily report of new STF distributions.                                                                  |

Help on any command: `uv run judex <command> --help`. Source of truth
for flag names / defaults is `judex/cli.py` (Typer decorators); each
sweep module exposes a `run_X(**kwargs)` library function that the Typer
command calls directly. There is no longer an argparse shim —
detached sweeps invoke `uv run judex <command>` and the sharded
launcher's child subprocesses do the same.

**Sharded sweeps.** For >1000-target sweeps with proxy rotation,
`executar` supports `--shards N --proxy-pool FILE` — one flat file
of proxy URLs (one per line, `#`-comments + blank lines ignored).
The launcher round-robin-splits the file into N per-shard pools at
`<saida>/proxies/proxies.{a..p}.txt` and detaches one child per
shard.

```bash
uv run judex executar --csv X.csv --saida runs/active/<label>/ \
    --rotulo hc_q2 --shards 8 --proxy-pool config/proxies
```

Partitions the CSV (interleave by default), splits the proxy file,
spawns N children (per-shard label `<rotulo>_shard_<letter>`), writes
`<saida>/shards.pids`. Each child runs `uv run judex executar` against
its own per-shard subdir. Monitor with `uv run judex acompanhar
<saida>/` (auto-detects sharded layout) or `pgrep -af <rotulo>_shard_`,
or read each `<saida>/shard-<letter>/executar.state.json`.
`xargs -a <saida>/shards.pids kill -TERM` stops cleanly. The launcher
lives in `judex/sweeps/shard_launcher.py` (`launch_sharded(command="executar", ...)`).

## Testing

```bash
uv run pytest tests/unit/                               # ~21 s, 893 tests — run before every change
uv run python scripts/validate_ground_truth.py         # parity vs. hand-verified JSON
```

## Non-obvious gotchas

These prevent a cold agent from taking the wrong action. Everything else is findable.

- **STF serves UTF-8 without declaring a charset.** `requests` defaults to Latin-1 → mojibake. `scraper._decode` sets `r.encoding = "utf-8"` before reading `r.text`. Never bypass.
- **`/processos/*` is WAF-throttled with HTTP 403 (not 429).** The block clears within minutes. `cfg.retry_403=True` rides it out with tenacity backoff. Non-browser UAs (`curl/*`) get permanent 403. Process-level pacing doesn't drain the per-IP reputation counter; use `--proxy-pool` rotation instead of `--throttle-sleep`.
- **`abaX.asp` endpoints need all three**: `ASPSESSIONID…` + `AWSALB` cookies, `Referer: detalhe.asp?incidente=N`, and `X-Requested-With: XMLHttpRequest`. Otherwise 403.
- **`extract_partes` reads `#todas-partes`**, not `#partes-resumidas` (which collapses multi-lawyer IMPTE entries and drops PROC on HC).
- **Use `judex.analysis.lawyer_canonical` for any ADV/IMPTE name work; don't roll your own regex in a notebook.** The raw `partes[].nome` column is a minefield: OAB parentheticals (`(12345/SP)`, `(12345/SP) E OUTRO(A/S)`), portal sentinels meaning "same as previous row" (`O MESMO`, `OS MESMOS`, typos like `O MESM0`, `IO MESMO`, ~3k phantom IMPTE rows if not filtered), accent-missing institutional variants (`DEFENSORIA PUBLICA DA UNIAO` — 4.7k rows — slips past any `DEFENSORIA PÚBLICA` prefix check), non-parenthetical OAB forms (`OAB/SP 148022`, `OAB-PE 48215`), law firms / unions / federations that are not individual lawyers, and courts-as-parties. `canonical_lawyer(nome)` returns `(key, oab_codes)` with tail/paren/sentinel handling; `classify(nome)` returns `LawyerEntry(kind, key, oab_codes)` with `kind ∈ {sentinel, placeholder, pro_se, institutional, juridical, court, with_oab, bare}`. Tests in `tests/unit/test_lawyer_canonical.py` pin every real-data edge case surfaced by a full-corpus stress test. Sample callers: `analysis/hc_judge_lawyer_network.py`, `analysis/hc_top_volume.py`.
- **Use `judex analisar-regimes <run_dir>` to detect cliffs / SSL-EOF storms / saturation tails — don't compute regime buckets by hand from `pdfs.log.jsonl`.** Reads `sweep.log.jsonl` (varrer) or `pdfs.log.jsonl` (baixar/extrair) — auto-detected — and reconstructs the regime trajectory via the same `CliffDetector` the live sweep used. `--apenas-transicoes` shows only state changes (warming → under_utilising → approaching_collapse → collapse); `--json` emits one event per line for jq pipelines. For a live monolithic run, `tail -f .../launcher-stdout.log` + `pgrep -af baixar[-_]pecas` gives liveness; for sharded, `judex probe --out-root <dir> --watch N` is the rich-rendered live table. There's no first-class "live status of a monolithic run" command — composing `tail` + `pgrep` + `analisar-regimes` post-hoc is the documented path. Hand-rolling 5-min throughput buckets from `pdfs.log.jsonl` reinvents `analisar-regimes`'s output and missed a real SSL-EOF tail-storm in at least one Claude session.
- **Use `judex {varrer,baixar,extrair}-pecas --prever` to forecast cost + wall before launching, not handrolled arithmetic.** Returns a side-by-side table for single direct-IP and 16-shard + proxy modes. Constants and the re-anchoring rule of thumb live in the module docstring of `judex/utils/cost.py` (the SOT — values drift over time, so don't quote them here; current anchors as of 2026-05-01 include `_AVG_PDF_MB = 0.1685` re-measured after the `.rtf.gz` separation, `_AVG_REQ_WALL_S_DIRECT = 3.0`, `_SHARD_SPEEDUP_X = 12.7`). The same module covers pre-launch forecasting and end-of-run `report.md` cost attribution. Re-anchor when the corpus doubles or after any major scrape change; tests at `tests/unit/test_cost.py` use bounds, not exact values, so re-anchoring within ±10% doesn't break them. OCR rates flow from each provider's `SPEC` (post the OCR-deepening), so `judex/utils/cost.py` doesn't carry per-provider duplicates. Interpretation layer (year-of-HC volumes, OCR provider trade-offs, BRL/USD policy): `docs/cost-estimates.md`.
- **Use `judex.sweeps.peca_targets.collect_peca_targets` for any "how many PDFs / which PDFs" question over the corpus; don't walk source JSONs by hand.** As of 2026-05-01 (ADR-0001 accepted, both steps landed) it walks all three peça URL surfaces — `andamentos[].link.url`, `sessao_virtual[].documentos[].url`, and `publicacoes_dje[].decisoes[].rtf.url` — tagging each `PecaTarget` with `surface ∈ {"andamento", "sessao_virtual", "dje"}`. Every surface emits URL-only pointers on disk; canonical extracted text lives in `data/derived/pecas-texto/<sha1(url)>.txt.gz` and is materialised by `baixar-pecas` (bytes) → `extrair-pecas` (text), never by the case-scrape. A one-shot `baixar-pecas` pass scoped to surfaces 2 + 3 is the natural step-3 backfill (warms the bytes side; not yet run — existing text stays valid until a re-extraction is requested). Andamento-tipo filters (`doc_types` / `exclude_doc_types`) apply only to surface 1; surface 2 + 3 fail-open through `filter_substantive` because their discriminators (`Relatório` / `Voto` / `decisao` / `ementa`) are intrinsically substantive — there is no tier-C analogue on those surfaces (resolved in ADR-0001 § Consequences, pinned by `tests/unit/test_peca_classification.py`). Handles the two `andamento.link` shapes (string vs `{url, tipo}` dict via `_andamento_link`), filters all surfaces through `_is_supported_doc_url` (`.pdf` / `.rtf` / `ext=RTF`), skips capture-gap entries (`url=None`) on surfaces 2 / 3, and dedupes by URL across surfaces and cases (4,936 cross-case duplicates exist in the HC corpus via apenso/conexão — same PGR opinion linked from multiple consolidated cases — and the `sha1(url)`-keyed cache only stores one copy). Pair with `judex.sweeps.peca_classification.filter_substantive` to match the runner's `--apenas-substantivas` default — drops ~56% of the andamento URLs as tier-C procedural (CERTIDÃO, INTIMAÇÃO, COMUNICAÇÃO ASSINADA, etc.; full list in `peca_classification.TIER_C_DOC_TYPES`). Empirical chain on full HC corpus (andamento-only baseline; surfaces 2 / 3 add to the numerator): raw andamento refs **280,838** → URL-deduped **275,902** → substantive **120,587** (≈1.33/case). Cross-validates `docs/completion-tracker.md:129` (2024 dry-run "15,482 fresh URLs"). Variants for scoping: `targets_from_range` (CSV-free range mode), `targets_from_csv` (explicit list), `targets_from_errors_jsonl` (replay only failed; rehydrated targets carry `surface=None` since prior errors.jsonl pre-dates the field). Tests at `tests/unit/test_peca_targets.py` and `tests/unit/test_peca_classification.py`. Sample callers: `judex/sweeps/peca_cli.py`, `docs/cost-estimates.md` (year-of-HC budget). Handrolling this walk has bitten at least one Claude session — over- or under-counts depending on which step you skip.
- **PDF URLs live on `sistemas.stf.jus.br`**, not `portal.stf.jus.br`. Separate origin, separate throttle counter.
- **The PDF cache is a four-file quartet keyed on `sha1(url)`.** `<sha1>.pdf.gz` = raw bytes (written by `baixar-pecas`), `<sha1>.txt.gz` = extracted text, `<sha1>.elements.json.gz` = provider elements, `<sha1>.extractor` = provider label sidecar (written by `extrair-pecas`). Re-runs are controlled by the sidecar (`--provedor` match → skip; `--forcar` → overwrite). No monotonic-by-length guard: provider is the quality axis.
- **`varrer-pdfs` is split into two commands.** `baixar-pecas` is the only path that talks to STF (WAF-bound; throttle, proxy pool, circuit breaker all live here). `extrair-pecas --provedor {pypdf|mistral|chandra|unstructured}` reads cached bytes and writes text — zero HTTP, no throttle, no breaker. Switch providers / re-OCR a tier without re-downloading. See `docs/superpowers/specs/2026-04-19-varrer-pdfs-ocr-knob.md` for the spec.
- **Scope follow-up passes to what you just collected — `--csv` is the scoping knob, `--saida` only locates state.** After a `baixar-pecas` sweep on year-N, the natural next step is `extrair-pecas` to flip those bytes into text. Always pair them: `extrair-pecas --csv <sweep>/cases.csv --saida <sweep>/`. The 2026-04-30 design hardening makes `judex/sweeps/peca_cli.py:resolve_targets` *raise* `ValueError` on bare invocation (no `--retentar-de`, no `--csv`, no range, no filter), so both `baixar-pecas` and `extrair-pecas` exit-2 with a clean error instead of falling through to corpus-wide enumeration — the historical footgun. The guard's primary role today is **over-scoping protection**: bare resolve walks the full corpus target list (`collect_peca_targets` over all `data/source/processos/HC/`), so a 15k-record year-sweep follow-up would walk 120k records — 8× wasted work just from scope. (Pre-deepening, a second compounding cliff hit: `peca_store.py` rewrote the entire `pdfs.state.json` per record, so a 53 MB corpus state capped `extrair-pecas` at ~0.13 rec/s — a further 27× rate gap. The state-store deepening on this commit makes state.json a periodic snapshot rather than a per-record rewrite, so that cliff is gone; only the 8× over-scoping cost remains.) The guard is pinned by `tests/unit/test_peca_cli.py::test_resolve_raises_when_no_scope_specified`. Same scoping rule still applies to analysis: when "I want to look at what we just collected", point DuckDB/pandas at `<sweep>/pdfs.log.jsonl` or rebuild a year-scoped warehouse — don't grep the corpus-wide warehouse for a single year.
- **Corpus is uniformly v8 on disk (as of 2026-04-19).** `SCHEMA_VERSION = 8` in `judex/data/types.py`; every file under `data/source/processos/HC/` carries `_meta.schema_version = 8` and dict-shaped (or `None`) `outcome`. The renormalizer (`scripts/renormalize_cases.py`) has been run full-corpus twice — bare-string `outcome` no longer exists in production data. The warehouse builder's `_unpack_outcome` and the pre-v8 inline-text fallback in `_flatten_documentos` are retained as legacy-tolerant guards for cold checkouts / old backups, not because current data needs them. See [`docs/data-dictionary.md § Schema history`](docs/data-dictionary.md#schema-history) for the v1→v8 changelog.
- **`judex/scraping/extraction/__init__.py` is intentionally empty** to keep the HTTP backend Selenium-free. Pinned by `tests/unit/test_http_backend_no_selenium.py`.
- **DataJud does not have STF.** `api_publica_stf` returns 404. Don't re-check.
- **`sessao_virtual[].documentos` entries with `url=None` are capture gaps, not inline-text documents.** Every `Relatório` / `Voto` row *is* a URL-linked PDF — a null URL means the scrape didn't capture the link (older scrape versions, or the link wasn't live yet on STF). Consequence: a year-scoped warehouse's `pdfs` table count reflects *captured URLs*, not the total PDF population for that year. If a `--year 2026` warehouse comes out with `pdfs=0`, investigate the scraper's link-capture path before assuming those cases genuinely have no PDFs.
- **After `extrair-pecas` finishes, spot-check a handful of `.txt.gz` files before declaring the cycle closed.** The `report.md` `ok` count only confirms the extractor returned without raising — it does **not** confirm the text is usable. pypdf in particular fails silently on scanned/image-only PDFs (returns mostly whitespace), borked encodings (returns mojibake), and PDFs with vector-rendered text that isn't extractable at all. Sample 5–10 sha1s spanning the run and decompress-and-read: `gzip -dc data/derived/pecas-texto/<sha1>.txt.gz | head -50`. Look for: (1) actual sentences (not just headers/footers), (2) Portuguese words spelled correctly (no `Ã§` / `Ã£` corruption), (3) length plausible for the document type (a `DECISÃO MONOCRÁTICA` should be ≥1k chars, not 200). If a meaningful fraction look bad, re-extract that subset with `--provedor chandra` or `mistral` (`extrair-pecas --csv <subset> --provedor chandra --forcar`). The 2026-04-30 HC 2024 anomaly (text 80% vs 97-99% on 2023/2022) is exactly the kind of gap a spot-check would have surfaced before the warehouse rebuild.

## Don't break these

- `tests/ground_truth/*.json` — 5 hand-verified cases; source of truth for `validate_ground_truth.py`.
- `tests/fixtures/sessao_virtual/*.json` — captured JSON for the sessao_virtual unit tests.
- `tests/unit/*.py` — run before every change.
- `judex/data/types.py` — `StfItem` TypedDict. Fields are Optional for a reason; don't make them non-Optional again.
- `judex/sweeps/process_store.py` + `judex/sweeps/peca_store.py` — atomic write contracts are load-bearing; don't add non-atomic state updates.

## Conventions

- **`dev` is the trunk; `main` is promote-only.** Commit directly to `dev` for all routine work; never commit to `main`. Branch off `dev` only when a change is risky / experimental enough to warrant isolation (large refactor, work that might be abandoned). **Push `dev → origin/dev` after each commit** (`git push origin dev`) — this keeps `origin/dev` current so `gh pr create --head dev` always sees the full state. Batching commits locally and pushing only at promote-time is how PR #5 (2026-04-26) lost 8 of 12 commits in its squash; required a corrective PR. Promote `dev → main` at the end of each working session, or when `dev` is more than ~10 commits ahead of `main` — whichever comes first — via `gh pr create --base main --head dev` and `gh pr merge --squash`. Each promotion becomes one commit on `main`; the squash message is the session's narrative. **Before opening the PR**, verify `origin/dev` matches local `dev` (`git status` shows "up to date with origin/dev"; if ahead, push first). After merge, reset `dev` to match: `git fetch origin && git reset --hard origin/main && git push --force-with-lease origin dev`. The force-push is safe — `dev` is the solo trunk, `main` is the protected canonical line.
- **No backwards-compat shims.** Change the call sites + tests.
- **Always use code for non-trivial arithmetic** — `uv run python -c "..."`. Never mental math; numbers get quoted downstream.
- **Keep files focused.** `scraper.py` past ~600 lines → split by concern.
- **Extractor tests diff against captured fixtures**, not hand-built dicts. Pattern: `tests/fixtures/<feature>/<case>.json`.
- **Sweeps write a directory**, not a single file. `<out>/report.md`, `<out>/sweep.log.jsonl`, etc.
- **Recommend `judex acompanhar <run_dir>` as the canonical live sweep monitor** before reaching for anything fancier. Wraps `tail -F` with auto-detection: monolithic runs → top-level `driver.log` / `launcher.log`; sharded runs → all `shard-*/driver.log` interleaved (with `==> shard-X/driver.log <==` headers). The unified `executar` writes per-record `[N/total] ...` + periodic `[progress] ok=… fail=… · X.XX proc/s · eta Y min` to that log — liveness, throughput, ETA, and recent errors in one view. Pair with `pgrep -af <run_label>` for liveness. Sharded runs also have a richer (`judex debug probe --out-root <dir> --watch N`), though probe predates `executar`'s nested state shape and only renders 0/X for that pipeline; regime-trajectory analysis (cliffs / SSL-EOF storms) is post-hoc via `judex debug analisar-regimes <run_dir>`. Don't write bespoke monitor scripts when `judex acompanhar` already carries the live signal.
- **Measure before optimising.** Cold perf numbers don't extrapolate to sweep scale (WAF ceiling dominates).
- **CLI: Typer-wins, pure-function library modules.** New commands go in `judex/cli.py` as Typer subcommands and call a `run_X(**kwargs)` library function directly with typed kwargs — see `fazer-backup` calling `judex.backup.make_backup`, or `executar` calling `judex.pipeline.runner.run_pipeline`. There is no argparse shim layer; detached sweeps invoke `nohup uv run judex <command> …` (the Typer command works via subprocess as well as in-process). `_push` in `judex/cli.py` builds argv for child subprocesses spawned by `launch_sharded(command="executar", ...)` — one `uv run judex executar` per shard.

## Agent skills

### Issue tracker

Issues for this repo live as local markdown files under `.scratch/<feature>/`. See `docs/agents/issue-tracker.md`.

### Triage labels

Five canonical triage states (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`), recorded as a `Status:` line in each issue file. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context layout — one `CONTEXT.md` at the repo root, ADRs under `docs/adr/`. See `docs/agents/domain.md`.
