# Data layout

Where things live in judex-mini, and how they reference each other.
New contributors start here.

## The three data stores

| Store | Path | Key | Contents |
|---|---|---|---|
| **Case JSON** | `data/output/**/judex-mini_<CLASSE>_<N>.json` | `(classe, processo_id)` | One record per STF process: parties, andamentos (events), relator, outcome, metadata. Written by `main.py` / sweep drivers. Tracked in git where useful. |
| **PDF text cache** | `data/pdf/<sha1(url)>.txt.gz` | `sha1(andamento link URL)` | Flat extracted text of each andamento PDF, gzipped. Written by pypdf on first scrape; re-written by `scripts/reextract_unstructured.py` when OCR beats pypdf. **Not in git** (`.gitignore`'d). |
| **PDF elements cache** | `data/pdf/<sha1(url)>.elements.json.gz` | same as text cache | Structured Unstructured element list (`type` / `metadata` / `text` per element) for OCR-sourced entries only. Lets consumers filter Header/Footer, group by page, extract Tables. Absent for pypdf-sourced URLs. Not in git. |
| **HTML fragment cache** | `data/html/<CLASSE>_<N>/*.html.gz` | `(classe, processo, tab)` | Per-process raw HTML of each STF tab. Lets re-scrapes replay from disk in ~60× less time. Not in git. |

## The foreign key

The join from a case to its PDF text is a three-hop:

```
data/output/.../judex-mini_HC_135041.json   ← case record
  └── andamentos[17].link                    ← STF portal URL for a PDF
       └── sha1(link)                        ← content-addressed key
            └── data/pdf/<sha1>.txt.gz     ← the extracted text
```

Reading it in code:

```python
import json
from pathlib import Path
from src.utils import pdf_cache

record = json.loads(Path("data/output/sample/hc_sweep/judex-mini_HC_135041.json").read_text())
for a in record[0]["andamentos"]:
    link = a.get("link")
    if not link or not link.lower().endswith(".pdf"):
        continue
    text = pdf_cache.read(link)           # None if cache miss; str if hit
    print(a["link_descricao"], len(text or ""))
```

`pdf_cache.read` / `pdf_cache.write` handle the sha1 + gzip layer —
you never compute the hash yourself. For structure-aware consumers
there's a parallel read path:

```python
elements = pdf_cache.read_elements(link)  # None if not OCR-sourced
if elements:
    body = [e for e in elements if e["type"] not in ("Header", "Footer")]
    pages = [e["metadata"]["page_number"] for e in elements if "metadata" in e]
```

The text cache is populated for every cached URL; the elements cache
is populated only where `scripts/reextract_unstructured.py` wrote it
(OCR-sourced entries). Code that needs structure should gracefully
fall back to the flat text when `read_elements` returns `None`.

## Sweep run artifacts

Sweeps (process or PDF) write to dedicated directories, one per run.
Layout is the same across both:

| Sweep type | Directory root | Driver module |
|---|---|---|
| Process sweep (scrape N cases, compare vs ground truth) | `docs/sweep-results/<date>-<label>/` | `scripts/run_sweep.py` + `src/sweeps/process_store.py` + `src/sweeps/shared.py` |
| PDF sweep (walk JSON, fetch andamento PDFs) | `docs/pdf-sweeps/<date>-<label>/` | `scripts/fetch_pdfs.py` routing through `src/sweeps/pdf_driver.run_pdf_sweep` |

Each sweep directory follows the same institutional shape when
driven through `pdf_driver.py` or the process-sweep equivalent:

| File | Purpose |
|---|---|
| `sweep.state.json` / `pdfs.state.json`     | atomic per-item state, compacted |
| `sweep.log.jsonl` / `pdfs.log.jsonl`       | append-only attempt log (fsynced per write) |
| `sweep.errors.jsonl` / `pdfs.errors.jsonl` | derived non-ok entries; feeds `--retry-from` |
| `requests.db`                              | per-GET SQLite WAL archive (PDF sweeps only) |
| `report.md`                                | auto-generated human report |
| `SUMMARY.md`                               | human narrative over the run — headline, outliers, implications |

See `docs/sweep-results/2026-04-16-E-full-1k-defaults/SUMMARY.md`
for the canonical template, and `docs/pdf-sweeps/README.md` for
the PDF-side conventions.

**Known deviation**: `scripts/reextract_unstructured.py` runs an
inlined loop instead of routing through `pdf_driver.run_pdf_sweep`,
so its runs only produce `run.log` + `SUMMARY.md` — the
`pdfs.{state,log,errors}.jsonl` + `requests.db` are absent. Migration
is a small follow-up (see the script's "Known gaps" docstring).

## Analysis / notebooks

`analysis/` is **git-ignored scratch** (`.gitignore`). Marimo
notebooks, ad-hoc markdown profiles, one-off JSON dumps, hand-curated
text extracts all live here. Contents won't be on a fresh checkout;
see `docs/handoff.md` § "HC who-wins — investigation-strand layout"
for the canonical list of notebooks that currently populate this
directory.

The notebooks read from the three stores above; they don't write to
them. They do sometimes write their own intermediate files (e.g.
`analysis/data/defmg_texts.json`) — those are scratch too, never a
shared artifact.

## Source of truth for schemas

- **Case JSON**: `src/data/types.py` defines `StfItem` as a
  `TypedDict`. Fields are Optional for a reason — STF data is
  irregular and fields-that-can-be-absent must be nullable.
- **Attempt records**: `src/sweeps/process_store.AttemptRecord` (process
  sweeps) and `src/sweeps/pdf_store.PdfAttemptRecord` (PDF sweeps) are the
  dataclasses written into the `.jsonl` files.
- **Ground-truth fixtures**: `tests/ground_truth/*.json` — five
  hand-validated cases that `scripts/validate_ground_truth.py`
  diff-checks against. Don't break these.

## Non-obvious implications

- **Cache is monotonic-by-length, not archival.** When OCR rewrites
  a `data/pdf/<sha1>.txt.gz` entry, the prior pypdf extract is
  lost. See `CLAUDE.md` § "Non-obvious gotchas". For an audit trail
  of which extractor produced what when, use the `pdfs.log.jsonl`
  written by `pdf_driver`-routed runs.
- **URL, not case, is the cache key.** Two cases that cite the same
  PDF URL share a cache entry. That's generally what you want (cites
  are deduplicated), but it means cache-per-case accounting requires
  walking `andamentos[].link` from each case.
- **`data/output/` contains both sample and production data.**
  Conventionally `data/output/sample/` is the curated testing corpus,
  `data/output/` (top-level) is production sweep output. The notebooks
  in `analysis/` default to reading both roots
  (`[Path("data/output"), Path("data/output/sample")]`) unless overridden.
- **This doc is the spatial map; four sibling docs cover the rest of the conceptual surface.**
  - [`docs/stf-portal.md`](stf-portal.md) — how the portal works (URL flow, auth triad, UTF-8, field→source map, DataJud dead-end).
  - [`docs/rate-limits.md`](rate-limits.md) — WAF behavior, validated sweep defaults, the robots.txt posture question.
  - [`docs/process-space.md`](process-space.md) — class sizes (HC / ADI / RE), density probes, ceiling refresh.
  - [`docs/performance.md`](performance.md) — HTTP vs Selenium numbers and why caching is the real lever.
  - [`docs/handoff.md`](handoff.md) — temporal view: what's in flight, blocked, next. Read this one first, handoff for what's current.
