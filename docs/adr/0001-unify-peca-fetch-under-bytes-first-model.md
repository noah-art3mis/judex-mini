# ADR-0001: Unify peça fetch under the bytes-first / extract-later model

**Status**: Accepted (2026-05-01). Both implementation steps landed; backfill pending operator action.

| Step | What | Landed in | Notes |
|---|---|---|---|
| 1 | `collect_peca_targets` enumerates all three surfaces with a `surface ∈ {"andamento", "sessao_virtual", "dje"}` tag | commit `bc04799` | Read-side; tested in `tests/unit/test_peca_targets.py`. |
| 2 | Synchronous PDF/RTF fetch removed from `varrer-processos` (deletes `_make_pdf_fetcher`, `resolve_documentos`, `pdf_fetcher` plumbing); `documentos[]` and `decisoes[].rtf` become URL-only pointers on disk | this commit | Write-side; `peca_cache` is no longer warmed at scrape time. |
| 3 (operator) | One-shot `baixar-pecas` pass scoped to surfaces 2 + 3 to warm the bytes side | not yet run | Existing `<sha1>.txt.gz` stays valid until re-extraction is requested; no urgency unless a provider switch is planned. |

## Context

`StfItem` references peças via three URL surfaces: `andamentos[].link.url`, `sessao_virtual[].documentos[].url`, and `publicacoes_dje[].decisoes[].rtf.url`. All three currently end up with extracted **text** in `data/derived/pecas-texto/<sha1(url)>.txt.gz`, but via two different operational paths:

- **Surface 1 (andamentos):** `varrer-processos` records only the URL pointer. Bytes are later fetched by `baixar-pecas` (writing `<sha1>.pdf.gz`); text is then produced by `extrair-pecas` (`pypdf` / `pypdf_layout` / `unstructured` / `mistral` / `chandra`). Re-extraction with a different provider is supported because the bytes are kept.
- **Surfaces 2 + 3 (sessao_virtual + DJe):** `varrer-processos` invokes a `fetcher(url)` synchronously during case scraping (see `scraper.py:395-416`, `extraction/sessao.py:260-282`); the fetcher downloads bytes, extracts text, writes text to `peca_cache`, and **discards the bytes**. Re-extraction is impossible — the bytes were never persisted.

Two practical consequences follow: (a) text quality on surfaces 2 + 3 is locked to whichever extractor ran at scrape time, with no recovery path; (b) `varrer-processos` quietly performs PDF fetches against `sistemas.stf.jus.br` as a side effect of case scraping, violating the otherwise-clean property that `baixar-pecas` is the only path that talks to STF for PDF content.

## Decision

All three surfaces will use surface 1's model: **`varrer-processos` records the URL only; `baixar-pecas` fetches the bytes; `extrair-pecas` produces the text.** The synchronous fetcher in `extraction/sessao.py` and the corresponding DJe fetch path in `scraper_dje.py` will be removed, replaced by URL-pointer emission. `judex.sweeps.peca_targets.collect_peca_targets` will be extended to enumerate URLs from all three surfaces, deduped by `sha1(url)` at the cache layer.

## Why

1. **Re-extraction parity across the corpus.** The `extrair-pecas --provedor` knob exists so the project can adopt better OCR/extraction tools without re-scraping. Today that knob is a no-op for sessão-virtual + DJe peças. After this change, every peça is re-extractable.
2. **Single-purpose passes.** `varrer-processos` becomes a pure case-JSON scraper. `baixar-pecas` becomes the only path that fetches PDF/RTF bytes from STF. The rate-limit / WAF / circuit-breaker logic applies uniformly to all peça fetches.
3. **Cleaner forecasts.** `judex/utils/cost.py` constants are anchored on andamento-only sweeps and do not model the in-line PDF cost `varrer-processos` currently incurs. Once both passes are pure, forecasts apply uniformly.

## Consequences

- **Backfill is required.** Existing cache has `<sha1>.txt.gz` but no `<sha1>.pdf.gz` for surfaces 2 + 3. After implementation, a one-shot `baixar-pecas` pass scoped to those URLs warms the bytes side. Existing text stays valid until re-extraction is requested.
- **Forecasts re-anchor.** First mixed-surface sweep should be treated as a re-anchoring run (per the rule in `judex/utils/cost.py`'s module docstring).
- **Substantive filter scope — resolved (no follow-up ADR needed).** Surface 1 uses `andamento.link.tipo` for tier-A/B/C filtering; surface 2 has `documentos[].tipo` (`Relatório` / `Voto` / `Voto Vista`); surface 3 has `decisoes[].kind` (`decisao` / `ementa`). All surface-2 and surface-3 values are intrinsically substantive — there is no procedural noise on those surfaces equivalent to surface 1's `CERTIDÃO` / `INTIMAÇÃO`. The existing `filter_substantive` fail-open behaviour on tipos outside `TIER_C_DOC_TYPES` is therefore the *correct* semantics for surfaces 2 + 3, not a placeholder. Pinned by `tests/unit/test_peca_classification.py::test_filter_keeps_all_sessao_virtual_documentos` and `::test_filter_keeps_all_dje_decisoes`.
- **`varrer-processos` runtime drops.** Pre-step-2 the case-scrape included synchronous PDF/RTF fetches; removing them shifts the bytes cost to a separate `baixar-pecas` pass against `sistemas.stf.jus.br`. The next overnight HC run after step 2 lands is the natural re-anchoring point for `_AVG_REQ_WALL_S_DIRECT` in `judex/utils/cost.py`.
- **`CLAUDE.md` gotcha rewrite.** Pre-step-2 the gotcha said "URLs ... populated at scrape time and never re-fetched"; post-step-2 it must read "URL-only pointers on every surface; bytes-first via `baixar-pecas` on demand." Rewrite is part of this commit.

## Considered alternatives

- **Status quo (asymmetric).** Rejected: locks surfaces 2 + 3 to whichever extractor ran at scrape time, and mixes case-scrape with PDF-fetch in `varrer-processos`.
- **Persist bytes inside the synchronous fetcher.** Rejected: would unify the *bytes* layer (re-extraction would work) but still couple `varrer-processos` to PDF fetches, blocking the pure-case-scrape simplification and leaving the rate-limit / WAF logic split between two scrape paths.
