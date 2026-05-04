# Peça tipo classification — applications

The classifier itself — tier definitions, the case/accent fold contract,
the fail-open policy on unseen tipos — lives next to the code as the
module docstring of
[`judex/sweeps/peca_classification.py`](../judex/sweeps/peca_classification.py).

Read it first, then come back here for the *uses*: the warehouse view
that stitches both source surfaces into one queryable table, and the
operator-facing CLI surface on `baixar-pecas`.

For the empirical row counts, median character lengths, and the
two-round content sampling that backs the current tier assignments,
see [`docs/reports/2026-04-23-peca-tipo-tier-validation.md`](reports/2026-04-23-peca-tipo-tier-validation.md).

## 1. Warehouse view — `pdfs_substantive`

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

## 2. Sweep filter — `--apenas-substantivas` on `executar` (default ON)

`executar` applies the tier-C filter at target-build time — before
any HTTP request is emitted. The flag **defaults to ON**, so every
new sweep skips procedural stubs by default. `--todos-tipos` opts back
in to the full set; see `uv run judex executar --help` for the
flag surface.

On every run the launcher prints two diagnostic lines before any HTTP:

```
top tipos: 'DECISÃO MONOCRÁTICA' (72,434), 'INTEIRO TEOR DO ACÓRDÃO' (17,706), …
--apenas-substantivas: dropped 12,340 tier-C targets (22,700 → 10,360).
Use --todos-tipos to disable.
⚠  unseen tipo(s) — not in classification, kept by default: 'NOTA DE SANEAMENTO' (n=123)
```

The unseen-tipos warning fires when any tipo in the resolved target
list isn't in `KNOWN_DOC_TYPES` (tier A ∪ B ∪ C, after case/accent
folding). Operators see it at sweep launch and can abort to classify
before burning HTTP requests on something they'd rather skip. The
warehouse `SELECT DISTINCT link_tipo FROM andamentos` query is the
confirmation path after the next `atualizar-warehouse`.

If STF introduces a new tipo label, sample a few PDFs (the report has
the methodology) and add it to the appropriate frozenset in
`peca_classification.py` (usually `TIER_C_DOC_TYPES`) after a content
check. The classifier is the single source of truth; both
`baixar-pecas` and the `pdfs_substantive` warehouse view import from it.

Tier-B `DESPACHO` is left in the download set because filtering it
would require a length estimate before download (not available).
Accept the 13.8k Despachos as the cost of a simple pre-fetch filter;
prune them at query time via `pdfs_substantive`'s tier label.

## Out of scope — DJe peças

DJe documents (table `decisoes_dje`, columns `kind` / `rtf_tipo`) are
fetched by a different pipeline (not `baixar-pecas`) and currently
show 7 HC rows total in the warehouse. Classification is premature
until the DJe backfill lands. See the "DJe capture — three paths"
entry in the backlog.
