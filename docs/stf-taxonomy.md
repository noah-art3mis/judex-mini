# STF taxonomy — the axes a case can be classified along

Domain reference for the categorical dimensions used in STF empirical
work. Written for a non-lawyer: each axis is named, defined, and cross-
referenced to where (if anywhere) the value lands in our `StfItem`.

Most of these taxonomies are **standardised by CNJ** (Resolução 46/2007
— Tabelas Processuais Unificadas, TPU), so STF, STJ, TRFs share the
same classe and movimento codes. That is why `courtsbr/*` scrapers
generalise across courts.

See also:
- [`docs/stf-portal.md`](stf-portal.md) — where on the portal each axis is rendered.
- [`docs/data-layout.md`](data-layout.md) — where the scraped output lives.
- [`docs/hc-who-wins-lit-review.md`](hc-who-wins-lit-review.md) — how these axes are used as controls in empirical work.

Ten independent axes. Most papers cut along only 2–3 of them; confusing
the axes ("collegiate" vs "HC" vs "plenário") is the single most common
error when reading STF empirical papers.

## 1. `classe` — what kind of lawsuit (procedural form)

CNJ Tabela Processual Unificada. STF uses ~53 of the national codes.

- **Controle concentrado / abstrato** — challenges a law directly, no concrete victim: **ADI** (direta de inconstitucionalidade), **ADC** (declaratória de constitucionalidade), **ADO** (por omissão), **ADPF** (arguição de descumprimento de preceito fundamental).
- **Recursos** — someone lost below and is appealing: **RE** (recurso extraordinário), **ARE** (agravo em RE), **AI** (agravo de instrumento), **RHC** (recurso em HC), **RMS** (recurso em MS).
- **Original criminal** — STF is the trial court for authorities with "foro privilegiado": **AP** (ação penal), **Inq** (inquérito), **PET** criminal.
- **Garantias individuais / writs**: **HC** (habeas corpus — our focus), **MS** (mandado de segurança), **MI** (mandado de injunção), **HD** (habeas data).
- **Originária federativa**: **ACO** (ação cível originária — state vs state / union), **AO** (ação originária), **Rcl** (reclamação — "you disobeyed our binding precedent").
- **Regimentais / incidentais**: **AgR**, **ED** (embargos de declaração), **EDv** (embargos de divergência), **QO** (questão de ordem), **Ext** (extradição), **SL/SS/STA** (pedidos de suspensão).

Captured in `StfItem.classe`.

## 2. `órgão julgador` — which collegiate body decided

- **Plenário** — all 11 ministers; abstract review, high-salience cases.
- **Primeira Turma** — 5 ministers (rotates); appellate + original in criminal matters.
- **Segunda Turma** — 5 ministers (rotates); same role as 1ª.
- **Presidência** — monocratic acts by the chief justice (recesso, plantão).
- **Decisão monocrática** — a single minister (usually the *relator*) deciding alone under RISTF art. 21 and art. 192. **Majority of HC rulings.**

Rosevear 2024 **excludes monocrática**; we **include** it — that is why our 216 k HC backfill is not covered by their 2.23 M-vote dataset.

## 3. `decision mode` — how many judges signed off

- **Colegiada** — plenário or turma vote (a decision signed by 3+ ministers).
- **Monocrática** — relator alone.

Binary axis, orthogonal to `órgão julgador`: plenário can issue monocráticas via its president; turmas via the relator.

## 4. `rito` / deliberation mode — synchronous vs asynchronous

- **Síncrono** — old-style session, ministers present, televised since 2002 (plenário) / 2020 (turma).
- **Plenário Virtual (PV)** — asynchronous online platform, ministers upload votes within a window. Expanded 2016, again 2020 (COVID). Rosevear's key treatment variable.
- **Sessão por videoconferência** — COVID-era synchronous online, now rare.

Captured (sparsely) in `StfItem.sessao_virtual` when PV metadata is available.

## 5. `função jurisdicional` — what role the court is playing

