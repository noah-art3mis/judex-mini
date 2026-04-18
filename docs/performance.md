# Performance — HTTP vs Selenium, and where the real lever is

Measured performance of the scraper, the reasoning behind the
HTTP-only architecture, and a clear statement of what this does (and
doesn't) buy at scale.

See also:
- [`docs/stf-portal.md`](stf-portal.md) — per-tab latencies live there too.
- [`docs/rate-limits.md`](rate-limits.md) — the ceiling at scale.
- [`docs/data-layout.md`](data-layout.md) — cache locations.

## TL;DR

The scraper's slowness has **two** layers with very different fixes:

1. **Per-request Selenium overhead.** Browser startup + JS + click-wait dominates when you're not being throttled. ~5 s/item → ~1 s/item on a cold request via plain `requests`. Real, measurable.
2. **Server-side rate limiting.** STF's WAF throttles progressively over a sustained sweep. The HTTP client hits this ceiling same as Selenium does — it just burns through the budget faster. Under steady-state sweep load, client choice doesn't move the needle much. See [`rate-limits.md`](rate-limits.md).

**Practical implication**: HTTP is the right client for many reasons
(faster iteration, lower memory, simpler code, easier testing), but
the **primary production lever is caching**, not raw per-request
speed. Once a case's HTML is on disk, re-extraction is free — and
that's where development time actually lives.

## Measured: HTTP vs Selenium (AI 772309, cold)

From `scripts/bench_http_vs_selenium.py`:

| Path                          | Wall clock | Notes                                      |
|-------------------------------|-----------:|--------------------------------------------|
| Selenium (from `main.py`)     | 18.00 s    | includes ~13 s one-time driver startup     |
| Selenium steady-state         |  4.98 s    | `ProcessTimer` — excludes driver startup   |
| HTTP fresh (no cache)         |  0.87 s    | resolve incidente + detalhe + 9 tabs (‖8)  |
| HTTP cache hit                |  0.27 s    | still does the 302 incidente lookup        |
| Andamentos parse only         |  3.5 ms    | from cached fragment                       |

**~5.7× faster than Selenium steady-state** on a cold, unratelimited
request. Per-tab breakdown lives in [`stf-portal.md`](stf-portal.md#url-flow).

This number does **not** extrapolate to a full sweep. The WAF
ceiling is what dominates over 100+ consecutive requests; see
[`rate-limits.md`](rate-limits.md).

## Cold vs cache hit — the actual production lever

| Operation            | Cold     | Cache hit | Ratio |
|----------------------|---------:|----------:|------:|
| Full HTTP scrape     | 0.87 s   | 0.27 s    |  3.2× |
| Andamentos re-parse  | ~0 (from fragment) | 3.5 ms | — |
| PDF text (ADI 2820)  | ~12.9 s  | 0.18 s    | ~70× |

The HTML fragment cache (`data/html/<CLASSE>_<N>/*.html.gz`) is a
~60× speedup on re-scrapes of the same process. The URL-keyed PDF
text cache (`data/pdf/<sha1(url)>.txt.gz`) is a ~70× speedup on
re-reads of the same PDF. **Iterating on extractor code against a
cached corpus runs effectively at local-CPU speed**; the scraper
never has to talk to STF.

This is why CLAUDE.md insists the cache contracts are load-bearing
and why sweeps wipe-cache explicitly rather than by default.

## OCR pass (Unstructured hi_res)

Image-only scans in the andamentos PDFs (older decisões monocráticas
and acórdãos pre-2020 are frequently stamped scans, not text-born
PDFs) need OCR to be usable. `scripts/reextract_unstructured.py`
posts the PDF bytes to the Unstructured SaaS API at
`strategy=hi_res` with `languages=por`.

Measured wall cost from two runs:

| Run                                      | Docs | Wall/doc | API timeouts | Notes |
|------------------------------------------|-----:|---------:|-------------:|-------|
| `2026-04-17-famous-lawyers-ocr`           | 55 | ~23 s    | 0            | 34/55 improved (6.6× aggregate gain on improved) |
| `2026-04-17-top-volume-ocr` (narrow)      | 19 | ~18 s    | 1 (300 s)    | 13/19 improved on first pass; transients retried |

The 300 s `ReadTimeout` is the Unstructured API default and
documents the tail — occasional stuck OCR jobs that the generic
`http_error` classification catches. Not worth a specific retry
path; it'll clear if the same URL is attempted in a later run.

The **improvement signature** is consistent: pypdf returns
~2 000–5 000 chars (headers + stamps + stray running text) for a
scanned PDF; OCR at `hi_res` returns ~10 000–40 000 chars of body
text, a 4–10× per-doc gain. PGR manifestações tend to be text-born
and pypdf reads them cleanly — they don't benefit from OCR (and one
verify-pass showed OCR strictly shorter than pypdf on such a doc).

## Field coverage on the HTTP path

All ~27 fields the Selenium scraper emitted are reachable from the
same HTML fragments the browser eventually renders — we just fetch
them directly instead of letting jQuery do it. The field-to-source
map lives in [`stf-portal.md § Field → source map`](stf-portal.md#field--source-map).

Validated against `tests/ground_truth/*.json`:

| Fixture              | Wall  | Result                             |
|----------------------|------:|------------------------------------|
| ACO_2652             | 0.81s | 2 diffs (both non-bugs, see below) |
| ADI_2820_reread      | 0.76s | MATCH                              |
| AI_772309            | 0.48s | MATCH                              |
| MI_12                | 0.49s | MATCH                              |
| RE_1234567           | 0.51s | MATCH                              |

The two ACO 2652 diffs are **not scraper bugs**:

1. `assuntos` text drift — live site has `'... CADIN/SPC/SERASA/SIAFI/CAUC'`, fixture captured `'... CADIN'`. STF updated the assunto taxonomy since the fixture was recorded.
2. `pautas: []` vs `null` — fixture inconsistency. ACO has `null`; the other four have `[]`. Current HTTP path produces `[]`, matching 4/5 fixtures and the former Selenium behavior.

Run yourself: `PYTHONPATH=. uv run python scripts/validate_ground_truth.py`.

## Expected speedup table

Small = AI 772309–shaped (2 andamentos, 4 partes). Heavy = a case
with full docket depth.

| Approach                       | Per process (small) | Per process (heavy) | 100 processes | 1000 processes |
|--------------------------------|-------------:|-------------:|--------------:|---------------:|
| Selenium (measured baseline)   | 5 s          | ~20 s        | ~33 min       | ~5.5 h         |
| HTTP serial                    | ~2.5 s       | ~5 s         | ~8 min        | ~1.4 h         |
| HTTP, tabs parallel            | ~1.5 s       | ~2 s         | ~3 min        | ~33 min        |
| HTTP, tabs + processes ‖8      | ~0.2 s amort.| ~0.3 s amort.| ~25 s         | ~4 min         |

The **per-process speedup is larger on heavier cases**. Click-gated
tabs (`andamentos`, `peticoes`, `recursos`) are where Selenium pays
the `button_wait` penalty and where HTTP pays nothing. Small
processes show 2–3×; processes with full docket depth show 5–10×.

**These are upper bounds** — the WAF ceiling in
[`rate-limits.md`](rate-limits.md) means the "processes ‖8" row is
aspirational at sweep scale. Measured sweep pace at the validated
defaults (2 s throttle + retry-403) is **3.60 s/process**, which is
the "HTTP serial (small)" row — the parallelism has to be traded
off against block risk.

## What this does NOT fix

- **Server-side rate limiting.** More workers hit the ceiling faster, not past it. See [`rate-limits.md`](rate-limits.md).
- **PDF parsing cost.** `pypdf.PdfReader.extract_text(extraction_mode="layout")` and the Unstructured OCR path run at local-CPU / external-API speed. HTTP doesn't move that number.
- **Site ToS and courtesy.** Faster scraping without proper caching is the same load concentrated in time. The cache does the ethical work, not the client choice.

## What we intentionally didn't do

- **Playwright instead of Selenium.** Both drive a real browser; the floor cost (startup + full page render) is the same. Playwright buys maybe 1.5–2×, not the 10× we see from HTTP. If a browser fallback is ever needed, either works, and Selenium is already frozen in `deprecated/`.
- **IP rotation / UA spoofing.** Gray-area legally, brittle technically, and single-IP throughput at the validated defaults is already sufficient. See [`rate-limits.md § The unresolved policy question`](rate-limits.md#the-unresolved-policy-question--robotstxt).
- **Chase a bulk dataset.** STF is not on DataJud; Corte Aberta is aggregates-only; commercial aggregators are paid and inappropriate for research. Scraping the portal is the only path.
