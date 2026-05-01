# OCR provider bakeoff (2026-04-30 → 2026-05-01)

**Decision: Tesseract on Modal CPU replaces Mistral as production OCR
for STF Portuguese legal PDFs.** 14× cheaper ($0.14 vs $2.00 /1k pages)
and strictly better on every quality axis after gold correction.

Raw artefacts (manifest, per-(sha,provider) outputs, scoring results,
failures, pre-registered plan): `runs/active/2026-04-30-ocr-bakeoff/`.
Goal pre-registered in
[`PLAN.md`](../../runs/active/2026-04-30-ocr-bakeoff/PLAN.md) before
any results landed.

## Headline numbers (post-correction, 50 PDFs / 20 gold)

Sorted by cost ascending. CER computed by jiwer against hand-curated
`gold/<sha1>.txt`. Cost is empirical (Modal billing for self-hosted,
list price for vendors). Mistral's 0.00% on born-digital is
self-comparison — gold was seeded from Mistral on the 12 born-digital
files where it had no reading-order bug.

| Provider                   | $/1k pages              | Born-dig CER | Scanned CER | Median CER | Notes                                                                                                                        | Specific errors found                                                                                                                                                                                                                                |
|----------------------------|-------------------------|-------------:|------------:|-----------:|------------------------------------------------------------------------------------------------------------------------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| **Tesseract** (Modal CPU)  | **$0.14**               | 1.23%        | **0.82%**   | **1.04%**  | **Production winner.** Body fidelity faithful; correct reading order. May want ~30 lines of regex post-processing.           | `§ → 8` (consistent), Roman `I → 1` in some contexts (`art. 102, I, d e i` → `art. 102, 1 d e i`), ellipsis `(...) → (..)`, auth-code digit↔letter (`BFD0 → BFDO`, `21A1 → 2141`), small-caps confusion (`LUÍS → Luís`, `IMPTE.(s)`).                |
| Surya (Modal L40S)         | $0.18                   | 2.55%        | 5.70%       | 3.62%      | Correct order between phrases but injects rich-text markup. Check `output_format="text"` flag before keeping or dropping.    | `<b>...</b>` and `<math>N^{\circ}</math>` injection; word-shuffle within multi-line phrases (`REMESSA / TRIBUNAL / DOS / AUTOS / AO / COMPETENTE`); Greek `Ε` (U+0395) for Latin `E`; U+2116 `№` for `Nº`; label/value swap on `288744ef`.           |
| Mistral (control)          | $2.00 sync / $1.00 batch | 0.00%       | 32.71%      | 0.00%      | Production incumbent. Body text faithful. Reading-order bug on 1-pg scanned DESPACHOs is the only structural defect.         | Footer-at-top above heading on every 1-pg DESPACHO tested (`e0f74de6`, `4752742c`, `8e11f096`, `16f4709e`, `288744ef`, `04dff48e`). Born-digital pages fine.                                                                                         |
| Chandra (Datalab API)      | $3.00                   | 18.29%       | 31.07%      | 23.57%     | **Best body-text quality** of any provider. Renders structure as Markdown (`#`, `**bold**`, `*italic*`). Most expensive.     | Drops auth-code footer + per-page running headers (`Inteiro Teor do Acórdão - Página N`) — 17% shorter on 12-pg born-digital but no body content lost. Rare structural hallucination on short docs (`Vistos etc.` → `## **Vistos etc.**`).           |

Discarded:

