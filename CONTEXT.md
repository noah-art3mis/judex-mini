# judex-mini

A scraper and analytic toolkit for STF (Supremo Tribunal Federal, Brazilian Supreme Court) process data. Collects per-**processo** case files, downloads filings, extracts text, and serves the corpus via a DuckDB warehouse for legal-research and judicial-behavior analysis.

The glossary below is bilingual on purpose. Brazilian legal vocabulary stays in Portuguese (the language native to the domain and the codebase); English aliases appear on first use where they help an English-first reader, then disappear. Implementation-only terms (atomic state-write, Typer wrapper, four-file cache quartet, etc.) belong in `CLAUDE.md § Non-obvious gotchas`, not here.

## Language

### Legal vocabulary

**Processo** _(English alias on first use: case)_:
A single proceeding before the STF, identified by a `classe` (HC, ADI, RE, …) and a within-class `processo_id`. The unit of analysis for this project — one `StfItem` per processo, one JSON file under `data/source/processos/<classe>/`.
_Avoid_: process, lawsuit, suit

**Classe**:
The legal category of a **processo** (HC, ADI, ADPF, RE, …); determines its on-disk partition, URL path, and applicable procedural rules.
_Avoid_: type, kind, category

**HC** _(habeas corpus; English: writ of habeas corpus)_:
A **classe** invoked when someone alleges unlawful deprivation of (or threat to) personal liberty. The only **classe** present in the current corpus.

**Incidente**:
STF's portal-internal numeric ID for a **processo** — the `?incidente=N` URL parameter on every detail page. The **HTTP-layer handle**: used in URL construction, Referer headers, and redirect parsing.
_Avoid_: case ID, internal ID, STF ID

**Processo_id** _(número do processo)_:
The within-**classe** sequence number for a **processo** (e.g., the `118201` in "HC 118201"). The **storage- and human-layer handle**: appears in on-disk filenames (`<classe>_<processo_id>-<processo_id>.json`) and is the form humans say out loud.
_Avoid_: case number, process number

**Numero_unico**:
The CNJ-canonical cross-judiciary ID (format `NNNNNNN-DD.AAAA.J.TR.OOOO`, e.g., `0123456-78.2024.1.00.0000`). Optional on `StfItem`. **Operationally dead in this project** — the DataJud public API does not serve STF data, so the cross-judiciary link this ID would enable does not exist. Do not rely on it.

**Processo_id não alocado** _(English alias on first use: unallocated processo_id)_:
A **processo_id** for which STF's portal never bound an **incidente** — the `(classe, processo_id)` pair returns from `listarProcessos.asp` with no `incidente=<n>` in the redirect Location, signalling that the number was never used. STF's processo numbering space is sparse: numbers may be reserved-but-unused, withdrawn before distribution, or skipped by allocator gaps. A não-alocado **processo_id** is *not* a **processo** — no underlying case exists, so it has no **partes**, **andamentos**, or any other **processo**-bound concept. Discovered per-attempt during a **sweep** and recorded as a distinct terminal status (peer to `ok` / `fail` / `error`); confirmed across sweeps when ≥ 2 independent observations agree (with empty Location body, ruling out proxy soft-blocks) and persisted as a per-**classe** registry that the next sweep pre-filters against.
_Avoid_: morto, dead ID (informal — replaced by *não alocado*), processo inexistente, missing process

**Andamento**:
A row in the **processo**'s primary event timeline (`StfItem.andamentos`) — one step in the case's life, with a date, an event label (`nome`), optional detail (`complemento`) and `julgador`, and an optional `link` to a peça.
_Avoid_: event, step, movement, movimento, movimentação

**Sessão virtual**:
A virtual-plenary judgment session (`StfItem.sessao_virtual`) carrying session metadata, the voto do relator text, vote tallies (acompanha / diverge / pedido_vista), and a list of session-attached **documentos** (relatório, voto, etc.). Deliberation is asynchronous over a date window, distinguishing it from a physical plenary.
_Avoid_: session, virtual session, plenary session

**Petição** _(English: petition, motion)_:
An incoming protocol-numbered filing sent *to* the court (`StfItem.peticoes`) — has an `id`, protocol date, and receipt metadata, but no peça `link` (petição content is not exposed by the public portal as of the current scraper version).
_Avoid_: filing, motion, request

