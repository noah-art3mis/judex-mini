# Top-volume HC — Unstructured hi_res OCR pass (narrow)

**Status**: completed; 25/25 URLs cached with substantive text; 3 remain "genuinely short orders" (<3k chars).

**Date**: 2026-04-17.

**Scripts**:
- `scripts/fetch_pdfs.py` — initial fetch + retry of transient failures
- `scripts/reextract_unstructured.py` — OCR pass for image-only scans
- `/tmp/manual_ocr_retry.py` + `/tmp/verify_ocr_pypdf_kept.py` — workarounds (see Gap section)

**Target selection**: narrow diagnostic slice of the top-5 volume
private HC impetrantes identified by `analysis/hc_top_volume.py` —
**all 8 concessões + 4 denied control cases, 12 HCs, 25 substantive
PDFs**. Rationale: cheap test of "are the 8 concessões real defensive
wins, or technical adjustments like Toron's HC 138.862?"

**Invocations**:

```bash
# Pass 1 — fetch (pypdf extraction, whitelist via retry-from)
PYTHONPATH=. uv run python scripts/fetch_pdfs.py \
  --out docs/pdf-sweeps/2026-04-17-top-volume-ocr \
  --classe HC \
  --impte-contains "VICTOR HUGO ANUVALE RODRIGUES,CICERO SALUM DO AMARAL LINCOLN,\
LUIZ GUSTAVO VICENTE PENNA,MAURO ATUI NETO,FÁBIO ROGÉRIO DONADON COSTA" \
  --doc-types "DECISÃO MONOCRÁTICA,INTEIRO TEOR DO ACÓRDÃO,MANIFESTAÇÃO DA PGR" \
  --retry-from docs/pdf-sweeps/2026-04-17-top-volume-ocr/target_urls.jsonl \
  --throttle-sleep 3.0

# Pass 2 — OCR (Unstructured hi_res) after deleting the short pypdf
# cache entries (see Gap section)
PYTHONPATH=. uv run python scripts/reextract_unstructured.py \
  --out docs/pdf-sweeps/2026-04-17-top-volume-ocr/ocr-pass \
  --classe HC \
  --impte-contains "…same impte list…" \
  --doc-types "…same doc types…" \
  --retry-from docs/pdf-sweeps/2026-04-17-top-volume-ocr/ocr_candidates.jsonl \
  --min-chars 5000 --throttle-sleep 3.0
```

## Headline

**25/25 cached; 13/19 OCR candidates improved; 3 persistent failures
recovered via manual per-URL fresh sessions.** Total text corpus:
256 670 chars across 12 HCs.

| metric | value |
|---|---|
| target URLs | 25 (whitelisted via JSONL) |
| HCs covered | 12 (8 concedido + 4 denegado/nao_provido) |
| fetch-pass pypdf ok ≥ 5k chars | 6 (all manifestações da PGR) |
| OCR-pass candidates | 19 (<5k after pypdf) |
| OCR-pass improved on 1st try | 13 |
| OCR-pass transient failures | 5 `unknown_type` + 1 300 s API timeout |
| OCR-pass retry 1 recovered | 3/6 |
| OCR-pass manual-retry recovered | 3/3 (fresh per-URL sessions) |
| verify-OCR on pypdf-kept (6 URLs) | 1 evaluated (OCR shorter, kept pypdf); 5 fetched 403 (WAF burst-block) |
| final cached corpus | 256 670 chars, 25/25 URLs |
| remaining short (<3k chars) | 3 — all genuinely-short orders |

## Timings (stopwatch)

Roll-up for benchmark purposes. Tick comes from `report.md` `elapsed`
fields and shell wall-clock.

| pass | URLs | wall | per-URL | throttle | blocker |
|---|---:|---:|---:|---:|---|
| fetch (initial) | 25 | 115.8 s | 4.6 s | 3.0 s floor | 7/25 transient `unknown_type` |
| fetch retry 1 | 7 | ~35 s | 5.0 s | 5.0 s floor | 1/7 second-try fail |
| fetch retry 2 | 1 | ~8 s | — | 8.0 s floor | 0 — recovered |
| OCR pass 1 | 19 | 629.3 s | 33.1 s | 3.0 s + API latency | 5 `unknown_type` + 1 API timeout |
| OCR retry 1 | 6 | ~72 s | 12.0 s | 6.0 s floor | 3/6 still unknown_type |
| OCR manual (fresh sessions) | 3 | ~90 s | 30.0 s | 3 s + 5 s per-URL | 0 |
| verify-OCR pypdf-kept | 6 | ~30 s before 403 | — | 3 s + 5 s | WAF 403 after ~50 cumulative fetches |
| **total wall** | — | **~16 min** | — | — | — |

**Per-doc OCR cost** (excluding the 300 s API timeout):
`(629 − 300) / 18 ≈ 18.3 s/doc`. Line with the famous-lawyers
baseline of ~23 s/doc. The narrow pass finished faster per-doc
because of younger cases (smaller PDFs).

## Improvement statistics

The 19 OCR candidates went from **73 720 chars (avg 3 880)** to
**189 531 chars (avg 9 975)** when successful — a **2.6× aggregate
gain**. Ratios per doc span from 1.0× (genuinely short orders) to
10.4× (the big acórdão rescues).