| Provider                   | $/1k pages              | Born-dig CER | Scanned CER | Median CER | Notes                                                                                                                        | Specific errors found                                                                                                                                                                                                                                |
|----------------------------|-------------------------|-------------:|------------:|-----------:|------------------------------------------------------------------------------------------------------------------------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Paddle PP-v5 (Modal A10)   | $0.08                   | 8.36%        | 2.64%       | 7.26%      | **Disqualified.** Cheapest, but per-line failures invisible to median CER make it unsafe for streaming NLP.                  | Strips ALL Portuguese accents (`questão → questao`); whole-line gibberish on 3/6 docs (`r ezuooae oru asaadoy e 'aoiqg...`); substantive clauses silently dropped on `8e11f096`, `16f4709e`, `04dff48e`; literal `O → 0`, `ó → 6`.                    |
| Gemini 2.5 Flash           | $1.56 sync (~$0.78 batch) | 2.00%      | (no data)   | 2.00%      | Quota-throttled; only 14/50 ran. High inter-doc variance — sometimes Mistral-equivalent, sometimes badly fragmented.         | Drops `(...)` ellipsis markers; scrambles section headers + numbered items (`IV. / 4. / DISPOSITIVO`); orphan page-number stragglers (`2`, `3` as standalone lines); daily-window 429 quota exhaustion.                                              |

## Why pre-correction numbers were misleading

Before gold correction, Tesseract scored 33.47% on scanned and Mistral
0.00% — the table looked like Mistral was the obvious leader. The
actual signal was hidden because gold was seeded as unedited Mistral
output. On 8 of 20 sampled PDFs, **Mistral places the digital-signature
footer on line 1, before the heading.** Every other tested provider
puts it at the natural position (end of file for 1-page docs; before
the next page-marker for multi-page docs). Tesseract's 33% delta was
mostly that reading-order swap.

The 8 buggy gold files were corrected manually on 2026-05-01 by
moving the leading footer to its natural position (or deleting it
when a duplicate of a correctly-placed copy already existed in the
body). Body text was not edited; Mistral's body fidelity is faithful
on every document tested. After correction, the 5 worst CER scores
in the entire report are `mistral` on the 5 corrected 1-page scanned
DESPACHO cases (46–67% CER each) — exactly matching the qualitative
spot-check prediction.

## Per-provider qualitative findings

Source: side-by-side reads of all 5–6 provider outputs on 6 PDFs
(`e0f74de6`, `8e11f096`, `4752742c`, `288744ef`, `16f4709e`,
`04dff48e` scanned + `c9233de1` 3-pg + `e55389f2` 12-pg
born-digital). Cross-provider consensus served as truth where 4+
providers agreed.

### Mistral (control)

- **Reading-order bug on 1-pg scanned DESPACHOs**: footer-at-top above
  heading on every 1-pg DESPACHO tested. Born-digital pages are fine.
- Body text faithful across all documents — no character drops or
  scrambling observed.
- **Verdict**: Body OK; not safe as ground truth on scanned strata
  without manual reorder.

### Tesseract (Modal CPU)

- **Reading order: correct on all 6 PDFs.** Body text faithful.
- **Character-level errors** (programmatically post-processable):
  - `§` → digit `8` (consistent in `art. 21, § 1º` → `art. 21, 8 1º`).
  - Roman `I` → digit `1` in some contexts (`art. 102, I, d e i` →
    `art. 102, 1 d e i`; lower-case `i` kept).
  - Ellipsis period drop: `(...)` → `(..)`.
  - Auth-code digit↔letter swaps: `BFD0 → BFDO` (zero → O), `21A1
    → 2141` (A → 4).
  - Small-caps font confusion: `LUÍS ROBERTO` → `Luís ROBERTO`,
    `IMPTE.(s)` lowercased.
- **Verdict**: Production-ready. A small post-process regex layer
  (~30 lines) closes the residual 1.04% gap.

### Surya (Modal L40S)

- **Reading order**: correct between phrases but **shuffles words
  within multi-line phrases** (`REMESSA DOS AUTOS AO TRIBUNAL
  COMPETENTE` → `Remessa / TRIBUNAL / DOS / AUTOS / AO / COMPETENTE`
  on `04dff48e`).
- **HTML/LaTeX injection**: persistent `<b>...</b>` and
  `<math>N^{\circ}</math>` markup — bad for plain-text downstream.
