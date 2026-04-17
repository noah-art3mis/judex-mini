# Andamentos classifier — gaps between legacy and production

`src/analysis/andamentos.py` was ported from
`docs/reference/processar_andamentos_legacy.py` (Costa, 2025-10-12).
The port is **partial**. This note lists what didn't make it across, so
downstream analyses (especially ADI/ADC merits, HC liminares) don't
silently run on an incomplete taxonomy.

Cross-check before any andamentos-driven analysis: legacy line numbers
below reference `docs/reference/processar_andamentos_legacy.py`.

## Missing rules

### 1. `LANCAMENTO INDEVIDO` cleanup (legacy 43-146)

Not a classifier — a **data-cleaning pass**. When `LANCAMENTO INDEVIDO`
appears, the legacy script finds its referent in the preceding entries
(matched by `nome` / `data` / `complemento` substring across a 6-branch
fallback) and removes **both** the indevido entry and its referent.

Production path: no equivalent. Indevidos and their referents both
survive into downstream counts. Material for any analysis that counts
decisions.

### 2. `liminar` classifier (legacy 821-875)

Distinguishes:
- `COMUNICADO DEFERIMENTO DE LIMINAR` (separate bucket)
- `LIMINAR` substring (but not bare `PEDIDO DE LIMINAR`)
- `DETERMINO O SOBRESTAMENTO DO PROCESSO` in complemento
- `PROVIDO` + `EMBARGOS DE DECLARACAO COMO PEDIDO CAUTELAR` in complemento
- `REJEITADO` + `REJEITO O PEDIDO DE MEDIDA CAUTELAR` in complemento
- `DECISAO` + `LIMINAR` or `CAUTELAR` in complemento

Production path: no `liminar` bucket at all. Matters for any
HC-outcome / ADI-urgência analysis.

### 3. `amicus_curiae` classifier (legacy 651-683)

Three branches:
- `PETICAO` in nome + `AMICUS CURIAE` in complemento
- `PROVIDO` in nome + `CURIAE` + `DEFIRO O PEDIDO` in complemento
- `DEFERIDO` in nome + `AMICUS CURIAE` in complemento

Production path: no `amicus_curiae` bucket.

### 4. `art12` classifier (legacy 621-648)

- `ADOTADO RITO DO ART. 12, DA LEI 9.868/99` in nome
- `DECISAO` in nome + `RITO DO ART. 12` in complemento

ADI/ADC-specific procedural marker. Production path: no bucket.

### 5. `complemento`-aware `decisao_merito` (legacy 663-1008, 1131-1168)

Legacy also routes to `decisao_merito` / `agravo` / `embargo` based on
complemento strings, e.g.:
- `PROVIDO` nome + `PROVIMENTO AO AGRAVO REGIMENTAL` in complemento → agravo
- `PROVIDO` nome + `O AG.REG. NO ...` in complemento prefix → agravo
- `PROVIDO` nome + `DOU PROVIMENTO AOS EMBARGOS DE DECLARACAO` in complemento → embargo
- `PROVIDO` nome + `OS EMB.DECL. NO ...` in complemento prefix → embargo
- `PROVIDO` nome + `PROVEJO OS EMBARGOS DECLARATORIOS` → embargo
- `PROVIDO` nome + `NOS TERCEIROS ED` in complemento prefix → embargo
- `PROVI` nome + `DESPROVEJO OS DECLARATORIOS` in complemento → embargo
- `REJEITADO` nome + `REJEITO O PEDIDO DE MEDIDA CAUTELAR` → liminar (see §2)
- `DECISAO` nome + `RITO DO ART. 12` → art12 (see §4)

Production `mask_decisao_merito` and `mask_agravo` / `mask_embargo`
inspect only `nome`. They miss the `PROVIDO`-nome + complemento-keyed
cases above.

### 6. DECISAO julgador normalization (legacy 1010-1036)

Canonicalization pass applied after merits-extraction:

| input `nome`                         | output `nome` | output `julgador` |
| ------------------------------------ | ------------- | ----------------- |
| `DECISAO DO RELATOR`                 | `DECISAO`     | `RELATOR`         |
| `DECISAO DA RELATORA`                | `DECISAO`     | `RELATOR`         |
| `DECISAO DA PRESIDENCIA`             | `DECISAO`     | `PRESIDENCIA`     |
| `DECISAO DA PRESIDENCIA - <X>`       | `<X>`         | `PRESIDENCIA`     |
| `DECISAO DO(A) RELATOR(A) - <X>`     | `<X>`         | `RELATOR`         |

Production path: no normalization — these reach downstream as distinct
`nome` values, fragmenting decisão counts.

## Porting checklist

When porting, follow the project TDD convention:
1. Capture legacy behavior as fixture input → expected-label JSON in
   `tests/fixtures/andamentos_classifier/` (one case per rule above).
2. Red: add a failing test that asserts the new bucket.
3. Green: add the mask to `src/analysis/andamentos.py::STRING_MASKS`.
4. Refactor only after all six gaps have green tests.

Order suggestion (by analysis blast radius):
1. DECISAO julgador normalization (§6) — touches every existing bucket.
2. `LANCAMENTO INDEVIDO` cleanup (§1) — changes counts everywhere.
3. `liminar` (§2) — needed for HC who-wins and ADI-urgência work.
4. `art12` (§4), `amicus_curiae` (§3) — ADI/ADC-specific.
5. `complemento`-aware decisao_merito (§5) — last, after the rest stabilize.