**Recurso** _(English: appeal)_:
A thin marker row (`StfItem.recursos`) recording an appeal against a prior decision in the **processo** — only `index` + `tipo` label (e.g., `AG.REG.`, `EMB.DECL.`). Substantive appeal content lives in the corresponding **andamento** + peça; an appeal's own decisional cycle may itself produce a separate **processo** with its own `incidente`.
_Avoid_: appeal record (a recurso row is *just* a marker — do not conflate with the underlying appeal **processo**)

**Deslocamento**:
A physical or logical transfer of the **processo** between bodies (`StfItem.deslocamentos`) — gabinetes, secretarias, sections — recording the transfer guide (`guia`), sender, receiver, and dates.
_Avoid_: transfer, routing event

**Pauta**:
A future court-calendar entry (`StfItem.pautas`) — the **processo** is on the agenda for an upcoming session; same shape as an **andamento** minus the peça `link`. Distinct from an actual deliberation event: a pauta says "will be considered on date X"; the consideration itself produces an **andamento** when it happens.
_Avoid_: agenda item, schedule entry

**Peça** _(English alias on first use: document)_:
A document filed in or attached to a **processo** — typically PDF, or RTF on the **DJe** surface. Referenced via URL from `andamentos[].link`, `sessao_virtual[].documentos`, or `publicacoes_dje[].decisoes[].rtf`. Text content for all surfaces is canonically cached at `data/derived/pecas-texto/<sha1(url)>.txt.gz`, deduped across surfaces and **processos**.
_Avoid_: filing, paper, exhibit

**Substantive peça** _(vs procedural)_:
A **peça** whose `andamento.link.tipo` label carries deliberative or argumentative content (PARECER, VOTO, DECISÃO, PETIÇÃO INICIAL, …), as opposed to procedural peças (CERTIDÃO, INTIMAÇÃO, COMUNICAÇÃO ASSINADA, …) that record routine case-management actions. The split is implemented as a tier-A/B/C system in `judex/sweeps/peca_classification.py`; the `--apenas-substantivas` flag drops tier C (~56% of andamento URLs in the HC corpus). The corresponding mapping for **sessão-virtual** `documentos[].tipo` and **DJe** `decisoes[].kind` is an open implementation question per [ADR-0001](docs/adr/0001-unify-peca-fetch-under-bytes-first-model.md).

**DJe** _(Diário de Justiça eletrônico)_:
The Brazilian federal judiciary's official electronic gazette, where decisions and publications are formally published. For a **processo**, the relevant surface is `StfItem.publicacoes_dje[]`, with each entry carrying RTF-formatted decision text under `decisoes[].rtf`.

**Apenso**:
A **processo** physically or logically attached to another **processo** for joint judgment — typically because both deal with the same factual matter or arise from the same proceeding. Apenso relationships create cross-**processo** **peça** duplicates (the same PARECER may appear under multiple incidentes); the `sha1(url)`-keyed cache silently dedupes them.
_Avoid_: attachment, annex

**Conexão**:
A logical relationship between **processos** with related issues, justifying joint judgment but without physical/logical attachment — looser than **apenso**, with similar cross-**processo** peça-duplication patterns.
_Avoid_: relation, link

**Parte** _(English alias on first use: party)_:
A named participant in a **processo** — listed in `StfItem.partes[]` with a `tipo` (role label) and a `nome` (free-string identifier). Includes lawyers, petitioners, respondents, public prosecutors, and institutional bodies. The raw `nome` field is unsafe for direct grouping or counting (see **Canonical lawyer**).
_Avoid_: party, participant

**ADV** _(advogado / advogada — lawyer)_:
A **parte** whose `tipo` is `ADV`. Represents a lawyer acting on behalf of another **parte**. The dominant **parte** kind for the project's analytic surface; ADV names range from individual lawyers (with OAB) to institutional bodies (Defensoria Pública). Always normalize via **Canonical lawyer**.

**IMPTE** _(impetrante — petitioner)_:
A **parte** whose `tipo` is `IMPTE` — the person filing the **HC** (typically the patient seeking the writ, or a co-petitioner filing on their behalf). Each IMPTE row corresponds to one filer; multi-IMPTE filings appear as separate rows. Note: a substantial fraction of IMPTE rows in the HC corpus carry sentinel `nome` values like `O MESMO` ("same as previous IMPTE") — never group on raw `nome`; route through `lawyer_canonical.classify` first.