Per Rosevear 2024:
- **Abstract / controle concentrado** — ADI, ADC, ADO, ADPF. ~1.5 % of docket but most politically prominent.
- **Appellate** — RE, ARE, HC, RMS, etc. ~78 % of collegiate docket.
- **Original** — AP, Inq, ACO, MS, Ext, Rcl. Trial-court role.

Orthogonal to `classe`: an HC can be appellate (from STJ) or original (filed directly against a high authority).

## 6. `procedimento especial` — special-track flags

- **Repercussão geral (RG)** — EC 45/2004; a RE needs demonstrated "general repercussion" to be heard. Each RG theme aggregates thousands of RE/ARE.
- **Súmula vinculante (SV)** — binding summary doctrine; creation and revision are their own procedures.
- **Tema de RG** — numeric identifier joining all cases under the same general-repercussion question.

Not yet captured in `StfItem`. Gap worth filling before the backfill — a Tema ID extractor would let us join across recurso classes.

## 7. `publicidade` — visibility regime

- **Público** — default.
- **Segredo de justiça** — family law, minors, selected criminal. Restricts what partes / andamentos / PDFs show publicly.
- **Sigilo decretado** — stronger variant in originária criminal (e.g. Inq 4781).

Captured in `StfItem.publicidade` via `judex/scraping/extraction/extract_publicidade.py`.

## 8. `meio` — physical vs electronic

- **Físico** — pre-2008 era, paper dossier.
- **Eletrônico** — post STF Portaria 360/2009, most new cases.

Affects whether PDFs are scanned images (needing OCR) vs. born-digital text. Matters massively for the `docs/pdf-sweeps/` pipeline — see `docs/pdf-sweeps/2026-04-17-top-volume-ocr/`. Captured in `StfItem.meio`.

## 9. `partes` — role taxonomy inside a case

Each process has typed actors — 10+ distinct roles, most visible in `abaPartes.asp`.

- **Originário de HC**: IMPTE (impetrante — filer), PACTE (paciente — person whose liberty is at stake), COATOR (the authority being accused of coercion), IMPDO (impetrado).
- **Controle concentrado**: REQTE (requerente), REQDO (requerido), AM. CURIAE (amicus curiae), INTDO (interessado).
- **Recursal**: RCRTE / RCRDO (recorrente / recorrido), EMBTE / EMBDO (embargante / embargado), AGTE / AGDO (agravante / agravado).
- **Original criminal**: AUTOR, RÉU, DENUNCIANTE (MPF).

Lawyer (ADV) links back to an **OAB** number (90 % coverage in HC per `docs/hc-who-wins-lit-review.md:41`). Captured in `StfItem.partes` list.

## 10. `assunto` / `matéria` — what the case is about (substantive subject)

CNJ Tabela de Assuntos — hierarchical, up to 5 levels. STF usually tags 1–3 per case.

- Direito Penal → Crimes contra o Patrimônio → Roubo → Roubo majorado
- Direito Constitucional → Controle de Constitucionalidade → ADI
- Direito Tributário → Impostos → ICMS

**Distinct from `classe`**: classe = procedural form, assunto = substantive subject. Captured in `StfItem.assuntos`.

## 11. `movimentos` / andamentos — the procedural timeline

CNJ Tabela de Movimentos — coded events. Examples: *autuado*, *distribuído por sorteio*, *conclusos ao relator*, *vista a*, *julgado procedente*, *baixa definitiva*. Each andamento has `codigo`, `data`, `descricao`, optional `link` to a PDF.

Rosevear 2024 extracts vote-level data *from andamentos* using "a deterministic algorithm" — the equivalent of our `judex/scraping/extraction/http.py` andamento parser.

Captured in `StfItem.andamentos` list.

## 12. `outcome` / resultado — who won

There is **no standard STF code** for outcome; you derive it. Label space varies by classe:

- **Conhecido / não conhecido** — procedural: was the case even allowed?
- **Provido / improvido / parcial** — for recursos: partial wins are common.
- **Procedente / improcedente / parcial** — for ADI/ADC/ADPF.
- **Concedida / denegada / parcial / prejudicada / extinta** — for HC/MS.
- **Monocrática negativa de seguimento** — relator killed it alone.

