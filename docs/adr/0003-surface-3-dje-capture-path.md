# ADR-0003: Surface 3 (DJe publications) capture path after STF migration

**Status**: Proposed (2026-05-01).

## Summary

STF migrated the substantive DJe publication backend (Decisão / Acórdão / Despacho content) to `digital.stf.jus.br/publico/publicacoes` on **2022-12-19** (date pinned by STF's own page footer: *"Até o dia 19/12/2022, o Supremo Tribunal Federal mantinha dois Diários de Justiça Eletrônicos com conteúdos distintos"*). The legacy listing endpoint at `portal.stf.jus.br/servicos/dje/listarDiarioJustica.asp` **still serves publication metadata** (DJ date, DJ number, redirect link), but the substantive content URLs are gone — replaced by plain-text "Para consultar essa publicação, acesse ..." messages. Our `parse_dje_listing` parser hard-requires `abreDetalheDiarioProcesso(...)` `onclick` JS calls, so it silently discards every post-migration entry. Result: 0% surface-3 capture for 2023+ corpus despite the metadata being right there in the response.

## Context

[ADR-0001](0001-unify-peca-fetch-under-bytes-first-model.md) unified the three peça URL surfaces (`andamento`, `sessao_virtual`, `dje`) under a single `collect_peca_targets` enumerator and a single `baixar-pecas` → `extrair-pecas` flow. ADR-0001 step 3 validates 2 of 3 surfaces; surface 3 is what this ADR addresses.

### Year-by-year capture rates (HC corpus)

| Year | DJe pubs captured | DJe decisions captured |
|------|-------------------:|------------------------:|
| 2020 | 95 | 73 |
| 2021 | 99 | 73 |
| **2022** | **18,585** | **10,233** |
| 2023 | 0 | 0 |
| 2024 | 0 | 0 |
| 2025 | 0 | 0 |
| 2026 | 0 | 0 |

The cliff between 2022 and 2023 lines up with STF's migration of the DJe content URLs from inline `verDecisao.asp?...` links (parseable via `abreDetalheDiarioProcesso(...)` `onclick`) to plain-text redirects pointing at `digital.stf.jus.br/publico/publicacoes`.

### What 2026-05-01 reconnaissance found

**The legacy listing endpoint still serves data for every year.** Same URL pattern as before:

```
GET portal.stf.jus.br/servicos/dje/listarDiarioJustica.asp?classe=HC&numero=N
```

returns HTTP 200 + ~55 KB of HTML for HC 2022, 2024, and 2026 alike. Sample response shapes:

**Pre-migration (HC 2022 — 210826):**
```html
<strong>DJ Nr. 2 do dia 11/01/2022</strong>
<strong>  Presidência</strong>
<strong>    Distribuição</strong>
<a onclick="abreDetalheDiarioProcesso(2, '11/01/2022', 6327127, 1, 287, 8)">HABEAS CORPUS 210826</a>
```
→ **Captured** by current parser.

**Post-migration (HC 2024 — 236529):**
```html
<strong>DJ do dia 26/02/2024</strong>
&nbsp;&nbsp;Para consultar essa publicação, acesse <a href="https://digital.stf.jus.br/publico/publicacoes">https://digital.stf.jus.br/publico/publicacoes.</a>

<strong>DJ Nr. 2 do dia 09/01/2024</strong>
&nbsp;&nbsp;Para consultar essa publicação, acesse <a href="https://digital.stf.jus.br/publico/publicacoes">https://digital.stf.jus.br/publico/publicacoes.</a>
```
→ **Silently dropped** by current parser. Two gates filter it out:

1. `_DJ_HEADER_RE = r"^\s*DJ Nr\.\s*(\d+)\s+do dia\s+(\d{2}/\d{2}/\d{4})\s*$"` requires the *"DJ Nr. N"* form, but redirect entries use both *"DJ Nr. N do dia ..."* and *"DJ do dia ..."* (without a number).
2. The `<a>` walk requires `onclick="abreDetalheDiarioProcesso(...)"`. Redirect entries have a plain `<a href="https://digital.stf.jus.br/...">` instead.

**Probing the new platform** at `digital.stf.jus.br` was the originally-imagined fix path, but it leads nowhere clean: the user-facing publicacoes browser at `/publico/publicacoes` is gated by AWS WAF (HTTP 202 + `token.awswaf.com` JS challenge); no public API analogue to surface 2's `decisoes-monocraticas/api/public/votos/{id}/conteudo.pdf` exists for publicacoes (probed `/publicacoes/api/public/...`, `/dje/api/public/...`, etc. — all return the SPA shell, no backend module mounted). The 714 KB JS bundle on `digital.stf.jus.br` is the **internal STF staff app** (MSAL OAuth, internal-process APIs), not the publicacoes consumer. Reconnaissance details are documented in `docs/system-changes.md` row dated 2022-12-19.

But that detour was unnecessary: **the data we want for the metadata layer is already on the legacy endpoint, parseable via a regex update.**

## Decision

Two-tier strategy, recommended in this order:

**Phase 1 (recommended): Patch `parse_dje_listing` to capture redirect-style entries.** Effort: ~1-2 hours.

Specifically:
1. Loosen `_DJ_HEADER_RE` to also match *"DJ do dia DD/MM/YYYY"* (no DJ number) — emit `numero=None` for those rows.
2. Extend the parsing loop to recognise `<a href="https://digital.stf.jus.br/publico/publicacoes...">` redirects as entries (parallel branch alongside the existing `abreDetalheDiarioProcesso` branch). Each emits a `PublicacaoDJe` entry with `detail_url=None`, `external_redirect=<the digital.stf.jus.br URL>`, and the parsed `numero` + `data` from the most recent header.
3. Tests: extend `tests/unit/test_extract_dje.py` with fixtures captured today from HC 236529 (one-DJ-number + zero-DJ-number redirect cases). Pin the expected output shape.

Outputs after this lands:
- `publicacoes_dje[].numero`: int or None (None when STF emits *"DJ do dia ..."* without a number).
- `publicacoes_dje[].data`: ISO date string (always present).
- `publicacoes_dje[].decisoes[].rtf.url`: None for post-migration entries (the content URL is gone). Existing pre-migration entries unaffected.
- `publicacoes_dje[].external_redirect`: `https://digital.stf.jus.br/publico/publicacoes` for post-migration entries; None for pre-migration. Future Phase-2 work has a hook URL to consume.

This recovers full DJ-level metadata coverage for 2023+ without touching infrastructure: no Playwright, no AWS WAF, no new endpoint. CONTEXT.md gets a clarifying note that `decisoes[].rtf.url` is None for post-2022 publications until Phase 2 lands; queries that depend on DJe *content* (as opposed to metadata) need to fall back on surface 1 + surface 2 PDFs in the meantime.

**Phase 2 (deferred): Playwright + AWS WAF challenge solving.** Defer until a concrete coverage gap demands it.

The actual decision *text* for post-migration DJe publications lives on `digital.stf.jus.br` behind the WAF. Recovering it requires:
- Playwright (or equivalent) to solve the WAF JS challenge;
- Replicating the network calls the publicacoes SPA makes once authenticated;
- New scraper module + ongoing browser-process maintenance.

Cost: 1-2 days plus ongoing fragility. The forcing question for going there: *"Does any analytical question we want to ask need DJe-only content text, beyond what surfaces 1 + 2 already provide?"* DJe was historically a metadata index — substantive decision content for HC overwhelmingly arrives via `andamento.link.url` (surface 1) and `sessao_virtual.documentos[].url` (surface 2, working). Until measurement shows a real content gap, Phase 2 is overengineering.

## Why

1. **The user could see the data in their browser.** That fact alone refuted my initial "Playwright needed" conclusion. The legacy endpoint is alive; our parser is the broken link.

2. **Phase 1 is parser work, not protocol work.** The bytes go over the wire today; the response has the metadata; only `parse_dje_listing` is filtering it out. A regex update + test update is the entire change. No new HTTP path, no auth, no WAF.

3. **Phase 1 preserves the architectural property pinned by ADR-0001.** Surface 3 entries become URL-only pointers (with `external_redirect` instead of `rtf.url` for post-migration), exactly matching the bytes-first / extract-later shape ADR-0001 promises. When Phase 2 lands, the `external_redirect` URL is the hook the byte-fetcher consumes.

4. **Phase 2's necessity is unproven.** The 2026-04-21 system-changes.md note observed that *"andamentos carry `PUBLICADO O ACÓRDÃO, DJE N` as structured rows with dates → ~80% of DJe-level metadata queries answerable without fixing"*. Phase 1 raises that to ~100% for metadata. The remaining gap (DJe-only content text) hasn't been demonstrated to matter for any active analysis.

5. **Reconnaissance closed three theoretical alternatives.**
   - *"Public API on digital.stf.jus.br"* — no module mounted under `/publicacoes/`, `/dje/`, or any obvious prefix; only the user-facing WAF-gated SPA exists.
   - *"Re-scrape pre-migration data"* — the legacy endpoint serves the new redirect form for old cases too; we can't recover pre-migration content URLs we missed.
   - *"Negotiate API access with STF"* — long lead time, low probability; superseded by Phase 1's existence.

## Consequences

- **Phase 1 is a one-shot renormalize, not a re-scrape.** New DJe captures land via the next varrer-processos sweep automatically; existing case JSONs need a renormalizer pass to back-fill metadata from cached HTML (since 2023+ HTML caches were captured but parsed empty).
- **`publicacoes_dje[].decisoes[]` stays empty for post-2022 entries until Phase 2.** The metadata is there; the decisões content array is intentionally empty. CONTEXT.md needs an explicit note distinguishing the metadata layer (Phase 1) from the content layer (Phase 2).
- **HC 2022's full coverage stays as-is.** 18,585 publications + 10,233 decisions remain the only year with full-platform coverage. Phase 1 does not regress them.
- **The "DJe migration" entry in `docs/system-changes.md` (row dated 2022-12-19) updates** from "diagnosed, not yet fixed" to "Phase 1 lands DJe metadata; Phase 2 (content) deferred pending coverage-gap measurement".
- **Warehouse builder gains a column.** `decisoes_dje.has_content` boolean (true if `rtf.url` populated, i.e. pre-migration; false for post-migration metadata-only rows). Lets queries discriminate between "we have the decision text" and "we have a publication record but the text is on STF's new platform".
- **`external_redirect` is an explicit acknowledgment of incomplete coverage**, not a working URL. Calling it `external_redirect` (rather than `url`) prevents any pipeline from accidentally feeding it into the bytes-first cache.

## Open questions

1. **Concrete coverage gap of metadata-only.** What % of `publicacoes_dje[].decisoes[]` content (in HC 2022, our reference year) is *not* recoverable from andamento (surface 1) + sessao_virtual (surface 2) PDFs? Determines Phase 2's priority. *Owner: data-side analysis on HC 2022 — compare DJe-extracted text against the union of surface-1 + surface-2 cached text per case. Run after Phase 1 so the metadata-vs-content distinction is sharp.*
2. **The `verDiarioProcesso.asp` detail endpoint.** Pre-migration entries went through `parse_dje_detail` (a second HTTP call to the detail page, not the listing). For post-migration entries we'd skip that step (no `detail_url`). Verify this doesn't break the rest of the pipeline (warehouse builder, downstream analyses). *Likely fine — `decisoes_dje` table just has fewer rows for post-2022.*
3. **Alphabetical-listing classes (e.g. when STF lists "HABEAS CORPUS" by name only, no per-case detail).** The `verDiarioProcesso.asp` detail page is *per-case*; the listing redirects don't link to detail at all. Need to confirm `parse_dje_detail` won't be called accidentally on post-migration entries with `detail_url=None`.
