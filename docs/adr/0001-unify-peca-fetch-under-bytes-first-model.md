# ADR-0001: Unify peça fetch under the bytes-first / extract-later model

**Status**: Proposed (2026-04-30). Implementation pending.

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
3. **Cleaner forecasts.** `judex/utils/forecasts.py` constants are anchored on andamento-only sweeps and do not model the in-line PDF cost `varrer-processos` currently incurs. Once both passes are pure, forecasts apply uniformly.

## Consequences

- **Backfill is required.** Existing cache has `<sha1>.txt.gz` but no `<sha1>.pdf.gz` for surfaces 2 + 3. After implementation, a one-shot `baixar-pecas` pass scoped to those URLs warms the bytes side. Existing text stays valid until re-extraction is requested.
- **Forecasts re-anchor.** First mixed-surface sweep should be treated as a re-anchoring run (per the rule in `forecasts.py`'s module docstring).
- **Substantive filter scope is open.** Surface 1 uses `andamento.link.tipo` for tier-A/B/C filtering; surface 2 has `documentos[].tipo` (Relatório / Voto / etc.); surface 3 uses `decisoes[].kind` (`decisao` / `ementa`). The filter logic in `peca_classification` must be extended to cover all three discriminators. **If the mapping is non-trivial, defer to a follow-up ADR.**
- **`varrer-processos` runtime drops.** Today's case-scrape includes synchronous PDF fetches; removing those should make case-scrape faster and reduce WAF pressure on `portal.stf.jus.br`, at the cost of a follow-up `baixar-pecas` pass against `sistemas.stf.jus.br`.
- **`CLAUDE.md` gotcha update needed.** The current "URLs ... populated at scrape time and never re-fetched" phrasing becomes false (URLs only); the gotcha should be rewritten in the same PR that lands the implementation.

## Considered alternatives

- **Status quo (asymmetric).** Rejected: locks surfaces 2 + 3 to whichever extractor ran at scrape time, and mixes case-scrape with PDF-fetch in `varrer-processos`.
- **Persist bytes inside the synchronous fetcher.** Rejected: would unify the *bytes* layer (re-extraction would work) but still couple `varrer-processos` to PDF fetches, blocking the pure-case-scrape simplification and leaving the rate-limit / WAF logic split between two scrape paths.
