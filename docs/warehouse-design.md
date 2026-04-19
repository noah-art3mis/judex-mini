# DuckDB warehouse — design sketch

Design-only document for a DuckDB-backed analytical warehouse over
judex-mini's case JSON and caches. No code lands with this doc; it
captures the schema + pipeline shape for review before we build.

## Goals

- Answer cross-case questions without opening thousands of JSON files
  (e.g. "all HCs where relator is Min. X and impte is AGU", "all
  andamentos whose PDF text mentions Y").
- Join cases ↔ PDFs in one SQL query — today that join lives in
  ad-hoc Python via `judex.utils.pdf_cache.read(url)`.
- Stay **derived**: the scraper never writes to the warehouse.
  `data/cases/*.json` remains the single source of truth; the
  warehouse is a rebuildable artifact.
- Manual refresh (cron / post-sweep trigger), not continuous.

## Non-goals

- Not a query layer for the scraper itself. Live scraping continues
  to read/write JSON + the HTML/PDF caches directly.
- Not a replacement for `tests/ground_truth/*.json`. Those stay.
- Not a raw-HTML store. HTML fragments stay in the tar.gz cache;
  the warehouse only holds parsed fields.

## Data layout

```
data/
  cases/                             ← primary (scraper-owned)
    HC/judex-mini_HC_135041.json
    ADI/judex-mini_ADI_2820.json
  cache/
    html/HC_135041.tar.gz            ← raw-HTML cache (tarball)
    pdf/<sha1>.txt.gz                ← PDF text cache
    pdf/<sha1>.elements.json.gz      ← Unstructured element list
  warehouse/                         ← derived (rebuildable)
    judex.duckdb                     ← single file; cases + children + pdfs
    manifest.json                    ← last-built timestamps per classe
```

One file — `warehouse/judex.duckdb` — not parquet. Reasons:

1. Single-file backup story mirrors the scientific product (case
   JSONs). `warehouse/judex.duckdb` goes to B2 as one object.
2. DuckDB reads its own format faster than parquet for ad-hoc
   queries (zero-copy, no parquet-decoder per column).
3. Schema evolution is a `CREATE OR REPLACE` away; with parquet
   partitions you manage file-level lifecycle yourself.

If the DB ever exceeds ~10 GB and build time hurts, we partition to
per-classe parquet. Not now.

## Schema

Four fact tables + one manifest. All tables are **rebuilt from
scratch** on every refresh — no in-place updates, so no migration
logic and no "orphaned rows after a case is rescraped" edge cases.

### `cases` (one row per process)

```sql
CREATE TABLE cases (
    classe              VARCHAR NOT NULL,     -- 'HC', 'ADI', 'RE', ...
    processo_id         INTEGER NOT NULL,
    incidente           INTEGER,
    url                 VARCHAR,
    schema_version      INTEGER,
    numero_unico        VARCHAR,
    meio                VARCHAR,
    publicidade         VARCHAR,
    badges              VARCHAR[],
    assuntos            VARCHAR[],
    data_protocolo      VARCHAR,              -- Portuguese text form
    data_protocolo_iso  DATE,                 -- ISO date, from StfItem v3
    orgao_origem        VARCHAR,
    origem              VARCHAR,
    numero_origem       VARCHAR,
    volumes             INTEGER,
    folhas              INTEGER,
    apensos             INTEGER,
    relator             VARCHAR,
    primeiro_autor      VARCHAR,
    outcome             VARCHAR,              -- derived (granted / denied / pending)
    status_http         INTEGER,
    extraido            TIMESTAMP,
    source_path         VARCHAR,              -- data/cases/HC/judex-mini_HC_135041.json
    source_mtime        TIMESTAMP,
    PRIMARY KEY (classe, processo_id)
);
CREATE INDEX cases_relator_idx  ON cases (relator);
CREATE INDEX cases_autuacao_idx ON cases (data_protocolo_iso);
CREATE INDEX cases_autor_idx    ON cases (primeiro_autor);
```

### `partes` (one row per party per case)

```sql
CREATE TABLE partes (
    classe        VARCHAR NOT NULL,
    processo_id   INTEGER NOT NULL,
    seq           INTEGER NOT NULL,
    papel         VARCHAR,     -- IMPTE, IMPDO, PROC, AMICUS, ...
    nome          VARCHAR,
    PRIMARY KEY (classe, processo_id, seq)
);
CREATE INDEX partes_nome_idx  ON partes (nome);
CREATE INDEX partes_papel_idx ON partes (papel);
```

### `andamentos` (one row per timeline entry; joinable to PDFs)

```sql
CREATE TABLE andamentos (
    classe        VARCHAR NOT NULL,
    processo_id   INTEGER NOT NULL,
    seq           INTEGER NOT NULL,
    data          VARCHAR,
    data_iso      DATE,
    descricao     VARCHAR,
    documento     VARCHAR,      -- "Despacho" / "Decisão Monocrática" / ...
    link_url      VARCHAR,      -- PDF URL on portal.stf.jus.br (NOT sistemas.)
    link_text     VARCHAR,
    PRIMARY KEY (classe, processo_id, seq)
);
CREATE INDEX andamentos_link_idx ON andamentos (link_url);
CREATE INDEX andamentos_doc_idx  ON andamentos (documento);
```

### `documentos` (sessao_virtual documentos — one row per voto doc)

Separate from `andamentos` because the URL origin is different
(`sistemas.stf.jus.br/repgeral/…`, not `portal.stf.jus.br/processos/…`)
and the shape is `{url, text}` post-extraction rather than raw
andamento fields.

```sql
CREATE TABLE documentos (
    classe        VARCHAR NOT NULL,
    processo_id   INTEGER NOT NULL,
    seq           INTEGER NOT NULL,
    kind          VARCHAR,      -- 'voto_relator', 'voto_ministro', ...
    ministro      VARCHAR,      -- null for voto_relator
    url           VARCHAR,
    PRIMARY KEY (classe, processo_id, seq)
);
CREATE INDEX documentos_url_idx ON documentos (url);
```

### `pdfs` (one row per sha1, flat from `data/cache/pdf/`)

```sql
CREATE TABLE pdfs (
    url           VARCHAR PRIMARY KEY,        -- logical key
    sha1          VARCHAR NOT NULL,
    text          TEXT NOT NULL,
    n_chars       INTEGER NOT NULL,
    has_elements  BOOLEAN NOT NULL,           -- OCR pass was run?
    source        VARCHAR,                    -- 'pypdf' | 'unstructured_hi_res'
    cache_path    VARCHAR
);
CREATE INDEX pdfs_sha1_idx ON pdfs (sha1);
```

Full-text search is NOT built-in — DuckDB ships the `fts` extension
which you'd enable lazily per session: `INSTALL fts; LOAD fts;
PRAGMA create_fts_index('pdfs', 'url', 'text');`. Don't bake it into
the schema; it's a query-time concern.

### `manifest` (build provenance)

```sql
CREATE TABLE manifest (
    built_at      TIMESTAMP NOT NULL,
    classes       VARCHAR[],          -- classes included in this build
    n_cases       INTEGER,
    n_andamentos  INTEGER,
    n_pdfs        INTEGER,
    build_wall_s  DOUBLE,
    judex_commit  VARCHAR             -- git rev-parse HEAD
);
```

## Build pipeline

### `scripts/build_warehouse.py`

Manual trigger (`uv run python scripts/build_warehouse.py`). Three
phases, each idempotent:

```
1. Enumerate inputs
   cases_paths   = Path('data/cases').rglob('judex-mini_*_*.json')
   pdf_paths     = Path('data/cache/pdf').glob('*.txt.gz')
2. Build in-memory rows
   for p in cases_paths:
       item = json.loads(p.read_text())
       cases.append(flatten_case(item, p))
       partes.extend(flatten_partes(item))
       andamentos.extend(flatten_andamentos(item))
       documentos.extend(flatten_documentos(item))
   for p in pdf_paths:
       pdfs.append(read_pdf_row(p))

3. Write to DuckDB (atomic)
   tmp = 'data/warehouse/judex.duckdb.tmp'
   with duckdb.connect(tmp) as con:
       con.execute(SCHEMA_SQL)
       con.executemany('INSERT INTO cases ...', cases)
       ...
       con.execute('INSERT INTO manifest VALUES (?, ...)', [...])
   os.replace(tmp, 'data/warehouse/judex.duckdb')
```

Full rebuild on every run keeps the code trivial: no
"what-changed-since-last-build" tracking, no UPSERT logic, no
orphaned rows. The whole thing is a CPU-bound scan of JSON + gzip
decompression.

**Expected cost at current scale** (55k cases, 17k PDFs):

- Input: 4.4 GB case JSON + 48 MB PDF text
- Rebuild: ~2–3 min dominated by JSON parsing (DuckDB inserts are
  fast; the warehouse won't exceed ~500 MB on disk)
- Output DB: dominated by `pdfs.text` blob (~50 MB); `andamentos`
  and `cases` together under 100 MB

At 350k-HC scale (~29 GB case JSON), rebuild time is ~15–20 min.
Still fine for a manual/post-sweep refresh cadence. If it grows
past 30 min, the escape hatch is per-classe parquet partitioning.

### Incremental mode (future, not for v1)

If full rebuild becomes painful:
- Track `manifest.built_at`
- On refresh, `find data/cases -newer <manifest.built_at>` and
  upsert just those case records
- Re-derive `partes` / `andamentos` / `documentos` for those cases
  only
- `pdfs` table: walk `data/cache/pdf/` with a `sha1 NOT IN (SELECT
  sha1 FROM pdfs)` filter

Keep this for v2. v1 is full rebuild.

## Refresh cadence

Three triggers, pick the simplest you tolerate:

1. **Manual** — `uv run python scripts/build_warehouse.py`. Cost:
   human has to remember. Fine for exploratory use.
2. **Post-sweep** — `run_sweep.py`'s `_finalize()` calls
   `build_warehouse.py` on success. Cost: 2-3 min added to each
   sweep. Rebuilds stale data automatically.
3. **Cron** — `/schedule` nightly. Cost: wastes build time on
   days nothing scraped. Simplest ops story.

Recommendation: **manual for v1**. Add post-sweep in v2 once
build-time settles. Don't cron — wasted rebuilds on quiet days
aren't free.

## Usage examples

These are the questions we actually want to answer — worth including
the queries here so the schema is motivated.

```sql
-- HCs where AGU is impetrante and the outcome is 'granted'
SELECT c.classe, c.processo_id, c.relator, c.outcome
FROM cases c
JOIN partes p USING (classe, processo_id)
WHERE c.classe = 'HC'
  AND p.papel = 'IMPTE'
  AND p.nome LIKE '%UNIAO%'          -- AGU represents a União
  AND c.outcome = 'granted'
ORDER BY c.data_protocolo_iso DESC;

-- Andamentos whose PDF text mentions "prisão preventiva"
SELECT a.classe, a.processo_id, a.data_iso, a.documento, p.url
FROM andamentos a
JOIN pdfs p ON p.url = a.link_url
WHERE p.text LIKE '%prisão preventiva%'
  AND a.classe = 'HC';

-- Voto-relator documents per minister, last year
SELECT d.ministro, COUNT(*) AS n_votes
FROM documentos d
JOIN cases c USING (classe, processo_id)
WHERE d.kind = 'voto_relator'
  AND c.data_protocolo_iso >= DATE '2025-01-01'
GROUP BY d.ministro
ORDER BY n_votes DESC;
```

## Open questions (resolve before building)

1. **`outcome` normalization.** Current `derive_outcome` returns
   free-form strings. Warehouse users will want an enum. Promote
   the enum to `judex/data/types.py` first, then mirror it in the
   schema. Doing this during the build adds coupling.
2. **Are sessao_virtual `votes[]` first-class?** Probably yes —
   one vote per (case, ministro) is the natural fact for "how does
   minister X vote". Add a fifth table `votes` or fold into
   `documentos`. Defer the decision until we have a concrete query
   that needs it.
3. **Stable ids for `andamentos.seq` and `partes.seq`.** The JSON
   preserves insertion order; are those orderings stable across
   re-scrapes of the same case? If not, we can't reliably upsert
   incrementally later. Empirically verify with two scrapes of one
   case before the v2 incremental effort.
4. **Full-text index on `pdfs.text` at build time vs. session time.**
   Build-time bakes it in (bigger DB, faster queries); session-time
   keeps DB small but needs `CREATE INDEX` once per session. Lean
   toward session-time for v1.

## Relationship to the HTML cache

The HTML cache (`data/cache/html/*.tar.gz`) is deliberately
**not** ingested. That data is pre-parse — useful only for
re-running extractors (see `scripts/renormalize_cases.py`). The
warehouse holds post-parse fields. Keeping the distinction clean
means an extractor change can rebuild case JSON from cached HTML
without rebuilding the warehouse, and a warehouse rebuild doesn't
require the HTML cache to be present.
