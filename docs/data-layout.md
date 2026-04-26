# Data layout

Where things live in judex-mini. New contributors start here.

## One axis: cost of deletion

Under `data/`, the path encodes "what happens if I `rm -rf` this?". Three
top-level dirs, three answers.

| top-level         | cost of deletion                                    | example contents                                      | git-tracked? |
|-------------------|-----------------------------------------------------|--------------------------------------------------------|--------------|
| `data/source/`    | Catastrophic — irreplaceable scientific output      | `processos/<CLASSE>/judex-mini_<CLASSE>_<N>.json`     | no           |
| `data/raw/`       | Expensive — re-fetch is hours + proxy budget        | `html/`, `pecas/<sha1>.<ext>.gz`                       | no           |
| `data/derived/`   | Cheap — local rebuild in minutes                    | `warehouse/`, `exports/`, `reports/`, `dead-ids/`, `pecas-texto/` | no    |

Operational artifacts (logs, request audit DB, canary outputs, sweep
state, daily report watermarks) live **outside** `data/` — under
`runs/` (per-sweep, ephemeral) and `state/` (persistent).

| top-level         | role                                                | git-tracked?                                         |
|-------------------|-----------------------------------------------------|------------------------------------------------------|
| `config/`         | proxy pools, secrets                                | no                                                   |
| `tests/sweep/`    | hand-staged input CSVs                              | yes (master) / no (`shards/`)                        |
| `runs/`           | per-sweep operational state                         | no                                                   |
| `state/`          | persistent operational state                        | partial — `daily_report.json`, `watchlist/` tracked; `logs/`, `canary-outputs/`, `requests-archive.duckdb` ignored |
| `docs/`           | curated knowledge                                   | yes                                                  |

## The three `data/` trees in detail

### `data/source/` — the scientific product (precious)

**Never tracked (too big); backed up via `judex fazer-backup`; precious.**

```
data/source/
└── processos/
    ├── HC/
    │   └── judex-mini_HC_<N>.json        ← one record per HC
    └── ADI/
        └── judex-mini_ADI_<N>.json       ← one record per ADI (future)
```

One directory per `classe`; one JSON file per processo. Schema at
`judex/data/types.py` (`StfItem` TypedDict). This is the final output
that downstream analyses (marimo notebooks, research papers) consume.
**Domain naming**: `processos/` matches the CLI verb (`varrer-processos`)
and the README glossary.

### `data/raw/` — immutable upstream bytes (expensive to refetch)

**Never tracked; safe to delete-but-expensive (re-scrape costs hours + proxy budget).**

```
data/raw/
├── html/
│   └── <CLASSE>_<N>.tar.gz               ← per-processo HTML fragments (one tar)
└── pecas/
    └── <sha1(url)>.<ext>.gz              ← raw peça bytes from STF
                                            (.pdf.gz, .rtf.gz, …;
                                             format-agnostic, sha1-keyed)
```

The `pecas/` directory is **deliberately format-agnostic**. The cache
key is `sha1(url)`; STF serves PDF for most documents but RTF for some
(e.g. older `notaTaquigrafica`). The on-disk extension reflects the
actual format STF served — naming the dir `pdf/` would lie. Read/write
via `judex.utils.peca_cache` (see `PECAS_ROOT`).

HTML cache: one `.tar.gz` per processo, members are gzipped tabs +
`incidente.txt` + DJe pseudo-tabs. Read/write via
`judex.utils.html_cache` (see `CACHE_ROOT`).

### `data/derived/` — regenerable in minutes (cheap to rebuild)

**Never tracked; safe to delete at any time.**

```
data/derived/
├── warehouse/
│   └── judex.duckdb                      ← analytical DuckDB, ~3.7 min rebuild
├── exports/
│   └── <study>/{*.feather,*.parquet}     ← per-study materialized tables
├── reports/
│   └── <slug>/{stats.json,summaries.jsonl,narrative.md}
│                                            outputs of analysis/reports/*.py
├── dead-ids/
│   ├── <CLASSE>.txt                      ← confirmed-nonexistent process IDs
│   └── <CLASSE>.candidates.tsv           ← audit table behind .txt
└── pecas-texto/                          ← extracted-text + sidecars (peça quartet)
    ├── <sha1>.txt.gz                     ← from extrair-pecas
    ├── <sha1>.extractor                  ← provider label sidecar
    └── <sha1>.elements.json.gz           ← (rare) structured OCR output
```

