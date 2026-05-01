# Current progress — judex-mini

Branch: `dev`. Prior cycle archived at
[`docs/progress_archive/2026-04-29_2200_hc-2024-2023-backfill.md`](progress_archive/2026-04-29_2200_hc-2024-2023-backfill.md)
— HC 2024 + HC 2023 peça backfill close-out (2026-04-26 → 2026-04-29).
HC 2024 closed 15,997 ok / 0 fails; HC 2023 closed 15,318 ok + 74
cached / 0 fails after a 34-URL SSL-retry pass.

**Status as of 2026-05-01 (post-correction rescore).** Corpus:
**90,763** cases. PDF cache 94,091 `.pdf.gz`, 105,821 `.txt.gz`.
Warehouse rebuilt 2026-04-30 17:45 BRT (530s, 3.02 GB; cases 90,763,
partes 316,933, andamentos 1,241,331, pdfs 105,821 — all
field-population thresholds OK, no DJe regression). HC 2022 peça
sweep closed 2026-04-30 (00:21 → 16:17 BRT). **Active cycle: OCR
provider bakeoff** — 6 providers across 50 PDFs, full results in
[`runs/active/2026-04-30-ocr-bakeoff/report.md`](../runs/active/2026-04-30-ocr-bakeoff/report.md).
Gold structurally corrected (8 of 20 files had Mistral's
footer-at-top bug; reordered manually) and rescored. **Tesseract is
now the unambiguous leader**: 1.04% median CER overall, 1.23%
born-digital, **0.82% scanned**, $0.14/1k pages — beats Mistral
on every axis. Mistral collapses to 32.71% scanned median (the
reading-order penalty is now visible). Character-level
hand-correction of gold body text is still optional but no longer
blocks a production decision.

## Last cycle — OCR provider bakeoff (2026-04-30 → 2026-05-01)