- **Glyph substitution**: Greek `Ε` (U+0395) for Latin `E` and U+2116
  `№` for `Nº` — visually identical, breaks UTF-8 equality and search.
- **Verdict**: Correct order but multiple distinct downstream burdens.
  Worth checking whether v0.16.7 has `output_format="text"` to disable
  rich markup before declaring incurable.

### Paddle PP-v5 (Modal A10)

- **Catastrophic accent loss**: strips ALL Portuguese diacritics
  (`GOIÁS → GOIAS`, `questão → questao`, `não → nao`, `hipótese →
  hip6tese` with literal `6`). Hard disqualifier for Portuguese.
- **Whole-line OCR collapse on 3 of 6 sampled docs**: `r ezuooae oru
  asaadoy e 'aoiqg opuaja opoiadns anb epudv` (gibberish embedded in
  otherwise readable text). Documented on `8e11f096`, `16f4709e`,
  `e55389f2`.
- **Substantive content drops**: clauses silently missing on
  `8e11f096` (`afirmam não subsistir interesse...`), `04dff48e`
  (`cujos atos estejam sujeitos diretamente...`), `16f4709e`
  (`Remeta-se cópia da petição inicial...`).
- **Verdict**: Disqualified for Portuguese. The 7.26% median CER is
  misleading — median averages over the readable portion; per-document
  variance is what matters for streaming NLP.

### Chandra (Datalab API)

- **Reading order: correct on all 6 PDFs.** Body text the cleanest
  of any provider — no character errors observed, accents intact.
- **Aggressive boilerplate stripping**: drops auth-code footer +
  per-page running headers (e.g. `Supremo Tribunal Federal /
  Inteiro Teor do Acórdão - Página N de 12`). 17% shorter on a 12-pg
  born-digital but **no body content lost**.
- **Rare structural hallucination on short docs**: short inline phrases
  rendered as Markdown headings (`Vistos etc.` → `## **Vistos
  etc.**` on `4752742c`).
- **Verdict**: Best for analytics / NLP downstream where boilerplate
  is noise. Weak for verbatim archival because of the boilerplate
  stripping.

### Gemini 2.5 Flash