**Why `pecas-texto/` is `derived/`, not `raw/`**: text extraction is
deterministic from bytes given a provider — `pypdf` is free, OCR
providers (mistral, chandra, unstructured) cost money but the bytes
themselves are upstream. The `.extractor` sidecar records which
provider produced each text; re-running with the same provider is a
no-op (skip), with a different provider rewrites both `.txt.gz` and
`.extractor`. See `judex.utils.peca_cache` (`TEXTO_ROOT`).

## Operational artifacts (outside `data/`)

### `config/` — secrets and hand-staged credentials

**Never tracked (whole tree gitignored).** Bring your own proxy files
here; the launcher scripts read by path.

```
config/
└── proxies              ← one URL per line (any name; --proxy-pool path)
```

### `tests/sweep/` — CSV inputs

```
tests/sweep/
├── hc_all_desc.csv                       ← master, 273 000 HC ids
├── canary_50.csv                         ← 50-row canary for validation
├── shape_coverage.csv                    ← small, class-diverse
└── shards/                               ← generated — gitignored
    └── hc_all_desc.shard.{0..3}.csv
```

`shards/` is regenerated by `scripts/shard_csv.py`; the master CSVs
are source-of-truth and version-controlled.

### `runs/` — per-sweep operational state

**Never tracked in git.** Full `/runs/` rule in `.gitignore`.

```
runs/
├── active/<date>-<label>/                ← in-flight sweep
│   ├── manifest.json                     (optional: what/when/by-whom)
│   ├── shards.pids                       (sharded sweeps only)
│   └── [shard-{0..N-1}/]                 (sharded) OR (monolithic files here)
│       ├── sweep.state.json              atomic per-item state
│       ├── sweep.log.jsonl               append-only attempt log
│       ├── sweep.errors.jsonl            derived non-ok entries
│       └── driver.log                    stdout / progress
├── archive/<date>-<label>/               ← completed sweep (same shape + report.md)
└── coletas/<timestamp>-<label>/          ← legacy varrer-processos default output
```

Promote one human-written narrative per finished sweep to
`docs/reports/<date>-<label>.md`; leave operational artifacts under
`archive/`.

### `state/` — persistent operational state

```
state/
├── daily_report.json                     ← marca d'água do relatorio-diario [tracked]
├── watchlist/<id>.json                   ← snapshots da watchlist          [tracked]
├── logs/scraper_*.log                    ← session logs                    [ignored]
├── canary-outputs/                       ← canary fixtures                 [ignored]
└── requests-archive.duckdb               ← per-GET HTTP audit              [ignored]
```

Why partial-tracking: `daily_report.json` and `watchlist/` are persistent
*configuration* a fresh checkout needs. `logs/`, `canary-outputs/`, and
`requests-archive.duckdb` are bulky operational byproducts — gitignored
by explicit rules in `.gitignore`.

### `docs/` — curated knowledge

**Git-tracked, deliberately.**

```
docs/
├── current_progress.md                   ← live lab notebook (active task + strategic state)
├── data-layout.md                        ← this file
├── stf-portal.md                         ← how the portal works
├── rate-limits.md                        ← WAF behavior + cooldowns
├── process-space.md                      ← HC / ADI / RE ceilings
├── performance.md                        ← HTTP vs Selenium numbers
├── progress_archive/<YYYY-MM-DD_HHMM_slug>.md  ← prior lab-notebook snapshots
├── reports/<date>-<label>.md             ← promoted human-written narratives
└── superpowers/specs/                    ← design specs for major features
```

## The foreign key — processo → peça text

The join from a processo record to its peça text is a three-hop:

```
data/source/processos/HC/judex-mini_HC_135041.json   ← processo record
  └── andamentos[17].link                            ← STF portal URL for a peça
       └── sha1(link)                                ← content-addressed key
            └── data/derived/pecas-texto/<sha1>.txt.gz  ← the extracted text
```