**IMPDO** _(impetrado — respondent)_:
A **parte** whose `tipo` is `IMPDO` — the authority against whom the **HC** is filed (typically a court, judge, tribunal, or other state actor whose action allegedly threatens the patient's liberty).

**PROC** _(procurador / procuradoria)_:
A **parte** whose `tipo` is `PROC.(A/S)(ES)` — a representative (private or public) acting in a procedural capacity for another party (often a public-law body acting for the State).

**OAB** _(Ordem dos Advogados do Brasil)_:
The Brazilian bar association. Every licensed lawyer has an OAB registration with a state section, e.g., `OAB/SP 148022` (São Paulo, registration 148022) or `OAB-PE 48215` (Pernambuco). In STF data, OAB codes appear *inside* `parte.nome` strings in multiple formats — parentheticals (`(12345/SP)`, `(12345/SP) E OUTRO(A/S)`), inline (`OAB/SP 148022`, `OAB-PE 48215`), or absent entirely. Extract via `lawyer_canonical.canonical_lawyer(nome)`, never via ad-hoc regex.

**Canonical lawyer**:
The project's unified handle for one ADV/IMPTE name, computed by `judex.analysis.lawyer_canonical.classify(nome) -> LawyerEntry(kind, key, oab_codes)`. The `kind` field places the name into one of eight project-invented taxonomy buckets:

| `kind`          | Meaning                                                                              |
|-----------------|--------------------------------------------------------------------------------------|
| `sentinel`      | "O MESMO" / "OS MESMOS" family — placeholder meaning "same as previous IMPTE"         |
| `placeholder`   | "SEM REPRESENTAÇÃO NOS AUTOS" — explicitly no representation                            |
| `pro_se`        | "EM CAUSA PROPRIA" — the patient represents themselves                                  |
| `institutional` | Defensoria Pública, AGU, PGR, MP — accent-insensitive institutional-prefix match        |
| `juridical`     | Sindicato, instituto, federação, law firm — collective non-individual juridical body    |
| `court`         | Juízo, juiz, relator, desembargador appearing as a party                                |
| `with_oab`      | Real lawyer with one or more OAB codes (any extraction format)                          |
| `bare`          | Real-looking individual name with no OAB code and not matching any other category        |

`sentinel` and `placeholder` return `key=""` so callers filter with `if not key: continue`; all other kinds return a non-empty grouping `key`. Treat the eight `kind` values as the project canon — do not invent ad-hoc lawyer classifiers.

**Outcome**:
The derived terminating decision of a **processo** — `OutcomeInfo { verdict, source, source_index, date_iso }`, computed by `judex.scraping.extraction.outcome.derive_outcome`. `source` ∈ {`sessao_virtual`, `andamentos`} and `source_index` points back to the originating row, so analysis can re-validate the verdict against the live source on warehouse rebuild. Returns `None` for interlocutórias / liminares (they match no **Verdict** pattern, so the upstream code emits no Outcome).
_Avoid_: result, decision (too generic — say "outcome" or "verdict")

**Verdict**:
The normalized label inside an **Outcome**, drawn from `judex.analysis.legal_vocab.VERDICT_PATTERNS`. Patterns are tried in declaration order; the first regex match wins, and negative-side patterns are listed first so they don't lose to positive overlaps (`denego` before `concedo`). Full label set:

| Label                  | Meaning                                                                                  | Family    |
|------------------------|------------------------------------------------------------------------------------------|-----------|
| `concedido`            | Ordem concedida (patient wins)                                                            | writ      |
| `concedido_parcial`    | Ordem concedida em parte                                                                  | writ      |
| `denegado`             | Ordem denegada (patient loses on merits)                                                  | writ      |
| `nao_conhecido`        | Petition not admitted; covers monocratic `nego seguimento` per RISTF art. 21 §1            | universal |
| `prejudicado`          | Moot / perda de objeto                                                                    | universal |
| `extinto`              | Extinção sem resolução de mérito                                                          | universal |
| `provido`              | Recurso provido (appeal granted) — RE / ARE / AI / RHC / RMS / AgR / ED / EDv             | appeal    |
| `provido_parcial`      | Provimento parcial                                                                        | appeal    |
| `nao_provido`          | Recurso não provido                                                                       | appeal    |
| `procedente`           | Ação julgada procedente — ADI / ADC / ADPF / ACO / AO / Rcl / AP / Inq                    | action    |
| `improcedente`         | Ação julgada improcedente                                                                 | action    |
| `procedente_parcial`   | Parcialmente procedente                                                                   | action    |

The set is exposed as `OUTCOME_VALUES` (frozenset). The label–classe reachability matrix lives in the same module and gates which labels can legitimately terminate which **classe**.

**FGV partition** _(favorable vs unfavorable)_:
The project's canonical win/loss split for **Verdict** labels, adopted 2026-04-17. Sourced from Falcão, Moraes & Hartmann, *IV Relatório Supremo em Números — O Supremo e o Ministério Público* (FGV DIREITO RIO, 2015), §b "A Taxa de Sucesso do MP", p. 50. Every "success rate" / "grant rate" report the project publishes uses this split; pass `FGV_FAVORABLE_OUTCOMES` to `grant_rate_table(..., win_labels=)`.

| Side          | Labels                                                                                                | Set name                       |
|---------------|-------------------------------------------------------------------------------------------------------|--------------------------------|
| Favorable     | `concedido`, `concedido_parcial`, `provido`, `provido_parcial`, `procedente`, `procedente_parcial`     | `FGV_FAVORABLE_OUTCOMES`       |
| Unfavorable   | `denegado`, `nao_provido`, `improcedente`, `nao_conhecido`, `prejudicado`, `extinto`                    | `FGV_UNFAVORABLE_OUTCOMES`     |

The two sets exhaustively partition `OUTCOME_VALUES`. Two non-obvious framing choices to flag:

- **`nao_conhecido` is coded as unfavorable** — following FGV. The petitioner came for relief and didn't receive it; procedural non-admission is treated as a loss. A different study could plausibly recode it; do so deliberately, not by accident.
- **Interlocutórias and liminares are excluded upstream** — `derive_outcome` returns `None` for non-terminating decisions, so they never enter the partition. Success-rate denominators count only terminating decisions.

Justification: `docs/hc-who-wins.md` § "Research question".

### Operational vocabulary

**Sweep**:
A single execution of `varrer-processos`, `baixar-pecas`, or `extrair-pecas`, producing a directory of artifacts (`<out>/report.md`, `<out>/sweep.log.jsonl`, `<out>/sweep.state.json`, …). The sweep is the project's unit of operational work and the unit of cost forecasting (`--prever`).
_Avoid_: run, job, batch — `run_dir` is a CLI artifact path, not a parallel concept

**Shard**:
One of N parallel children spawned by a sharded sweep, each with its own per-shard CSV partition, proxy pool, and state file (`pdfs.state.json` / `sweep.state.json`). Shards write to per-shard report directories (`<out>/shard-<letter>/`); the launcher writes `<out>/shards.pids`. Sharding is the proxy-pool-aware mode of running a sweep at >1000 targets.

**Direct-IP mode** _(vs sharded mode)_:
Running a sweep from a single source IP without proxy rotation. Throughput plateaus at the **WAF** ceiling regardless of CPU. Cost: $0; wall: longer (~12-13h for a year-of-HC peça sweep). Preferred when the proxy pool is stale or has not been validated recently.

**Sharded mode** _(vs direct-IP)_:
Running N parallel **shards**, each with its own proxy URL pool. Spreads load across N IPs so each draws below the per-IP **WAF** ceiling; total throughput scales near-linearly until the pool itself starts erroring. Cost: residential-proxy bandwidth (~$3.65/GB at the current contract); wall: shorter (~1h for the same sweep that takes 12.5h direct-IP). Preferred for sweeps >1000 targets when the proxy pool is fresh.

**WAF** _(web application firewall — at `portal.stf.jus.br` and `sistemas.stf.jus.br`)_:
The rate-limit boundary STF interposes in front of `/processos/*` (case JSON) and `sistemas.stf.jus.br/pdf/*` (peça bytes). Throttles by per-IP reputation; **responds with HTTP 403, not 429**. The block clears within minutes. Non-browser User-Agents (`curl/*`) get permanent 403. Process-level pacing (`--throttle-sleep`) does not drain the per-IP reputation counter — only cooling time + IP rotation does.
_Avoid_: rate limiter, throttle (those are mechanisms; "WAF" names the boundary)

**Regime**:
The state of the live throttle relationship between a running **sweep** and the **WAF**, computed by `judex.utils.cliff_detector`. Four states form a state machine: `warming` (cold start, polite ramp) → `under_utilising` (steady-state below ceiling) → `approaching_collapse` (rising 403 rate, controller demoting) → `collapse` (sustained 403 / failure storm; controller cools and re-promotes). Read live with `judex probe --watch`; reconstruct post-hoc with `judex analisar-regimes <run_dir>`.

**Cliff**:
A sudden throughput collapse during a **sweep** — typically a transition from `under_utilising` through `approaching_collapse` to `collapse` within minutes. Triggers the cliff detector to demote the **regime**; the controller cools the WAF reputation by reducing concurrency or pausing. Cliffs are the load-bearing failure mode the regime state machine exists to handle.

**Saturation tail**:
The slow-rate tail observed in hours 8–13 of long **sweeps** (anchored on the HC 2024 + HC 2023 overnight runs). TLS-handshake degradation produces SSL-EOF errors at increasing frequency; rather than a sharp **cliff**, throughput trickles down. Default action: wait 30 minutes for the controller to demote → cool → re-promote. Killing the sweep throws away TLS-layer reputation that is already cooling.

**Coleta** _(English alias on first use: total run / pipeline run)_:
The full backfill of a (**classe**, processo_id range) — six **sweeps** in per-stage interleave: forward `varrer-processos` → `varrer-retry` → forward `baixar-pecas` → `baixar-retry` → forward `extrair-pecas` → `extrair-retry`. Each retry stage is scoped to the prior forward stage's **transient residual** (read through the `error_triage` classifier). Cap of 2 retry cycles per stage with early-exit when the residual is empty or stops shrinking. The unit of canonical operator work for backfilling a year-of-HC; orchestrated by `judex coletar`.
_Avoid_: backfill (overloaded — used both for the run-dir naming convention and for ad-hoc per-stage replays), pipeline (too generic)

**Error triage**:
The classification of a **sweep**'s non-ok rows into one of `transient` / `terminal` / `cross_stage` / `ok` by `judex.sweeps.error_triage.classify_error(stage, row)`. Driven by `(status, error_substring)` — status alone is too coarse (`varrer-processos`'s `fail` row covers both *processo_id não alocado* and transient WAF blocks). Only `transient` rows are replayed in a **coleta**'s retry stage; `terminal` is dropped permanently, `cross_stage` is reported as out-of-scope for this **coleta**.