Derived, not stored. Our `derive_outcome` logic does the equivalent of Rosevear's "deterministic algorithm."

## 13. `minister`-level dimensions — judge attributes

For each case, these travel with the *relator* and (for collegiate) each *voter*. None are in `StfItem` — they are external coding tables you join on minister name.

- **Ideologia**: progressive / conservative (Oliveira 2008, 2012; Martins 2018 codings).
- **Trajetória**: career judge / quinto constitucional / direct appointment.
- **Appointing president**: PT / PSDB / MDB / PL / PP etc.
- **Common-law exposure**: studied / researched in US/UK (Rosevear treatment).
- **Gender**.
- **Tenure on court**: freshman (<2 y) / mid / senior.
- **Ideal-point score**: Hudson & Hartmann 2016, Desposato et al. 2015 — published tables, no CSV.

## 14. `órgão de origem` — where the appealed decision came from

For *recursos* only: STJ / TRF1–6 / TJ(state) / TRE / Others. Lives on `abaInformacoes.asp` in the HTML.

Important case-mix control (CEM stratification variable per `docs/hc-who-wins-lit-review.md:72`). Currently only *partial* — lives as free text inside `StfItem.informacoes`. Gap worth filling before the backfill.

## 15. Temporal regimes — era flags

Three discontinuities Rosevear flags as treatment variables:

- **Pre- / post-EC 45 (2004)** — Judicial Reform Amendment: creates RG, SV, CNJ.
- **Pre- / post-TV Justiça** (2002 plenário, 2020 turma) — live broadcasting.
- **Pre- / post-Plenário Virtual expansion** (2016, 2020) — asynchronous deliberation.
- **Pre- / post-COVID** (March 2020) — remote everything.
- **Pre- / post-RISTF 2022 revision** — docket-handling rules.

Derived from `StfItem.data_autuacao` / decision dates.

---

## `StfItem` coverage matrix

| Axis                             | In `StfItem`? | Where                                       |
|----------------------------------|---------------|---------------------------------------------|
| classe                           | yes           | `classe`                                    |
| órgão julgador                   | partial       | inferable from `andamentos`                 |
| decision mode                    | derived       | via `voto_relator` + `andamentos`           |
| rito (PV vs síncrono)            | partial       | `sessao_virtual` if present                 |
| função jurisdicional             | derived       | from classe                                 |
| repercussão geral                | no            | would need its own extractor                |
| publicidade                      | yes           | `publicidade`                               |
| meio (físico/eletrônico)         | yes           | `meio`                                      |
| partes (typed roles)             | yes           | `partes` list                               |
| assunto                          | yes           | `assuntos`                                  |
| movimentos/andamentos            | yes           | `andamentos` list                           |
| outcome                          | derived       | `derive_outcome`                            |
| minister attributes              | no (external) | join on external coding tables              |
| órgão de origem                  | partial       | free text in `informacoes`                  |
| temporal regime                  | derived       | from `data_autuacao`                        |

**Gaps worth filling before the 216 k HC backfill:**
1. `repercussão_geral` — a Tema ID extractor.
2. `órgão_julgador` — explicit field, not inferred from andamento text.
3. `órgão_de_origem` — structured extractor over the free-text "informações" blob.

## Sources

- [CNJ Tabelas Processuais Unificadas (Resolução 46/2007)](https://www.cnj.jus.br/sgt/consulta_publica_classes.php)
- [CNJ Tabelas de Assuntos](https://www.cnj.jus.br/sgt/consulta_publica_assuntos.php)
- [RISTF consolidado](https://portal.stf.jus.br/textos/verTexto.asp?servico=legislacaoRegimentoInterno)
- [Rosevear et al. 2024 — open-access PDF](https://eprints.soton.ac.uk/496885/2/rosevear-et-al-2024-dissenting-votes-on-the-brazilian-supreme-court.pdf)
- [Corte Aberta taxonomies](https://portal.stf.jus.br/hotsites/corteaberta/)