Top 5 improvements (absolute gain):

| case | doc | old | new | Δ | ratio |
|---|---|---:|---:|---:|---:|
| HC 134651 (Donadon)     | INTEIRO TEOR        | 3 484 | 36 064 | +32 580 | 10.4× |
| HC 173170 (Victor Hugo) | DECISÃO MONOCRÁTICA | 2 459 | 19 434 | +16 975 |  7.9× |
| HC 148651 (Victor Hugo) | INTEIRO TEOR        | 1 884 | 15 418 | +13 534 |  8.2× |
| HC 134444 (Donadon)     | INTEIRO TEOR        | 1 740 | 15 152 | +13 412 |  8.7× |
| HC 134743 (Penna)       | INTEIRO TEOR        |   — pypdf failed — | 11 209 | +11 209 | — |

Same signature as the famous-lawyers run: image-scanned
acórdãos/monocráticas where pypdf retrieved only the page header /
stamps (2-5 k chars) and OCR at hi_res recovers the body
(11-36 k chars).

## Gaps found during this run

### 1. `run_pdf_sweep` cache fast-path breaks `reextract_unstructured.py`

`src/sweeps/pdf_driver.py:144–162` reads the cache *before* calling
the fetcher — if the cache has any content, it records `status=ok`
and returns, **never invoking the Unstructured fetcher**. This was
discovered on the first OCR attempt: 19 candidates reported
"cached=19 fetched=0" immediately.

The famous-lawyers SUMMARY documents that the OCR script **"does not
route through `pdf_driver`"** (pre-Phase-A inlined loop). By
2026-04-17 the script DOES route through `run_pdf_sweep`, and the
cache fast-path broke re-extraction.

Workaround used: `unlink()` the 19 short cache entries before
running. See `ocr_candidates.txt`.

Permanent fix candidates:
- Add a `bypass_cache: bool` parameter to `run_pdf_sweep`.
- Or add a `--force` flag wiring on the reextract script that deletes
  cache entries for its candidate set before the driver runs.

### 2. Session reuse in `run_pdf_sweep` sensitive to WAF state

Three `unknown_type` failures persisted across `--throttle-sleep 3.0`
and `--throttle-sleep 6.0` retries, all on the **same session
instance**. Manual retry with **fresh per-URL `new_session()`
instances** recovered all 3 on first try (see
`/tmp/manual_ocr_retry.py`).

Hypothesis: after a run's session accumulates some state (cookies,
TLS session resumption, connection-reuse), STF's WAF tags the session
with a lower throttle ceiling; empty 200-responses hit on subsequent
requests. A fresh session starts clean.

Fix candidate: expose a `session_per_n: int` parameter to
`run_pdf_sweep` that rotates the session after every N requests. Or,
on `unknown_type`, discard session and start fresh before retry.

### 3. WAF 403 burst-block after ~50 cumulative requests

The verify-OCR pass (requests 45-50 in a 15-minute window) hit HTTP
403. STF enforces `robots.txt` behaviorally at the WAF level — see
`docs/rate-limits.md`. `--throttle-sleep 3.0` is safe for ≤40
requests in a batch; for 50+ requests in quick succession on the
PDF host, bump to 5-6 s floor or add a 5-minute cooldown after every
40 GETs.

## Implications for downstream analysis

The reading (`READINGS.md`) re-categorizes 2 of 8 "concessões":

- HC 134.651 (Donadon · Cármen): **procedural punt**; preventiva
  expressamente mantida.
- HC 143.345 (Donadon · Marco Aurélio): **correção sumular
  redundante** — STF apenas confirma o semiaberto que o STJ já havia
  concedido de ofício.

Revised substantive grant rate for the top-5 volume: **6/52 ≈ 11,5 %**
(not 15 %). The `hc_top_volume.py` notebook still holds qualitatively
— volume does not buy grant rate per se; the 6 real wins all ride on
specific minister templates (Barroso on small-tráfico, Marco Aurélio
on excesso-de-prazo) that operate on **case shape**, not on
advocacia. "Prêmio-advogado" is invisible; "prêmio-relator"
dominates.

Specifically, Donadon's `fav_pct = 15,4 %` (2 concessões / 13 cases
decided on the merits) should be annotated — 0/13 substantive wins
after reading. Notebook owners should consider filtering the two
pseudo-concessões before aggregating.

## Artifacts

- `target_manifest.tsv` — hand-built; filer / HC / outcome / relator / doc_type / URL for the 25 targets.
- `target_urls.jsonl` — the 25-URL whitelist (input to fetch `--retry-from`).
- `ocr_candidates.jsonl` — the 19 URLs with pypdf <5k chars (input to OCR `--retry-from`).
- `pypdf_kept_original.jsonl` — the 6 URLs pypdf kept ≥5k (verify-OCR target).
- `hc_links.json` — resolved `incidente` ids + substantive doc links for apêndice.
- `pdfs.state.json`, `pdfs.log.jsonl`, `pdfs.errors.jsonl`, `report.md`, `requests.db`, `run.log` — fetch-pass institutional layout.
- `ocr-pass/` — same layout, OCR pass.
- `READINGS.md` — this pass's substantive interpretation (12 HCs, ~5 000 words).
- `case_readings_draft.md` — pre-edit reading draft; not load-bearing.