**Transient residual**:
The count of `transient`-classified rows still failing after a stage's retry cap (2 cycles) is exhausted. Reported per stage in the **coleta**'s `REPORT.md`. Not the same as raw error count — terminal rows (e.g., `processo_id não alocado` at varrer, real `404` at baixar) are excluded.

**Cross-stage residual**:
Rows that are terminal at the current **sweep** stage but whose underlying failure is upstream — concretely, `no_bytes` rows surfaced by `extrair-pecas` that mean `baixar-pecas` did not deliver bytes. Surfaced as a count in the `coletar` `REPORT.md`. Not auto-recovered within a **coleta** (would require a second `baixar-retry` after the cap was already exhausted); the operator drains manually via `baixar-pecas --retentar-de` if motivated.

**Transient gate**:
A per-stage upper bound on transient rate above which `judex coletar` aborts mid-chain rather than firing retry cycles or advancing to the next stage. Default 2% per stage (anchored on the 0.04–7.3% range of healthy transient rates observed across HC 2025/2026 backfills, with the HC 2026 extrair `provider_error` outlier treated as anomalous). Trip indicates a systemic issue — proxy pool dead, cookies/WAF rolling block, Fly OCR saturated — that retries cannot fix and that produces silently-incomplete downstream artifacts if ignored. Resume via `judex coletar --retomar` after the systemic issue is fixed.

