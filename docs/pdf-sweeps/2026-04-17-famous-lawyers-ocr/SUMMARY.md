# Famous-lawyer HC — Unstructured hi_res OCR pass

**Status**: completed cleanly (55/55 candidates processed, 0 exits, 0 breaker trips).

**Date**: 2026-04-17 (commits `ef464cc` → `ca3ce83`).

**Script**: `scripts/reextract_unstructured.py` (inlined loop —
**does not route through `src/pdf_driver.run_pdf_sweep`**; see the
script's "Known gaps" docstring block). Consequence: no
`pdfs.state.json` / `pdfs.log.jsonl` / `requests.db` were produced by
this run; only this `run.log` (tee-captured stdout).

**Invocation**:

```bash
PYTHONPATH=. uv run python scripts/reextract_unstructured.py \
  --classe HC \
  --impte-contains "TORON,PIERPAOLO,PEDRO MACHADO DE ALMEIDA CASTRO,\
ARRUDA BOTELHO,MARCELO LEONARDO,NILO BATISTA,VILARDI,PODVAL,\
MUDROVITSCH,BADARO,DANIEL GERBER,TRACY JOSEPH REINALDET" \
  --doc-types "DECISÃO MONOCRÁTICA,INTEIRO TEOR DO ACÓRDÃO,MANIFESTAÇÃO DA PGR,DESPACHO" \
  --exclude-doc-types "DESPACHO" \
  --min-chars 5000 \
  --throttle-sleep 3.0 --api-sleep 1.0
```

(The invocation includes DESPACHO in `--doc-types` then excludes it
via `--exclude-doc-types` because that was the shape of the script at
the time — before the filter-helper refactor landed in `ca3ce83`.
Equivalent modern invocation: drop DESPACHO from `--doc-types`.)

## Headline

**34 / 55 improved (62 %)**. Total extracted-text across the
improved set went from **73 720 → 489 419 chars (6.6×)**. Zero
regressions; zero breaker trips; two transient WAF empty-body
downloads that the retry path did not catch (retry-403 only fires on
status 403, not on 200-with-empty-body).

| metric | value |
|---|---|
| target pool | 78 PDFs across 35 HCs |
| already ≥ 5 000 chars (skipped) | 23 |
| re-extraction candidates | **55** (1 with no cache entry) |
| improved | **34** (62 %) |
| unchanged | 19 (35 %) |
| failed | 2 (4 %) — both `not a PDF (first bytes: b'')` |
| total chars on improved docs | 73 720 → **489 419** (+415 699, 6.6×) |
| wall clock (approx) | ~21 min (13:09 → 13:30 local) |
| Unstructured strategy | `hi_res` (`por` language hint) |

## Per-doc-type breakdown

| doc_type | improved | unchanged | failed |
|---|---:|---:|---:|
| DECISÃO MONOCRÁTICA        | 19 | 10 | 2 |
| INTEIRO TEOR DO ACÓRDÃO    | 13 |  7 | 0 |
| MANIFESTAÇÃO DA PGR        |  2 |  2 | 0 |

Image-only failure is concentrated in the **monocrática** + **acórdão**
types, as expected — the cases that previously showed up as
"just header/footer" in pypdf output are now readable for ~65 % of
the pool.

## Top 10 improvements (by absolute gain)

| case | doc | old | new | Δ | ratio |
|---|---|---:|---:|---:|---:|
| HC 135041 | DECISÃO MONOCRÁTICA         |  4 919 | 42 916 | +37 997 | 8.7× |
| HC 149328 | INTEIRO TEOR DO ACÓRDÃO     |  3 871 | 40 448 | +36 577 | 10.4× |
| HC 135041 | DECISÃO MONOCRÁTICA (2nd)   |  4 823 | 36 383 | +31 560 | 7.5× |
| HC 158921 | INTEIRO TEOR DO ACÓRDÃO     |  3 667 | 29 712 | +26 045 | 8.1× |
| HC 188538 | INTEIRO TEOR DO ACÓRDÃO     |  3 219 | 27 376 | +24 157 | 8.5× |
| HC 230430 | INTEIRO TEOR DO ACÓRDÃO     |  2 176 | 18 930 | +16 754 | 8.7× |
| HC 188395 | DECISÃO MONOCRÁTICA         |  4 184 | 19 390 | +15 206 | 4.6× |
| HC 188540 | INTEIRO TEOR DO ACÓRDÃO     |  2 194 | 17 211 | +15 017 | 7.8× |
| HC 203209 | INTEIRO TEOR DO ACÓRDÃO     |  2 019 | 16 482 | +14 463 | 8.2× |
| HC 188538 | DECISÃO MONOCRÁTICA         |  4 184 | 18 522 | +14 338 | 4.4× |

Pattern: the big wins cluster around **3 000–5 000-char pypdf output
→ 15 000–45 000-char OCR output**. This is the signature of an
image-stamped acórdão/monocrática where pypdf's `extraction_mode="layout"`
retrieved page headers + signatures + some stray running text but
missed the body. OCR at `hi_res` (with Portuguese language hint)
recovers the body cleanly.

Noteworthy case-level outcomes:

- **HC 135041** (Pierpaolo Bottini): two decisões, both 8× expansion.
  Roughly 80 000 chars of new substantive text on a case the profile
  doc currently treats as metadata-only.
- **HC 149328** — 10.4× expansion, the largest ratio gain. Previously
  unreadable acórdão now accessible.
- **HC 230430** (Pedro Machado de Almeida Castro / Badaro): two
  acórdãos that were sub-2 500 chars each, now 15–19k each.

## Implications for the famous-lawyer interpretation

The prior `analysis/famous_lawyers_profile.md` (since removed as part
of the 2026-04-17 simplification pass) reported the substantive-text
corpus as **"30/108 readable, 78 image-only scans, 17/35 HCs
substantively readable."** That characterisation was always
pypdf-specific; after this OCR run it is *no longer the reality on
disk*. The corrected picture:

| claim in the old profile doc | reality after this OCR run |
|---|---|
| 78/108 are image-only scans | overcounted — conflated "short pypdf output" with "image-only". Of the 55 substantive-doc candidates OCR actually examined, 19 stayed short after `hi_res` OCR → those are *genuinely-short orders*, not image-only. Real image-only-or-broken cliff ≈ **34/78 (44 %)** of the substantive set. |
| 30/108 substantively readable | substantive set (no DESPACHO): `23 (already ≥ 5k chars) + 34 (OCR rescued) = ` **57/78 (73 %) readable**. |
| 17/35 HCs substantively readable | rises substantially; exact figure needs a fresh pass over the cache. |

If the profile doc is regenerated (from the notebook +
cache), the updated numbers above should be its starting point, and
the narrative claim "most cases are known only from metadata" should
be dropped entirely.

## Failures (retry later)

The two failures are both the same transient WAF empty-body signal:

| case | doc | URL hash | failure |
|---|---|---|---|
| HC 158921 | DECISÃO MONOCRÁTICA | [truncated] | `not a PDF (first bytes: b'')` |
| HC 202903 | DECISÃO MONOCRÁTICA | [truncated] | `not a PDF (first bytes: b'')` |

Both cases had a *second* document of the same type that succeeded on
the immediately-following request, consistent with a brief WAF
burst-block rather than a stale URL. Both are retry candidates with a
gentler throttle (`--throttle-sleep 5.0` on a second pass) or after a
~5-minute WAF cooldown. Left unresolved for now — the losses are not
load-bearing for the profile doc's arguments.

## Pacing notes

- `--throttle-sleep 3.0` (STF portal side, via `AdaptiveThrottle`
  min_delay floor) held against the WAF with only 2 transient empty
  bodies; no 403s.
- `--api-sleep 1.0` (Unstructured side, fixed `time.sleep`) is padding
  atop a naturally response-time-paced API. On a future run we can
  drop it to 0 without observable change.
- Mean pace: **~23 s/doc** wall, dominated by Unstructured's OCR
  response time on acórdão-sized PDFs.

## Artifacts

- `run.log` — tee-captured stdout of the run (55 per-doc lines +
  summary).
- `.cache/pdf/<sha1(url)>.txt.gz` — 34 entries were overwritten with
  OCR text. The pre-OCR extracts are not archived (see `CLAUDE.md` §
  "Non-obvious gotchas" for the monotonic-by-length cache
  implication).
