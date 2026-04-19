# Data dictionary — `StfItem` and its inner structures

This document catalogues every field emitted by the HTTP scraper into
a case JSON (`data/cases/<CLASSE>/judex-mini_<CLASSE>_<N>.json`) —
type, source, extraction logic, allowed values (where categorical),
and preprocessing notes.

Canonical schema: [`src/data/types.py`](../src/data/types.py).
Portal contract (URL flow, field → source tab): [`stf-portal.md`](stf-portal.md).
Classification axes (HC vs ADI vs RE, órgão julgador, rito, etc.):
[`stf-taxonomy.md`](stf-taxonomy.md).
Concrete examples: [`tests/ground_truth/*.json`](../tests/ground_truth)
(7 hand-verified fixtures, one per classe family).

**Current version:** `SCHEMA_VERSION = 3`. See [`## Schema history`](#schema-history) at the bottom of this file for the per-version changelog and the migration path. Every item emitted by the current scraper carries `"schema_version": 3`; items with lower values (or no key) need `scripts/renormalize_cases.py`.

## Conventions used below

- **`Optional[X]`** — field can be `null` in the JSON output. Fields are Optional for a reason — see `CLAUDE.md § Don't break these`. Never make them non-Optional retroactively.
- **`List[...]`** — never `null`; an empty list is `[]`.
- **Source tab** — the portal fragment (`detalhe.asp`, `abaInformacoes.asp`, …) the field is parsed from. A single process involves 1 `detalhe` + 9 tab fragments; see [`stf-portal.md § URL flow`](stf-portal.md#url-flow).
- **Extractor** — the pure-soup function that parses the field. Lives under `src/scraping/extraction/`.
- **Categorical values** are closed sets — every value emitted by the scraper is one of the listed labels (or `null`). Lists of values known to occur in practice (but not type-enforced) are marked "observed".

---

## Top-level schema at a glance

| Field                | Type                     | Source tab           | Extractor                 |
|----------------------|--------------------------|----------------------|---------------------------|
| `schema_version`     | `int`                    | stamped by scraper   | constant `SCHEMA_VERSION` |
| `incidente`          | `Optional[int]`          | listarProcessos.asp  | `extract_incidente`       |
| `classe`             | `str`                    | input (+ detalhe)    | `extract_classe`          |
| `processo_id`        | `int`                    | input                | —                         |
| `url`                | `Optional[str]`          | derived              | `_canonical_url(incidente)` |
| `numero_unico`       | `Optional[str]`          | detalhe.asp          | `extract_numero_unico`    |
| `meio`               | `Optional[Literal]`      | detalhe.asp          | `extract_meio`            |
| `publicidade`        | `Optional[Literal]`      | detalhe.asp          | `extract_publicidade`     |
| `badges`             | `List[str]`              | detalhe.asp          | `extract_badges`          |
| `assuntos`           | `List[str]`              | abaInformacoes.asp   | `extract_assuntos`        |
| `data_protocolo`     | `Optional[str]` (DD/MM/YYYY) | abaInformacoes.asp | `extract_data_protocolo`  |
| `data_protocolo_iso` | `Optional[str]` (YYYY-MM-DD) | derived          | `to_iso(data_protocolo)`  |
| `orgao_origem`       | `Optional[str]`          | abaInformacoes.asp   | `extract_orgao_origem`    |
| `origem`             | `Optional[str]`          | abaInformacoes.asp   | `extract_origem`          |
| `numero_origem`      | `Optional[List[str]]`    | abaInformacoes.asp   | `extract_numero_origem`   |
| `volumes`            | `Optional[int]`          | abaInformacoes.asp   | `extract_volumes`         |
| `folhas`             | `Optional[int]`          | abaInformacoes.asp   | `extract_folhas`          |
| `apensos`            | `Optional[int]`          | abaInformacoes.asp   | `extract_apensos`         |
| `relator`            | `Optional[str]`          | detalhe.asp          | `extract_relator`         |
| `primeiro_autor`     | `Optional[str]`          | derived from partes  | `extract_primeiro_autor`  |
| `partes`             | `List[Parte]`            | abaPartes.asp        | `extract_partes`          |
| `andamentos`         | `List[Andamento]`        | abaAndamentos.asp    | `extract_andamentos`      |
| `sessao_virtual`     | `List[dict]`             | repgeral JSON        | `extract_sessao_virtual_from_json` |
| `deslocamentos`      | `List[Deslocamento]`     | abaDeslocamentos.asp | `extract_deslocamentos`   |
| `peticoes`           | `List[Peticao]`          | abaPeticoes.asp      | `extract_peticoes`        |
| `recursos`           | `List[Recurso]`          | abaRecursos.asp      | `extract_recursos`        |
| `pautas`             | `Optional[List]`         | abaPautas.asp        | (not parsed; always `[]`) |
| `outcome`            | `Optional[OutcomeInfo]`  | derived              | `derive_outcome`          |
| `status_http`        | `int` (HTTP)             | detalhe.asp response | —                         |
| `extraido`           | `str` (ISO 8601)         | client clock         | —                         |

---

## Identity + classification fields

### `incidente: Optional[int]`

STF's internal, session-independent primary key for the process. All
tab fetches (`abaX.asp?incidente=N`) are keyed on this value — not on
`classe` + `processo_id`.

- **Source:** 302 redirect Location header from `GET /processos/listarProcessos.asp?classe=<C>&numeroProcesso=<N>`. Empty Location = `NoIncidente`, meaning STF has no record of that classe+numero (dead-zone sparse ID).
- **Preprocessing:** `extract_incidente` reads `<input id="incidente" value="N">` from the detalhe fragment. Validates `value.isdigit()` before casting.
- **Null when:** STF returns 200 with empty Location (see `filter_skip=True` behaviour documented in `rate-limits.md § CliffDetector`).

### `classe: str`

The procedural classe code (HC, ADI, RE, …). CNJ-standardised; see
[`stf-taxonomy.md § classe`](stf-taxonomy.md) for the full taxonomy.

- **Source:** primarily the input CSV. Also verifiable from `detalhe.asp` via `.processo-dados` div starting with "Classe:".
- **Categorical levels (observed in the codebase):** Writ family — `HC`, `MS`, `MI`, `HD`, `Ext`. Appeal family — `RE`, `ARE`, `AI`, `RHC`, `RMS`, `AgR`, `ED`, `EDv`. Action family — `ADI`, `ADC`, `ADO`, `ADPF`, `ACO`, `AO`, `Rcl`, `AP`, `Inq`. STF uses ~53 CNJ codes total; these are the ones referenced by `src/analysis/legal_vocab.CLASSE_OUTCOME_MAP`.
- **Preprocessing:** uppercase, no spaces. HC + trailing suffixes like `MC-AgR` live in the display identificacao, not in `classe`.

### `processo_id: int`

The per-classe sequence number. Carries leading-zero semantics only
in `numero_unico`; the scalar form is fine as an int.

- **Source:** input CSV.
- **HC range:** 1..270 994 as of 2026-04-16 (see [`process-space.md`](process-space.md)). Actual real-HC count: ~216 k (bimodal density).

### `numero_unico: Optional[str]`

CNJ's 20-digit unified process number: `NNNNNNN-DD.YYYY.J.OO.UUUU`
where `YYYY` is the year of filing. Useful for cross-court joins.

- **Source:** `detalhe.asp` `.processo-rotulo` element: "Número Único: 0004022-92.1988.0.01.0000".
- **Null when:** STF renders "Sem número único" for the process (older paper-era cases predating the CNJ unification). `extract_numero_unico` normalises both the literal string "Sem número único" and empty values to `None`.

### `meio: Optional[Literal["FISICO", "ELETRONICO"]]`

Whether the process is paper-based or digital.

- **Source:** `detalhe.asp` `.badge` elements with "Físico" or "Eletrônico" text.
- **Levels:** `"FISICO"` | `"ELETRONICO"` | `None` (neither badge present).
- **Preprocessing:** uppercased + ASCII-folded ("Eletrônico" → `"ELETRONICO"`).

### `publicidade: Optional[Literal["PUBLICO", "SIGILOSO"]]`

Whether the process is public (default) or sigiloso (sealed).

- **Source:** `detalhe.asp` `.badge` elements checked for "SIGILOSO" | "PÚBLICO" | "PUBLICO".
- **Levels:** `"PUBLICO"` | `"SIGILOSO"` | `None`.
- **Consequences of `SIGILOSO`:** partes names are redacted by STF, andamentos descriptions may be truncated. Don't treat a sigiloso case as data-equivalent to a public one.

### `badges: List[str]`

Flag-badges STF shows in red (`.badge.bg-danger`) on the detalhe
page. Blue/green badges duplicate `meio`/`publicidade` and are
intentionally excluded.

- **Source:** `detalhe.asp` `.badge.bg-danger` text content.
- **Observed values:** `"Criminal"`, `"Medida Liminar"`, `"Réu Preso"`, `"Maior de 60 anos"`, `"Benefício da Justiça Gratuita"`, `"Resolução 175 CNJ"`.
- **Preprocessing:** whitespace-normalised; empty strings filtered out.
- **HC-specific:** Most HCs carry `"Criminal"`. `"Réu Preso"` is a strong predictor of preliminar decisions. `"Maior de 60 anos"` invokes statutory priority under Lei 10.741/2003 art. 71.

---

## Information-tab fields (abaInformacoes)

### `assuntos: List[str]`

CNJ Tabela Processual Unificada subject hierarchy — pipe-separated
breadcrumbs. Multiple assuntos possible on cross-cutting cases.

- **Source:** `abaInformacoes.asp` `.informacoes__assunto` `<li>` elements.
- **Example:** `"DIREITO PROCESSUAL PENAL | Prisão Preventiva | Revogação"`.
- **Preprocessing:** whitespace-normalised. The pipe `|` is STF's rendering of nested levels — consumers that need structured hierarchy can split on ` | `.
- **HC-specific:** almost always starts with `"DIREITO PROCESSUAL PENAL"` or `"DIREITO PENAL"`. Third-level is the merits axis (`Prisão Preventiva`, `Tráfico`, `Recurso em Sentido Estrito`, …).

### `data_protocolo: Optional[str]`

Date the process was filed at STF. Format `DD/MM/YYYY`, Portuguese
locale.

- **Source:** `abaInformacoes.asp` `.processo-detalhes-bold` labelled "Data de Protocolo".
- **Preprocessing:** `extract_data_protocolo` returns the raw label value. Downstream consumers should `datetime.strptime(v, "%d/%m/%Y")` — no zero-padding enforcement observed on the wild field.
- **Null when:** older paper-era cases sometimes lack this label.

### `orgao_origem: Optional[str]`

Court or body the case came from. For HCs it's usually the appellate
court whose decision is under review (STJ, TRFs, TJs).

- **Source:** `abaInformacoes.asp` `span#orgao-procedencia` (preferred) or labelled "Órgão de Origem".
- **Observed values:** `"SUPREMO TRIBUNAL FEDERAL"` (originário), `"SUPERIOR TRIBUNAL DE JUSTIÇA"`, `"TRIBUNAL REGIONAL FEDERAL DA 4ª REGIÃO"`, `"TRIBUNAL DE JUSTIÇA DO ESTADO DE SÃO PAULO"`, etc.
- **HC-specific:** STJ dominates (~60 % of HC origins per hc-who-wins findings). TJs and TRFs follow.

### `origem: Optional[str]`

Geographic origin in `"<UF> - <City>"` format.

- **Source:** `abaInformacoes.asp` `span#descricao-procedencia` or labelled "Origem".
- **Example:** `"RJ - RIO DE JANEIRO"`.
- **Preprocessing:** STF usually normalises the state to its 2-letter UF code. City is uppercase.

### `numero_origem: Optional[List[str]]`

Origin court's case number(s). Multi-valued because a case can
aggregate several lower-court proceedings.

- **Source:** `abaInformacoes.asp` label "Número de Origem", comma-separated.
- **Preprocessing:** split on `,`, each value stripped. **Kept as strings** — leading zeros are meaningful in court-specific formats. HC 158802 has 7 origin numbers; ADI 2820 has 1.
- **Null when:** label absent. Empty string → `None`.

### `volumes`, `folhas`, `apensos: Optional[int]`

Physical-record counts STF tracks in `.processo-quadro` info boxes.
Meaningful for `meio="FISICO"` cases; `ELETRONICO` cases frequently
have `null` for all three.

- **Source:** `abaInformacoes.asp` `.processo-quadro` boxes labelled "VOLUMES", "FOLHAS", "APENSOS".
- **Preprocessing:** `extract_volumes` / `_folhas` / `_apensos` all delegate to `_quadro_value` which returns `int` only if the cell text is `.isdigit()`. Non-numeric renders → `None`.

---

## People fields

### `relator: Optional[str]`

The minister assigned to the case — writes the voto, sets the
rhythm. Central variable in most empirical analyses of STF.

- **Source:** `detalhe.asp` `.processo-dados` starting with "Relator(a):".
- **Preprocessing:** `"MIN. "` prefix stripped. Upper-case full name, e.g. `"GILMAR MENDES"`, `"CÁRMEN LÚCIA"`, `"LUIZ FUX"`.
- **Null when:** process has no assigned relator yet (rare; usually between distribution events).
- **Note:** `relator` is the *current* relator. Andamentos record distribuição / redistribuição events that carry the history.

### `primeiro_autor: Optional[str]`

Derived field — the name of the first party in `partes` whose `tipo`
matches `AUTHOR_PARTY_TIPOS` from `legal_vocab.py`. For HC, this
naturally surfaces the **paciente** (PACTE) before the **impetrante**
(IMPTE) because STF lists PACTE first.

- **Prefix match order:** `AUTOR`, `REQTE`, `RECTE`, `AGTE`, `PACTE`, `IMPTE`, `RECLTE`, `EMBTE`.
- **Logic:** `extract_primeiro_autor(partes)` scans `partes` in order; first match wins.
- **HC-specific:** `primeiro_autor` is **the prisoner / defendant**, not the lawyer who filed the HC. For "who filed" use `partes` and look for the IMPTE entry's `nome`.

### `partes: List[dict]`

Every named party in the case, each in its own dict. The HTTP
extractor reads `#todas-partes` which includes all lawyers and
amici curiae separately (9 entries for ADI 2820, 7 for HC 158802).

- **Source:** `abaPartes.asp` `#todas-partes` container, pairing `.detalhe-parte` (label) with `.nome-parte` (name).
- **Inner shape:** `{"index": int, "tipo": str, "nome": str}`. Example: `{"index": 1, "tipo": "PACTE.(S)", "nome": "ROBERTO RZEZINSKI"}`.
- **Common `tipo` values** (not exhaustive):
  - `PACTE.(S)` — paciente (HC/MS) — subject of the writ
  - `IMPTE.(S)` — impetrante (HC/MS/MI) — the lawyer or party who filed
  - `AUTOR(A)(S)` — author (generic filings)
  - `REQTE.(S)` — requerente (ADI/ADC/ADPF/ADO/petitions)
  - `RECTE.(S)` — recorrente (RE/ARE/ED)
  - `AGTE.(S)` — agravante (AI/AgR)
  - `RECLTE.(S)` — reclamante (Rcl)
  - `EMBTE.(S)` — embargante
  - `PROC.(A/S)(ES)` — procurador (lawyer/prosecutor)
  - `ADV.(A/S)` — advogado (private defense lawyer)
  - `COATOR(A/S)` — the authority the HC is filed against
  - `AM. CURIAE` — amicus curiae
  - `INTDO.(A/S)` — interessado (ADI: government body whose law is challenged)
- **HC-specific:** Order matters. A standard HC presents `PACTE` first, `IMPTE` second, `COATOR` third. A PACTE's name is the prisoner; the IMPTE is typically the defense attorney (when self-filed) or the same as PACTE (when the prisoner files pro se). Multiple `PROC` / `ADV` entries list the full legal team.
- **Gotcha:** `#todas-partes` vs `#partes-resumidas` — we use the former. `#partes-resumidas` collapses multi-lawyer groups into "E OUTRO(A/S)" and drops PROC on HC. See the CLAUDE.md gotcha at `extract_partes`.

---

## Event-list fields

### `andamentos: List[dict]`

Every procedural step STF logs (distribution, decisions, transfers,
filings). Time-ordered by `data`, but **indexed newest-first**
(`index_num=len(list)` at the top).

- **Source:** `abaAndamentos.asp` `.andamento-item` divs.
- **Inner shape (`Andamento`):** `{"index_num": int, "data": "DD/MM/YYYY", "data_iso": Optional[str], "nome": str, "complemento": Optional[str], "julgador": Optional[str], "link_descricao": Optional[str], "link": Optional[AndamentoLink]}`.
- **Field meanings:**
  - `index_num` — reverse-chronological index. `index_num=60` is the newest event of a 60-event case; `index_num=1` is the filing.
  - `data` — event date, display format `DD/MM/YYYY` (sometimes with trailing `" às HH:MM"`).
  - `data_iso` — ISO companion `YYYY-MM-DD`, derived by `to_iso(data)`. Use this for sorting, range filters, `datetime.fromisoformat`.
  - `nome` — event type, uppercase. Examples: `"AUTUADO"`, `"DISTRIBUÍDO AO MIN. GILMAR MENDES"`, `"CONCLUSOS AO RELATOR"`, `"DECISÃO MONOCRÁTICA"`, `"BAIXA AO ARQUIVO DO STF"`.
  - `complemento` — free-text body of the event. Where decisão content, legal citations, parte references live. Often null for administrative events.
  - `julgador` — the minister who authored the event, where applicable (decisões, despachos).
  - `link` — `{"url": str, "text": Optional[str]}` or `None`. URL is joined against `https://portal.stf.jus.br`; `text` is populated later by the PDF-enrichment pass.
  - `link_descricao` — anchor text, uppercased.
- **HC-specific:** The key events are `DECISÃO MONOCRÁTICA`, `ACÓRDÃO`, `BAIXA AO ARQUIVO DO STF`. Majority of HCs terminate with a monocrática. See [`andamentos-classifier-gaps.md`](andamentos-classifier-gaps.md) for the classifier gaps the HC analysis has to work around.
- **PDF extraction:** `link` → PDF URL → downloaded by `scripts/baixar_pecas.py` to `data/cache/pdf/<sha1(url)>.pdf.gz` → text extracted by `scripts/extrair_pecas.py --provedor {pypdf|mistral|chandra|unstructured}` into `<sha1>.txt.gz` (+ `<sha1>.extractor` sidecar, + `<sha1>.elements.json.gz` for providers that emit element lists). Read text via `src.utils.pdf_cache.read(url)`.

### `deslocamentos: List[dict]`

Physical/electronic document transfers between STF sectors and
external courts. Mostly meaningful for `meio="FISICO"` cases.

- **Source:** `abaDeslocamentos.asp` `.lista-dados` rows.
- **Inner shape (`Deslocamento`):** `{"index_num": int, "guia": str, "recebido_por": Optional[str], "data_recebido": Optional[str] "DD/MM/YYYY", "data_recebido_iso": Optional[str] "YYYY-MM-DD", "enviado_por": Optional[str], "data_enviado": Optional[str] "DD/MM/YYYY", "data_enviado_iso": Optional[str] "YYYY-MM-DD"}`.
- **`guia`** — STF's tracking number for the shipment. Often empty string `""` (not `None`) when STF rendered a guia-less transfer.
- **`*_iso`** — ISO companion for each date, derived by `to_iso`. Null when the display field is null or unparseable.

### `peticoes: List[dict]`

Petitions filed in the case. Separate from `andamentos` because
petitions get their own event thread before a relator acts on them.

- **Source:** `abaPeticoes.asp` `.lista-dados` rows.
- **Inner shape (`Peticao`):** `{"index": int, "id": str, "data": "DD/MM/YYYY", "data_iso": Optional[str], "recebido_data": Optional[str] "DD/MM/YYYY HH:MM:SS", "recebido_data_iso": Optional[str], "recebido_por": Optional[str]}`.
- **Key difference from `andamentos`:** has an STF-assigned `id` (e.g. `"47384/2020"`) referenced from andamento complementos.
- **`*_iso`** — ISO companions stripped to `YYYY-MM-DD` (trailing time discarded).

### `recursos: List[dict]`

Internal recursos (AgR, ED, EDv) filed within the same process.

- **Source:** `abaRecursos.asp` `.lista-dados` rows.
- **Inner shape (`Recurso`):** `{"id": int, "data": Optional[str]}`.
- **Note on key name:** uses `"id"` (not `"index"`) — GT schema convention; don't change it without updating fixtures.
- **`data` is a label, not a date.** Historically misnamed: the value is the recurso-type string (e.g. `"AG.REG. NA MEDIDA CAUTELAR NO HABEAS CORPUS"`, `"EMB.DECL. NA AÇÃO CÍVEL ORIGINÁRIA"`). No `*_iso` companion — don't try to parse it as DD/MM/YYYY.

### `pautas: Optional[List]`

Hearing / voto scheduling. **Fetched but not parsed** — HTTP path
always emits `[]` (matches Selenium behaviour). Parsing this would
require touching `abaPautas.asp` which the research question hasn't
needed yet.

- **Note:** ACO 2652 fixture has `null`; the other five fixtures have `[]`. Known inconsistency; don't treat as a bug (see [`performance.md § Ground-truth parity`](performance.md)).

---

## `sessao_virtual: List[dict]` — async plenário virtual sessions

STF's asynchronous voting platform (expanded 2016, 2020). Each
entry is one listaJulgamento (a case can appear in multiple sessions,
e.g. medida cautelar + merits). Populated only for cases that went
through PV; otherwise `[]`.

- **Source:** `sistemas.stf.jus.br/repgeral/votacao` JSON endpoints (not the `abaSessao.asp` fragment — that's a JS template). Two/three endpoints: `?oi=<incidente>` lists the objeto-incidentes; `?sessaoVirtual=<id>` returns listasJulgamento per oi; `?tema=<N>` adds Tema / Repercussão Geral data when applicable.
- **Inner shape:** `{"metadata": {...}, "voto_relator": str, "votes": {...}, "documentos": {...}, "julgamento_item_titulo": str}`.

### `sessao_virtual[i].metadata`

```json
{
  "relatora": "MIN. GILMAR MENDES",
  "órgão_julgador": "Segunda Turma",
  "lista": "137-2020",
  "processo": "HC 158802 MC-AgR",
  "data_início": "10/04/2020",
  "data_prevista_fim": "17/04/2020"
}
```

### `sessao_virtual[i].voto_relator`

Short text of the relator's recommendation (`"Nega agravo regimental
do MPF."`, `"Concede a ordem."`, etc.). Key input to `derive_outcome`
— `derive_outcome` scans the **last** session's voto_relator first.

### `sessao_virtual[i].votes`

Categorised vote dict. Ministers are listed under their vote category:

```json
{
  "relator": ["MIN. GILMAR MENDES"],
  "acompanha_relator": [],
  "diverge_relator": [],
  "acompanha_divergencia": [],
  "pedido_vista": ["MIN. EDSON FACHIN"]
}
```

- **Categories emitted:** `relator`, `acompanha_relator`, `diverge_relator`, `acompanha_divergencia`, `pedido_vista`.
- **Source code mapping:** `tipoVoto.codigo` 9 → `acompanha_relator`, 7 → `diverge_relator`, 8 → `acompanha_divergencia`. Codes 1–6 (suspeito, impedido, ressalva, etc.) are **intentionally dropped** for Selenium parity — see `sessao.py::_VOTE_CATEGORY`.
- **Known gap:** vote categories are partial — a minister who voted "com ressalva" will not appear. See [`stf-portal.md § sessao_virtual`](stf-portal.md#sessao_virtual--not-from-abasessao).

### `sessao_virtual[i].documentos`

Key-value map of document-type → URL or extracted text. Populated
with URLs on first write; PDF text is swapped in by
`resolve_documentos` when a `pdf_fetcher` is injected.

- **Keys observed:** `"Relatório"`, `"Voto"`, `"Voto Vista"`, `"Voto Vencido"`, sometimes minister descriptions.
- **Values are mixed types:** either raw PDF text (success) or a URL starting with `https://` (fetch failed, kept for retry). Consumers must check `value.startswith("https://")` before treating as text.

### Tema (Repercussão Geral) branch

When the process carries a `tema`, an additional entry is prepended
with a different shape:

```json
{
  "tipo": "tema",
  "tema": 1020,
  "titulo": "...",
  "data_inicio": "...",
  "data_fim_prevista": "...",
  "classe": "ARE",
  "numero": "NNN",
  "relator": "MIN. ...",
  "votos": [{"ministro": "...", "QC": "...", "RG": "...", "RJ": "..."}]
}
```

Mixed-shape lists are unusual; consumers should check for `"tipo":
"tema"` before assuming the ADI shape.

### Why `sessao_virtual` is in `src.sweeps.diff_harness.SKIP_FIELDS`

Captured ground-truth fixtures have inconsistent shapes (Selenium-era
capture sometimes emits different keys), so parity diffs false-positive.
Do not try to diff this field.

---

## Derived verdict field

### `outcome: Optional[OutcomeInfo]`

Coarse verdict plus provenance. Shape:

```python
OutcomeInfo = TypedDict("OutcomeInfo", {
    "verdict": str,                                   # one of OUTCOME_VALUES
    "source": Literal["sessao_virtual", "andamentos"],
    "source_index": int,                              # which record matched
    "date_iso": Optional[str],                        # YYYY-MM-DD of that record
})
```

Derived from two sources in order:

1. **`sessao_virtual[-1].voto_relator`** — the last session's voto text. Regex-matched against `VERDICT_PATTERNS` in `src.analysis.legal_vocab`. `source_index` is the index within `sessao_virtual`; `date_iso` comes from `metadata.data_início`.
2. **Andamentos fallback** — concatenated `nome + complemento` of each event, scanned with the same patterns. `source_index` is the matching andamento's `index_num`; `date_iso` is the andamento's own `data_iso`.

First match wins; `None` means no pattern matched (pending case, liminares only, or parser gap).

**Reading the verdict only.** The coarse label is under `.verdict`:
```python
item["outcome"]["verdict"] if item["outcome"] else None
```

**Recognized labels (all of `OUTCOME_VALUES`):**

| label                | classe family | meaning                                          |
|----------------------|---------------|--------------------------------------------------|
| `concedido`          | writ (HC/MS/MI/HD/Ext) | ordem concedida — paciente wins         |
| `concedido_parcial`  | writ          | ordem concedida em parte                         |
| `denegado`           | writ          | ordem denegada — paciente loses on merits        |
| `provido`            | appeal (RE/ARE/AI/RHC/RMS/AgR/ED/EDv) | appeal granted           |
| `provido_parcial`    | appeal        | provimento parcial                                |
| `nao_provido`        | appeal        | appeal denied                                    |
| `procedente`         | action (ADI/ADC/ADO/ADPF/ACO/AO/Rcl/AP/Inq) | direct action granted |
| `procedente_parcial` | action        | parcialmente procedente                          |
| `improcedente`       | action        | direct action denied                             |
| `nao_conhecido`      | any           | petition not admitted (procedural)               |
| `prejudicado`        | any           | moot / lost its object                           |
| `extinto`            | any           | extinguished without merits judgement            |

**FGV §b favourability partition** (project-wide win/loss definition,
adopted 2026-04-17):

- **Favourable:** `concedido`, `concedido_parcial`, `provido`, `provido_parcial`, `procedente`, `procedente_parcial`.
- **Unfavourable:** everything else in `OUTCOME_VALUES`.
- **Excluded from the denominator:** `None` outcomes (pending / parser gap).

See `src/analysis/legal_vocab.FGV_FAVORABLE_OUTCOMES` and
[`hc-who-wins.md § Research question`](hc-who-wins.md).

**Per-classe legal outcome universe** pinned in
`CLASSE_OUTCOME_MAP`. An HC can only end in a writ-family outcome plus
universal terminators; an RE can only end in an appeal-family outcome
plus universal terminators. Enforced by
`tests/unit/test_classe_outcome_map.py`.

---

## Plumbing fields

### `url: Optional[str]`

Canonical portal URL for the process, derived from `incidente`:
`https://portal.stf.jus.br/processos/detalhe.asp?incidente=<N>`. `None`
when `incidente` is null (dead-zone sparse ID). Lets a reader open
the case in a browser without reconstructing the URL.

### `status_http: int`

HTTP status of the primary `detalhe.asp` fetch. Almost always 200 in
practice; non-200 statuses typically don't survive into a saved item
(the sweep driver writes a `fail` record instead). Renamed from
`status` in v3 — the bare name was confusable with a case-status
field that readers expected.

### `extraido: str`

ISO 8601 client timestamp of when the item was assembled. Format:
`"2026-04-17T15:21:01.322582"` (local tz, microseconds). Useful for
detecting stale captures in a multi-day dataset.

---

## HC-specific usage patterns

Things that come up repeatedly in the HC research work but aren't
obvious from the schema:

- **Paciente name** is `primeiro_autor` (via PACTE matching), **not** `partes[0]` in general — though in practice STF orders PACTE first.
- **Defense lawyer** is in `partes` with `tipo="IMPTE.(S)"` when the lawyer files. If the paciente self-filed pro se, PACTE and IMPTE carry the same name.
- **Most HCs terminate monocraticamente** — look at `andamentos[i].nome` containing `"DECISÃO MONOCRÁTICA"`, then fetch `andamentos[i].link` to read the actual verdict text. `derive_outcome` already scans both sessao_virtual and andamentos for you.
- **`orgao_origem` is the court whose decision is under attack.** STJ dominates (>50 % of HC origins). TJs and TRFs follow.
- **`badges` → "Réu Preso"** strongly predicts requests for preliminar release. Usually appears with `assuntos` containing `"Prisão Preventiva"` or `"Prisão em Flagrante"`.
- **Multi-hearing (MC + merits) cases** appear as 2+ entries in `sessao_virtual`. `derive_outcome` takes the **last** one; if you want the MC outcome specifically, scan `sessao_virtual` with the match-index manually.
- **`numero_unico` may be `None` on pre-2008 cases** — CNJ unification post-dated some paper-era HCs. Don't use `numero_unico` as a primary join key against external datasets unless you've filtered to post-2008 filings.

---

## Inner-list schemas — quick reference

Empty lists (`[]`) for all fields below are valid and common (newly
filed case, cases without sessões virtuais, etc.).

```python
# partes[i]
{"index": int, "tipo": str, "nome": str}

# andamentos[i]
{
    "index_num": int,          # reverse-chrono; max = len(andamentos)
    "data": str,                # "DD/MM/YYYY"
    "nome": str,                # UPPERCASE event type
    "complemento": Optional[str],
    "julgador": Optional[str],
    "link_descricao": Optional[str],
    "link": Optional[str],      # absolute URL to PDF
}

# deslocamentos[i]
{
    "index_num": int,
    "guia": str,                # "" if no guia rendered
    "recebido_por": Optional[str],
    "data_recebido": Optional[str],
    "enviado_por": Optional[str],
    "data_enviado": Optional[str],
}

# peticoes[i]
{
    "index": int,
    "id": Optional[str],         # "NNNN/YYYY"
    "data": Optional[str],       # "DD/MM/YYYY"
    "recebido_data": Optional[str],
    "recebido_por": Optional[str],
}

# recursos[i]
{"id": int, "data": Optional[str]}

# sessao_virtual[i] — ADI-shape
{
    "metadata": {
        "relatora": str, "órgão_julgador": str, "lista": str,
        "processo": str, "data_início": str, "data_prevista_fim": str,
    },
    "voto_relator": str,
    "votes": {
        "relator": list[str], "acompanha_relator": list[str],
        "diverge_relator": list[str], "acompanha_divergencia": list[str],
        "pedido_vista": list[str],
    },
    "documentos": dict[str, str],   # value is URL or extracted text
    "julgamento_item_titulo": str,
}

# sessao_virtual[i] — Tema shape (when process carries a tema)
{
    "tipo": "tema", "tema": int, "titulo": str,
    "data_inicio": str, "data_fim_prevista": str,
    "classe": str, "numero": str, "relator": str,
    "votos": list[{"ministro": str, "QC": str, "RG": str, "RJ": str}],
    "julgamento_item_titulo": str,
}
```

---

## Worked example — HC 158802

Realistic "heavy" HC (included as ground-truth fixture):

```
classe             "HC"
processo_id        158802
numero_unico       "0073563-11.2018.1.00.0000"
meio               "ELETRONICO"
publicidade        "PUBLICO"
badges             ["Criminal", ...]                (3 entries)
assuntos           ["DIREITO PROCESSUAL PENAL | Prisão Preventiva | Revogação"]
data_protocolo     "21/06/2018"
orgao_origem       "SUPREMO TRIBUNAL FEDERAL"
origem             "RJ - RIO DE JANEIRO"
numero_origem      ["158802", ...]                  (7 entries)
volumes            1
folhas             null
apensos            null
relator            "GILMAR MENDES"
primeiro_autor     "ROBERTO RZEZINSKI"              (the paciente)
partes             7 entries (PACTE, IMPTE, COATOR, PROC, ...)
andamentos         60 entries
sessao_virtual     2 entries (MC + merits)
deslocamentos      20 entries
peticoes           7 entries
recursos           1 entry
pautas             []
outcome            "provido"                         (appeal granted — this was an AgR)
status             200
extraido           "2026-04-17T15:21:01.322582"
```

---

## Preprocessing quick-reference

| task                                | code                                                        |
|-------------------------------------|-------------------------------------------------------------|
| Parse `data_protocolo` / andamento date | `datetime.strptime(v, "%d/%m/%Y")`                      |
| Split `assuntos` hierarchy          | `value.split(" | ")`                                        |
| Unified number year → filing year   | `int(numero_unico.split(".")[1])` when not `None`           |
| Count merits decisions              | `len([a for a in andamentos if "DECISÃO" in (a["nome"] or "")])` |
| Pull lawyer names from partes       | `[p["nome"] for p in partes if p["tipo"].startswith(("IMPTE","ADV","PROC"))]` |
| Is a case pending                   | `item["outcome"] is None` (under FGV §b this is excluded from the denominator)  |
| Coarse verdict label                | `item["outcome"]["verdict"] if item["outcome"] else None`   |
| FGV favourable                      | `item["outcome"] and item["outcome"]["verdict"] in FGV_FAVORABLE_OUTCOMES` |
| Event date for sorting              | `datetime.fromisoformat(andamentos[i]["data_iso"])`         |
| Open in browser                     | `item["url"]` (or reconstruct from `incidente`)             |
| PDF text for andamento[i]           | `src.utils.pdf_cache.read(andamentos[i]["link"]["url"])`    |
| Session vote tally                  | `{k: len(v) for k,v in sessao_virtual[-1]["votes"].items()}` |

---

## Known schema inconsistencies

- **`pautas`: `null` vs `[]`** — ACO 2652 fixture has `null`; others have `[]`. HTTP path always produces `[]`. Not a bug; Optional in the schema.
- **`assuntos` text drift** — STF occasionally updates the assunto vocabulary (ACO 2652 has text the fixture hasn't updated). Noted in `performance.md`.
- **`sessao_virtual` shape differences** — HC's AgR session shape vs ADI's plenary session shape have the same keys but different typical population. The SKIP_FIELDS entry is there for a reason.
- **`guia` empty string vs `None`** — `deslocamentos[i].guia` is `""` when STF renders a guia-less row, not `None`. Different from every other Optional[str] field.

---

## Schema history

`SCHEMA_VERSION` lives in [`src/data/types.py`](../src/data/types.py) and is
stamped onto every `StfItem` by the scraper. Bump on every breaking
change; the renormalizer (`scripts/renormalize_cases.py`) dispatches on
missing / lower values and re-runs the current extractors against the
cached HTML fragments.

### v3 — 2026-04-18 (current)

Nested-list types promoted to TypedDicts, ISO-date companions added
everywhere dates live, outcome carries provenance, `status` renamed to
`status_http`, canonical `url` surfaced, and the per-process JSON is
now a bare dict (not a 1-element list).

| area                 | change                                               |
|----------------------|------------------------------------------------------|
| `partes` / `andamentos` / `deslocamentos` / `peticoes` / `recursos` | promoted from bare `List` to `List[Parte]` / `List[Andamento]` / … — see `src/data/types.py`. |
| dates                | `*_iso` companions on `andamentos[*].data`, `deslocamentos[*].data_recebido`, `deslocamentos[*].data_enviado`, `peticoes[*].data`, `peticoes[*].recebido_data`, plus top-level `data_protocolo_iso`. |
| `outcome`            | `Optional[str]` → `Optional[OutcomeInfo]` = `{verdict, source, source_index, date_iso}`. Provenance lets consumers disambiguate HC-main vs HC-AgR verdicts and sort by verdict date. |
| `status`             | **renamed** to `status_http` (HTTP-code semantics). |
| `url`                | **added** — canonical portal URL derived from `incidente`. |
| per-process JSON     | bare `dict` (was `[dict]`). Overwrite-on-save; use `.jsonl` for multi-record batches. |

**v2 → v3 migration.** `scripts/renormalize_cases.py` dispatches on
`schema_version` and re-runs the current extractors against cached
HTML — all the new fields fall out for free. Ground-truth fixtures
(`tests/ground_truth/*.json`) migrated in-place, not via the
renormalizer (different layout).

```bash
PYTHONPATH=. uv run python scripts/renormalize_cases.py --dry-run
PYTHONPATH=. uv run python scripts/renormalize_cases.py --workers 8
```

### v2 — 2026-04-18

Six breaking commits between 2026-04-17 and 2026-04-18; the
`schema_version` field itself landed in the same cycle.

| commit    | field                                    | change                                               |
|-----------|------------------------------------------|------------------------------------------------------|
| `1ae0920` | `html`                                   | **removed** (was raw detalhe HTML; ~50–200 KB/file)  |
| `45d86df` | `numero_origem`                          | `Optional[str]` → `Optional[List[str]]`              |
| `49abd8c` | `badges`                                 | keeps only `.badge.bg-danger`; duplicate `meio` / `publicidade` badges dropped |
| `ad7cafa` | `partes`                                 | reads `#todas-partes` instead of `#partes-resumidas` — every IMPTE lawyer listed separately, PROC preserved, amici curiae included |
| `e4200da` | `sessao_virtual[i].voto_relator`         | HTML stripped to plain text                          |
| `e4200da` | `sessao_virtual[i].documentos`           | values became `{"url": str, "text": Optional[str]}` (was a string: URL or extracted text, impossible to tell apart) |
| `f054979` | `andamentos[i].link`                     | became `{"url": str, "text": Optional[str]}` (was a bare URL string) |
| (this cycle) | `schema_version`                      | **added** as required `int` field                    |

**v1 → v2 migration.** Run `scripts/renormalize_cases.py` from the
repo root. Cases with cached HTML are rebuilt offline (~8 files/s
single-worker; linear with `--workers`). Cases without cache are
listed in `runs/active/renormalize_needs_rescrape.csv` for a
follow-up `scripts/run_sweep.py --resume` pass.

```bash
# Full coverage check (no writes).
PYTHONPATH=. uv run python scripts/renormalize_cases.py --dry-run

# Rebuild everything at ~2 h for 54k cases.
PYTHONPATH=. uv run python scripts/renormalize_cases.py --workers 8
```

### v1 — pre-2026-04-18

Implicit default for files with no `schema_version` key. Do not
consume these directly in analysis — the partes count is
undercount (PROC missing on HC, multi-lawyer IMPTE collapsed),
`andamentos[i].link` and `documentos` values are bare URL strings
that can't be distinguished from extracted-text entries by type,
and the raw `html` field inflates files by orders of magnitude.

---

## See also

- [`src/data/types.py`](../src/data/types.py) — the canonical TypedDict.
- [`src/scraping/extraction/`](../src/scraping/extraction/) — one module per fragment.
- [`src/analysis/legal_vocab.py`](../src/analysis/legal_vocab.py) — party-type prefixes, verdict patterns, FGV favourability partition, classe→outcome map.
- [`docs/stf-portal.md`](stf-portal.md) — URL flow, auth triad, field→source tab.
- [`docs/stf-taxonomy.md`](stf-taxonomy.md) — the 10 classification axes STF uses.
- [`docs/hc-who-wins.md`](hc-who-wins.md) — how these fields feed the HC research question.
- [`docs/andamentos-classifier-gaps.md`](andamentos-classifier-gaps.md) — known gaps in event-type classification relevant to HC work.
- [`tests/ground_truth/HC_158802.json`](../tests/ground_truth/HC_158802.json) — heaviest HC fixture; read it when you want to see a realistic populated shape.
