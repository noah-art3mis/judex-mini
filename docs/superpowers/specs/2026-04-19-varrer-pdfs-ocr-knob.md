# `varrer-pdfs` OCR knob — single command, provider-parameterized

Status: **draft**, not yet executed. Author: 2026-04-19.

## Goal

Make `judex varrer-pdfs` the single entry point for every PDF-text
operation (baseline pypdf, Mistral OCR, Chandra OCR, Unstructured
OCR). Input shape mirrors `varrer-processos` (range / CSV / retry /
filter). Extractor choice is `--provedor`. Re-runs are controlled
by `--forcar`. Cost and wall-time are previewed transparently before
any API call; `--dry-run` exits after the preview. The length-based
skip heuristic (`--min-caracteres`) and the two-pass `--ocr-resgate`
default are dropped entirely — provider becomes the one quality axis.

This spec implements Open question 7 in
[`docs/current_progress.md`](../../current_progress.md#open-questions)
and supersedes the ad-hoc re-extract pattern (`scripts/reextract_unstructured.py`)
by folding its behaviour into `varrer-pdfs --provedor mistral --forcar`.

## Non-goals

- **No backcompat shims.** Per `CLAUDE.md § Conventions`, the deprecated
  flags (`--ocr`, `--ocr-resgate`, `--sem-ocr-resgate`, `--min-caracteres`)
  are removed outright. No deprecation warnings, no aliases. Users who
  relied on them change their invocation.
- **No monotonic-by-length cache guard.** The current behaviour of "only
  overwrite cache if new text is strictly longer" goes away. Provider
  choice is now the explicit quality commitment; length is not a proxy.
- **No elements-cache restructuring.** `<sha1>.elements.json.gz` writes
  continue to work the way they do today; provider-specific element
  shapes stay opaque. Unifying them across providers is out of scope.
- **No unification of the bakeoff harness target collector**
  (`scripts/ocr_bakeoff.py::_collect_candidates`). It keeps its inline
  walker for now; a follow-up can merge it with `targets_from_*`.
- **No `coletar-lote` retries on `FAILED` / `TIMEOUT_EXCEEDED` batches.**
  The collect command reports state and exits non-zero; user decides how
  to resubmit.

## Context

### What exists today

- `scripts/fetch_pdfs.py` + `src/sweeps/pdf_driver.py` handle the PDF
  sweep. Current extractor is hardwired to pypdf (via the fetcher
  passed to `run_pdf_sweep`). Cache-hit short-circuit at
  `src/sweeps/pdf_driver.py:144-162` is unconditional — any non-None
  cache is treated as "done".
- `scripts/reextract_unstructured.py` exists as a separate script for
  re-running Unstructured `hi_res` on short cached entries. Uses a
  `--min-chars` threshold to pick candidates. Not wired into the Typer
  CLI hub.
- `src/cli.py::varrer_pdfs` (the Typer command) has a richer surface
  than the script: `--ocr`, `--ocr-resgate`, `--provedor`,
  `--min-caracteres`. The `--ocr-resgate` default is "two-pass: pypdf
  first, Mistral rescue on shorts".
- `src/scraping/ocr/` ships a provider abstraction
  (`base.py::OCRProvider`, `dispatch.py::extract_pdf`) with three
  implementations (`unstructured`, `mistral`, `chandra`). Mistral batch
  helpers (`build_batch_jsonl`, `submit_batch`, `get_batch_status`,
  `wait_for_batch`, `download_batch_output`, `parse_batch_results`) are
  already pure functions in `src/scraping/ocr/mistral.py`.
- `src/utils/pdf_cache.py` writes a `<sha1>.extractor` sidecar on every
  successful write, tagging which extractor produced the cached text.
  Nothing in the sweep path currently reads it.
- 5-PDF bakeoff run 2026-04-19 ~03:00 UTC
  (`runs/active/2026-04-19-ocr-bakeoff/`) found Mistral dominates
  Unstructured on quality (no column un-weaving, preserved `§` /
  `(i)(ii)(iii)`, intact table pairing), speed (12×), and cost (10×).
  Decision to migrate default to Mistral captured in
  `docs/current_progress.md § Decisions` (2026-04-19 ~03:00 UTC).

### Why the length filter must die

`--min-caracteres N` encodes "skip PDFs with ≥ N chars already cached".
Its intent was a two-tier cost ladder — pypdf for documents pypdf handles,
OCR only when text was too short (scanned docs). Three problems:

1. **Length is a poor proxy for quality.** The bakeoff showed Unstructured
   outputs at 22k chars contained `§→8` / `(i)→(1)` / column-reordering
   defects. A long pypdf extract on a multi-column acórdão is also likely
   garbled. Char count says "this has text", not "this extraction is good."
2. **The `--forcar` escape hatch is a code smell.** When every production
   invocation needs an override flag to get the intended behaviour, the
   default is wrong.
3. **Mistral is cheap enough that the cost ladder stops mattering** at
   every tier below all-HC. Famous-lawyer 354 PDFs = $1.77 on Mistral
   batch; 64k HC + key-doc-types = $323. The heuristic saves pennies at
   the cost of complexity.

Dropping the filter collapses the three-branch truth table
("force overrides length but not emptiness" etc.) into a two-state skip:
the sidecar matches the requested provider or it doesn't.

## Final CLI surface

```
uv run judex varrer-pdfs \
    # --- INPUT MODE (pick one; later modes fall back to the next) ---
    -c HC -i 252000 -f 253000            # range mode (like varrer-processos -c/-i/-f)
    --csv alvos.csv --rotulo foo         # CSV of (classe, processo)
    --retentar-de <pdfs.errors.jsonl>    # retry failures from a prior run
    --classe HC --impte-contem TORON     # filter mode (fallback)

    # --- EXTRACTOR ---
    --provedor mistral                   # pypdf | mistral | chandra | unstructured. Default: pypdf.
    --forcar                             # re-run even if sidecar matches --provedor
    --lote                               # Mistral batch: submit job, write pdfs.batch.json, exit

    # --- OUTPUT + EXECUTION ---
    --saida runs/active/<date>-<label>   # inferred from --rotulo if omitted
    --dry-run                            # preview only, no fetches/calls
    --nao-perguntar                      # skip the interactive confirm prompt

    # --- UNCHANGED FROM PRIOR VARRER-PDFS ---
    --retomar                            # skip targets already status=ok in state
    --sleep-throttle 2.0
    --janela-circuit 50 --limiar-circuit 0.8
    --tipos-doc "DECISÃO MONOCRÁTICA,..."
    --excluir-tipos-doc "..."
    --relator-contem ...
    --limite N
```

### Input-mode resolution

Direct selectors (`-c/-i/-f`, `--csv`, `--retentar-de`) win over filters.
Filters (`--classe`, `--impte-contem`, `--tipos-doc`, `--relator-contem`,
`--excluir-tipos-doc`) apply only when no direct selector is set.

`-c` alone (without `-i/-f`) remains a filter. `-c` with `-i` or `-f`
promotes to range mode and the other filters are ignored. If none of the
four modes produces any targets, exit 2 with a clear message.

### Flag names — Portuguese/English mix

Keep established Portuguese: `--provedor`, `--rotulo`, `--saida`,
`--retomar`, `--retentar-de`, `--impte-contem`, `--tipos-doc`,
`--relator-contem`, `--excluir-tipos-doc`, `--sleep-throttle`,
`--janela-circuit`, `--limiar-circuit`, `--limite`.

New Portuguese: `--forcar`, `--lote`, `--nao-perguntar`.

Keep English: `--dry-run` (already established), `-c/-i/-f` short flags
(inherit from `varrer-processos`, which already uses these).

## Semantics

### Skip logic (sidecar-match)

Before fetching a target, read `<data/cache/pdf>/<sha1(url)>.extractor`:

| sidecar value                      | default action         | with `--forcar` |
|---|---|---|
| equal to `--provedor`              | **skip** (record `status=cached`)        | run + overwrite |
| not equal (different provider)     | **run** + overwrite    | run + overwrite |
| missing (no prior extraction)      | **run** + write        | run + write     |
| present but file `.txt.gz` missing | **run** + overwrite    | run + overwrite |

`--retomar` is orthogonal and evaluated first: if the target's URL is
already `status=ok` in `pdfs.state.json`, skip regardless of sidecar.
`--retomar --forcar` composes as *behaviour A* from the design thread:
`--retomar` still skips already-ok state entries; `--forcar` only affects
targets that `--retomar` didn't skip. Users who want "re-run everything"
omit `--retomar`.

### Write semantics

After a successful extract (`status=ok`, non-empty text):

```python
pdf_cache.write(url, text, extractor=<provedor>)
```

No length comparison. Whatever the extractor returned is written. The
sidecar is updated to the new provider tag in the same write.

If the extractor returned empty text (whitespace-only or zero bytes):
record `status=empty`, do not call `pdf_cache.write`, continue.

If the extractor raised: record `status=http_error` (for HTTP-level
failures, classified via `_shared.classify_exception`) or
`status=provider_error` (for API-level failures like 4xx/5xx on the OCR
endpoint, JSON decode errors, or explicit provider error fields). Both
go into `pdfs.errors.jsonl` and are retryable via `--retentar-de`.

### Pricing preview

Runs once, after target resolution, before any fetch. Same block whether
or not `--dry-run` is set:

```
targets: 354 PDFs across 28 processes (modo: filtros)
filtros aplicados: --classe HC --impte-contem TORON,PIERPAOLO --tipos-doc "DECISÃO MONOCRÁTICA,INTEIRO TEOR DO ACÓRDÃO"
já em cache por mistral (pulados): 12
a processar:                        342
páginas estimadas (~5 pg/PDF):    1 710

provedor: mistral (sync)
custo estimado:  $3.42
tempo estimado:  ~17 min (at ~3 s/PDF)

Prosseguir? [s/N]
```

With `--dry-run`: exit 0 after the block.

With `--nao-perguntar`: skip the prompt, proceed immediately. Required
for non-TTY invocations (cron, nohup). If stdin is a TTY and
`--nao-perguntar` is absent, wait for `s` / `n`.

If stdin is not a TTY and `--nao-perguntar` is absent: **exit non-zero
with a clear message** ("use --nao-perguntar when running unattended").
Never silently proceed in a non-interactive context — that's the
irreversible-action guardrail from `CLAUDE.md § Executing actions with care`.

### Wall-time anchors

Per-PDF wall estimates, from the 2026-04-19 bakeoff:

| provider      | wall/PDF (sync)              |
|---|---|
| `pypdf`       | 0.1 s                        |
| `mistral`     | 3.5 s                        |
| `chandra`     | 15.0 s                       |
| `unstructured`| 25.0 s                       |

For `mistral --lote`, wall is "submit ~30 s + Mistral's stated ~24 h SLA
(typically faster)". The preview reports "submit-and-exit now, collect
with `coletar-lote` later".

## Phase 1 — single commit

Scope covers everything in § "Final CLI surface" except `--lote`.

### Files modified

- `src/sweeps/pdf_targets.py` — add `targets_from_range`,
  `targets_from_csv`, `targets_from_errors_jsonl`. Existing
  `collect_pdf_targets` stays.
- `src/sweeps/pdf_driver.py` — plumb `extractor: str` + `forcar: bool`
  through config. Replace cache-hit short-circuit with sidecar-aware
  skip. Replace fetcher pypdf call with dispatcher routing to
  `src.scraping.ocr.extract_pdf`. Drop length-based write guard.
- `src/utils/pdf_cache.py` — add `read_extractor(url) -> Optional[str]`
  helper.
- `src/scraping/ocr/dispatch.py` — add `estimate_wall(provider, n_pdfs, *, batch=False) -> float`.
- `scripts/fetch_pdfs.py` — rewrite CLI surface with the four input
  modes + `--provedor` / `--forcar` / `--dry-run` / `--nao-perguntar`.
  Implement `_print_preview` + interactive confirm. Drop `--ocr`,
  `--ocr-resgate`, `--sem-ocr-resgate`, `--min-caracteres` flags.
- `src/cli.py::varrer_pdfs` — align Typer signature with the script.
  Portuguese flag names where parallel to `varrer-processos`.

### Files deleted

- `scripts/reextract_unstructured.py`
- `tests/unit/test_reextract_unstructured.py`

### Files added

- `tests/unit/test_pdf_targets_modes.py` — `targets_from_range`,
  `targets_from_csv`, `targets_from_errors_jsonl`.
- `tests/unit/test_pdf_driver_extractor.py` — sidecar-match skip logic,
  extractor dispatch, empty-text write-skip, compose with `--retomar`.
- `tests/unit/test_fetch_pdfs_preview.py` — preview shape, dry-run exit,
  interactive confirm via stubbed stdin, non-TTY fail-closed.

### Docs updated

- `CLAUDE.md § Caches`, `§ Sweep drivers` — new flag documentation,
  sidecar-match skip is the canonical "already done?" axis.
- `docs/pdf-sweep-conventions.md` — extractor-knob description, four
  input modes.
- `docs/performance.md` — one-line note that `varrer-pdfs --provedor mistral`
  is the canonical OCR path.
- `docs/current_progress.md` — tick migration items, close OQ7
  follow-ups, update `## What just landed`.

### Verification

- `uv run pytest tests/unit/` green (target ≥ 310 tests).
- `PYTHONPATH=. uv run python scripts/validate_ground_truth.py` green.
- Smoke: `scripts/fetch_pdfs.py -c HC -i 252920 -f 252920 --provedor mistral --dry-run`
  → preview prints, exits 0 without spending.
- Smoke: same with `--provedor pypdf --dry-run` → shows $0.00.

## Phase 2 — separate commit

Scope: `--lote` on `varrer-pdfs` + new `coletar-lote` command.

### Files modified

- `src/sweeps/pdf_driver.py` — branch on `lote: bool`. When true,
  resolve + fetch bytes, build one JSONL, submit batch, write
  `pdfs.batch.json`, exit.
- `scripts/fetch_pdfs.py` — add `--lote` flag. Valid only with
  `--provedor mistral`. Batch pricing in preview.
- `src/cli.py` — add `--lote` to `varrer-pdfs`; add new top-level
  `coletar-lote <saida>` command.

### Files added

- `scripts/coletar_lote.py` — poll loop + `--check` single-shot.
- `tests/unit/test_pdf_driver_batch.py` — mocked Mistral HTTP.
- `tests/unit/test_coletar_lote.py` — arg surface, `--check`, exit
  codes.

### Verification

- `--lote --dry-run` prints preview, does not submit.
- Real smoke on 5 PDFs: submit → `pdfs.batch.json` written → exit;
  `coletar-lote --check` reports `RUNNING`/`SUCCESS`; final
  `coletar-lote` writes to cache; unit suite green.

## Risks

| risk                                                                                        | mitigation                                                                                          |
|---|---|
| Existing runs or docs depending on `--min-caracteres` / `--ocr-resgate` flags break          | Project convention is no backcompat shims. Migration note in commit message. Archives untouched.    |
| Sidecar-less cache entries (pre-sidecar era) re-run every invocation                         | `read_extractor` returns `None` → treated as "unknown" → target runs. Safe default; $$ gated by preview. |
| Pricing preview drifts from reality (avg pg/PDF, wall anchors)                               | Preview is "estimated"; actual cost lands in `report.md`. Re-anchor when new bakeoff data arrives.  |
| Interactive prompt blocks non-TTY runs                                                       | `--nao-perguntar` bypasses. Non-TTY without `--nao-perguntar` fails closed, does not silently proceed. |
| Mistral batch mode writes `pdfs.batch.json` but user forgets to `coletar-lote`               | Batch job visible via Mistral dashboard; state file is durable and resumable. Only cost is the submitted spend. |
| Bakeoff harness target collector diverges further from `collect_pdf_targets`                 | Out of scope. Follow-up open question: "unify `_collect_candidates` with `targets_from_*`."          |

## Decisions already locked (from design thread)

1. Portuguese-English flag mix, leaning Portuguese for parallels with `varrer-processos`.
2. Auto-confirm flag named `--nao-perguntar`.
3. Empty-output → `status=empty`, no retry.
4. This spec file committed before Phase 1 coding starts.
5. Compose semantics for `--retomar --forcar`: `--retomar` wins on already-ok state records; `--forcar` affects only non-skipped targets.
6. Direct selectors (range / CSV / retry) win over filters.