Reading it in code:

```python
import json
from pathlib import Path
from judex.utils import peca_cache

record = json.loads(Path("data/source/processos/HC/judex-mini_HC_135041.json").read_text())
for a in record[0]["andamentos"]:
    link = a.get("link")
    if not link or not link.lower().endswith((".pdf", ".rtf")):
        continue
    text = peca_cache.read(link)             # None if cache miss; str if hit
    print(a["link_descricao"], len(text or ""))
```

`peca_cache.read` / `peca_cache.write` handle the sha1 + gzip layer —
you never compute the hash yourself. For structure-aware consumers
there's a parallel path:

```python
elements = peca_cache.read_elements(link)  # None if not OCR-sourced
if elements:
    body = [e for e in elements if e["type"] not in ("Header", "Footer")]
    pages = [e["metadata"]["page_number"] for e in elements if "metadata" in e]
```

Text cache is populated for every cached URL where extraction ran; the
elements cache is populated only where OCR ran. Code that needs
structure should gracefully fall back to flat text when `read_elements`
returns `None`.

## Schema sources of truth

- **Processo JSON**: `judex/data/types.py` defines `StfItem` as a
  `TypedDict`. Fields are Optional for a reason — STF data is
  irregular; fields-that-can-be-absent must be nullable.
- **Attempt records**: `judex/sweeps/process_store.AttemptRecord` (process
  sweeps) and `judex/sweeps/peca_store.PecaAttemptRecord` (peça sweeps)
  are the dataclasses written into the `.jsonl` files.
- **Ground-truth fixtures**: `tests/ground_truth/*.json` — five
  hand-validated cases that `scripts/validate_ground_truth.py`
  diff-checks against. Don't break these.

## Non-obvious implications

- **Deletion safety is path-visible.** `rm -rf data/derived/` is always
  safe and cheap. `rm -rf data/raw/` is safe but expensive (must
  re-scrape). `rm -rf data/source/` loses the scientific product.
  The path tells you the cost.
- **The peça quartet split between `raw/` and `derived/`**: bytes
  (`<sha1>.<ext>.gz`) live in `data/raw/pecas/`; text + extractor
  sidecar + elements live in `data/derived/pecas-texto/`. They share
  `sha1(url)` so a join is one string operation. Don't merge them
  back — the cost-of-deletion split is the whole point.
- **URL, not processo, is the peça-cache key.** Two processos that cite
  the same peça share one cache entry. Generally desirable (de-dup),
  but it means cache-per-processo accounting requires walking
  `andamentos[].link` from each processo. Also: the `--classe` filter
  on `fazer-backup` only narrows the processos subtree — peças always
  ship as a complete set (per-class scoping would break shared keys).
- **Format-agnostic peça naming.** `data/raw/pecas/<sha1>.<ext>.gz`
  carries whatever extension STF served. Today the corpus is mostly
  `.pdf.gz`; RTF and other formats are real and the layout doesn't
  pretend they aren't.
- **`runs/` is fully gitignored.** Operational state never pollutes
  the git history. Human-written narratives get promoted to
  `docs/reports/` one file per run.
- **`config/` is fully gitignored.** Proxy files, any future API
  keys or connection strings go here; never inline in code.
- **`state/` is partially tracked.** Two whitelist exceptions
  (`daily_report.json`, `watchlist/`) keep persistent runtime
  configuration in version control; everything else under `state/` is
  gitignored by explicit rules.

## Sibling docs

This file is the spatial map; sibling docs cover the rest of the
conceptual surface:

- [`docs/stf-portal.md`](stf-portal.md) — how the portal works (URL flow, auth triad, UTF-8, field→source map, DataJud dead-end).
- [`docs/rate-limits.md`](rate-limits.md) — WAF behavior, validated sweep defaults, robots.txt posture question.
- [`docs/process-space.md`](process-space.md) — class sizes (HC / ADI / RE), density probes, ceiling refresh.
- [`docs/performance.md`](performance.md) — HTTP vs Selenium numbers + why caching is the real lever.
- [`docs/current_progress.md`](current_progress.md) — temporal view: what's in flight, blocked, next. The live lab notebook.