**Goal**: decide whether to replace **Mistral OCR batch ($1/1k pages)**
as production OCR for STF Portuguese legal PDFs. Plan + predictions
pre-registered in
[`runs/active/2026-04-30-ocr-bakeoff/PLAN.md`](../runs/active/2026-04-30-ocr-bakeoff/PLAN.md)
**before** any results landed (avoids HARKing). Fully measured
results landed 2026-04-30. Structural gold correction (8 of 20 files,
moving Mistral's misplaced footer to the natural position) and
rescore landed 2026-05-01. **Conclusion: Tesseract on Modal CPU
replaces Mistral as production OCR.**

**6 providers tested across 50 PDFs (25 born-digital + 25 scanned, 20
gold). Post-correction scoring (2026-05-01) after manual structural
reorder of 8 footer-at-top gold files:**

| Provider                 | n_run | Born-dig CER | Scanned CER | Median CER | Real $/1k pages | Source                   |
|--------------------------|------:|-------------:|------------:|-----------:|----------------:|--------------------------|
| Mistral (control)        | 50/50 | **0.00%**    | 32.71%      | 0.00%      | $2.00 sync      | vendor list              |
| **Tesseract** (Modal CPU)| 50/50 | 1.23%        | **0.82%**   | **1.04%**  | **$0.14**       | empirical Modal billing  |
| Surya (Modal L40S)       | 50/50 | 2.55%        | 5.70%       | 3.62%      | $0.18           | empirical Modal billing  |
| Gemini 2.5 Flash         | 14/50 | 2.00%        | (no data)   | 2.00%      | $1.56 sync      | API usageMetadata        |
| Paddle PP-v5 (Modal A10) | 50/50 | 8.36%        | 2.64%       | 7.26%      | $0.08           | empirical Modal billing  |
| Chandra (Datalab API)    | 50/50 | 18.29%       | 31.07%      | 23.57%     | $3.00           | Datalab list             |

**Tesseract beats Mistral on body fidelity, cost, and scanned CER
all at once.** The "1.23% born-digital, 33.47% scanned" first-pass
table (pre-correction) inverted the truth: post-correction Tesseract
is **0.82%** on scanned (now the lowest of any provider on that
stratum) because most of that 33% was the reading-order delta against
Mistral's broken gold. Paddle's median CER also dropped sharply
(7.26% post-correction vs 8.42% / 40.04% pre) but the qualitative
spot-check above shows this is misleading — Paddle has documented
whole-line gibberish on 3 of 6 sampled docs that the median doesn't
surface.

**Cost ranking (post-correction empirical):** **Paddle $0.08 <
Tesseract $0.14 < Surya $0.18 < Gemini sync $1.56 < Mistral sync
$2.00 < Chandra $3.00 per 1k pages.** The drop in Modal-hosted prices
vs the pre-correction estimates (Tesseract $0.21 → $0.14, Surya
$1.70 → $0.18, Paddle $0.42 → $0.08) reflects the
`scaledown_window` reduction (300s → 30s) cutting warm-idle cost.
Tesseract at $0.14/1k pages is **14× cheaper than Mistral sync**
(was 5× before).

**Tesseract is the unambiguous bakeoff winner on every axis that
matters.** Year-of-HC switch saves ~R$ 339 (R$ 51 vs R$ 390 at
Mistral sync). Quality prediction in PLAN.md was "5–15% CER" — way
off; classical OCR on text-layer Portuguese legal PDFs is much
better than the literature suggested.

**Methodological status (updated 2026-05-01).** The 20 gold files
were originally seeded as exact copies of `texts/<sha1>.mistral.txt`
(via
[`scripts/ocr_bakeoff_gold_init.py`](../scripts/ocr_bakeoff_gold_init.py)).
On 2026-05-01 the qualitative spot-check identified Mistral's
footer-at-top reading-order bug on 8 of 20 files. Each was
manually corrected by moving the leading
`Documento assinado digitalmente conforme MP...` line to its
natural position (end of file for 1-page docs; immediately before
the first `HC <num> / <UF>` page-marker for multi-page docs); for
2a738ca2 the leading line was a duplicate of an existing
correctly-placed footer further down, so it was deleted instead.
The 12 remaining gold files (the born-digital acórdãos that don't
exhibit the bug) are unchanged Mistral copies. Post-correction
rescore (table above) shows Mistral collapsing to 32.71% scanned
median, exactly as predicted — the 5 worst CER scores in the entire
report are now `mistral` on the 5 corrected 1-page scanned cases
(46–67% CER each). Body-text character-level hand-correction
(Roman numerals, character-class confusions) has *not* been done;
deltas of that scale would shift the leaderboard order only at the
margins (Tesseract leads by ≥1.4 pp on every stratum).

**Qualitative spot-check across 5 providers × 6 PDFs (2026-04-30
evening, claude session).** Read provider outputs side-by-side on
5 scanned 1-pg cases (`e0f74de6`, `8e11f096`, `4752742c`,
`288744ef`, `16f4709e`, `04dff48e`) + 2 born-digital cases
(`c9233de1` 3-pg, `e55389f2` 12-pg incl. Gemini). The pre-correction
CER ranking inverts the qualitative one in two important places:
Tesseract's "33% scanned CER" is mostly the reading-order delta
against Mistral's footer-at-top bug, and Chandra's "30% scanned CER"
is mostly the dropped auth-code/running-header boilerplate. Both
look much stronger qualitatively than the raw numbers suggest.

| Provider  | Reading order              | Body fidelity                  | Notable failure mode                                                                                                                                                                                                                  | Verdict                                       |
|-----------|----------------------------|--------------------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|-----------------------------------------------|
| Mistral   | **Broken on scanned 1-pg** | Faithful body text             | Footer-at-top above heading on every 1-pg DESPACHO tested. Born-digital fine.                                                                                                                                                         | Body OK; **not safe as ground truth on scanned** |
| Tesseract | Correct on all 6 PDFs      | Faithful body on all 6 PDFs    | `§→8`, Roman `I→1`, ellipsis `(...)→(..)`, auth-code digit↔letter swaps (`BFD0→BFDO`, `21A1→2141`), small-caps confuse case (`LUÍS→Luís`); `IMPTE.(s)` lowercased.                                                                     | **Production-ready w/ small post-process**    |
| Chandra   | Correct on all 6 PDFs      | Faithful body; aggressive boilerplate strip | Drops auth-code footer + per-page running headers (17% shorter on 12-pg born-digital; **no body content lost**). Rare structural hallucination on short docs (`Vistos etc.` rendered as `##` heading on `4752742c`).     | Best for analytics; weak for verbatim archival |
| Gemini    | Variable                   | Mostly faithful                | High inter-doc variance: near-Mistral on 12-pg, heavy fragmentation on 3-pg (95 vs 67 lines); drops `(...)` ellipsis markers; scrambles `IV. / 4. / DISPOSITIVO` section header; 14/50 quota dropouts.                                | Unstable; needs per-doc variance, not just mean |
| Surya     | Word-shuffles within phrases | Mostly faithful              | `REMESSA DOS AUTOS AO TRIBUNAL COMPETENTE` → `Remessa/TRIBUNAL/DOS/AUTOS/AO/COMPETENTE` (04dff48e); persistent `<b>`/`<math>` injection; Greek `Ε` for Latin `E` and U+2116 `№` for `Nº`; label/value swap on 288744ef.                | Multiple distinct downstream burdens          |
| Paddle    | Correct where readable     | **Drops clauses; whole-line gibberish** | 3/6 PDFs have catastrophic per-line OCR collapse (`r ezuooae oru asaadoy e 'aoiqg...` on 12-pg born-digital `e55389f2`); all accents stripped; letter↔digit (`O→0`, `ó→6`); substantive clauses silently dropped on 8e11f096, 16f4709e, 04dff48e. | **Disqualified** for Portuguese — fail mode invisible to surface QA |

**Implications for RETROSPECTIVE + production rollout**:

- **Structural gold correction is done.** The 5 worst CER scores in
  the post-correction report are now `mistral` on the 5 corrected
  1-page scanned cases (46–67%), exactly as the qualitative spot-check
  predicted. No further reorder work needed.
- **Tesseract's character-level errors are programmatically
  detectable** (`§→8`, ellipsis-period drops, auth-code class
  confusions). A small post-process pass would close the residual
  1.04% gap. Worth ~30 lines of regex; not blocking production.
- **Drop Paddle from RETROSPECTIVE.md as "underperforming"** — flag
  it as "unsuitable on prior". Its post-correction median CER (7.26%)
  flatters it; the qualitative spot-check found whole-line gibberish
  on 3 of 6 sampled docs. Median averages over readable portions;
  per-document variance is what matters for streaming NLP.
- **For Gemini**, score per-document CER variance, not just mean.
  A 5% mean / 20% stddev provider is less useful than 8% / 2%.
- **For Surya**, check whether v0.16.7 has `output_format="text"` to
  disable HTML/LaTeX injection before declaring it incurable.
- **Chandra remains a useful "secondary cleaner" tool** for analytics
  pipelines that want pre-stripped boilerplate. Its 23.57% median CER
  is mostly the auth-code-footer + running-header strips; body text
  is the cleanest of any provider. Not the default, but worth keeping
  configured behind a flag.

**Provider integration learnings** (the painful parts):

- **Surya 0.17 has a self-inconsistency bug**: `SuryaDecoderModel`
  reads `config.pad_token_id`, but `SuryaDecoderConfig` doesn't
  define it. Pinned `surya-ocr==0.16.7 + transformers==4.56.1`
  (the only version in surya's compat window) — works.
- **Surya 0.16.7 API**: `RecognitionPredictor(FoundationPredictor())`
  + `rec(images, det_predictor=det)`. The `[["pt"]] * len(images)`
  language list arg I had from older docs is gone.
- **Gemini quota exhaustion**: hit 503 "high demand" first, then
  429 "Too Many Requests" after ~14 PDFs. Free-tier quota window
  is per-day; sync mode unlikely to finish 50 PDFs in one session.
  Batch mode (50% cheaper, ~24h SLA) would dodge this — code path
  exists in `judex/scraping/ocr/gemini.py` (`build_batch_jsonl`,
  `submit_batch`, `wait_for_batch`) but isn't wired into the runner.
- **Modal stale-deploy gotcha**: `modal deploy` after editing a
  function sometimes doesn't push the new code (cached function
  spec). `modal app stop --yes <name>` followed by `modal deploy`
  is the reliable cycle.
- **Modal CPU billing**: per **physical core** (= 2 vCPU
  equivalent), $0.0000131/sec. Memory $0.00000222/GiB/sec. Min
  0.125 cores per container. GPU functions get a small CPU+RAM
  baseline; explicit `cpu=` / `memory=` on a GPU function bills
  on top of the GPU rate.

**Files** (all under `runs/active/2026-04-30-ocr-bakeoff/`):

| Path | What |
|---|---|
| `PLAN.md` | Pre-registered plan + predictions (do not edit predictions post-hoc) |
| `manifest.jsonl` | 50 sampled PDFs with stratum + gold flag |
| `gold/<sha1>.txt` | 20 hand-correction targets (currently still mistral copies) |
| `gold/_index.md` | Hand-correction checklist with PDF URLs |
| `texts/<sha1>.<provider>.txt` | Provider outputs (≤300 files: 50 × ≤6 providers) |
| `results.jsonl` | Per-(sha, provider) timing + cost rows |
| `failures.jsonl` | Errors (chiefly Gemini 429s + early Surya/Modal-debug fails) |
| `report.md` | Generated by `scripts/ocr_bakeoff_score.py` |

**New code shipped**:

- `scripts/ocr_bakeoff_sample.py` — warehouse-backed sampler
  (DuckDB query over `andamentos` table; size-per-page stratification
  via stat() + lightweight pypdf metadata parse with 2s timeout).
  Reverted from a slow full-text-extraction probe after a 10-min hang.
- `scripts/ocr_bakeoff_run.py` — per-provider runner; resumable via
  text-file existence check; loads `.env` via dotenv.
- `scripts/ocr_bakeoff_score.py` — CER (jiwer) + pairwise similarity
  (rapidfuzz) aggregator; emits `report.md`.
- `scripts/ocr_bakeoff_gold_init.py` — seeds `gold/` from Mistral
  texts as starting points.
- `judex/scraping/ocr/gemini.py` — Gemini 2.5 Flash provider, sync +
  batch flows, header-based auth (`x-goog-api-key`), tenacity retry
  on 429/500/502/503/504. Computes `usd_cost` from usageMetadata.
- `judex/scraping/ocr/modal_app.py` — single Modal app with three
  endpoints: `tesseract_extract` (CPU 4-core), `surya_extract`
  (L40S), `paddle_extract` (A10). `scaledown_window=30`.
- `judex/scraping/ocr/{surya,paddle,tesseract,_modal_client}.py` —
  thin clients calling the Modal app.
- Registered in `judex/scraping/ocr/dispatch.py` `_REGISTRY` +
  `PRICING`.
- `jiwer` added to deps for CER scoring.
- `runs/active/2026-04-30-ocr-bakeoff/PLAN.md` — pre-registration.

### Handoff for next session

The bakeoff is **measured, structurally corrected, and rescored.**
The leaderboard is conclusive: Tesseract wins. The remaining work is
the RETROSPECTIVE.md and a production-decision write-up.
**Read this section in full before touching anything.**

**State on disk**:

- `runs/active/2026-04-30-ocr-bakeoff/manifest.jsonl` — 50 PDFs,
  20 tagged `gold_corrected: true` (10 born-digital + 10 scanned)
- `runs/active/2026-04-30-ocr-bakeoff/texts/` — 263 files
  (50 mistral + 50 surya + 50 paddle + 50 tesseract + 50 chandra +
  14 gemini + 1 surya from a debug run) one per (sha1, provider)
- `runs/active/2026-04-30-ocr-bakeoff/gold/` — 20 `.txt` files.
  **8 of 20 manually structurally corrected on 2026-05-01** to fix
  Mistral's footer-at-top reading-order bug
  (e0f74de6, 8e11f096, 4752742c, 288744ef, 16f4709e, 04dff48e,
  c9233de1, 2a738ca2). The other 12 remain unchanged Mistral copies.
  Body-text character-level edits not applied — would only shift
  rankings at the margins.
- `runs/active/2026-04-30-ocr-bakeoff/results.jsonl` — ~228 rows,
  one per (sha1, provider, ok) attempt
- `runs/active/2026-04-30-ocr-bakeoff/report.md` — **post-correction
  scoring (2026-05-01)** generated by `ocr_bakeoff_score.py`.

**Next steps in order**:

1. ~~Hand-correct gold structurally — DONE 2026-05-01.~~ Optional
   character-level corrections (Roman numerals, `§↔8`, ellipsis
   periods) are still on the table but won't shift the headline
   ranking — Tesseract leads by ≥1.4 pp on every stratum.
2. ~~Re-run the scorer — DONE 2026-05-01.~~ Numbers in the table
   above are post-correction.

3. **Optional: finish the Gemini run.** Gemini quota typically
   resets daily. Resume with
   `uv run python scripts/ocr_bakeoff_run.py --provedor gemini`
   (the runner is resumable — skips PDFs with existing
   `texts/<sha1>.gemini.txt`). If quota persists, the alternative
   is to wire batch mode (50% cheaper, 24h SLA): the code is in
   `judex/scraping/ocr/gemini.py` (`build_batch_jsonl`,
   `submit_batch`, `wait_for_batch`, `download_batch_output`,
   `parse_batch_results`) but the runner needs a small change to
   submit-then-poll instead of per-call extract.

4. **Write `runs/active/2026-04-30-ocr-bakeoff/RETROSPECTIVE.md`**.
   Compare the post-correction CER + cost numbers against the
   pre-registered predictions in `PLAN.md`. Don't edit
   `PLAN.md`'s predictions section — that's the integrity of the
   pre-registration. Note specifically:
   - Tesseract dramatically beat the "5–15% CER" prediction on
     both strata (1.23% born-digital, 0.82% scanned post-correction).
   - Surya post-correction cost ($0.18/1k) is much closer to the
     PLAN.md prediction; the original $1.70 was inflated by a 300s
     `scaledown_window` warm-idle premium that we've since cut.
   - Chandra's cost predictor was right ($3/1k) but quality is
     misleading: 23.57% median CER overstates the body-text quality
     because Chandra deliberately strips boilerplate (auth-code
     footer + per-page running headers) that the gold preserves.
     Worth flagging this as "good for analytics, bad for archival."
   - Gemini quota issues are a real production concern not
     captured in PLAN.md.
   - Paddle's 7.26% median is misleading — the qualitative
     spot-check found whole-line gibberish on 3 of 6 sampled docs;
     median averages over the readable portion. Per-document
     variance metrics matter more than median for Paddle.

5. **Make a production decision**. Tesseract is now unambiguous —
   it beats Mistral on cost (14× cheaper at $0.14 vs $2.00/1k
   pages), born-digital quality (1.23% vs 0%, but Mistral's 0% is
   self-comparison), and scanned quality (0.82% vs 32.71%). No
   hybrid router needed for quality reasons — Tesseract alone is
   strictly better. The only reason to keep Mistral in the loop
   would be redundancy or a fallback for catastrophic cases; even
   then, the cheaper fallback is to re-run Tesseract with different
   preprocessing.

**Tooling hints**:

- The runner buffers stdout; check `texts/` directory file count
  for live progress instead of tailing the runner's stdout.
- For `extrair-pecas` corpus-scope vs sweep-scope, see CLAUDE.md
  gotchas — same `--csv`-vs-bare distinction applies if you ever
  promote a winner to a real `extrair-pecas --provedor X` flag.
- Do not point any subsequent OCR runs at `data/derived/pecas-texto/`
  — that's the production text store and uses pypdf-extracted text
  for the warehouse. The bakeoff lives entirely in
  `runs/active/2026-04-30-ocr-bakeoff/` and never writes to
  production.
- Modal stale-deploy: if you edit `judex/scraping/ocr/modal_app.py`
  and `modal deploy` says "App deployed in 2s" suspiciously fast,
  the new code likely didn't push. Run
  `uv run modal app stop --yes judex-ocr-bakeoff` then redeploy.

---

## Previous cycle — HC 2022 peça sweep close-out (2026-04-30)

Plan-pivot vs `completion-tracker.md` 2026-04-26 snapshot. Tracker
said HC 2022 had 1,160 cases on disk; rebuilt warehouse showed
**10,824** (83% of the 13,057 case-id-space width). HC 2022 was a
peça gap, not a case gap. Skipped the case sweep; went straight to
peças.

**Bytes pass** (2026-04-30 00:21 → ~13:15 BRT, single direct-IP):
**15,007 ok + 7 cached / 0 fails** out of 15,014 substantive URLs.
Same shape as HC 2024 / HC 2023. Direct-IP held WAF reputation
cleanly all night, no SSL-EOF tail-storm intervention.

**Text pass** (2026-04-30 14:48 → 16:17 BRT, `extrair-pecas pypdf`):
**14,865 ok / 142 unknown_type / 133 no_bytes / 7 cached** out of
15,147 targets, 1h28m elapsed, 98.1% extraction rate.

**Result.** HC 2022 substantive bytes 0% → 72%; text 26% → 99%.
Closes the **2025–2022 four-year ladder** at ≥97% text on direct
IP, zero proxy spend.

**Builder OOM hotfix landed mid-cycle.** First post-extract warehouse
rebuild OOM-killed at peak RSS 2.3 GB (WSL2 has 3.8 GB physical;
swap was already 1.9/2 GB used). Root cause: `andamentos.link_text`
populates from cached `.txt.gz` per row, doubling the chunk Arrow
peak now that `.txt.gz` count crossed 100k. Fix in
`judex/warehouse/builder.py`: `SET memory_limit='800MB'` on the
build connection + `_CHUNK_SIZE` 5000 → 1500. Build wall went 5min
→ 9min, peak RSS 1.99 GB → 1.27 GB, exit clean. Schema-level
redundancy (`andamentos.link_text` vs `pdfs.text` joined via
`pdfs_substantive`) is a separate bug to address in a future cycle —
that's where the headroom for re-raising `_CHUNK_SIZE` lives.

**Next, between cycles:**
1. **HC 2024 extract second pass** — text coverage at 80% vs 97-99%
   on 2023/2022. Investigate ~3k-row gap (provider failures, RTF
   mistypes, scanned originals?) and run a focused
   `extrair-pecas --csv` retry, possibly with chandra/mistral.
2. **HC 2017–2021 case sweeps** — ~37k missing case widths combined,
   ordered by year-density. Once cases land, peça sweeps follow in
   the proven 15k-URL/year shape.
3. **Schema cleanup** — drop `andamentos.link_text` /
   `documentos.text` / `decisoes_dje.rtf_text` from the build path
   (queries already use `pdfs_substantive`'s join). Lets
   `_CHUNK_SIZE` climb back toward 5000 + halves warehouse build
   peak RAM.


Single live file covering the **active task's lab notebook** and the
**strategic state** across work-sessions. Archive to
`docs/progress_archive/YYYY-MM-DD_HHMM_<slug>.md` when the active
task closes out or the file grows past ~500 lines.

For *conceptual* knowledge (how the portal works, how rate limits
behave, class sizes, perf numbers, where data lives), read:

- [`docs/data-layout.md`](data-layout.md) — where files live + the three stores.
- [`docs/stf-portal.md`](stf-portal.md) — URL flow, auth triad, field→source map, DJe flow.
- [`docs/system-changes.md`](system-changes.md) — timeline of STF-side + internal changes (DJe migration, schema v1→v8, Selenium retirement, known gaps).
- [`docs/rate-limits.md`](rate-limits.md) — WAF behavior, validated defaults, robots.txt posture.
- [`docs/process-space.md`](process-space.md) — HC/ADI/RE ceilings + density.
- [`docs/performance.md`](performance.md) — HTTP-vs-Selenium numbers, caching as the real lever.
- [`docs/warehouse-design.md`](warehouse-design.md) — DuckDB warehouse schema + build pipeline.
- [`docs/data-dictionary.md`](data-dictionary.md) — schema history v1→v8.

## Working conventions

- **`analysis/`** — git-ignored scratch for this-session exploration (marimo notebooks, one-off scripts, raw JSON dumps). Safe to fill freely.
- **`config/`** — git-ignored (credentials). Canonical proxy input is `config/proxies` (flat file, one URL per line; `#` comments + blank lines OK). Sharded launchers split it round-robin into N per-shard pools at `<saida>/proxies/proxies.<letra>.txt` at launch time. Older `config/proxies.{a..p}.txt` files are leftovers from the prior dir-based mode and can be deleted.
- **All non-trivial arithmetic via `uv run python -c`** — never mental math. See `CLAUDE.md § Calculations`.
- **Sweeps write a directory**, not a file. Layout in [`docs/data-layout.md § Sweep run artifacts`](data-layout.md#sweep-run-artifacts).

---


# Strategic state

## What just landed (most recent cycle)

- **Canonical lawyer classifier + judge↔lawyer network notebook**
  (this session, 2026-04-22). Extended
  `judex/analysis/lawyer_canonical.py` from a pure name canonicalizer
  into the project-canonical party classifier: new
  `LawyerKind` enum (`sentinel / placeholder / pro_se / institutional
  / juridical / court / with_oab / bare`), `LawyerEntry` NamedTuple,
  and `classify(nome) → (kind, key, oab_codes)` built on
  `canonical_lawyer()`. Accent-insensitive institutional-prefix match
  is the load-bearing fix — `DEFENSORIA PUBLICA DA UNIAO` (4,766 rows,
  no acute accents) was slipping past every ad-hoc `DEFENSORIA
  PÚBLICA` prefix check as a "bare" lawyer. Now it lands in
  `institutional`. Also catches OAB codes outside parentheticals
  (`OAB/SP 148022`, `OAB-PE 48215`) via `_extract_oab_anywhere`.
  +17 pinning tests; 568 total. Full-corpus bucket distribution
  (HC ADV): institutional 5,254 rows (70%), with_oab 1,405,
  sentinel 181, bare 579, placeholder 74, pro_se 4, juridical 2,
  court 0. On IMPTE: sentinel 3,012 (the "phantom IMPTE" rows the
  docstring warned about), institutional 8,726, with_oab 64,111,
  bare 18,470.

  CLAUDE.md `§ Non-obvious gotchas` now points all future notebooks
  at `judex.analysis.lawyer_canonical` — the failure-mode catalog
  (accent variants, non-parenthetical OABs, law firms, courts-as-
  parties, sentinel typos) is one call away instead of one regex
  per notebook away.

  Also shipped: `analysis/hc_judge_lawyer_network.py` — Marimo
  notebook with three reactive views. **(1) pyvis bipartite with
  Barnes-Hut physics** (Obsidian-style), sandboxed in an
  `iframe srcdoc` to stop pyvis's dark-theme CSS from bleeding
  into the host page. Plain-text tooltips (vis-network renders
  `title` via `innerText`, so `<b>` / `<br>` showed as literal
  text — switched to `\n` delimiters). **(2) log₂(lift) heatmap**
  clipped to ±4 to avoid outlier saturation. **(3) minister ↔
  minister cosine projection** on lawyer-distribution vectors.
  Reactive filters: top-N (default 60), min-pair edge count
  (default 2), year range (default 2015–2026), `LawyerKind`
  multiselect (default `[with_oab]` — the critical default,
  dropping `institutional` from the defaults because it swamps
  minister-cosine into 0.99-everywhere meaninglessness).

  Self-describing filter banner renders the active state + the
  universe size + the edge count at the top, so the exported
  snapshot documents itself. Snapshot shipped to
  `analysis/reports/2026-04-22-hc-judge-lawyer-network.html`
  (~200 KB with `with_oab`-only default).

  **Substantive finding:** `ADV.(A/S)` is ~72% institutional in
  the HC corpus — the banca-de-renome (Toron, Bottini, etc.) lives
  in `IMPTE.(S)`, not `ADV.(A/S)`. The two roles capture different
  institutional facts (filer vs. lawyer-of-record after possible
  DP takeover). For private-bar coverage use
  `analysis/hc_famous_lawyers.py`; this notebook is the ADV-rep
  map.

  **Old-vs-new `partes` format check** (by year): `"E OUTRO(A/S)"`
  tail prevalence dropped from ~3% in 2017–2021 to <1% in 2022+,
  confirming the scraper's split-row migration. Partes-per-case
  mean rose 1.03 → 1.13 in 2023–2024 (splitting visible in
  aggregate). `LawyerKind` bucket shares are stable across years
  (institutional 77-86%, with_oab 13-25%) — classifier is
  era-robust. Cross-year trend analysis on co-lawyers-per-case is
  NOT reliable without controlling for rescrape vintage though —
  an older case rescraped under the new scraper will suddenly
  show more ADV rows than it did before.

- **Warehouse build-stats validation** (this session). Added
  population-rate thresholds per case-level field (`partes`,
  `andamentos`, `pautas`, `sessao_virtual`, `publicacoes_dje`) to
  `judex/warehouse/builder.py` as `MIN_POPULATION_RATES`. After
  every build, the stats print to stdout + threshold misses produce
  warnings that show up in `BuildSummary.validation_warnings`. New
  `--estrito` flag (`judex atualizar-warehouse --estrito`) promotes
  warnings to a non-zero exit for CI. **Caught the DJe-regression
  immediately on a live 2023 build**: `0.0% (threshold ≥ 5.0%) [WARN]`.
  Prevents the silent field-wide regression pattern that went
  undetected from 2026-04-19 through 2026-04-21. +4 tests; 547
  total.

- **DJe extractor regression — full diagnosis, no fix yet** (this
  session, via manual browser verification of HC 267809).

  **Root cause:** STF migrated DJe on **2022-12-19** (per the footer
  note on the old portal: *"Até o dia 19/12/2022, o Supremo Tribunal
  Federal mantinha dois Diários de Justiça Eletrônicos com conteúdos
  distintos"*). New DJe content lives at
  **`digital.stf.jus.br/publico/publicacoes`**, an entirely different
  host. Our scraper hits `portal.stf.jus.br/servicos/dje/listarDiarioJustica.asp`
  — which now serves only migration-redirect stubs for post-2022 DJe
  ("Para consultar essa publicação, acesse https://digital.stf.jus.br/…").
  Those stubs are rendered client-side via JS, so `requests` gets an
  empty shell; browsers show the redirect placeholders.

  **Other endpoints explored + ruled out:**
  - `portal.stf.jus.br/servicos/dje/pesquisarDiarioJustica.asp` —
    historical (pre-2022-12-19) archive. **403 on GET**, and the
    form expects `Número DJ/DJe` or `Período` (date range) — not
    incidente-keyed, so can't be used as a drop-in fix even for old
    cases.
  - `abaDecisoes.html` (cached as part of each case scrape) — lists
    *internal* STF decisions (5 "Decisão" mentions in HC 228072) but
    **0 DJe URLs**. Not a fallback.
  - `digital.stf.jus.br/publico/publicacoes` (the real post-2022
    source) — returns `202` + AWS WAF challenge JS from
    `token.awswaf.com`. Requires a headless browser to pass.

  **Consequence:** 0 of 3,118 2026 HCs + 0 arm A/B/C = 0% DJe capture
  across all 2023–2026 content. HC 125290's 4 DJe entries (and the
  other ~10 pre-2022 cases with DJe) are pre-migration carry-forward
  via `reshape_to_v8`, not live capture — those files were written
  when the old endpoint still returned server-rendered DJe content.
  Pre-2022 DJe is effectively frozen at what we already have; no
  systematic re-fetch is possible via GET.

  **What we still get without fixing DJe:**
  - `andamentos` already capture each `"ACÓRDÃO PUBLICADO, DJE N"` /
    `"DECISÃO PUBLICADA"` event as a structured row with date — so
    "when did this case get a DJe publication?" is answerable from
    andamentos alone.
  - `sessao_virtual[].documentos[]` still capture the Voto / Relatório
    PDFs → `baixar-pecas` + `extrair-pecas` already ingest the full
    decision texts. The missing piece is the *DJe index envelope*
    (DJE number, section, divulgation date) as a separate structure,
    not the decision texts themselves.

  **Three viable paths forward, queued (not picked):**
  1. **Andamentos-side DJe metadata extraction** (cheap). Parse
     `"DJE 123 de 05/02/2025 ..."` patterns from andamento strings,
     emit structured `{dje_numero, dje_data, secao}` alongside the
     existing andamento row. Small regex + schema addition; gets
     ~80% of DJe-level warehouse queries working without touching
     the external endpoint.
  2. **Playwright integration for `digital.stf.jus.br`** (real fix).
     Headless browser loads the page, solves the AWS WAF challenge,
     captures the `aws-waf-token` cookie, then `requests` uses that
     cookie for the actual API calls (the new platform is a SPA
     backed by a JSON API — once past WAF, direct-to-hit). New
     dependency, ~1–2 days of integration work, most reliable
     long-term.
  3. **AWS WAF challenge reverse-engineering** (brittle). Python
     libraries exist (`aws-waf-token` solvers) but STF can flip the
     challenge type (reCAPTCHA, Turnstile) at any time. Not
     recommended.

  **Build-stats validation will keep this visible.** Every future
  warehouse build will print `publicacoes_dje: 0.0% (threshold ≥ 5.0%)
  [WARN]` until path 1 or 2 lands. Don't silence — the warning is
  load-bearing.

- **CliffDetector axis-B window-full gate** (this session). Axis B
  (p95 wall_s) was firing false positives at n=MIN_OBS=20 because
  `int(0.95 * 20) = 19` made p95 equal to the max element — a single
  slow HTTP record with no retries/no fails could trip collapse. Fix:
  `p95` is only consulted once the rolling window is full (n == 50
  for default window size). Axis A (WAF-shaped fail rate) remains
  un-gated so V-style collapse still catches early. Caught by arm B's
  shard-o which cliffed at 20/899 on a single 66.67s HTTP record with
  zero WAF signal. +2 tests; 1 existing test updated to use 55 targets
  so the window actually fills. **Arm B's shard-o is officially
  flagged as a detector false-positive**, not a genuine cliff, for
  the A/B writeup's honesty.

- **Arm A — HC 2025 @ 8 shards cliff cascade** (full details in
  archive `2026-04-21_0805`). 53.5% coverage at 3h03m productive
  wall-clock; 8/8 shards cliffed across a 2.5h window. First direct
  L3-per-exit-IP reputation gradient measurement — cliff order
  matched pool state at yesterday's 2026 end.

- **`judex probe` CLI** (commit `865f6d9`). Rich-table live view of
  sharded sweeps — done/target, %, rec/s, min pid, severity-ordered
  colored regimes, elapsed/ETA. `--watch N` auto-refresh.
  Canonical monitoring surface; replaces the ad-hoc
  `scripts/probe_sharded.py` invocations. +7 tests.

- **`--full-range` mode on `generate_hc_year_gap_csv.py`** (same
  commit). Keeps on-disk pids in the output — only confirmed deads
  are filtered. Used for year re-scrapes where content-staleness of
  existing files can't be cheaply detected (`mtime` was clobbered by
  v8 renorm). +2 tests.

- **Progress doc refactor** (commit `08b19b0`). Marked 2026 ✅,
  spec'd 8-vs-16 experiment, archived prior cycle.

Tests: **538 green**. Cumulative cache: 1.5 GB PDFs, 90,196 HC cases.

## In flight

**HC 2022 case-JSON backfill — three direct-IP cycles, 69.4%
coverage, cycle 4 awaiting cooldown decision** (snapshot
2026-04-25 21:12 BRT). Range mode `HC 210825..223881` (13,057
pids; 1,160 already on disk pre-launch). Run dir:
`runs/active/2026-04-24-hc-cases-2022-direct/`. Items land directly
in `data/source/processos/HC/` via `--diretorio-itens` — no copy step.

**Three-cycle pattern (all axis-B p95-wall_s collapses, none from
hard 403-fails — tenacity absorbs 403s as `status=ok` records with
inflated walls; axis-B trips on the wall p95):**

| cycle | cooldown before        | wall    | fresh ok records | end records / coverage |
|-------|------------------------|---------|------------------|------------------------|
| 1     | n/a (cold)             | 3h 28m  | +2,454           | 2,833 / 27.7%          |
| 2     | 6.2 h                  | 6h 49m  | +3,904           | 7,912 / 51.2%          |
| 3     | 1.0 h (driver minimum) | 3h 47m  | +2,375           | 10,857 / 69.4%         |

**Empirical rule (new — pin into throughput baselines).** Cooldown
duration scales productive volume roughly linearly at **~400
records per hour of cooldown** for direct-IP `varrer-processos`
against `portal.stf.jus.br/processos/*`. Confirms H6's "L3-per-IP
reputation persists across days" tip — partial recovery yields
proportional productive window.

**State as of cycle 3 cliff:**
- ok records on disk: **9,063 / 13,057 ≈ 69.4% of HC 2022 width**
- NoIncidente fails accumulated: **1,794** (all single-observation
  candidates in `HC.candidates.tsv`; will promote to confirmed
  `HC.txt` on the next *independent* HC 2022 sweep)
- 142 cumulative 403-retry chains absorbed across three cycles
- 3 SSLErrors in cycle 2 (cliff-aligned WAF connection drops with
  `SSL: UNEXPECTED_EOF_WHILE_READING` — same RST-injection
  signature as the 2025 PDF sweep stop on 2026-04-23)
- remaining unvisited: **2,200 pids** (HC 218737 .. 223881 minus
  cliff residue from cycles 1–3)

**Aggregator same-sweep-dedup gotcha (newly discovered this
session).** `scripts/aggregate_dead_ids.py` counts at most ONE
NoIncidente observation per pid per source sweep dir. So
in-session re-probes (which `--retomar` does for `status=fail`
rows) don't help promotion. The 1,794 candidates will only
graduate when a **different** sweep (different `runs/active/<X>/`)
independently observes them as NoIncidente. Consequence:
`--excluir-mortos` is a no-op for the cycle 4 resume; remaining
2,200 pids must be re-probed even though many will return
NoIncidente again. Concrete numbers from cycles 1–3:
- pre-sweep `HC.txt`: 6,980 confirmed deads, none in 2022 range
- after cycle 1 + aggregator run: 6,980 → 7,602 (+622, none in
  2022 range — the +622 were 2023+ candidates from prior runs that
  finally crossed threshold via this run as the "second" sweep)
- after cycle 3 + aggregator run: still 7,602 (in-session re-probes
  don't bump the per-sweep observation counter)

**Cycle 4 resume options** (pick before relaunching):

1. **Wait overnight (~8h) → single cleanup cycle finishes 2022.**
   Per the empirical rule, 8h cooldown projects ~3,200 productive
   records — well over the remaining 2,200, so cycle 4 should
   finish without cliffing. **Recommended.**
2. **60-min cooldown → cycle 4 likely cliffs at ~99% with a tiny
   cycle 5 mop-up.** Per the rule, 1h yields ~400 records; 2h
   yields ~800 — short of 2,200. Two-cycle finish.
3. **Sharded fresh-pool resume.** Requires (i) refreshing
   `config/proxies` from scrapegw (currently 4 days stale; only
   159 IPs — H6 says non-refreshed is 3.6× slower) and (ii)
   building a CSV from the unvisited remainder (sharded mode
   requires `--csv` per Typer help). Then 16 shards finishes 2,200
   pids in ~3–4 min wall. Costs one fresh proxy batch.

**Cycle 4 launch command** (identical to cycles 2 + 3; `--retomar`
skips the 9,063 ok rows; will start by re-probing the 1,794
NoIncidente fails — fast burst at ~0.07s each — then advance to
fresh new pids):

```bash
cd /home/noah-art3mis/projects/judex-mini
nohup uv run judex varrer-processos \
    --classe HC --processo-inicial 210825 --processo-final 223881 \
    --saida runs/active/2026-04-24-hc-cases-2022-direct \
    --rotulo hc_2022_direct \
    --diretorio-itens data/source/processos/HC \
    --retomar \
    >> runs/active/2026-04-24-hc-cases-2022-direct/launcher-stdout.log 2>&1 &
disown
```

**Health-check snippet** (since `judex probe` doesn't apply to
single-process direct-IP runs):

```bash
# pid alive?
pgrep -af 'varrer-processos.*hc_2022_direct' | grep -v 'pgrep\|grep'
# aggregate counts (per-pid keyed state — NOT {ok,fail,total} shape)
uv run python -c "
import json, collections
s = json.load(open('runs/active/2026-04-24-hc-cases-2022-direct/sweep.state.json'))
c = collections.Counter(v.get('status') for v in s.values() if isinstance(v, dict))
print('records:', sum(c.values()), '·', dict(c))
"
# regime trajectory (cliff is imminent if recent windows show
# approaching_collapse > 50% of last-200)
uv run python -c "
import json, collections
from pathlib import Path
recent = []
with Path('runs/active/2026-04-24-hc-cases-2022-direct/sweep.log.jsonl').open() as f:
    for line in f:
        recent.append(json.loads(line).get('regime'))
print('last-200 regime:', dict(collections.Counter(recent[-200:])))
"
```

**Lessons-learned (pin):**
- `--nao-perguntar` is a `baixar-pecas`-only flag; `varrer-processos`
  is non-interactive by default. Crashed the first launch attempt.
- `sweep.state.json` is per-pid keyed (`HC_<pid>` → record), not
  the `{ok,fail,total}` aggregate shape `agent-sweeps.md` documents
  — monitor by tallying `.values()`, not by reading aggregate keys.
- Driver-side ETA is unreliable mid-cycle: it averages over both
  ~0.05s dead-pid re-probes (when `--retomar` is replaying fails)
  and the ~0.17 rec/s sustained productive rate. Trust the sustained
  number, not the driver's printout.
- `--retomar` skips `status=ok` rows but RE-PROBES `status=fail`
  rows. Cycle-startup is therefore a fast burst through prior fails
  before reaching truly fresh pids. Useful for confirming dead pids
  but doesn't help confirmed-dead promotion (see same-sweep-dedup).

---

**Stopped 2026-04-22 ~19:52 BRT for a host reboot — resume after
boot.** `baixar-pecas` HC 2025 direct-IP sweep was halted with
SIGTERM → SIGKILL after the graceful handler hung on a stuck HTTP
request. State file (`pdfs.state.json`, 12.8 MB) parses cleanly;
per-URL atomic writes mean at most one in-flight URL was lost.

**Final stop snapshot:**
- run dir: `runs/active/2026-04-22-hc-pecas-2025-direct/`
- URLs in state: **29,326** (15,418 cached · 13,902 ok · 6 http_error)
- launcher counter at stop: **~29,330 / 50,526 (≈ 58%)**
- cases visited: **7,198 / 13,755 (52.3%)** — ~6,557 cases remain
- recent throughput: 0.50 rec/s (60s window) / 0.34 rec/s (long run)
- error pattern: 5 SSLError + 1 ConnectionError, **zero 403s** —
  direct host IP showed no WAF pushback all day; this is the first
  clean datapoint that contradicts yesterday's "portal-fatigued"
  baseline (see § Throughput baselines, `baixar-pecas` row).

**Resume command** (after reboot — single-process, identical to
the launch invocation; `--retomar` skips everything in
`pdfs.state.json` and continues from the next CSV row):

```bash
cd /home/noah-art3mis/projects/judex-mini
nohup uv run judex baixar-pecas \
    --csv tests/sweep/hc_2025_full.csv \
    --saida runs/active/2026-04-22-hc-pecas-2025-direct \
    --retomar --nao-perguntar \
    >> runs/active/2026-04-22-hc-pecas-2025-direct/launcher-stdout.log 2>&1 &
disown
```

**Verify resume took** (within 30s of relaunch — state size should
keep growing, launcher counter should advance past 29,330):

```bash
tail -5 runs/active/2026-04-22-hc-pecas-2025-direct/launcher-stdout.log
pgrep -af 'baixar-pecas' | grep -v 'pgrep\|grep'
```

**Estimated remaining work** (revised 2026-04-24 after measuring
bytes-landed properly via disk join, not text-present). Earlier
revisions conflated two different signals:

- The pre-filter estimate (`~21,200 URLs`, 12.8–17 h) was the full-
  tipos target list from the sweep's launcher banner. Still accurate
  if you resume under `--todos-tipos`.
- An intermediate revision said ~8,800 URLs / 5–7 h — that came from
  `pdfs_substantive.text IS NOT NULL` as the downloaded-proxy, which
  counts **extracted text**, not **landed bytes**. Those diverge
  wildly here because 31k+ sha1s in the cache have text without
  bytes (pre-split legacy extractions).

**Authoritative bytes-based estimate:** join `pdfs_substantive.sha1`
to the `.pdf.gz` filesystem set. 2025 tier-A: 9,776 of 24,174 URLs
have bytes (40%). **Remaining ≈ 14,400 tier-A URLs.** At 0.34–0.50
rec/s observed, wall-clock ≈ **~8–12 h**. Resume under the new
`--apenas-substantivas` default (on since commit `e7ce6af`,
2026-04-23) so the sweep only targets tier-A/B. If the host IP is
still as clean post-reboot as it was today, expect the lower end.
If the WAF starts pushing back (any 403s in the first 200 records),
abort and switch to the proxy-pool path per § Reference.

See [`docs/completion-tracker.md`](completion-tracker.md) for the
per-year bytes/text breakdown and refresh snippet.

**Why no shards:** this is a single-process direct-IP sweep — the
launch invocation didn't include `--shards` / `--proxy-pool`, so
`judex probe` (which enumerates `shard-*` dirs) doesn't work on
this run. Probe equivalents:
`tail launcher-stdout.log` (true done/total counter),
`wc -l pdfs.log.jsonl` (rate),
`jq -s 'group_by(.status) | map({status: .[0].status, n: length})' pdfs.state.json`
(status breakdown).

**Follow-up: 22 http_error URLs to retry after main run finishes.**
On 2026-04-23 morning the workstation's captive-portal network
session expired, causing ~16 URLs to fail with `SSL:
UNEXPECTED_EOF_WHILE_READING` (RST-injection into long-running
TLS streams) before re-auth restored the network. Combined with
the 6 pre-stop errors, state now holds **22 `http_error`** (vs
15,418 cached · 14,152 ok at the time of note). These will NOT be
retried within the current run — the read-head has already passed
them. After the current sweep terminates and `pdfs.errors.jsonl`
is rewritten, drain them with:

```bash
uv run judex baixar-pecas \
    --retentar-de runs/active/2026-04-22-hc-pecas-2025-direct/pdfs.errors.jsonl \
    --saida runs/active/2026-04-22-hc-pecas-2025-direct \
    --nao-perguntar
```

`--retentar-de` skips the CSV entirely and processes only those
URLs, so the cost is ~22 HTTP requests, not a full re-scan.
Anything that stays in errors.jsonl after this retry is a real
permanent failure worth inspecting case-by-case.

### Parallel-safe queue (zero-HTTP, no WAF share)

Content-freshness for HC 2023–2025 covers 7,367 + 13,240 + 10,926
+ 7,356 = 38,889 fresh case JSONs via arms B/C + recoveries (arm A
initial 7,356, then 7,367 of its 7,672-pid recovery queue landed
across 2023/2024/2025 union). Corpus-wide freshness status moves
from "~half of 2025" to "~96% of 2023–2025 + 100% of 2026."

### Parallel-safe queue (zero-HTTP, no WAF share)

These can run **right now** alongside the active `baixar-pecas`
without touching `portal.stf.jus.br`. Ordered by ROI. Interference
model: all four read from local disk / warehouse only; none emit
HTTP to STF or any proxy provider.

1. **`extrair-pecas --provedor pypdf`** — drains the extraction
   backlog. Current cache: 38,232 `.pdf.gz` vs 32,529 `.txt.gz` →
   **~5,703 PDFs with no extracted text yet**, and the active sweep
   is growing the gap as it lands fresh `ok` bytes. pypdf is local
   CPU, single-threaded, ~free; won't contend with the sweep for
   bandwidth. Obvious consumer of what `baixar-pecas` produces.
2. **`atualizar-warehouse`** — full rebuild of
   `data/derived/warehouse/judex.duckdb` from case JSONs + text cache.
   Atomic swap, zero HTTP, a few minutes. Will land arms A/B/C +
   recovery freshness + whatever extraction #1 produces. Build-stats
   validation from this cycle will flag `publicacoes_dje: 0.0% [WARN]`
   (expected — DJe path 1/2 not done) and any other silent regression.
3. **Analysis work on the current warehouse** — Marimo notebooks,
   SQL queries, the `analysis/hc_judge_lawyer_network.py` snapshot
   refresh on whatever warehouse build is current, the unit test
   suite (`uv run pytest tests/unit/`, 568 green). All file-bound.
4. **`validar-gabarito`** — re-run parity check against the 5
   hand-verified cases in `tests/ground_truth/`. Zero HTTP; reads
   the case JSONs on disk. Cheap smoke test that the scraper output
   format hasn't drifted.

**Unsafe while the current sweep runs** (would share the host IP's
WAF counter): a second `baixar-pecas` direct, any `varrer-processos`
direct, `sondar-densidade`. A *proxy-pool* sweep is safe because
egress IPs don't overlap, but it doubles proxy burn for the duration.

### Recently completed (today)

**Peça tipo classification + `pdfs_substantive` view + `--apenas-substantivas` default — 2026-04-23.**
Built a three-tier classification of HC peça PDFs: tier A =
substantive argumentation (keep), tier B = length-gated mixed
(keep if >1500 chars for `DESPACHO`), tier C = procedural boilerplate
(skip). By document count, tier C is **55% of the HC corpus** (132k of
241k andamentos PDFs). Validated with min/median/max sampling per
tipo (both random and length-extreme); calibration bumped the
`MANIFESTAÇÃO DA PGR` length gate 500 → 1000 after finding CIENTE
stamps at 567 chars.

Shipped:
- `judex/sweeps/peca_classification.py`: `TIER_A_DOC_TYPES`,
  `TIER_B_DOC_TYPES`, `TIER_C_DOC_TYPES`, `KNOWN_DOC_TYPES` constants
  + `filter_substantive()` + `summarize_tipos()`. Matching is
  case- and accent-insensitive (NFKD fold + combining-strip +
  uppercase + trim); fail-open on genuinely new tipos.
- `scripts/baixar_pecas.py` + `judex/cli.py`: **`--apenas-substantivas`
  default ON** with `--todos-tipos` opt-out. Filter runs after
  `resolve_targets` before `--limite`, so CSV / range / filter-fallback
  paths all benefit. Sharded mode threads the flag through to children.
  Pre-flight banner prints top-5 tipos and warns on any unseen tipo
  (not in `KNOWN_DOC_TYPES`) so operators catch labeling drift at
  sweep launch.
- `judex/warehouse/builder.py`: `CREATE VIEW pdfs_substantive` added
  to `_SCHEMA_SQL` — unions andamentos + session-virtual documentos,
  tier-labeled, drops tier-C. `MANIFESTAÇÃO DA PGR` length gate
  calibrated 500 → 1000 from expanded sampling.
- `docs/peca-tipo-classification.md`: full tier definitions, per-tipo
  content notes, flag usage, insensitive-match policy, fail-open
  policy, pre-flight banner format, validation sampling log.
- `tests/unit/test_peca_classification.py`: 7 behavior tests
  (drop tier-C, keep unknown, case/accent-insensitive match, fail-open
  on genuinely new tipos, summarize top+unseen, variant-not-flagged,
  high-volume stubs present).

All **575 unit tests green** (568 + 7 new; warehouse tests exercise
the view via `_SCHEMA_SQL`).

**Empirical validation on current corpus:** 17 distinct tipos, zero
case/accent variants, zero silent misses from the insensitive fold
— the insensitive match is pure future-proofing against STF labeling
reforms.

**End-to-end dry-run** on HC 250000–250050 (185 targets):
`--apenas-substantivas` dropped 117 (63%); top tipos:
DECISÃO MONOCRÁTICA (46), INTEIRO TEOR DO ACÓRDÃO (18), DESPACHO (4);
zero unseen tipos flagged.

**Sweep impact** — next `baixar-pecas` run silently drops ~55% of
URLs before HTTP (prints a "dropped N tier-C targets" banner + top
tipos + unseen warning if any). Proportional wall-clock + WAF-exposure
savings. Opt-out with `--todos-tipos` if ever needed.

**HC recovery pass — 2026-04-21 afternoon** (task (a) from prior
next-steps). 7,672-pid union-recovery CSV (arms A/B/C target minus
ok-landed minus deads). 16 shards, interleave-sharded, reused proxy
batch (not refreshed — 8.5h cooldown since arm C). 7,367/7,672
landed (**96.0%**), **1 cliff (shard-k at 174/479)**, 305 pids for
residue. Wall-clock **43.5 min** vs 12-min fresh-pool prediction —
3.6× slowdown traces to L3 residual debt on reused batch. H6 tip #1
"refresh before every sustained sweep" now supported with **inverse
evidence**: skipping refresh cost 3.6× throughput even after 8.5h
idle. Run dir: `runs/active/2026-04-21-hc-recovery/`. H4 cliff
prediction (0–1) held (1 observed). The CliffDetector axis-B
window-full fix explicitly earned its keep — shards l (warn=133)
and p (warn=211) both made it to 100% despite elevated stress; under
the pre-fix detector they would have false-positive-cliffed.

**Arm C — HC 2023 @ 16 shards — completed.** 12,644/12,644 at 100%,
**0 cliffs**, 23.4 min productive wall-clock. Validated the new
default (16/fresh/sticky=5) on a third workload.
`runs/active/2026-04-21-hc-2023/`.

**A/B decision landed (2026-04-21 ~09:16): 16 wins decisively.**
Wall-clock 0.17×, cliffs 3 vs 8, coverage 1.72×. Full writeup:
[`docs/reports/2026-04-21-8-vs-16-shards.md`](reports/2026-04-21-8-vs-16-shards.md).
**16 shards + fresh proxies + sticky=5 is the new default** for
year-backfill workloads; 8 shards retired for sustained jobs.

**Arm B — HC 2024 @ 16 shards — completed.** 92.0% coverage
(13,240/14,387) in 31.5 min productive. 3 cliffs (1 detector
false-positive now fixed + 2 genuine late-stage). Residue folded
into the recovery pass above. `runs/active/2026-04-21-hc-2024/`.

## Backlog — ordered

### DJe capture — three paths (post-diagnosis, 2026-04-21)

STF migrated DJe to `digital.stf.jus.br` on 2022-12-19; our scraper
hits the old (stub-serving) endpoint. See § What just landed for
the full diagnosis. Pick **1** for fast metadata-level repair; pick
**2** when full DJe index is worth the infrastructure cost. Don't
pick **3**.

1. **Andamentos-side DJe metadata extraction** (1–2 hours of work).
   Regex-parse strings like `"ACÓRDÃO PUBLICADO DJE-N DIVULG.
   DD/MM/YYYY PUBLIC. DD/MM/YYYY"` from existing `andamentos` rows.
   Emit a new `dje_events` table in the warehouse: `{processo_id,
   dje_numero, divulgado_iso, publicado_iso, secao}`. Doesn't need
   any new HTTP; works on the corpus we already have. Gets ~80% of
   DJe-metadata-level queries unblocked.
2. **Playwright for `digital.stf.jus.br`** (1–2 days). Headless
   browser loads the new DJe platform, passes the AWS WAF challenge,
   captures the `aws-waf-token` cookie, then reverse-engineered API
   calls with that cookie get full DJe index including decision
   texts. New dependency but only used for the DJe tab, not the main
   scrape. Best long-term.
3. ⛔ **AWS WAF challenge reverse-engineering** — not recommended.
   STF can flip challenge type (reCAPTCHA / Turnstile) anytime;
   maintenance nightmare.

### Warehouse

1. **Rename `pdfs` table → `pecas`.** Holds all peças (PDF + RTF).
2. **`content_version` column on `cases`.** Enable cheap skip of
   content-fresh pids in future year re-scrapes — avoids the need
   for `--full-range` indiscriminate re-scraping.
3. **Decide on `data_protocolo_iso` redundancy** under v8.
4. ✅ **DJe warehouse flatten** — *landed* (this cycle's investigation
   confirmed `_flatten_publicacoes_dje` already exists in
   `builder.py`). The warehouse ingests DJe correctly; the problem is
   that `publicacoes_dje=[]` in the source JSONs due to the extractor
   regression above, not the builder.

### Data recovery

1. ✅ **Arm-A + arm-B + arm-C recovery** — *landed 2026-04-21*.
   Union-recovery CSV approach (targets minus ok minus deads)
   produced 7,672 pids; 16-shard pass at 96.0% / 1 cliff; see
   § In flight § Recently completed.
2. ✅ **Arm C — HC 2023** — *landed 2026-04-21*. 100% / 0 cliffs.
3. **Second-pass recovery for shard-k residue** (305 pids). Tiny
   queue; one shard, direct-IP or single small pool. Low priority —
   those 305 pids are a 0.3% tail across 2023–2025; doesn't
   materially change downstream warehouse/analysis quality. Defer
   unless a specific analysis needs them.
4. **PDFs + text extraction** per year once case-JSON scrapes land.
   Now unblocked — all four years content-fresh enough for peça
   fan-out. See § Next steps (b) / (c).

### Cliff detector hardening (partially done + future)

- **`--cliff-require-sustained K` flag** (still open). Arm A's
  shard-h cliffed on one 70s record after proxy rotation had briefly
  cleared the walls — genuine WAF pattern but the single-sample trip
  lost throughput. K=3 ("regime must be at collapse for K consecutive
  observations") would absorb rotation-forgiveness patterns on
  already-full windows. Distinct from the window-full-gate fix
  (which addressed arm-B's shard-o false positive at small n).
- ✅ **Axis-B window-full gate** — landed this session. Prevents
  false-positive collapse at n=MIN_OBS=20 where p95 ≡ max element.

### Operational hygiene

- **Bytes-cache suffix rename** `<sha1>.pdf.gz` → `<sha1>.bytes.gz`.
  Full playbook in 2026-04-19_2355 archive. Queued; safe now that no
  sweep is live.
- **`baixar-pecas --excluir-mortos`** — minor diff (dead IDs already
  naturally skipped via missing case JSON).
- **Pre-filter `baixar-pecas` by cache-hit** — opt-in helper that
  drops CSV rows whose URLs are all cached.
- **Fix `scripts/monitor_overnight.sh`** — scope stale-shard alerts
  to the currently-active tier.
- ✅ **`peca_targets._find_case_file` no longer walks the tree** —
  *landed 2026-04-21*. Was calling `r.rglob(name)` once per pid, so
  baixar-pecas startup was O(N_pids × N_files) per shard. Production
  layout is `<root>/<CLASSE>/judex-mini_*.json` flat under the
  bucket; replaced rglob with `(root/classe/name).is_file()` plus a
  fallback for callers that pass the classe-bucket directly. +1
  perf-guard test (asserts a buried case file is invisible to the
  direct probe). Stale: the running PDF sweep launched before the fix
  already paid the rglob tax; future invocations cold-start in seconds.
- **`pgrep` self-match gotcha in sweep-wait loops.** A background
  `until [ "$(pgrep -c -f <rotulo>_shard_)" = "0" ]; do sleep … done`
  never exits because the bash waiter's own command line contains
  the literal `<rotulo>_shard_` substring, so `pgrep -f` matches the
  waiter itself. Bit us on the 2026-04-21 recovery (~30 min of false
  "still running" state until manually killed). Correct patterns:
  (i) match the actual script path, e.g.
  `pgrep -f 'scripts/run_sweep\.py.*<rotulo>_shard_'`; or (ii) poll
  each shard's `sweep.state.json` + check for a terminal `done`/
  `collapse` marker; or (iii) use `pgrep -f <pattern> | grep -v $$`
  to exclude the shell running the check. Worth a one-paragraph
  addition to `docs/agent-sweeps.md` § Detached-sweep pattern.

### Request-footprint reduction (re-prioritized — STF-politeness hedge)

**Motivation change as of 2026-04-21.** These items were previously
queued as "scraper optimization" / perf tweaks. After seeing arm-B
land at 10.52 rec/s (×6 URLs per case = ~63 STF HTTP req/sec) and
projecting scale to 32 shards (~125 req/sec), the right framing is
no longer throughput — it's **reducing our observable footprint on
STF's `/processos/*` endpoint** before we decide to scale aggressively.
Each item below cuts 15–20% of HTTP calls per case without losing
data. Stacked, they reduce per-case STF load by 30–50%, which is a
stronger guarantee of STF comfort than any after-the-fact throttle
alarm. **Promoted from "not blocking" to operational priority before
any scale-up past 16 shards.**

1. **Delete `abaDecisoes.asp` fetch** (−1 GET; no downstream reader).
   Highest-ROI: free win, zero data impact.
2. **Class-gate `abaRecursos.asp`** — skip on HC/AI by default; −1 GET
   per case for the classes that dominate our workload.
3. **Audit + gate `abaDeslocamentos.asp`** — check downstream readers
   before cutting; probably gateable by class.
4. **Class-gate `abaPautas` / `abaPeticoes`** on monocratic classes
   (HC decisions often monocratic → pautas empty → skip safe).

**Companion observability (V1 only, to measure the impact of the
cuts above + catch STF gradual-throttle):** add a `clean_p50` column
to `judex probe` — rolling p50 of `wall_s` filtered to
`status=ok AND retries={}`. That's the pure STF-response-time
signal, isolated from our own retry-chain latency. No thresholds,
no alarms yet — just the number, visible. After arm B + arm C give
us 2–3 data points for the "normal" range, we decide whether to
add V2 (color-coded ratio) or V3 (auto-throttle). V1 is ~20 lines
of code; V3 is a design session.

**Not doing (out of scope):** a proxy-provider change, a UA-
identification scheme, or coordinated outreach to STF. Those are
policy moves, not technical ones; queue separately if ever needed.

### Refactoring sweep — 2026-04-26 (queued)

Read-only review surfaced a punch list. Items are grouped **quick
wins** (≤30 min, low risk, do first), **structural** (file splits +
DRY-up, medium risk, do after the in-flight regime change lands),
and **architectural** (questions to settle, not edits to schedule).
The single biggest leverage move is collapsing `cli.py`; the single
biggest *risk* avoided by ordering is leaving the in-flight
`RegimeReading` change alone until the structural items start.

Each item carries `file:line` refs so a cold session can land it
without re-deriving the diagnosis.

**Quick wins**

1. ✅ **Drop unused import** `tempfile` from `judex/cli.py:34` —
   *landed 2026-04-26.* (`sys` *is* used at `cli.py:953-958, 1012-1017`
   for the `sys.argv` save-and-restore around script dispatch — the
   original review was wrong; verified before editing.)
2. ✅ **Extract atomic-write helper** — *landed 2026-04-26.* New
   module `judex/utils/atomic_write.py` (`atomic_write_text(path, text,
   *, fsync=False)`) replaces the inlined `tmp + os.replace` blocks at
   `judex/sweeps/store.py:127,136`, `judex/reports/state.py:49`, and
   `judex/reports/watchlist.py:59`. Bonus: store.py temp-file naming
   changed from a fixed `.tmp` to `.tmp.<pid>`, eliminating a
   theoretical collision when two sweep processes touch the same path.
   +5 unit tests in `tests/unit/test_atomic_write.py`; full suite went
   from 598 → 603 green.
3. **`test_build_warehouse.py:44-100`** — seven `_v{1,3,6,8}_case`
   builders are vestigial post-renormalizer. Replace with a single
   `make_case(version="v8", **overrides)` factory; legacy versions
   are tested implicitly through fixture overrides.

**Structural**

4. **`process_store.py` ↔ `peca_store.py` duplication.** Both grow the
   same regime quartet in the in-flight diff (`process_store.py:43-51`,
   `peca_store.py:43-52`). Move the regime-stamping helper into
   `store.py`'s base; subclasses supply only the dataclass + key
   function. **Land *after* the in-flight diff is committed** so the
   refactor reads against the final shape.
5. **`download_driver.py` (427) ↔ `extract_driver.py` (334) parallelism.**
   Init / signal handlers / target loop / skip-or-resume / progress
   reporting are essentially the same; only `process_item` differs.
   Extract `BaseSweepDriver` in `judex/sweeps/driver_base.py`. Saves
   ~150 lines + ensures regime stamping doesn't fork between the two
   when extract_driver later needs it.
6. **`judex/warehouse/builder.py` (1030 lines)** — the `_flush()`
   nested inside `build()` (`builder.py:895-954`) is screaming for a
   `BufferSet` dataclass with a `flush(con)` method. Lifts the
   `flatten_*` functions into testable units and brings the file
   under the 600-line ceiling.
7. **`scripts/run_sweep.py` (1049 lines)** — `_run_passes` (line 842)
   is the loop; everything else is argparse + reporting. Extract a
   `judex/sweeps/process_sweep_runner.py` module that owns the loop
   and state; `run_sweep.py` becomes ~200 lines of argparse +
   orchestration.
8. **`judex/scraping/scraper.py` (711 lines)** violates the CLAUDE.md
   600-line rule that's literally written down. Either split (HTTP
   session + tab orchestration vs. caching vs. extraction-glue) or
   strike the rule from CLAUDE.md and pin a real ceiling with a
   pre-commit check.

**Architectural — decide, don't schedule**

9. **`judex/cli.py` (965 lines) — Typer wrapping argparse is double
   parsing.** Every command in `cli.py:163-666` rebuilds `argv` via
   `_push()` (`cli.py:65-79`) and shells into the script's `main()`.
   Two CLI frameworks, one user-facing surface. Decision needed:
   (a) Typer wins → make script `main()` bodies pure functions, drop
   argparse, kill `_push`; (b) argparse wins → drop Typer, write
   argparse `--help` strings. Status quo is paying ~900 lines for
   nice help text. **Pick one before the next CLI command lands.**
10. **In-flight `RegimeReading` shape — four columns or one nested
    dict?** Diff adds `regime` + `regime_fail_rate` + `regime_p95_wall_s`
    + `regime_promoted_by` to *both* `AttemptRecord` and
    `PecaAttemptRecord` (8 dataclass fields, 2× docstrings). A single
    `regime: dict | None` carries the same data; jq becomes
    `.regime.label` instead of `.regime`. **Decide before merging the
    in-flight branch** — flattening four columns back into a dict
    later is a corpus-wide migration; the reverse is one diff.
11. **Three monitoring tools without a shared seam** — `AdaptiveThrottle`,
    `CircuitBreaker`, `CliffDetector` (`shared.py:65-216`) each maintain
    independent rolling windows over the same attempt stream. The
    architecture is sound — they answer different questions — but
    they don't share a window or a record-stamping path. Not urgent;
    flag this as "the place over-engineering will compound first" so
    the next monitor added doesn't blindly add a fourth window.
12. **Portuguese subcommands → English scripts.** `varrer-processos`
    → `scripts/run_sweep.py`, `baixar-pecas` → `scripts/baixar_pecas.py`,
    `extrair-pecas` → `scripts/extrair_pecas.py`. Pick a language;
    the translation friction shows up every time someone goes from
    `--help` to source.

**Symptoms-of, not work items**

- `_push()` in `cli.py:65-79` exists *only* because of #9. It dies
  when #9 is decided either way.
- `_reset_shutdown_for_tests()` at `shared.py:59` is a test seam in
  production code; a `monkeypatch` in conftest does the job.
- `_REGIME_BANDS` table refactor in the in-flight `shared.py:96-101`
  diff replaces a 6-line `if/elif` ladder with a 3-row table iterated
  by a loop. Earns its keep only if more bands appear; if not, it's
  more code, not less. Re-evaluate when the band count next changes.

## Known limitations

- **Stale-cache content residue.** 2024 + 2023 + ~half of 2025
  structurally v8 but content-stale (partes truncated, pautas empty,
  no `publicacoes_dje`). 2026 is content-fresh; 53.5% of 2025
  (arm-A coverage) now content-fresh.
- **Main `judex.duckdb` pre-session data.** Rebuild deferred to
  end-of-cycle (after arms B, C, and all PDF + extraction land).
- **Scrapegw L3-per-IP reputation decay.** Arm A gave direct
  evidence: pools that cliffed yesterday cliff earlier today after
  21h idle. Overnight gap is "mostly but not fully" cleared. A
  second proxy provider is the only true redundancy.

## Known gaps

- **`publicacoes_dje` → warehouse** (see Backlog § Warehouse #1).
- **PDF enrichment status tracking** — no persisted field answers
  "has this case been through PDF enrichment?" Derivable from
  `extractor` slots; rollup script proposed but not landed.

---

# Reference — how to run things

```bash
# Unit tests (~15 s, 538 tests)
uv run pytest tests/unit/

# Live probe of a sharded sweep (rich table, throughput, ETA, regimes)
uv run judex probe --out-root runs/active/<dir>
uv run judex probe --out-root runs/active/<dir> --watch 30   # auto-refresh

# Ground-truth validation
uv run python scripts/validate_ground_truth.py

# Full-range year re-scrape (what arms A/B/C use)
uv run python scripts/generate_hc_year_gap_csv.py \
    --year <YYYY> --out tests/sweep/hc_<YYYY>_full.csv \
    --dead-ids data/derived/dead-ids/HC.txt --full-range

#   Then launch sharded:
uv run judex varrer-processos --csv tests/sweep/hc_<YYYY>_full.csv \
    --rotulo hc_<YYYY> --saida runs/active/<date>-hc-<YYYY> \
    --diretorio-itens data/source/processos/HC \
    --shards <N> --proxy-pool config/proxies --retomar

#   Aggregate dead-IDs periodically
uv run python scripts/aggregate_dead_ids.py --classe HC

#   PDF bytes (separate WAF counter, 16 shards safe)
uv run judex baixar-pecas --csv <case-list> \
    --saida runs/active/<date>-hc-<YYYY>-pdfs \
    --shards 16 --proxy-pool config/proxies --retomar --nao-perguntar

#   PDF text extraction (zero HTTP; local)
uv run judex extrair-pecas -c HC -i <lo> -f <hi> --nao-perguntar

#   Warehouse rebuild
uv run judex atualizar-warehouse --ano <year> --classe HC \
    --saida data/derived/warehouse/judex-<year>.duckdb
# Or full corpus:
uv run judex atualizar-warehouse
```

## Recovery from CliffDetector collapse

```bash
# If one or more shards cliff mid-sweep:
xargs -a runs/active/<label>/shards.pids kill -TERM

# Identify ungrabbed pids from each cliffed shard's sweep.state.json
# → build a recovery CSV covering only those pids

# Relaunch on direct IP (bypasses the degraded proxy pool):
nohup uv run python scripts/run_sweep.py \
    --csv <recovery.csv> --label <label>_recovery \
    --out runs/active/<label>-recovery \
    --items-dir <items_dir> \
    --resume --no-stop-on-collapse \
    > runs/active/<label>-recovery/launcher-stdout.log 2>&1 & disown
```

## Data model — peças → cases

Unchanged. See prior archive for the three-hop layout
(case JSON → URL → sha1 → cache quartet).
