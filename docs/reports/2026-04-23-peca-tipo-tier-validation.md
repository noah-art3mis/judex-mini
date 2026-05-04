# Peça-tipo tier validation — empirical snapshot, 2026-04-23

Snapshot of the per-tipo row counts, median character lengths, and
the two-round content sampling that backs the tier-A / B / C
assignments now encoded in
[`judex/sweeps/peca_classification.py`](../../judex/sweeps/peca_classification.py).

This is a point-in-time artefact: counts will drift as the corpus
grows; the tier *assignments* are the load-bearing claim and live in
code. Re-validate when STF introduces a new tipo (the
`baixar-pecas` `unseen tipo` warning fires) or when any tier-C entry
gets contested.

Underlying corpus: 237k PDFs reached via `andamentos.link_url` on the
HC slice, plus 13k session-virtual `documentos`. Classification is
case- and accent-insensitive (see module docstring for the fold
contract).

## Tier A — substantive (keep)

Full argumentation. Where legal reasoning lives; the corpus for any
lawyer / minister / doctrine analysis is essentially this tier plus
tier-B-long.

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

## Tier B — mixed (keep when long)

Content varies within a single tipo. A cheap second-stage length
filter handles the split well.

| `link_tipo` | HC rows | Median chars | Filter | Rationale |
|---|---:|---:|---|---|
| `DESPACHO` | 13,816 | 974 | `n_chars > 1500` | <1500 chars is pure procedure ("defiro habilitação"); >1500 occasionally has substantive reasoning |

## Tier C — boilerplate (skip)

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

## How much filtering saves

Against the 237k-PDF HC corpus reached via `andamentos`:

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

## Tier-C confidence — sampling methodology

Two-round sample: first 3 PDFs per tipo (min/median/max via
random), then min + top-2 by length for every tier-C tipo (full
`CERTIDÃO` family, `COMUNICAÇÃO ASSINADA`, `DECISÃO DE JULGAMENTO`,
`VISTA À PGR`).

Results:

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

## Case/accent variants in current corpus

Empirically zero — verified 2026-04-23 across the 17 distinct tipos:
all uniformly uppercase + canonically accented. The case/accent fold
in `_fold()` is therefore pure defense — zero current silent misses
caught, but a future STF rename (e.g. portal migration to lowercase
labels) won't silently re-enable the filter for the renamed tipo.

| Input doc_type | Folds to | Matches `CERTIDÃO`? |
|---|---|---|
| `CERTIDÃO` | `CERTIDAO` | ✓ (canonical) |
| `CERTIDAO` | `CERTIDAO` | ✓ (no accent) |
| `Certidão` | `CERTIDAO` | ✓ (title case) |
| `certidão` | `CERTIDAO` | ✓ (lowercase) |
| `  CERTIDÃO  ` | `CERTIDAO` | ✓ (padded) |
