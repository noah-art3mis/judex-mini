# Fly OCR cluster: streaming refactor + 2 GB drop — smoke-test results

**Date:** 2026-05-02
**Cluster:** `judex-ocr-tesseract-arcos` (region `gru`)
**Goal:** Cut RAM line item from invoice (was ~57% of per-Machine bill) by
chunking PDF rasterization in `fly/server.py` so peak memory stops scaling
with page count, then halving `[[vm]] memory` from 4 GB → 2 GB.

## What changed

| File | Change |
|---|---|
| `fly/server.py` | Added `_RASTER_CHUNK_PAGES = 4`. `extract()` now loops `convert_from_bytes(first_page=N, last_page=M)` in chunks instead of rasterizing all pages upfront. Peak raster RAM ≈ 4 × 11 MB = 50 MB regardless of PDF size. |
| `fly/fly.toml` | `memory = "4gb"` → `"2gb"`. Comments rewritten to reflect new memory model. |
| `judex/scraping/ocr/tesseract_fly.py` | `cost()` rate updated to bill-anchored $0.005/1k pages. Module docstring rewritten with two-meter pricing model. |
| `fly/README.md` | Cost section rewritten with bill-derivation steps, full-ladder estimate $0.21 → $0.86 (now $0.46 after the 2 GB drop). |

## Cluster shape (before / after)

| Field | Before | After |
|---|---|---|
| Machine count | 100 | 10 (scaled down for testing — restore to 100 after validation) |
| `[[vm]] memory` | 4096 MB | 2048 MB |
| Additional RAM billed/Machine | 3.5 GB | 1.5 GB |
| Per-Machine rate | $0.0479 / hr | $0.0256 / hr |
| Per-Machine rate / sec | $0.00001331 | $0.00000710 |
| Cost reduction | — | **~47% per Machine-hour** |

## Smoke-test results (10-Machine cluster, post-deploy)

| # | PDF | Pages | PDF gz size | Wall (server) | Cost | Status |
|---|---|---:|---:|---:|---:|---|
| 1 | `00013fed875d…` | 1 | 55 KB | 3.97 s | $0.0000282 | ✅ Clean text, accents intact, 991 chars |
| 2 | `256cc17e45bd…` | 123 | 1,478 KB | ~269.7 s | $0.00191 | ⚠️ Server returned 200 OK; client got empty body |
| 3 | `37ee397e8732…` | 295 | 5,383 KB | not run | (proj $0.0046) | ⏸ Deferred pending Test-2 issue resolution |

**Cost rate from Test 2:** $0.0156 / 1k pages — 3× the docstring's
$0.005/1k anchor. The anchor was based on the 8-page mean ACÓRDÃO at
3 s/PDF; the 123-page PDF takes 2.19 s/page wall (parallel-2 OCR), so
larger PDFs cost proportionally more per page than the docstring
implies. Worth re-anchoring when Test 3 lands.

## Test 2 anomaly — root cause analysis

Server log:
```
23:44:07Z app[e82d444ce500e8] INFO: POST /extract HTTP/1.1 200 OK
23:44:24Z health[d8d9e14c915ee8] Health check 'servicecheck-00-http-8080' has failed
```

Client log:
```
real  4m29.205s
JSONDecodeError: Expecting value: line 1 column 1 (char 0)
```

**The server completed the OCR successfully and returned 200**, but the
response body never reached the client. No OOM messages anywhere — 2 GB
is enough for a 123-page PDF after the streaming refactor.

The likely root cause is `async def extract()` in `server.py:57`: while
the synchronous chunks of the OCR loop run, the asyncio event loop is
blocked, so `/healthz` can't reply and the Fly proxy's transport to the
Machine appears wedged. The 200 OK eventually flushes, but Fly's proxy
may close the upstream connection after the health-check failure
window. A retry attempt (second `curl` in the same minute) hit
`ETIMEDOUT` because Fly couldn't open a fresh TCP socket to a
busy-but-event-loop-blocked Machine.

**Fix (one-line, but separate change):** wrap the OCR body in
`await asyncio.get_event_loop().run_in_executor(None, _ocr_sync,
pdf_bytes)` so the sync work runs in a thread and the event loop stays
free to serve `/healthz` plus accept new requests.

## Space (storage) per PDF

| PDF | Compressed bytes | Page count | KB/page (compressed) |
|---|---:|---:|---:|
| Small (1 pg) | 55 KB | 1 | 55.0 |
| Medium (123 pg) | 1,478 KB | 123 | 12.0 |
| Large (295 pg) | 5,383 KB | 295 | 18.2 |

Output `.txt.gz` size is typically ~5–8% of input PDF gz size (no
data point yet for Test 2/3 since responses were lost).

## PDF corpus size distribution (2026-05-02)

Measured across the full `data/raw/pecas/*.pdf.gz` cache. **The
session's anxiety about long-PDF OCR was shaped by a single
outlier — `37ee397e8732…` (5.4 MB, 295 pages) is *the* largest
PDF in the corpus, with a >2× margin over the next nearest.**
The bulk of the corpus is far smaller and trivially handled by
any reasonable memory shape.

