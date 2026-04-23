# Peça tipo classification — what's substantive, what's boilerplate

STF's `andamentos[].link.tipo` labels cover ~17 distinct values on the
HC corpus. Most of them (~55% of rows) are procedural stubs whose
content is either pure metadata already structured in `cases` /
`andamentos`, or a one-line template ("De ordem, a Secretaria
Judiciária faz remessa..."). This document classifies every observed
tipo into three tiers so downstream tooling — warehouse queries,
LLM analyses, and `baixar-pecas` itself — can filter uniformly.

**Scope:** HC peça PDFs reached via `andamentos.link_url` (served by
`portal.stf.jus.br/processos/downloadPeca.asp`) and session-virtual
documents reached via `cases.sessao_virtual[].documentos[].url`.
Does **not** cover DJe RTFs under `decisoes_dje.rtf_url`, which are
a separate pipeline (see [`data-layout.md`](data-layout.md) § DJe).

## Tiers

### Tier A — substantive (keep)

Full argumentation. These are where legal reasoning lives; the
corpus for any lawyer / minister / doctrine analysis is essentially
this tier plus tier-B-long.

| `link_tipo` (andamentos) | HC rows | Median chars | What it is |
|---|---:|---:|---|
| `DECISÃO MONOCRÁTICA`    | 72,434 |  7,856 | Single-minister decision: facts + defense args + reasoning + outcome |
| `INTEIRO TEOR DO ACÓRDÃO` | 17,706 | 11,185 | Compiled collegiate ruling: ementa + relatório + every vote in one PDF |
| `MANIFESTAÇÃO DA PGR`     |  5,414 | 10,124 | PGR substantive opinion (the "other side" of the argument). Filter to `n_chars > 1000` — short versions (400–600 chars) are "CIENTE" acknowledgment stamps, sometimes with reversed-OCR mojibake |

| `doc_type` (documentos, session-virtual) | HC rows | Median chars | What it is |
|---|---:|---:|---|
| `Voto`        | 6,321 |  7,671 | Individual vote from a collegial session |
| `Relatório`   | 6,317 |  1,721 | Report introducing a case for collegial vote |
| `Voto Vogal`  |   404 |  2,971 | Vote from a non-relator minister |
| `Voto Vista`  |    33 | 12,942 | Long separate opinion after request for vista |

**Redundancy note.** `INTEIRO TEOR DO ACÓRDÃO` is the compiled form
of `Voto` + `Relatório` + `Voto Vogal` + `Voto Vista` for the same
case. When both are present, prefer Inteiro Teor (one PDF, complete
picture). Individual votes are the fallback when Inteiro Teor is
missing (still being compiled, or capture gap).

### Tier B — mixed (keep when long)

Content varies within a single tipo. A cheap second-stage length
filter handles the split well.

| `link_tipo` | HC rows | Median chars | Filter | Rationale |
|---|---:|---:|---|---|
| `DESPACHO` | 13,816 | 974 | `n_chars > 1500` | <1500 chars is pure procedure ("defiro habilitação"); >1500 occasionally has substantive reasoning |

### Tier C — boilerplate (skip)

Either a pure administrative stub (200–500 chars, template text) or
data already structured elsewhere in the warehouse. Nothing an LLM
would extract that isn't already a column.

| `link_tipo` | HC rows | Median chars | Why skip |
|---|---:|---:|---|
| `CERTIDÃO DE TRÂNSITO EM JULGADO`            | 51,627 |   350 | One-line "transitou em julgado em DD/MM/YYYY" stamp |
| `CERTIDÃO`                                    | 48,786 | 1,200 | Distribution record — relator, autuação, assunto already in `cases` |
| `DECISÃO DE JULGAMENTO`                       | 15,577 |   450 | Same info as structured `outcome` field |
| `COMUNICAÇÃO ASSINADA`                        |  4,316 |   900 | Cover-letter ofício; actual content is the attached decision |
| `CERTIDÃO DE JULGAMENTO`                      |  3,453 | 1,020 | Panel composition + one-line decision; redundant with `outcome` |
| `TERMO DE REMESSA`                            |  2,989 |   400 | Procedural forwarding stub |
| `VISTA À PGR`                                 |  2,520 |   225 | "De ordem, a Secretaria..." stub marking the referral to PGR |
| `TERMO DE BAIXA`                              |  1,673 |   400 | Closure record stub |
| `INTIMAÇÃO`                                   |    675 |   500 | Subpoena notification |
| `VISTA À PARTE EMBARGADA` / `VISTA À PARTE AGRAVADA` | 7 | ~300 | Same shape as `VISTA À PGR` |
| `OUTRAS PEÇAS`                                |      1 |     — | Single-row outlier |
| `CERTIDÃO DE DECURSO DE PRAZO PARA RESPOSTA`  |      1 |     — | Single-row outlier |

## How much this saves

Against the current HC corpus (237k PDFs reached via `andamentos`):

| Slice | Documents | Chars |
|---|---:|---:|
| Tier A (keep all)        |  95,554 | 1,077 MB |
| Tier B (keep len>1500)   |  13,816 |    21 MB |
| Tier C (skip)            | 131,616 |    96 MB |
| **Savings by count**     |         | **55%**  |
| **Savings by char volume** |       | **8%**   |

The savings asymmetry is the key planning fact: by document count,
filtering is a huge win (55% fewer documents to process); by raw
token volume, it's only 8% because tier C docs are individually tiny.
So the filter pays off most where there's per-document overhead:

- **Per-PDF LLM calls** (e.g. `relatorio-advogado` per-document summarization loop) — full 55% savings.
- **`baixar-pecas` HTTP requests** — full 55% savings in requests, which translates directly to proportional WAF exposure and wall-clock time at the observed throughput ceiling.
- **Bulk context-window loads** — only the ~8% token savings; probably not worth filtering if you're already batching.

## Applications

### 1. Warehouse view — `pdfs_substantive`

Added to `_SCHEMA_SQL` in `judex/warehouse/builder.py`; rebuilt on
every `judex atualizar-warehouse`. Unions the andamentos-side peças
and the session-virtual documentos into a single row-per-document
table with columns `classe, processo_id, seq, doc_type, url, sha1,
source, tier, text, n_chars`.

```sql
-- every substantive peça, both sources, tier-labeled
SELECT * FROM pdfs_substantive WHERE classe = 'HC' AND text IS NOT NULL;

-- only A-tier (the strictest analysis filter)
SELECT * FROM pdfs_substantive WHERE classe = 'HC' AND tier = 'A';

-- dedup: prefer Inteiro Teor over individual votes when both exist
SELECT * FROM pdfs_substantive s
WHERE classe = 'HC' AND tier = 'A'
  AND NOT (
    source = 'sessao_virtual'
    AND EXISTS (
      SELECT 1 FROM pdfs_substantive x
      WHERE x.classe = s.classe
        AND x.processo_id = s.processo_id
        AND x.doc_type = 'INTEIRO TEOR DO ACÓRDÃO'
    )
  );
```

Downstream notebooks and skills (e.g. `relatorio-advogado`,
`analysis/hc_*`) should reach for this view instead of rolling
their own `andamentos` + `pdfs` join with tipo logic.

### 2. Sweep filter — `--apenas-substantivas` on `baixar-pecas` (default ON)

`baixar-pecas` applies the tier-C filter at target-build time — before
any HTTP request is emitted. The flag **defaults to ON**, so every
new sweep skips procedural stubs by default:

```bash
# Default behavior (filter active) — no flag needed
uv run judex baixar-pecas \
    --csv tests/sweep/hc_2025_full.csv \
    --saida runs/active/YYYY-MM-DD-hc-pecas-substantive \
    --retomar --nao-perguntar

# Opt out — download everything, including tier-C boilerplate
uv run judex baixar-pecas --todos-tipos ...
```

On every run the launcher prints a line like:

```
--apenas-substantivas: dropped 12,340 tier-C targets (22,700 → 10,360).
Use --todos-tipos to disable.
```

so the filter's action is visible, not silent. The tier-C list is
defined once in `judex/sweeps/peca_classification.TIER_C_DOC_TYPES`
and reused by `baixar-pecas`, the `pdfs_substantive` view, and any
future callers.

Expected impact: ~55% fewer HTTP requests, proportional wall-clock
reduction at the throughput ceiling, proportional WAF-exposure
reduction. Tier-B `DESPACHO` is left in because filtering it would
require a length estimate before download (not available). Accept
the 13.8k Despachos as the cost of a simple pre-fetch filter; prune
them at query time via `pdfs_substantive`.

**Tier-C confidence (validated 2026-04-23).** Classification backed
by a two-round sample: first 3 PDFs per tipo (min/median/max via
random), then min + top-2 by length for every tier-C tipo (full
`CERTIDÃO` family, `COMUNICAÇÃO ASSINADA`, `DECISÃO DE JULGAMENTO`,
`VISTA À PGR`). Results:
- All largest tier-C samples were confirmed procedural / duplicative.
  `CERTIDÃO DE TRÂNSITO` maxes at ~800 chars; `CERTIDÃO` at 1,687;
  `COMUNICAÇÃO ASSINADA` at 1,193 — all template text.
- `DECISÃO DE JULGAMENTO` max = 2,119 chars. Its largest samples do
  contain cautelar-measure *conditions* (e.g. "recolhimento
  domiciliar" detail) that aren't always in structured `outcome`.
  Accepted as a known tradeoff — the headline decision is still
  in `outcome`, and keeping this tipo would recover <5% of its rows
  with any non-template content.
- `MANIFESTAÇÃO DA PGR` at 567 chars was still a "CIENTE"
  acknowledgment stamp — the length gate was raised from 500 to
  1000 as a result. Any PGR manifestation below that is
  extraction-garbled mojibake or a stamp.

**Matching is case- and accent-insensitive.** Both sides of the
comparison are folded via Unicode NFKD + combining-mark strip +
uppercase + whitespace-trim, so labeling drift doesn't silently
disable the filter:

| Input doc_type | Folds to | Matches `CERTIDÃO`? |
|---|---|---|
| `CERTIDÃO` | `CERTIDAO` | ✓ (canonical) |
| `CERTIDAO` | `CERTIDAO` | ✓ (no accent) |
| `Certidão` | `CERTIDAO` | ✓ (title case) |
| `certidão` | `CERTIDAO` | ✓ (lowercase) |
| `  CERTIDÃO  ` | `CERTIDAO` | ✓ (padded) |

Empirically the current corpus has zero case/accent variants
(verified 2026-04-23: 17 distinct tipos, all uniformly uppercase +
canonically accented), so the insensitive match is pure defense —
zero current silent misses caught, but a future STF rename (e.g.
portal migration to lowercase labels) won't silently re-enable the
filter for the renamed tipo.

**Policy for unseen tipos: fail-open.** `filter_substantive()` is a
strict allowlist-of-skip. Any tipo whose folded form isn't in
`TIER_C_DOC_TYPES` passes through:
- A genuinely new STF tipo (e.g. a reform introduces
  `"NOTA DE SANEAMENTO"`) → kept → downloaded.
- `doc_type = None` (pre-download ambiguity) → kept.

This is deliberate: the worst case is wasting some HTTP requests
on a new stub until we notice; there is never silent data loss.

**Detection loop.** Every `baixar-pecas` run prints two
diagnostic lines before any HTTP:

```
top tipos: 'DECISÃO MONOCRÁTICA' (72,434), 'INTEIRO TEOR DO ACÓRDÃO' (17,706), …
⚠  unseen tipo(s) — not in classification, kept by default: 'NOTA DE SANEAMENTO' (n=123)
```

The warning fires when any tipo in the resolved target list isn't
in `KNOWN_DOC_TYPES` (tier A ∪ B ∪ C, after case/accent folding).
Operators see it at sweep launch and can abort to classify before
burning HTTP requests on something they'd rather skip. The
warehouse `SELECT DISTINCT link_tipo FROM andamentos` query is
the confirmation path after the next `atualizar-warehouse`.

If STF introduces a new tipo label (e.g. a reform), sample a few
PDFs via the pattern at the top of this doc and add to the
appropriate tier frozenset (usually `TIER_C_DOC_TYPES`) after a
content check.

## Out of scope — DJe pecas

DJe documents (table `decisoes_dje`, columns `kind` / `rtf_tipo`) are
fetched by a different pipeline (not `baixar-pecas`) and currently
show 7 HC rows total in the warehouse. Classification is premature
until the DJe backfill lands. See the "DJe capture — three paths"
entry in the backlog.