**Run quality** _(of a coleta)_:
A post-hoc classification of a finished **coleta** by per-stage **transient residual**:

| Quality       | Per-stage transient residual    | Operator action                                       |
|---------------|----------------------------------|-------------------------------------------------------|
| `clean`       | all stages = 0                   | none — chain converged                                |
| `acceptable`  | all stages ≤ 1%                  | none required; manual drain optional                  |
| `degraded`    | any stage 1–5%                   | consider tail-drain via per-stage `--retentar-de`     |
| `broken`      | any stage > 5%                   | systemic problem; investigate before re-running       |

Distinct from the pre-flight **transient gate** (which aborts a running chain): **run quality** grades a finished chain. A `broken` outcome on a chain that *did* finish (gate didn't trip mid-flight) means transients accumulated only in the retry tail — a different failure mode than a forward-pass collapse.

## Bridges

**Peça → text cache.**
Every **peça**'s text content — regardless of which `StfItem` surface references it (`andamentos[].link.url`, `sessao_virtual[].documentos[].url`, `publicacoes_dje[].decisoes[].rtf.url`) — lives in `data/derived/pecas-texto/<sha1(url)>.txt.gz`, deduped by URL across both surfaces and **processos**. Reads always go through `peca_cache.read(url)`; the surface a URL came from is invisible to the analytic layer. Cross-**processo** dedup via **apenso** / **conexão** works through this same shared key.

## Relationships

For a single **processo**:
- A **processo** has exactly one **classe** and one **incidente** (STF-internal int); within its classe, one **processo_id**; optionally one **numero_unico** (CNJ — operationally dead).
- A **processo** has zero or more **partes** (each with a `tipo` and a raw `nome`).
- A **processo** has zero or more **andamentos**, plus parallel activity surfaces (**sessão virtual**, **petição**, **recurso**, **deslocamento**, **pauta**).
- A **processo** has zero or more **peças** referenced from three URL surfaces (`andamentos[].link.url`, `sessao_virtual[].documentos[].url`, `publicacoes_dje[].decisoes[].rtf.url`).
- A **processo** has at most one derived **outcome** (`None` while no terminating **verdict** has fired).

Across **processos**:
- An **apenso** or **conexão** relationship links two **processos**; their **peças** may appear under both — the `sha1(url)`-keyed cache dedupes silently.
- A **canonical lawyer** key (from `lawyer_canonical.classify`) groups **partes** with the same individual or institution across many **processos**.

Operational:
- A **sweep** is one execution of `varrer-processos`, `baixar-pecas`, or `extrair-pecas`, producing one output directory.
- A **sharded mode** sweep spawns N **shards**; **direct-IP mode** runs unsharded against the **WAF** ceiling.
- A running **sweep**'s **regime** evolves `warming` → `under_utilising` → `approaching_collapse` → `collapse`; a **cliff** is the rapid-traversal failure case, a **saturation tail** is the slow-trickle one.

## Example dialogue

> **Analyst:** "I'm looking at one HC — how do I find the petitioner's lawyers?"
> **Maintainer:** "Filter the **processo**'s `partes[]` where `tipo == "ADV"`, then route each `nome` through `lawyer_canonical.classify`. The raw `nome` is unsafe — it carries OAB parentheticals, "O MESMO" sentinel rows, and accent-missing institutional variants. `LawyerEntry.kind` will land in one of the eight buckets — `with_oab` for an individual lawyer with an OAB code, `institutional` for the Defensoria Pública / AGU / PGR / MP family, `sentinel` for the placeholder rows you'll want to drop."
>
> **Analyst:** "And the verdict on the case?"
> **Maintainer:** "Read `outcome.verdict`. For HC the labels you'll see are mostly `concedido`, `denegado`, `nao_conhecido`. `None` means the **processo** hasn't terminated yet — or the scraper didn't find a terminating **verdict** among the **andamentos** and **sessão virtual** entries."
>
> **Analyst:** "I want a grant rate by year."
> **Maintainer:** "Use the **FGV partition**. Pass `FGV_FAVORABLE_OUTCOMES` to `grant_rate_table(..., win_labels=)`. That treats `concedido` / `concedido_parcial` as wins and codes `nao_conhecido` as a loss — defensible per FGV (2015), but a non-obvious framing choice you should know about."
>
> **Analyst:** "Some **peças** seem to be missing PDF bytes — only text is cached?"
> **Maintainer:** "Right. Today only **andamento**-attached **peças** keep `<sha1>.pdf.gz` in the cache; **sessão virtual** documentos and **DJe** RTFs are fetched-and-extracted in one step at scrape time, so the bytes aren't preserved. ADR-0001 records the plan to unify all three under the bytes-first model so any **peça** can be re-extracted with a different `--provedor`."

## Flagged ambiguities

- **System is class-generic, corpus is HC-only.** `StfItem.classe: str` accepts any value and `judex/scraping/` handles arbitrary **classes**, but `data/source/processos/` only holds HC. Code in `judex/scraping/` must not assume HC; code in `judex/analysis/` may, provided HC-only assumptions are stated explicitly at module top.

- **Asymmetric peça fetch path (surface 1 vs surfaces 2 + 3).** Today, **andamento**-attached peças are fetched in two stages (`baixar-pecas` writes bytes, `extrair-pecas` writes text), so re-extraction with a different `--provedor` is supported. **Sessão-virtual** documentos and **DJe** RTF peças are fetched synchronously inside `varrer-processos` (text-only, bytes discarded), so re-extraction is *not* supported for those. The text content for all three surfaces is in the cache regardless. The plan to unify all three under surface 1's model is recorded in [ADR-0001](docs/adr/0001-unify-peca-fetch-under-bytes-first-model.md).