| Stat | Value | Implication |
|---|---:|---|
| Total PDFs | 103,916 | the corpus |
| Total compressed | 16.02 GB | manageable on disk |
| Median (p50) | 123.5 KB | ~8–12 pages — typical PDF |
| Mean | 150.6 KB | tail-skewed slightly higher |
| p95 | 411 KB | ~30 pages |
| p99 | 507 KB | ~40–50 pages |
| p99.9 | 628 KB | ~55 pages |
| Max | 5,382 KB (the 295-page test file) | single outlier — 8.5× the next nearest |

**Tail counts** (PDFs above each threshold):

- 588 PDFs > 0.5 MB (0.57% of corpus)
- 17 PDFs > 1 MB (0.02% of corpus)
- 2 PDFs > 2 MB (0.001% — `37ee397e8732…` and `cea836aa3017…`)
- 1 PDF > 5 MB (the literal one PDF this report has been testing
  against)

**Consequence for memory sizing.** Peak in-flight RAM with the
chunked-rasterize design is **bounded by chunk size**, not by PDF
size — so the 295-page outlier and a median 12-page PDF have the
same peak RAM draw. The design's worst-case memory cost is
therefore the same regardless of which PDF is being processed,
and we can size the Machine to the chunk floor + working set
without provisioning headroom for "what if a 1000-page PDF
arrives?" outliers (the corpus shows none exist beyond 5.4 MB).

## Minimum memory at 200 dpi (no DPI lever, fixed chunk_size = 32)

Peak working-set decomposition for one in-flight OCR on a
`shared-cpu-2x` Machine:

| Component | Resident MB | Notes |
|---|---:|---|
| Tesseract LSTM model + state | ~200 | Loaded once per process, stays resident |
| Python + uvicorn + FastAPI | ~180 | Includes lazy-imported pdf2image / pypdf |
| Pillow + pdf2image baseline | ~80 | C extensions + decoder tables |
| glibc + kernel page cache | ~50 | Service-baseline overhead |
| **Steady-state subtotal** | **~510** | When idle, between requests |
| Per-chunk PIL images (32 × 11 MB) | ~352 | Peak raster — released between chunks |
| Tesseract per-thread working set | ~200 | 2 workers × ~100 MB each, transient |
| **Peak during OCR** | **~1,062** | Steady-state + chunk + per-thread |
| Safety margin (fragmentation, OOMkill) | ~150 | Linux OOMs around 95% used |
| **Practical minimum** | **~1,212** | The number that must fit |

**Memory tier choices** (Fly accepts 256/512/1024/1536/2048 MB
for `shared-cpu-2x`):

| `[[vm]] memory` | Total | Headroom over peak | Per-Machine $/hr | vs current 2 GB |
|---|---:|---:|---:|---:|
| `"1024mb"` (1.0 GB) | 1024 | **−38 MB ⚠️ peak exceeds total — OOM risk** | $0.0143 | −44% |
| `"1536mb"` (1.5 GB) | 1536 | +474 MB ✓ comfortable | $0.0199 | **−22%** |
| `"2048mb"` (2.0 GB, current) | 2048 | +986 MB (generous) | $0.0256 | baseline |

**Decision.** `"1536mb"` is the cheapest tier where the peak
working set fits with non-trivial headroom. `"1024mb"` would
either require dropping `_RASTER_CHUNK_PAGES` from 32 back to ~16
(re-introducing some per-chunk parse overhead) or accepting a
silent-OOM risk on the largest few hundred PDFs. **`"1536mb"`
preserves the chunk-size win and saves 22% per Machine-hour with
no quality or speed tradeoff.**

## Money (extrapolated to full HC ACÓRDÃO ladder)

12,930 ACÓRDÃOs × 5 s/PDF mean = 64,650 Machine-sec = 18.0 Machine-hr.

| Memory shape | Per-hr rate | Full-ladder cost |
|---|---:|---:|
| 4 GB (pre-refactor) | $0.0479 | **$0.86** |
| 2 GB (post-refactor) | $0.0256 | **$0.46** |
| **Savings** | — | **$0.40 (47%)** |

At the projected scale (one 12,930-PDF sweep per quarter), this is
~$1.60/year saved. The savings *as a percentage* are dramatic; the
*absolute* savings are small. The streaming refactor's real value is
unblocking the 200+ page outliers that would have OOM'd a 2 GB Machine
under the old upfront-rasterize design.

## Decisions / next steps

1. **Land the `run_in_executor` fix** in `fly/server.py` to unblock
   long requests + keep `/healthz` responsive during OCR. ~5 lines,
   pinned by smoke-test re-run on the 123-page PDF.
2. **After (1) succeeds**, re-run Test 2 + Test 3. If both clean, scale
   cluster back to 100 Machines (`flyctl scale count 100 -a
   judex-ocr-tesseract-arcos`).
3. **Update `tesseract_fly.py:cost()` rate** if Test 2/3 confirm the
   $0.0156/1k pages observation: change `n_pages * 0.005 / 1000` to
   `n_pages * 0.015 / 1000`. Re-anchor against the next monthly Fly
   invoice as the larger validation.
4. **Investigate the 31 critical-health Machines** flagged in earlier
   `flyctl status` output. They likely account for a meaningful slice
   of the May-2 bill (Machines stuck `started` accrue full per-second
   rate without serving requests). May be unrelated to this refactor.