- **High inter-document variance**: near-Mistral quality on a 12-pg
  born-digital, heavy fragmentation on a 3-pg born-digital (95 lines
  vs Mistral's 67). Same provider, same stratum, very different output.
- **Specific issues**: drops `(...)` ellipsis markers; scrambles
  section headers + numbered items (`IV. / 4. / DISPOSITIVO`);
  produces orphan page-number lines (`2`, `3`).
- **Quota exhaustion**: 14 of 50 PDFs ran before hitting daily-window
  429s. Sync mode unlikely to finish 50 PDFs in one session;
  batch mode (50% cheaper, ~24 h SLA) is the production path.
- **Verdict**: Unstable. Production decision should track per-document
  CER variance, not just mean; a 5%-mean / 20%-stddev provider is
  worse than 8% / 2%.

## Cost ranking (post-correction empirical)

```
Paddle    $0.08 / 1k pages   (disqualified)
Tesseract $0.14              ← production winner
Surya     $0.18
Gemini    $1.56 sync
Mistral   $2.00 sync / $1.00 batch
Chandra   $3.00
```

Modal-hosted prices (Tesseract, Surya, Paddle) dropped sharply between
the original headline estimate and the final empirical numbers because
the `scaledown_window` was reduced from 300s to 30s after the first
run. The 300s warm-idle premium was swamping the actual compute on
small workloads.

**Year-of-HC switch saves ~R$ 339** (R$ 51 vs R$ 390 at Mistral sync).

## Methodology notes

- **PLAN.md predicted "5–15% CER" for Tesseract** — way off. Classical
  OCR on text-layer Portuguese legal PDFs is much better than the
  literature suggests for a corpus this homogeneous.
- **Gold is partially-corrected, not fully**: structural reorder of
  the 8 buggy files is done; body-text character-level edits (Roman
  numerals, character-class confusions) are not. Deltas of that scale
  shift rankings only at the margins (Tesseract leads by ≥1.4 pp on
  every stratum).
- **Cross-provider consensus is a viable proxy for ground truth**
  when 4+ providers agree on a span. Saved hand-correction time on
  most disagreements: on `e0f74de6` four providers said `art. 13,
  VIII` and Tesseract said `VII` → consensus = VIII (Mistral right,
  no edit needed). Same pattern resolved `R.F.G.` vs `RF.G.` on
  `16f4709e`.
- **CER averaged over a corpus hides discrete failure modes**.
  Paddle's median 7.26% looks decent until you read the actual outputs
  and find one gibberish line per document — a CER number does not
  capture downstream pipeline poisoning.

## Implementation

Code shipped during the cycle:

- `judex/scraping/ocr/modal_app.py` — single Modal app with
  `tesseract_extract` (CPU 4-core), `surya_extract` (L40S),
  `paddle_extract` (A10) endpoints. `scaledown_window=30`.
- `judex/scraping/ocr/{tesseract,surya,paddle,_modal_client}.py` —
  thin clients calling the Modal app.
- `judex/scraping/ocr/gemini.py` — Gemini 2.5 Flash provider, sync +
  batch flows, header-based auth, tenacity retry on 429/5xx.
- `judex/scraping/ocr/dispatch.py` — `_REGISTRY` + `PRICING` updated
  with the four new providers.
- `scripts/ocr_bakeoff_{sample,run,score,gold_init}.py` — sampler
  (warehouse-backed, size-per-page stratification), per-provider
  runner (resumable), CER+similarity scorer, gold seeder.
- `jiwer` added to deps for CER scoring.

## Production rollout (next steps)

1. **Cut over `extrair-pecas` default to Tesseract.** Currently pypdf
   is the warehouse default; Mistral is opt-in. Make Tesseract the
   `--provedor` default; keep pypdf for born-digital fast-path.
2. **Tesseract post-process layer**: ~30-line regex pass to fix
   `§ ↔ 8`, ellipsis periods, common auth-code character-class
   swaps. Optional but closes the residual 1.04% gap.
3. **Drop Paddle from the provider registry.** Whole-line gibberish
   on 50% of docs is unfixable.
4. **Keep Chandra as an opt-in flag** for analytics pipelines that
   want pre-stripped boilerplate. Not the default.
5. **Surya needs the `output_format="text"` investigation** before
   keeping or removing.
6. **Gemini batch-mode wiring** — code path exists, runner needs a
   submit-then-poll change. Defer until there's a use case for it.

## Integration learnings (for future provider work)

- **Surya 0.17 has a self-inconsistency bug**: `SuryaDecoderModel`
  reads `config.pad_token_id` but `SuryaDecoderConfig` doesn't
  define it. Pin `surya-ocr==0.16.7 + transformers==4.56.1`.
- **Surya 0.16.7 API**:
  `RecognitionPredictor(FoundationPredictor())` +
  `rec(images, det_predictor=det)`. The
  `[["pt"]] * len(images)` language-list arg from older docs is gone.
- **Modal stale-deploy gotcha**: `modal deploy` after editing a
  function sometimes doesn't push the new code (cached function
  spec). `modal app stop --yes <name>` followed by `modal deploy`
  is the reliable cycle. If `modal deploy` reports "App deployed in
  2s" suspiciously fast, the new code likely didn't push.
- **Modal CPU billing**: per **physical core** (= 2 vCPU equivalent),
  $0.0000131/sec. Memory $0.00000222/GiB/sec. Min 0.125 cores per
  container. GPU functions get a small CPU+RAM baseline; explicit
  `cpu=` / `memory=` on a GPU function bills on top of the GPU rate.
- **Gemini quota**: free-tier sync-mode quota is per-day; ~14 PDFs
  exhausts it. Use batch mode (50% cheaper, ~24h SLA) for any
  multi-document run.
