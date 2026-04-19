# Split `varrer-pdfs` into `baixar-pdfs` + `extrair-pdfs`

Status: **draft, in progress**. Author: 2026-04-19. Supersedes the
earlier draft of this file ("varrer-pdfs OCR knob — single command,
provider-parameterized") — no code landed against that direction, so
it is replaced rather than archived.

## Goal

Pull the two operations that `varrer-pdfs` currently fuses — HTTP GET
the PDF bytes from STF, and extract text from those bytes — apart
into two independent CLI commands:

1. **`baixar-pdfs`** — the only command that talks to the STF portal.
   Downloads PDFs to `data/cache/pdf/<sha1(url)>.pdf.gz` and does
   nothing else.
2. **`extrair-pdfs --provedor {pypdf|mistral|chandra|unstructured}`** —
   reads those bytes from disk, runs the chosen OCR/text extractor,
   writes `<sha1(url)>.txt.gz` + `<sha1(url)>.extractor` sidecar
   (+ optional `<sha1(url)>.elements.json.gz`). Zero HTTP.

`varrer-pdfs` retires. `scripts/reextract_unstructured.py` retires.
There is no convenience wrapper — per `CLAUDE.md § Conventions` no
backcompat shims. Users who want the old one-shot behavior run
`baixar-pdfs && extrair-pdfs`.

The length-based skip heuristic (`--min-caracteres`) and the two-pass
`--ocr-resgate` default are dropped entirely, same as the previous
draft. Provider is the one quality axis; length was a poor proxy.

## Why split

The original draft kept a single command and added a per-provider
sidecar to avoid re-extracting when the cached text already came from
the requested provider. That helps, but it doesn't stop re-downloading
the PDF from STF every time the cache entry is wrong provider or the
user wants to try a new one. STF's WAF enforces `robots.txt` at the
IP/behavioral layer (`docs/rate-limits.md` — 403, minutes to clear),
so every "switch provider and rerun" still costs WAF budget on
bytes we already had.

The 2026-04-19 bakeoff made this concrete: four providers × 5 PDFs
meant five fetches per PDF or careful per-provider cache juggling.
Neither is the behavior we want. **Download once, extract however
many times you want** is the behavior we want, and it is only
expressible as two separate commands.

Secondary wins:

- **Phase 2 `--lote`** (Mistral batch) becomes a clean read-from-disk
  step with no fetch coupling — the batch JSONL builder simply reads
  `pdf_cache.read_bytes(url)` per target.
- **Bakeoffs** (`scripts/ocr_bakeoff.py`) stop re-downloading. A single
  `baixar-pdfs` run seeds everything; bakeoff iterates providers
  against bytes.
- **WAF machinery concentrates**. Proxy pool, circuit breaker, 403
  retry, adaptive throttle — all of it lives on `baixar-pdfs`.
  `extrair-pdfs` has none of it because it has no network path.
- **Provenance**. The PDF bytes on disk become the auditable source of
  the extracted text. Today we discard them the moment pypdf is done.
- **Content-addressing becomes possible** as a follow-up: `sha256(bytes)`
  as a secondary index would detect URL rotation (the current
  `<sha1(url)>` scheme silently misses it). Not delivered here, but
  enabled.

## Non-goals

- **No backcompat shims.** `varrer-pdfs`, `--ocr`, `--ocr-resgate`,
  `--sem-ocr-resgate`, `--min-caracteres`, `scripts/fetch_pdfs.py`,
  `scripts/reextract_unstructured.py` are removed outright. No
  deprecation warnings, no aliases.
- **No monotonic-by-length cache guard.** Provider choice is the
  quality commitment; length is not a proxy.
- **No elements-cache restructuring.** Provider-specific element
  shapes stay opaque. Unifying them is out of scope.
- **No disk-retention policy.** PDFs accumulate in
  `data/cache/pdf/<sha1>.pdf.gz`. We revisit when someone actually
  feels the pinch (famous-lawyer tier ≈ 354 PDFs ≈ <1GB is trivial;
  full-HC ≈ 64k × ~5 × ~2MB ≈ ~640GB is the kind of number to scope
  by filter, not accumulate blindly).
- **No content-addressing in this change.** Follow-up.
- **No automatic backfill** of PDF bytes for existing text-only cache
  entries. `extrair-pdfs` handles them correctly: sidecar-match skip
  no-ops on them; only `--forcar` exposes the gap, and the
  `no_bytes` error tells the user to run `baixar-pdfs`.
- **No `coletar-lote` retries on FAILED / TIMEOUT_EXCEEDED.** Phase 2
  reports state and exits non-zero; user decides.
- **No convenience chain command.** Users run both commands.

## Command surface

### `baixar-pdfs`

```
uv run judex baixar-pdfs \
    # INPUT MODE (pick one; filters are fallback)
    -c HC -i 252000 -f 253000            # range mode
    --csv alvos.csv --rotulo foo         # CSV of (classe, processo)
    --retentar-de <pdfs.errors.jsonl>    # retry prior failures
    --classe HC --impte-contem TORON     # filter fallback

    # FILTERS (fallback only)
    --tipos-doc "DECISÃO MONOCRÁTICA,…"
    --excluir-tipos-doc "…"
    --relator-contem "…"
    --limite N
    --roots data/cases …

    # EXECUTION
    --saida runs/active/<date>-<label>
    --forcar                             # re-download even if bytes cached
    --dry-run                            # preview + exit
    --nao-perguntar                      # skip confirm; required for non-TTY
    --retomar                            # skip state=ok URLs
    --sleep-throttle 2.0
    --janela-circuit 50 --limiar-circuit 0.8
```

No `--provedor`. No OCR concept at this layer.

### `extrair-pdfs`

```
uv run judex extrair-pdfs \
    # INPUT MODE (same four, shared resolver)
    -c HC -i 252000 -f 253000
    --csv alvos.csv --rotulo foo
    --retentar-de <pdfs.errors.jsonl>
    --classe HC --impte-contem TORON

    # FILTERS (fallback only) — same set as baixar-pdfs

    # EXTRACTOR
    --provedor pypdf                     # pypdf | mistral | chandra | unstructured. Default: pypdf.
    --forcar                             # re-run even if sidecar matches
    --lote                               # Phase 2 only. In Phase 1, errors with "deferred".

    # EXECUTION
    --saida runs/active/<date>-<label>
    --dry-run
    --nao-perguntar
    --retomar
    --limite N
```

No `--sleep-throttle`, no `--janela-circuit`, no `--limiar-circuit`.
The extract driver is local + API-only; WAF-era machinery does not
apply. Provider errors (API 4xx/5xx, JSON decode, explicit error
fields) land in `pdfs.errors.jsonl`; users rerun with `--retentar-de`.

### Input-mode resolution (shared by both commands)

Priority: `--retentar-de` > `--csv` > `-c` with `-i`/`-f` range > filter
fallback. Zero targets in any mode → exit 2 with a clear message.

### Preview + confirm (shared shape, different content)

Both commands print a preview block before acting. `--dry-run` exits
0 after the block. Non-TTY + no `--nao-perguntar` → exit non-zero
("use --nao-perguntar when running unattended"), per
`CLAUDE.md § Executing actions with care`. Never silently proceed in
non-interactive contexts.

**`baixar-pdfs` preview (example):**

```
targets: 354 PDFs across 28 processes (modo: filtros)
filtros: --classe HC --impte-contem TORON,PIERPAOLO --tipos-doc "…"
já em disco (pulados):   12
a baixar:               342
espaço estimado:     ~684 MB (at ~2 MB/PDF)
tempo estimado:      ~19 min (at --sleep-throttle 2.0 + HTTP)

Prosseguir? [s/N]
```

**`extrair-pdfs` preview (example):**

```
targets: 354 PDFs across 28 processes (modo: filtros)
já extraídos por mistral (pulados): 12
sem bytes locais (falharão):         8
a extrair:                          334
páginas estimadas (~5 pg/PDF):    1 670

provedor: mistral (sync)
custo estimado:  $3.34
tempo estimado:  ~16 min (at ~3 s/PDF)

Prosseguir? [s/N]
```

## Cache layout

Four URL-keyed files under `data/cache/pdf/`:

| file                                 | produced by     | content                        |
|---|---|---|
| `<sha1(url)>.pdf.gz`                 | `baixar-pdfs`   | raw PDF bytes, gzip-wrapped    |
| `<sha1(url)>.txt.gz`                 | `extrair-pdfs`  | extracted text                 |
| `<sha1(url)>.elements.json.gz`       | `extrair-pdfs`  | provider structured elements   |
| `<sha1(url)>.extractor`              | `extrair-pdfs`  | plain-text provider label      |

All four share the same URL-derived sha1 key and the same
`tempfile → os.replace` atomic write contract used today by
`pdf_cache.py`.

## Skip logic

### `baixar-pdfs` per target

1. `--retomar` wins: state says `ok` for this URL → skip.
2. `pdf_cache.has_bytes(url)`:
   - `True` and not `--forcar` → skip, `status=cached`.
   - `True` and `--forcar`    → HTTP GET, overwrite.
   - `False`                  → HTTP GET, write.
3. HTTP error → `status=http_error`, classified via
   `src.sweeps.shared.classify_exception`.

### `extrair-pdfs` per target

1. `--retomar` wins: state says `ok` for this URL → skip.
2. `pdf_cache.has_bytes(url)` == `False` → `status=no_bytes`,
   explicit log line "run baixar-pdfs first", skip. (No silent
   success.)
3. Sidecar-match truth table (refocused on extract):

| `<sha1>.extractor` value         | default action     | with `--forcar`    |
|---|---|---|
| equals `--provedor`              | skip, `status=cached` | run + overwrite |
| differs from `--provedor`        | run + overwrite    | run + overwrite    |
| missing                          | run + write        | run + write        |
| present but `<sha1>.txt.gz` gone | run + overwrite    | run + overwrite    |

4. On dispatcher success → `pdf_cache.write(url, text, extractor=<provedor>)`;
   if `ExtractResult.elements is not None`, also
   `pdf_cache.write_elements(url, elements)`.
5. Empty text (whitespace-only or zero-bytes) → `status=empty`, no
   cache write, not retryable.
6. Provider error → `status=provider_error`, goes to
   `pdfs.errors.jsonl`, retryable via `--retentar-de`.

Compose: `--retomar --forcar` means `--retomar` still skips already-ok
state records; `--forcar` only affects targets `--retomar` didn't skip.

## Phase 1 — single commit

Scope: everything in § Command surface except `--lote`.

### Files modified

- `src/utils/pdf_cache.py` — add `has_bytes`, `read_bytes`, `write_bytes`.
- `src/scraping/ocr/pypdf.py` — **new** provider module
  (`PypdfProvider`).
- `src/scraping/ocr/dispatch.py` — register `pypdf` in `_REGISTRY`
  and `PRICING`; add `estimate_wall`.
- `src/sweeps/pdf_targets.py` — add `targets_from_range`,
  `targets_from_csv`, `targets_from_errors_jsonl`. Keep
  `collect_pdf_targets` as the filter-fallback path.
- `src/sweeps/pdf_store.py` — extend status vocabulary with `cached`
  and `no_bytes`; add `load_retry_records` (sibling of
  `load_retry_list` that returns `PdfTarget`).
- `src/sweeps/download_driver.py` — **new** (`run_download_sweep`).
- `src/sweeps/extract_driver.py` — **new** (`run_extract_sweep`).
- `src/cli.py` — delete `varrer_pdfs`; add `baixar_pdfs` and
  `extrair_pdfs` Typer commands.
- `scripts/baixar_pdfs.py` — **new** argparse CLI.
- `scripts/extrair_pdfs.py` — **new** argparse CLI.

### Files deleted

- `src/sweeps/pdf_driver.py`
- `scripts/fetch_pdfs.py`
- `scripts/reextract_unstructured.py`
- `tests/unit/test_pdf_driver.py`
- `tests/unit/test_reextract_unstructured.py`

### Files added

- `tests/unit/test_pdf_cache_bytes.py`
- `tests/unit/test_pdf_targets_modes.py`
- `tests/unit/test_download_driver.py`
- `tests/unit/test_extract_driver.py`
- `tests/unit/test_baixar_pdfs_preview.py`
- `tests/unit/test_extrair_pdfs_preview.py`

### Docs updated

- `CLAUDE.md` § Caches, § Sweep drivers, § Key source modules.
- `docs/pdf-sweep-conventions.md` — two commands + shared input modes.
- `docs/data-layout.md` — cache quartet.
- `docs/performance.md` — one-liner.
- `docs/current_progress.md` — close OQ7; update `## What just landed`.

### Wall-time anchors (2026-04-19 bakeoff)

Per-PDF wall estimate (sync):

| provider       | wall/PDF  |
|---|---|
| `pypdf`        | 0.1 s     |
| `mistral`      | 3.5 s     |
| `chandra`      | 15.0 s    |
| `unstructured` | 25.0 s    |

For `mistral --lote` (Phase 2): ~30 s to submit + Mistral SLA (up to
24 h, typically faster). Preview reports "submit-and-exit now, collect
with `coletar-lote` later".

### Verification

- `uv run pytest tests/unit/` green (baseline 333; aim for 345-360 post
  split).
- `PYTHONPATH=. uv run python scripts/validate_ground_truth.py` green.
- Smoke: `baixar-pdfs -c HC -i 252920 -f 252920 --dry-run` → preview,
  exit 0.
- Smoke: `baixar-pdfs -c HC -i 252920 -f 252920 --nao-perguntar` →
  `<sha1>.pdf.gz` lands.
- Smoke: `extrair-pdfs -c HC -i 252920 -f 252920 --provedor pypdf
  --nao-perguntar` → text + sidecar.
- Smoke: `extrair-pdfs -c HC -i 252920 -f 252920 --provedor mistral
  --nao-perguntar` → text + sidecar, **no** STF fetch.
- `rg 'varrer-pdfs|fetch_pdfs|reextract_unstructured|run_pdf_sweep|pdf_driver'
  -g '!deprecated' -g '!docs/progress_archive' -g '!docs/reports'
  -g '!runs/archive'` → zero hits.

## Phase 2 — separate commit

Scope: `extrair-pdfs --lote` + new `coletar-lote` command. Reads bytes
from disk (cheap, local), builds JSONL, submits via
`src/scraping/ocr/mistral.py::submit_batch`, writes `pdfs.batch.json`,
exits. `coletar-lote <saida>` polls + downloads + parses, writes text
via the same `pdf_cache.write` helpers.

Locked: no retries on `FAILED` / `TIMEOUT_EXCEEDED`; state + exit code
signal; user resubmits.

## Risks

| risk                                                                     | mitigation                                                                                      |
|---|---|
| Disk blows up at full-HC scale (~640GB)                                  | Scope downloads by filter/tier. Famous-lawyer 354 PDFs ≈ <1GB is trivial. Retention policy deferred. |
| User forgets to run `baixar-pdfs` first                                  | `extrair-pdfs` records `status=no_bytes` explicitly; preview surfaces the count up front.       |
| Sidecar-less existing text-only entries re-run under `--forcar`          | `read_extractor` → None → treated as "unknown" → runs. Preview gates spend.                     |
| Non-TTY without `--nao-perguntar` → fail closed                          | Covered in preview tests for both commands.                                                     |
| Archive references `pdf_driver.py` / `fetch_pdfs.py` in old sweep dirs   | Historical; `rg` sweep excludes `runs/archive`, `docs/progress_archive`, `docs/reports`.        |
| Phase 2 `coletar-lote` needs bytes that may have been evicted mid-batch  | Documented: don't evict PDFs between submit and collect. Re-download otherwise.                 |

## Decisions already locked

1. `varrer-pdfs` retires outright, no chain wrapper. Two commands.
2. Bytes-on-disk keyed by `sha1(url)`, gzipped. Content-addressing is a
   follow-up.
3. One `PdfStore` per command `--saida` directory. Status vocabulary
   extends with `cached` + `no_bytes`.
4. `extrair-pdfs` default provider is `pypdf` (cost-free; keeps
   behavioral parity with today's default for the first invocation).
5. Spec file rewritten in place on 2026-04-19. Previous draft lives in
   git history only.
6. Portuguese flag names (`--forcar`, `--provedor`, `--retomar`,
   `--retentar-de`, `--impte-contem`, `--tipos-doc`, `--relator-contem`,
   `--excluir-tipos-doc`, `--rotulo`, `--saida`, `--nao-perguntar`,
   `--sleep-throttle`, `--janela-circuit`, `--limiar-circuit`,
   `--limite`). English kept for `--dry-run` and short flags `-c/-i/-f`
   (parity with `varrer-processos`).
7. Direct selectors (range / CSV / retry) win over filters.
8. Compose semantics for `--retomar --forcar`: `--retomar` skips
   already-ok records; `--forcar` only affects non-skipped targets.
