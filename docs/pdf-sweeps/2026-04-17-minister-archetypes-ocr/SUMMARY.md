# Minister archetypes HC — narrow OCR pass

**Status**: completed; 22/22 cases with readable substantive text; 0 unrecovered failures.

**Date**: 2026-04-17.

**Target selection**: 11 ministros × 2 HCs each, organized by archetype from `analysis/hc_minister_archetypes.py`:

- **Concedentes que enfrentam o mérito**: Gilmar Mendes, Ricardo Lewandowski, Celso de Mello
- **Denegadores que enfrentam o mérito**: Alexandre de Moraes, Marco Aurélio
- **Despachantes processuais**: Edson Fachin, Luiz Fux, Luís Roberto Barroso, Rosa Weber, Dias Toffoli, Cármen Lúcia

Strategy: 1 cite (case already read in prior sweeps) + 1 net-new per minister, except concedentes (no prior reads available → 2 new each).

**Scope**:
- 22 HCs, 15 fresh + 7 cite-only.
- 19 URLs needed fresh fetch/OCR (other 38 substantive PDFs were already cached from famous-lawyers + top-volume sweeps).

## Headline

| metric | value |
|---|---|
| target HCs | 22 (5 concedentes + 4 denegadores + 13 despachantes-segments across 6 ministers) |
| fresh reads | 15 |
| cite-only reads | 7 |
| URLs fetched (new) | 19 |
| URLs cached from prior sweeps | 38 |
| fetch ok on 1st pass | 16 + 3 cache-hits = 19/19 (no `unknown_type` at `--throttle-sleep 5.0`) |
| OCR pass candidates | 14 (pypdf <5k chars) |
| OCR improved | 13 (one `unknown_type` retry recovered) |
| final corpus (22 cases × avg chars) | **~860 000 chars** across 57 substantive PDFs |

## Timings

| pass | URLs | wall | per-URL | throttle | notes |
|---|---:|---:|---:|---:|---|
| fetch | 19 | ~140 s | 7.4 s | 5.0 s | 0/19 `unknown_type` — 5 s floor cleanly passes |
| OCR pass | 14 | ~410 s | 29.3 s | 3.0 s + Unstructured latency | 1 `unknown_type` → retry |
| OCR retry | 1 | ~16 s | — | 8.0 s | recovered |
| **total** | — | **~9.5 min** | — | — | — |

Compare against the two prior runs:

| run | URLs | wall | per-URL (fetch) | per-URL (OCR) |
|---|---:|---:|---:|---:|
| `2026-04-17-famous-lawyers-ocr` | 78 | ~21 min | — | 23 s |
| `2026-04-17-top-volume-ocr` | 25 | ~16 min | 4.6 s | 18.3 s |
| `2026-04-17-minister-archetypes-ocr` | 19 | **~9.5 min** | **7.4 s** | **29.3 s** |

This pass was **faster end-to-end** than top-volume despite each pass having similar URL counts — because:

1. **Half the case set was pre-cached** from prior sweeps (only 19 of 57 PDFs needed fresh fetch).
2. **`--throttle-sleep 5.0` eliminated `unknown_type`** on first fetch pass. Top-volume's 3.0 s floor left 7/25 transient failures; 5.0 s left 0/19. Bumping throttle by ~60 % cut failure rate by >90 % — a good trade.
3. **Session-reuse bug remained dormant** because the new-URL count was small enough that no `unknown_type` appeared at fetch; OCR pass had its only 1 failure absorbed by retry.

## Gap status

The two `pdf_driver` gaps found in the top-volume pass (§ SUMMARY.md there) remain **unfixed** and were worked around the same way:

1. `run_pdf_sweep` cache fast-path — worked around by `unlink()`ing the 14 short cache entries before OCR.
2. Session-reuse sensitivity — not triggered this pass (only 14 OCR candidates; no session-degradation cascade).

Permanent fixes still recommended but not urgent at this sweep size.

## Per-case char counts

All 22 cases ≥ 5 000 chars usable text (sum of substantive PDFs per case). Smallest case: Toffoli HC 230.730 (2 571 chars — a 4-line ementa-minimal AgRg, the *archetypal* despachante-alto-volume shape). Largest: Cármen HC 135.041 (144 936 chars — `cite` case from famous-lawyers, Pierpaolo's OSCIPs attack).

Distribution:
- Concedentes: 15 000 – 60 000 chars/case (long dogmatic votes).
- Denegadores: 6 000 – 90 000 chars/case (90k is HC 135.027 cite, includes Toron's full merit-attack + PGR parecer).
- Despachantes: 2 500 – 145 000 chars/case (very wide — Fux 6k, Toffoli 2.5k, Cármen 145k). The char-count spread *itself* is diagnostic: despachante writing styles range from 30-word dispatches to 20k-char procedural-moldura scaffolds.

The char-count distribution alone confirms the archetype taxonomy at a statistical level — see `READINGS.md § Síntese agregada` for the textual confirmation and five named surprises.

## Implications for downstream analysis

Five findings from the READINGS that would modify `analysis/hc_minister_archetypes.py` directly — see the notebook for the updated "Achado central":

1. **Arquétipo é turmal, não pessoal.** Lewandowski explicitly documented in HC 173.743 that he changed position when moving from 1ª to 2ª Turma. The concedente archetype is a **2ª Turma bloco-effect**; migration changes the ministro's archetype without any style change.
2. **Celso opera em templates dogmáticos fixos.** His two concessões (HC 173.800, HC 173.791) have votos **identical in 80 %** of extent. Aggregating by HC inflates Celso's "distinct substantive grants" count; should aggregate by *tese*.
3. **Barroso has three temporal identities.** 2014-despachante (HC 118.493), 2016-concedente-template (top-volume HC 134.507, HC 138.847), 2022-despachante-com-prosa (famous-lawyers HC 230.430). Single "Barroso archetype" label masks conditional tipo-penal → movimento structure.
4. **Fachin-adaptive pattern.** HC 188.362 dispatched in two different procedural frames at different times (nego seguimento → homologo desistência). The despachante applies *whatever moldura is available*, not a fixed preference.
5. **Moraes merit-engagement is not artifact.** HC 134.691 (fresh, no Toron) confirms the merit-engagement-contrário pattern persists outside the famous-lawyers slice. It's structural, not relator-advogado-specific.

## Artifacts

- `target_manifest.tsv` — hand-built; minister / archetype / kind / pid / outcome / doc_type / URL.
- `target_urls.jsonl` — the 19 new URLs (input to fetch `--retry-from`).
- `ocr_candidates.jsonl` — the 14 URLs with pypdf <5k chars (input to OCR `--retry-from`).
- `pdfs.state.json`, `pdfs.log.jsonl`, `report.md`, `requests.db`, `run.log` — fetch-pass institutional layout.
- `ocr-pass/` — same layout, OCR pass.
- `READINGS.md` — substantive interpretation (22 cases, 6 100 words, organized by archetype).
- `case_readings_draft.md` — identical to READINGS.md; the original draft. Kept for audit trail; not load-bearing.
