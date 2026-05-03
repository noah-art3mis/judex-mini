# HC deep-dive — who wins cases at STF?

Scope note for the Habeas Corpus analysis. Drafted 2026-04-17 while
sweep I (HC 230000..230999, 2023 vintage) is in flight. Ties into
`docs/current_progress.md` § "Next major goal — Habeas Corpus deep dive" and
`docs/sweep-results/2026-04-16-H-hc-last-100/` for the smoke result.

This file consolidates the three original who-wins documents
(`hc-who-wins.md`, `hc-who-wins-lit-review.md`,
`hc-who-wins-validation.md`, all 2026-04-17) into one navigable read.

- [§1 Scope and plan](#scope-and-plan) — research question, lenses,
  signal strength, friction, data inputs, analysis plan, notebook
  layout, open questions.
- [§2 Literature review](#literature-review) — computational social
  science techniques applicable to the analysis (1000-case slice and
  the 216k backfill).
- [§3 Validation](#validation) — Cohen's κ on `derive_outcome` and the
  baseline-match check against Bottino/FGV.

---

## Scope and plan

### Research question

Who, in the STF Habeas Corpus caseload, consistently obtains favourable
decisions? "Favourable" follows the **FGV IV Relatório Supremo em
Números §b rule** (Falcão, Moraes & Hartmann, FGV DIREITO RIO, 2015,
p. 50): every final decision that terminates a process is either
*favorável* (procedência parcial ou total) or *desfavorável* (all else,
explicitly including "negativa de admissão"); intermediate orders
(liminares / interlocutórias) are excluded entirely.

Mapped onto `judex.extraction_http.derive_outcome` labels via
`judex.analysis.legal_vocab.FGV_FAVORABLE_OUTCOMES`:

- **favorável**:    `concedido`, `concedido_parcial`
- **desfavorável**: `denegado`, `nao_conhecido`, `prejudicado`, `extinto`
- **excluded**:     `None` (liminar / interlocutória — not a final ruling; `derive_outcome` emits None for these because they match no VERDICT_PATTERN)

#### Why adopt FGV's definition rather than defining our own

1. **Comparability.** FGV's published numbers (PGR 50 % vs STF-wide
   24 % in 2013; MP-SC 38.5 %; MP-Paraíba 1.8 %) are the most-cited
   baselines in Brazilian STF empirical work. Using their rule lets
   our HC numbers sit next to theirs without a methodology footnote —
   a reviewer can ask "how does HC grant rate compare to MP success
   rate?" and the answer is one subtraction, not a re-derivation.
2. **Defensibility.** Their rule is explicit in print, peer-reviewed
   (FGV DIREITO RIO imprint, ISBN 978-85-63265-50-0), and has
   survived a decade of citation. Any bespoke partition we invented
   would invite the question "why not FGV's?".
3. **Honest downside framing.** Lumping `nao_conhecido` into
   *desfavorável* is not methodologically neutral — it counts "court
   refused to hear it" as a loss. That is exactly what FGV does, and
   it matches the filer's lived experience: they went to court, they
   did not get what they asked for. The alternative ("neither win
   nor loss") hides a real loss inside a procedural bucket and makes
   the denominator shrink in ways that inflate apparent win rates
   for lawyers whose cases tend to be refused at the gate.

Ranking units must have enough mass in the *favorável* column to be
statistically meaningful — see base rate below.

### Three lenses

| lens | field | what it isolates |
|------|-------|------------------|
| lawyers (impetrantes) | `partes[i].nome` where `tipo == "IMPTE"` | The repeat-player effect: advocates / firms with a consistent win rate. Highest-signal lens. |
| ministers (relators) | `relator` | Which of the ~15 justices grant more often, controlling for case mix. |
| pacientes | `primeiro_autor` | Who benefits — usually individuals; low repeat-player density so low signal per identity. |

Primary target: **lawyers**. Secondary control: **relator**. Pacientes
mostly inform the case-mix narrative.

### Reality check on signal strength

STF's historical HC grant rate sits at roughly 5–10 %. Smoke sweep H
(100 fresh HCs filed 13–15 Apr 2026) yielded **zero** concedidos; all
decided cases were `nao_conhecido` (27) or `denegado` (5). Too fresh
to inform win-rate analysis.

Sweep I (1000 HCs from the 2023 vintage, matured) should yield 50–100
wins. That is enough to rank the top 5–10 repeat-player impetrantes and
all ~15 ministers with modest confidence intervals. Rarer buckets
(e.g. `concedido_parcial`, per-assunto slices) will be thin.

### Known friction

1. **Name normalization — mostly solved by OAB parsing.** Measured on
   the 867 cached HCs (2026-04-17): 90.5 % of IMPTE entries carry an
   OAB registration `(NNNNNN/UF)` after the name — exact match on
   primary OAB collapses the dedup problem. 6.1 % are Defensoria
   Pública (canonicalize as `DEFENSORIA_PUBLICA_{UF}`). Only 3.5 %
   are individuals without OAB — the residual that needs fuzzy
   matching. Three-tier pipeline: OAB exact → Defensoria rule →
   `text_norm.surname_key` + Levenshtein. Splink is overkill.
2. **Base-rate bias.** 1-of-1 wins look like 100 %. Apply a minimum
   case count (≥ 3) and display Wilson 95 % CIs on grant-rate bars.
3. **Case-mix bias.** Lawyers who only take high-merit cases look
   strong for reasons unrelated to advocacy quality. Partial controls:
   - `orgao_origem` — HCs arriving from STJ vs. state courts differ
     sharply in grant rate.
   - `assuntos` — topic tags let us compare like-with-like.
   Full causal identification is out of scope here; we will flag
   correlation, not cause.
4. **Advocate vs counsel confusion.** An HC can list multiple
   `IMPTE` entries (co-authors of the petition) and also `ADV`
   entries (lawyers later joining the defence). We count only
   `tipo.startswith("IMPTE")` for the "who filed it" signal.

### Data inputs

- **Primary**: sweep I output at
  `docs/sweep-results/2026-04-16-I-hc-230000-230999/` (pending). Full
  StfItem JSONs in `output/` (written via the post-sweep replay step
  currently done by hand — see open TODO below).
- **Ancillary**: sweep H output for parser-sanity comparison across
  eras.
- **Outcome labels**: derived by `judex.extraction_http.derive_outcome`,
  vocabulary in `judex/analysis/legal_vocab.py::VERDICT_PATTERNS`. Known
  limitation: the `andamentos`-fallback pattern fires on monocratic
  decisions (nego seguimento, denegada a ordem) but does not parse
  per-item accordão text. For 2023 matured cases that is fine; for
  edge cases with a full collegiate judgement, the voto_relator path
  in `sessao_virtual` carries the verdict.

### Analysis plan

Once sweep I lands, add a **"Who wins"** section to
`analysis/hc_explorer.py` with the following cells:

1. **Impetrante normalization column** on the summary dataframe.
   One canonical name per lawyer after ascii-fold + surname grouping.
2. **Top impetrantes by grant rate**, filtered to ≥ 3 cases, plotted
   as a horizontal bar with Wilson CIs. Hover shows n / wins /
   losses / procedurals.
3. **Minister grant-rate panel.** All ~15 relators, same plot style.
4. **Grant rate × orgao_origem.** Stacked bar of outcomes per
   origem bucket — confirms the "STJ-origin HCs win more" folk claim.
5. **Outcome × assunto.** Top-20 assuntos by volume, stacked-bar
   outcome split. First look at which topic areas are easier to win.

Ship as additions to the existing notebook, not a new file. Keep the
smoke-data-aware branches so the notebook does not break when
pointed at sweep H only.

### Notebook layout — investigation strands (2026-04-17)

The `analysis/` marimo notebooks are organized as a hub-and-strand
pattern. `hc_explorer.py` is the hub (case drilldown, EB-shrunk
lawyer/minister grant rates, affinity heatmap, narrative deep dives
on Gilmar's Súmula-691 exception and the Alexandre de Moraes /
Defensoria-MG archetypes). Four narrow sibling notebooks answer one
question each and point back at the hub:

| Notebook | Question |
| --- | --- |
| `hc_explorer.py` | Hub. Full treatment + case drilldown. Carries an **Investigation index** cell near the top. |
| `hc_famous_lawyers.py` | Do marquee criminal-defense lawyers (Toron, Bottini, Kakay, …) show up in HCs, with what outcomes? |
| `hc_top_volume.py` | Who files the most HCs? HC-mill practices + Defensoria breakdown + OAB-state geography. |
| `hc_minister_archetypes.py` | Stacked wins / losses / procedural bar per minister — grantor vs denier vs gatekeeper at a glance. |
| `hc_admissibility.py` | Who reaches the merits? `nao_conhecido` rate per minister. |
| `hc_funnel.py` | Three-stage funnel — filed → merits → granted — with per-relator admissibility + merits-win split, time-to-disposition, coator-class segmentation, and `outcome_source` provenance. Vintage-agnostic (`DB_PATH = None` → full warehouse; swap to `Path("data/derived/warehouse/judex-YYYY.duckdb")` for a year-scoped read). Interpretive snapshot at `analysis/reports/2026-04-19-hc-funnel.py`. |

`analysis/` is git-ignored scratch so these won't be on a fresh
checkout — recreate from this doc if needed.

**How the slicing was chosen.** The lawyer-side splits into "famous
name matching" (curated list) and "volume-by-count" (raw impetrante
ranking) — different populations, different dedup strategies, so
different notebooks. The minister-side splits into "how do they
dispose of cases" (3-way disposition shape) and "do they reach the
merits" (admissibility gate) — orthogonal axes that jointly generate
the archetype story.

Ran against `output/sample/hc_*` — 8,954 HCs across the sampled
ranges (2023-vintage dominated).

**Findings (sample-conditional, write up with appropriate hedges):**

1. **Public defenders dominate volume.** DPU 591, DPE-SP 287, DPE-MG 74. Any private lawyer is a rounding error against the Defensoria baseline.
2. **Top-volume *private* impetrantes are HC-mill practices, not marquee names.** Victor Hugo Anuvale Rodrigues tops the list at ~86 (solo + "E Outro" folded); Cicero Salum do Amaral Lincoln 70; Fábio Rogério Donadon Costa 50. Fav% near the corpus baseline.
3. **Marquee criminal-bar lawyers file in single digits** on this HC sample. Toron 11; Bottini 6; Pedro M. de Almeida Castro (Kakay firm) 2; everyone else ≤ 2. Famous ≠ volume at STF.
4. **Minister identity dominates lawyer identity for HC grant rate.** Once per-minister cells are restricted to ≥ 3 merits decisions, the famous list empties out entirely — only the Defensorias have enough volume to read a pattern per relator:
   - Fachin, Celso de Mello: 67–100 % for Defensorias.
   - Toffoli, Barroso: 70–80 % for DPU.
   - Gilmar, Lewandowski, Cármen: baseline (~25–50 %).
   - **Alexandre de Moraes: 5 % (2/38) for DPU, 7 % (1/14) for DPE-SP.** Same counsel, same pleadings, ~15× spread across ministers.
   Implication: at this sample size the relator draw is a larger factor than counsel. The famous-lawyer premium (if real) is invisible.
5. **Admissibility rate spans 4 %–98 % across relators.** Marco Aurélio engages on merits for ~96 % of his HCs; the Ministro Presidente bucket dismisses ~98 % procedurally. Same outcome label ("low grant rate") can mean completely different things — see `hc_admissibility.py`.
6. **Caveats bank**: ~68 % of STF HCs end in `nao_conhecido` (not heard on merits), so `N` overstates the decidable sample. Substring name-matching means "ALMEIDA CASTRO" picks up multiple lawyers at a firm; we narrowed to "PEDRO MACHADO DE ALMEIDA CASTRO". Selection bias uncontrolled — lawyers self-select into case types. Not causal.

**Doesn't block scraping**; the sample corpus is adequate for the
current question. Expanding to RHC or AP would give more coverage of
the marquee criminal bar (Toron, Bottini et al. more likely to appear
in criminal appeals than in HCs).

### Open TODOs that block this

1. **Sweep driver should persist per-process JSON natively.** Right
   now `scripts/run_sweep.py` writes state / log / errors / report
   only. The notebook loader globs `output/`, so every sweep needs a
   post-hoc cache-replay to dump the JSONs. One-liner addition to the
   driver: on each ok result, `json.dump(item, ...)` under
   `<out>/items/HC_<n>.json`. Tracked informally; no ticket yet.
2. **Impetrante normalization module.** Put the ASCII-fold + surname
   grouper in `judex/analysis/text_norm.py` (new file). Unit-test with a handful
   of known duplicate spellings pulled from the 2023 data.
3. **Wilson CI helper.** Three-line function; does not warrant a
   dependency on `statsmodels`. Inline in the notebook or
   `analysis/_stats.py`.

### Questions still to decide

- **Stratified follow-up sweep B** (100 HCs / year × 15 years) is
  still on the table. If the 2023 slice shows meaningful era drift
  against the sweep H parser sanity check, B becomes more valuable.
  Ranges are in `judex/utils/hc_calendar.py::year_to_id_range`.
- **Full HC backfill** (~216 k extant cases — see
  [`docs/process-space.md`](process-space.md)). Wall-time depends on
  shard count: **~2.5 days at 4-shard proxy rotation** (validated
  empirically over 20.1 h of continuous load with zero WAF events,
  see [`docs/rate-limits.md § 4-shard proxy-rotation validation`](rate-limits.md#4-shard-proxy-rotation-validation-2026-04-18)),
  ~1.3 days at 8-shard (pivot landed 2026-04-18 with 80 sessions
  across 8 pools, tier-0 smoke test pending), ~9 days single-IP.
  As of 2026-04-18 the on-disk capture is ~55 k HCs (range
  48 933–271 139); the remaining ~161 k is the year-priority
  gap-sweep queue (tiers 2026 → 2013, paper era out of scope).
  Bandwidth cost ~208 BRL regardless of shard count. Not blocked on
  this analysis; the who-wins plot quality at 1000 cases will tell
  us whether the ceiling analysis needs 10 k or 100 k.
- **Robots.txt posture.** See
  [`docs/rate-limits.md § The unresolved policy question`](rate-limits.md#the-unresolved-policy-question--robotstxt).
  Not blocking; shapes whether we publish raw aggregate numbers vs.
  just methodology.

---

## Literature review

Surveys techniques from quantitative legal studies and computational
social science that apply to the "who wins HC at STF?" analysis planned
for sweep I (HC 230000..230999) and the eventual 216k backfill.

Drafted 2026-04-17. Cited papers are real; entries flagged
"(citation needed)" are research leads, not established references.

### TL;DR — top 5 techniques by value-per-effort for the 1000-case slice

1. **Empirical Bayes / hierarchical-Bayesian shrinkage on lawyer grant rates.** For 5–10 % base rates and a long tail of 1–3-case lawyers, Wilson CIs are honest but dominated by partial pooling. A beta-binomial or logistic multilevel (lawyer random intercept) costs ~30 lines of PyMC/brms, produces shrunk posterior grant rates, and cleanly handles the "0-for-2" vs "0-for-20" distinction Wilson wraps but doesn't resolve. **Ship this.**
2. **Splink for impetrante dedup.** Fellegi-Sunter probabilistic linkage with blocking + Jaro-Winkler on surname tokens is the industry standard for messy personal-name data; the UK Ministry of Justice runs it on prison/court linkage at massive scale. Much more powerful than ad hoc surname grouping, and the library is pip-installable. Low effort, high quality uplift on the *primary* lens.
3. **Judge-leniency IV borrowed from Dobbie–Goldin–Yang (2018).** STF's RISTF-mandated electronic sorteio gives you the random-assignment premise the pretrial-detention literature needs. Compute leave-one-out minister grant rates, use as an instrument for "tough vs lenient bench" when estimating lawyer effects. This gives you a *causal* lawyer-effect estimator conditional on minister-mix, not just correlation. Medium effort; unusually clean identification for observational legal data.
4. **Coarsened Exact Matching on (orgao_origem × top-K assuntos × year).** At n=1000 this is strictly better than propensity scores, because CEM is monotonic-imbalance-bounding and needs almost no tuning. It lets you compare like-with-like cases across lawyers without the curse of high-dimensional propensity estimation. `cem` (R) or `cem` Python wrapper.
5. **Borrow the Arguelhes/Hartmann/Rosevear (2024) dissent dataset for a cross-check.** Their 2.23M-vote corpus covers 1988–2023 collegiate decisions. Even a lightweight merge by process number validates your parser's verdict labeling on a known fixture and gives you a population denominator for "how representative is our 2023 slice."

### 1. Repeat-player theory and Brazilian empirical tests

Galanter's 1974 "Why the 'Haves' Come Out Ahead" remains the canonical reference. The major empirical follow-ups are Kritzer & Silbey's edited volume *In Litigation: Do the "Haves" Still Come Out Ahead?* (Stanford UP, 2003) and Songer, Kuersten & Kaheny, "Why the Haves Don't Always Come Out Ahead" (*Political Research Quarterly*, 2000), which show that amicus support can offset repeat-player advantage at state supreme courts.

Brazil-specific work is thinner but exists. FGV's **Supremo em Números** project (coord. Ivar Hartmann) has published habeas-corpus-specific pieces — most directly Bottino et al., "Pesquisando Habeas Corpus nos Tribunais Superiores" (*REI*, 2019), which measured the STF's ~8 % HC grant rate vs STJ's ~28 % across 2008–2012. Asperti and others have revisited Galanter for Brazilian civil litigation (citation needed — "Why the Haves Come Out Ahead in Brazil" appears in Portuguese-language legal journals). Gen Jurídico / JOTA / Conjur have run practitioner-oriented pieces on "litigantes habituais" but none that I can find run a formal win-rate decomposition by impetrante. **This means your analysis, if done rigorously, is a genuine contribution** — not replication. Budget more care than you would for a me-too study.

Recommendation: explicitly cite Galanter, Kritzer-Silbey, and Bottino/Hartmann, and note your 2023 slice's grant rate against the 8 % historical baseline as a sanity check.

#### FGV *IV Relatório Supremo em Números — O Supremo e o Ministério Público* (2015)

Falcão, Moraes & Hartmann, FGV DIREITO RIO, ISBN 978-85-63265-50-0. 102 pp., CC-BY-NC-ND. Archived locally at `docs/IV Relatório Supremo em Números - O Supremo e o Ministério Público.pdf`. Three things it gives us, none of which substitute the analysis but all of which are worth wiring in:

**Operational outcome rule (§b, p. 50) — adopted as project standard 2026-04-17.** FGV's exact definition of *taxa de sucesso*: exclude interlocutórias e liminares, count every decision that terminates a process as favorável (procedência parcial ou total) or desfavorável (all else, explicitly including "negativa de admissão"). Ported into `judex/analysis/legal_vocab.py` as `FGV_FAVORABLE_OUTCOMES` / `FGV_UNFAVORABLE_OUTCOMES` with the partition pinned by `tests/unit/test_legal_vocab_fgv.py`. Now the project-wide win/loss definition — see [§ Research question](#research-question) above for the three-point justification (comparability with FGV's published MP baselines; defensibility of a peer-reviewed definition over a bespoke one; honest framing of *nao_conhecido* as a loss rather than a procedural limbo). Supersedes the prior ad-hoc "win / loss / procedural" partition; the main behavioural change is that `nao_conhecido`, `prejudicado`, and `extinto` now count as losses rather than being dropped from the denominator.

**Litigant-grouping precedent (§a).** FGV clusters MP by geographic origin — MPE by Tribunal de Justiça estadual, MPF by Tribunal Regional Federal (1ª–5ª Região). Direct analytical template for the repeat-player lens: impetrante → escritório → OAB-state tier. Cite for methodological lineage; it lowers reviewer friction on "why aggregate at that level."

**Baseline numbers to anchor against (§b + §f, 2009–2013 aggregate + 2013 snapshot).** Use these as sanity checks, not as targets — they are MP-centric and pre-Lava-Jato:

| Actor / slice | Success rate | Source |
|---|---|---|
| STF overall (2013)               | 24 %   | §f.7 |
| PGR (2013)                       | 50 %   | §f.7 |
| MP geral (parte, 2009–2013)      | 5.8 %  | §b.1 |
| MP como parte ativa (2009–2013)  | 16.1 % | §b.4 |
| MPF reversion rate (2009–2013)   | 5.1 %  | §b.2 |
| MP-SC (2009–2013, best MPE)      | 38.5 % | §b.4 |
| MPF 1ª Região (2009–2013, best)  | 20.6 % | §b.4 |
| MP-Paraíba (worst MPE)           | 1.8 %  | §b.1 |

Key framing that transfers: the PGR-to-STF-average gap (50 % vs 24 % in 2013, up to 70 points in 2000) is FGV's headline evidence that repeat-player identity at the STF moves win rates by tens of percentage points — exactly the effect size the HC deep-dive is sized to detect. The MPE spread (1.8 %–38.5 %) is the within-category variance a rigorous analysis should expect to find among impetrantes once case mix is controlled.

**What FGV did not do**: no shrinkage, no CIs, no causal identification — raw percentages only; no lawyer-level dedup (they group by institutional actor, which skips the hardest problem); no HC breakdown (data is 1988–2013 from an internal Oracle DB of 1.48M processes, not HC-specific); internal DB not distributable, so quote conclusions but don't merge.

**Action item**: the 2024 Rosevear/Hartmann/Arguelhes dissent dataset (§ open questions below) and this report share an author — Ivar Hartmann, FGV. One email, two asks.

### 2. Name entity resolution for Portuguese lawyer data

The mature tooling:

- **Splink** (Ministry of Justice, UK) — Fellegi-Sunter model, Python, SQL-backend. Handles blocking (essential at scale), supports unsupervised EM training of m- and u-probabilities. Works well with Jaro-Winkler for names.
- **dedupe.io** (open-source) — active learning with user-labeled pairs; easier ramp for 1000 records.
- **recordlinkage** (Python) — more classical, less opinionated.

For Portuguese specifically: ASCII-fold is non-negotiable (ç/ã/õ/é), but you should also strip honorifics ("DR.", "DRA."), handle OAB numbers as a strong unique key when present (parse from partes strings if they carry them — worth a grep pass), and normalize "FILHO"/"JUNIOR"/"NETO" suffixes. Sentence-transformer embeddings on `name + " " + firm` sound appealing but are overkill at n≈few-thousand distinct impetrantes and add a failure mode (two different lawyers at the same firm collapse).

**Brazilian legal-tech**: Jusbrasil, Escavador, and Digesto all run proprietary lawyer-identity resolution over public court data; none publish their pipeline. Jusbrasil's engineering blog on Medium has posts on legal NLP (Vianna, "Organizing Portuguese Legal Documents through Topic Discovery," SIGIR 2022). Nothing public I could find on their *dedup* approach specifically.

Recommendation: start with Splink, pre-blocked by surname-first-token, with Jaro-Winkler on full name + exact match on OAB/state if extractable. Keep the ASCII-fold preprocessing. Your simpler text_norm approach remains the fallback for sanity checks.

**Update 2026-04-17 (empirical):** OAB registrations ARE parsed from STF's partes HTML in the form `(NNNNNN/UF[, NNNNNN/UF]*)` right after the lawyer name. Measured across 867 cached HCs: **90.5 %** of IMPTE entries carry an OAB, 6.1 % are Defensoria Pública (institutional), and only 3.5 % are individuals without an OAB. This flips the recommendation: **Splink is overkill.** A three-tier rule-based pipeline handles 96.5 % cleanly — (1) regex `\b\d+(?:-[A-Z])?(?:/[A-Z])?/[A-Z]{2}\b` on primary OAB as the canonical key, (2) `DEFENSORIA_PUBLICA_{UF}` canonicalization for the 6.1 % institutional bucket, (3) `judex/analysis/text_norm.surname_key` + Levenshtein for the 3.5 % residual. Keep Splink in reserve for the 216 k backfill if the OAB-missing tail grows era-dependently.

### 3. Small-N grant-rate estimation — empirical Bayes wins

Wilson 95 % CIs are *correct* but hide the key structural feature: you have many lawyers, and most have few cases. This is the classic baseball-batting-average setup; Efron–Morris (1975, 1977) showed that James-Stein shrinkage on 45-at-bat slices predicted full-season averages better than raw means. Modern pipelines:

- **Beta-binomial empirical Bayes.** Fit Beta prior to the pooled grant rate (~7 %), compute posterior Beta(α + wins, β + losses) per lawyer. Three lines in scipy. Robinson's "Introduction to Empirical Bayes" (2017, also the varianceexplained.org blog) is the canonical intro — uses batting averages, directly transferable.
- **Hierarchical logistic** with random intercept per lawyer, per minister, per orgao_origem. In Python: PyMC; in R: `brms`/`rstanarm`. The rstanarm vignette "Hierarchical Partial Pooling for Repeated Binary Trials" is exactly your use case. Partial pooling gives you shrunken posterior means with credible intervals that degrade gracefully to the grand mean as n→1.
- **James-Stein explicitly** — not really any easier than full empirical Bayes and gives worse calibration; skip.

Practical note: the cross-level shrinkage (lawyers within minister within assunto) matters more than the priors. Don't waste time tuning prior hyperparameters; use weakly-informative Half-Normal(0, 1) on SDs.

Recommendation: Wilson CIs in the headline plot (legible to lay readers); shrunken posterior means in a second panel labeled "adjusted for small-sample bias." This two-view presentation is now the norm in judicial-analytics visualizations.

### 4. Judge fixed-effects IV design — directly applicable

Dobbie, Goldin & Yang, "The Effects of Pretrial Detention on Conviction, Future Crime, and Employment: Evidence from Randomly Assigned Judges" (*AER* 2018) is the modern template; Kling (2006) is the precursor. The design: within-court random judge assignment → judge leniency as instrument for detention decisions → causal effect on downstream outcomes.

STF's RISTF specifies an automated sorteio; investigative journalism (Agência Pública, JOTA) has questioned whether it is *actually* random, but no published empirical rejection exists. Prevenção (related-case routing) accounts for only ~8 % of cases per STF reporting — set those aside as an exclusion restriction or drop them from the IV sample. Pauta (calendar control) is a separate channel but affects *timing*, not *assignment*, of a full collegiate HC.

**Applicable version of the design for your question:**
- Construct leave-one-out minister HC grant rate over a rolling window (the jackknife leniency measure from Dobbie–Goldin–Yang).
- First stage: regress HC win on minister leniency + lawyer FE + case-mix controls.
- Use minister leniency as instrument for "minister ideology" when trying to isolate lawyer effect.

Caveats: monocratic decisions short-circuit the collegiate vote, and your `derive_outcome` uses `voto_relator` + `andamentos`. If the relator decides alone, the IV degenerates to a reduced-form difference in grant rates by minister. That's still interpretable but is not the Dobbie-Goldin-Yang design. Document this clearly.

Recommendation: worth doing, but flag honestly that at n=1000 with ~15 ministers the IV first-stage F-statistic is borderline. Better at the 216k backfill stage.

### 5. Case-mix controls: CEM yes, causal forests no

- **Coarsened Exact Matching** (Iacus, King, Porro, 2011 *Political Analysis*). MIB property, no iterative tuning, works great at n=1000 when you have 3–5 discrete strata. Coarsen orgao_origem (3–4 buckets: STJ / TRF / TJ / other), assuntos (top-K or hierarchical first level), and year. You lose unmatched cases, which is honest and interpretable.
- **Propensity score matching** — avoid. Needs a well-specified propensity model, and at n=1000 the model is noisy.
- **Causal forests** (Wager & Athey 2018) — overkill below n≈10,000. Save for backfill.
- **Stratification** (what you have) — fine for descriptive splits, bad for aggregate lawyer effect comparison. CEM is the strict upgrade.

Recommendation: stratification for your notebook-level diagnostic panels; CEM for the *single* "lawyer X's cases vs matched controls" headline number.

### 6. Ideal-point estimation for STF ministers

Yes, this exists. Desposato, Ingram & Lannes, "How judges think in the Brazilian Supreme Court: Estimating ideal points and identifying dimensions" (*EconomiA* 2015) applied MCMC Bayesian ideal-point estimation to STF ADI votes 2002–2012. Key finding: the dominant dimension is *pro-Executive vs anti-Executive economic interest*, not left-right. More recently, Rosevear, Hartmann & Arguelhes, "Dissenting Votes on the Brazilian Supreme Court" (*Journal of Law and Courts* / SAGE, 2024) built a 2.23M-vote dataset covering 1988–2023 and ran dissent-pattern analysis (not strictly ideal-point but related).

Luciano Da Ros has a 2017 review article on STF empirical literature (citation needed — likely *Revista de Direito Administrativo* or similar). Arguelhes's book *O Supremo: Entre o Direito e a Política* (2022) is a qualitative overview useful for framing.

For HC: ideal-point scores are estimated on *merits* cases; their applicability to HC — which is predominantly criminal-procedure-individual-rights — is contested. Don't over-promise. Pull the Desposato et al. scores as a covariate for your minister lens and note limitations.

Recommendation: reference the literature, pull ideal-point values if obtainable, include as a covariate in the hierarchical model. Don't fit your own ideal points at n=1000.

### 7. Priest-Klein — largely does not apply to HC (and that's the finding)

Priest & Klein (1984) predicts ~50 % plaintiff win in *trial* data because easy cases settle. Lee & Klerman (*International Review of Law and Economics*, 2016) formalized the conditions. HC at STF fails the settlement assumption entirely: the state is a passive respondent, not a settling defendant. Selection is still present — only defendants file, and high-quality petitions are filtered *upstream* by STJ — but the 50 % hypothesis does not predict anything useful for HC grant rates.

The real selection concern for you: **repeat-player lawyers may select cases they expect to win**, inflating their apparent grant rate without reflecting advocacy quality. That's case-mix bias (§5), not Priest-Klein. Cite Priest-Klein briefly to show awareness, then pivot to the CEM / IV machinery that actually addresses your selection concern.

### 8. Topic modeling on assuntos

Short answer: trust STF's tag taxonomy for the headline slice; use BERTopic for sensitivity analysis.

- STF's assunto tags are CNJ-standardized, hierarchical, and reviewed by court staff. Quality varies but beats unsupervised clusters for interpretability.
- BERTopic on ementas (not tags) is well-validated for Portuguese legal text — Vianna (Jusbrasil, SIGIR 2022) "Organizing Portuguese Legal Documents through Topic Discovery" + Silveira et al. "Topic Modelling of Legal Documents via LEGAL-BERT1" (2021). Both use BERTimbau-family embeddings.
- **Legal-BERTimbau** (rufimelo, HuggingFace) and **JurisBERT** (UFMS; "JurisBERT: Transformer-based model for embedding legal texts") are the main Portuguese-legal fine-tunes. For classification you want LegalBert-pt (Viegas et al., 2023) or RoBERTaLexPT (PROPOR 2024). For clustering, BERTimbau-base + BERTopic is the mainline pipeline.

Recommendation: use STF's assuntos as-is. If you see anomalies (one "assunto" mixing multiple real topics), validate with BERTopic on the ementas as a second opinion. Don't sink weeks into fine-tuning embeddings for 1000 cases.

### 9. Network analysis

Katz and Bommarito's body of work (computationallegalstudies.com) is the canonical computational-legal-networks reference — Bommarito, Katz & Zelner (2009) on SCOTUS citation networks, and Fowler et al. (*Political Analysis* 2007) "Network Analysis and the Law." Centrality, path-based importance, and community detection are the workhorse tools. The Christenson & Box-Steffensmeier chapter in the *Oxford Handbook of Political Networks* on judicial networks is a good entry point.

For your HC data: a bipartite **lawyer × minister** network is feasible. Metrics that would actually say something:
- **Assortativity** — do "tough" ministers get more cases from a specific cluster of lawyers? Weak evidence of directed submission or docket-shopping.
- **Degree/centrality of lawyers** — biggest repeat players.
- **Homophily between firms** — co-counsel patterns in multi-IMPTE petitions.

What *doesn't* travel well: citation-network metrics (your data has no citations parsed), and most diffusion-style models need directed edges.

Recommendation: defer networks to a second-pass analysis. The three-lenses question is cleaner as a per-actor regression. Networks belong in a richer follow-up.

### 10. Ethics / privacy — LGPD and the French shadow

France's **LOI 2019-222 art. 33** criminalized (up to 5 years, €300k) publication of "données d'identité des magistrats… dont la réutilisation a pour objet ou pour effet d'évaluer, d'analyser, de comparer ou de prédire leurs pratiques professionnelles réelles ou supposées." It does *not* ban internal use or press reporting; it targets automated analytics services naming judges. There is **no Brazilian analogue.** STF decisions are public, minister names are public, and LGPD's art. 4º, II exempts data processing for "fins exclusivamente jornalísticos e artísticos" and art. 7º permits processing based on legitimate interest for public-interest research. OAB has no general prohibition on publishing lawyer-specific win-rate statistics, though commercial analytics services (Escavador, Jusbrasil) have been sued by individual lawyers under honra/imagem theories (citation needed — specific cases).

Emerging norms in the judicial-analytics community (informal, not codified):
- Minimum cell size **k ≥ 5** before naming; CNJ's "Grandes Litigantes" dashboard uses similar thresholds.
- Differential privacy is overkill for named public figures acting in public capacity.
- Per-minister statistics are defensible under public-figure precedent; per-lawyer statistics are contestable if the lawyer is obscure and the sample is tiny (n < 10).

Recommendation: adopt n ≥ 5 for named lawyer statistics and n ≥ 10 before publishing anywhere non-academic. Publish minister stats freely — they are public officials in public roles. Keep a standing policy note in `docs/` so future contributors don't have to re-derive this.

### 11. What else a PhD in empirical legal studies would reach for

- **Audit studies / correspondence experiments** — not applicable here (you're observational).
- **Sentencing-disparity literature** (Rehavi & Starr; Yang) — transferable methods for disentangling race/gender disparities if partes data includes demographics, which it doesn't for STF HC. Skip.
- **Regression discontinuity on filing dates / procedural cutoffs** — if any STF rule changed mid-window (e.g. new RISTF article, new summary rule), a sharp RDD on filing date could identify its effect. Worth checking the 2023 timeline for rule changes.
- **Survival analysis / duration models** — time-to-decision by lawyer or minister. Cox proportional hazards on your `andamentos` timeline is a natural extension. Possibly the highest-value under-used angle given that your parsed data already has the procedural-step dates.
- **Outcome concordance / inter-rater reliability on `derive_outcome`.** Before anyone cites the win-rate numbers, hand-label 50 random cases and compute Cohen's κ against the automated label. This is standard practice in empirical legal studies and will forestall the "your labels are wrong" critique.

### Concrete next steps for judex-mini

**Implement first (this cycle):**
1. Hand-label 50 HCs and compute κ for `derive_outcome`. Gate all downstream numbers on this.
2. Beta-binomial empirical Bayes posterior grant rates per impetrante (plus Wilson CIs retained). Three-line scipy.
3. Splink on impetrante names, compared against your current surname-token grouper on a held-out gold set of 30 hand-verified dup pairs.
4. CEM-matched "top-10 impetrantes vs matched controls" headline effect.

**Defer to the 216k backfill:**
5. Dobbie-Goldin-Yang-style IV using leave-one-out minister leniency. At n=1000 the first-stage is too weak.
6. Ideal-point covariate merge (pull Desposato et al. scores once and cache).
7. BERTopic validation pass on ementas.

**Skip:**
8. Causal forests, propensity scoring, custom ideal-point estimation, full network analysis, differential privacy.

### Open questions for a Brazilian expert

- **Does STF distribution truly satisfy Dobbie-Goldin-Yang's "quasi-random" assumption?** JOTA/Agência Pública have raised concerns about sorteio opacity. A Brazilian IPEA/FGV researcher could say whether the empirical balance tests (covariate balance across ministers conditional on class+date) have been done.
- **OAB rule 34 / CED interpretation** — is publishing a named lawyer's per-minister win rate considered *publicidade indevida* or aggregated public-interest journalism? Practice varies.
- **Availability of OAB number in partes strings** — if OAB is parseable from any HC, name dedup becomes trivial and Splink is overkill. Worth a grep sweep of the raw HTML.
- **Coverage of the Rosevear/Hartmann/Arguelhes 2.23M-vote dataset for HC** — their paper focuses on collegiate dissent; does their public release include HC monocratic decisions, or only plenário/turma votes? A direct email to Hartmann (FGV) would answer this in a day.

### Sources

- [Why Marc Galanter's 'Haves' Article is One of the Most Influential Pieces of Legal Scholarship — Talesh](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2585735)
- [Why the Haves Don't Always Come Out Ahead — Songer, Kuersten, Kaheny (2000)](https://journals.sagepub.com/doi/10.1177/106591290005300305)
- [Habeas Corpus nos Tribunais Superiores — Bottino / FGV](https://direitorio.fgv.br/sites/default/files/arquivos/projeto-pesquisa-hc.pdf)
- [Pesquisando Habeas Corpus nos Tribunais Superiores — REI](https://www.estudosinstitucionais.com/REI/article/view/357)
- [How judges think in the Brazilian Supreme Court — Desposato, Ingram, Lannes](https://www.sciencedirect.com/science/article/pii/S1517758014000253)
- [Dissenting Votes on the Brazilian Supreme Court — Rosevear, Hartmann, Arguelhes (2024)](https://journals.sagepub.com/doi/10.1177/2755323X241296364)
- [Disagreement on the Brazilian Supreme Court — Rosevear, Hartmann, Arguelhes (SSRN)](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2629329)
- [The Effects of Pretrial Detention — Dobbie, Goldin, Yang (AER 2018)](https://www.aeaweb.org/articles?id=10.1257/aer.20161503)
- [Examining the causal effect of pretrial detention — judge-fixed-effect IV review](https://link.springer.com/article/10.1007/s11292-022-09542-w)
- [Splink — probabilistic record linkage (MoJ UK)](https://moj-analytical-services.github.io/splink/index.html)
- [An Interactive Introduction to Record Linkage — Linacre](https://www.robinlinacre.com/intro_to_probabilistic_linkage/)
- [Understanding empirical Bayes estimation (baseball) — Robinson](http://varianceexplained.org/r/empirical_bayes_baseball/)
- [Hierarchical Partial Pooling for Repeated Binary Trials — rstanarm vignette](https://cran.r-project.org/web/packages/rstanarm/vignettes/pooling.html)
- [In-season prediction of batting averages — Brown (2008)](https://arxiv.org/abs/0803.3697)
- [Causal Inference without Balance Checking: Coarsened Exact Matching — Iacus, King, Porro](https://gking.harvard.edu/files/political_analysis-2011-iacus-pan_mpr013.pdf)
- [The Priest-Klein Hypotheses: Proofs and Generality — Lee & Klerman](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2538854)
- [JurisBERT — UFMS institutional repository](https://repositorio.ufms.br/handle/123456789/5119)
- [LegalBert-pt — Springer](https://link.springer.com/chapter/10.1007/978-3-031-45392-2_18)
- [Legal-BERTimbau-base — HuggingFace](https://huggingface.co/rufimelo/Legal-BERTimbau-base)
- [RoBERTaLexPT — PROPOR 2024](https://aclanthology.org/2024.propor-1.38.pdf)
- [Organizing Portuguese Legal Documents through Topic Discovery — Vianna (Jusbrasil / SIGIR 2022)](https://medium.com/jusbrasil-tech/organizing-portuguese-legal-documents-through-topic-discovery-65384b37b92a)
- [Topic Modelling of Legal Documents via LEGAL-BERT1 — Silveira et al.](https://ceur-ws.org/Vol-2896/RELATED_2021_paper_6.pdf)
- [Law as a Seamless Web — Bommarito, Katz, Zelner (SSRN)](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=1419525)
- [Judicial Networks — Oxford Handbook chapter](https://dinopc.org/papers/judicialnets.pdf)
- [France Bans Judge Analytics — Artificial Lawyer](https://www.artificiallawyer.com/2019/06/04/france-bans-judge-analytics-5-years-in-prison-for-rule-breakers/)
- [Distribuição dos processos no STF é realmente aleatória? — JOTA](https://www.jota.info/stf/supra/distribuicao-dos-processos-no-supremo-e-realmente-aleatoria)
- [Litigantes repetitivos e modulação — Suprema RStF](https://suprema.stf.jus.br/index.php/suprema/article/view/151)
- [Poder Judiciário - Grandes Litigantes (CNJ)](https://grandes-litigantes.stg.cloud.cnj.jus.br/)

---

## Validation

Covers the κ study on `derive_outcome` (task 2) and the baseline-match
check against Bottino/FGV (task 3). Results feed directly into
[§ Reality check on signal strength](#reality-check-on-signal-strength)
and [§11 inter-rater reliability](#11-what-else-a-phd-in-empirical-legal-studies-would-reach-for)
above.

Raw artefacts:
- `tests/sweep/hc_kappa_labels/raw.json` — 50 sampled HCs with
  andamentos + voto_relator text
- `tests/sweep/hc_kappa_labels/review.txt` — human-readable dump used
  for the labelling pass
- `tests/sweep/hc_kappa_labels/labels.csv` — 50 (hc_id, auto, manual,
  confidence, note) rows
- `tests/sweep/hc_kappa_labels/sweep_i_outcomes.json` — full sweep I
  outcome distribution (883 parsed HCs)

### Headlines

- **Cohen's κ vs `derive_outcome`**: 0.815 raw (8-class vocabulary),
  0.719 bucketed (win / loss / procedural / pending). Both-decided
  subset (n=48): 0.868 raw, 0.840 bucketed.
- **Grant rate matches Bottino/FGV ~8% baseline** once the parser
  bias is corrected. Raw auto rate is 3.88 % (33/850 decided); manual
  ground-truth rate on the 50-case sample is 8.0 %. The 50 % under-
  count is explained by two systematic parser bugs (below).
- **Name-resolution problem is much smaller than the lit-review
  estimated** — 90.5 % of impetrantes carry OAB numbers in the
  partes string (task 1 finding). Dedup is a three-tier rule-based
  pipeline, not a Splink project.

### Six disagreements (of 50)

| HC | auto | manual | category |
|-----|-------------------|------------------|-------------------------------|
| 230104 | nao_conhecido | extinto          | desistência homologada — no pattern; falls through to older "nego seguimento" |
| 230123 | None           | nao_conhecido   | bare "NÃO CONHECIDO(S)" andamento title with empty complemento — regex misses |
| 230473 | nao_conhecido | concedido       | "não conheço... concedo a ordem de ofício" — nao_conhecido priority wins |
| 230560 | nao_conhecido | concedido       | "nego seguimento... concedo a ordem de ofício" — ditto |
| 230784 | None           | extinto         | desistência homologada — no pattern |
| 230834 | nao_conhecido | nao_provido     | AgRg "não provido" in voto_relator unmatched (regex requires "recurso não provido") — falls through to older "nego seguimento" |

### Four classes of parser bug

1. **`extinto` missing — desistência homologada.** 2/6 disagreements.
   RISTF art. 21 VIII homologations of desistência have no regex in
   `VERDICT_PATTERNS`. Fix: add pattern
   `homolog[oa].*desist[êe]ncia|desist[êe]ncia\s+homologada` → `extinto`.

2. **`nao_conhecido` misses bare title.** 1/6 disagreements.
   When the andamento title is `NÃO CONHECIDO(S)` and the complemento
   is empty, no pattern fires. Fix: extend the nao_conhecido regex to
   match `n[ãa]o\s+conhecid[oa]` without the trailing `(?:do|o|a)\s`
   requirement, OR match andamento titles separately.

3. **Older-andamento-wins.** 2/6 disagreements (both bucket-preserving,
   so they affect raw κ but not the win/loss/procedural classification).
   `derive_outcome` scans andamentos in list order (newest-first by
   extractor convention) and returns on the first regex match. If the
   NEWEST decisional andamento has no matching regex (e.g. "AGRAVO
   REGIMENTAL NÃO PROVIDO" doesn't match the `nao_provido` regex which
   expects "recurso não provido" or "nego provimento") the loop falls
   through to the older "nego seguimento" and stamps the stale label.
   Fix: extend `nao_provido` pattern to cover "agravo regimental não
   provido" / "negou provimento ao agravo regimental".

4. **Ofício grants shadowed by procedural rejection.** 2/6 disagreements,
   **HIGH IMPACT** — this is the 50 % win under-count. Monocratic
   decisions sometimes read "não conheço do habeas corpus. Contudo,
   concedo a ordem de ofício". The pattern priority puts nao_conhecido
   before concedido, so the first match wins and the grant is lost.
   Extrapolating to the full 1000-sample: if 4 % of cases have the
   ofício structure, the auto labeller mis-classifies ~40 wins as
   procedural. Fix: add a higher-priority pattern for
   `concedo?\s+a\s+ordem,?\s+de\s+ofício` → `concedido` that runs
   BEFORE the nao_conhecido pattern.

### Grant-rate triangulation

| source                                | n    | win rate |
|---------------------------------------|------|----------|
| Bottino et al. 2008–2012 (FGV)        | ~thousands | ~8 %  |
| Sweep I auto (2023, raw)              | 850 decided | 3.88 % |
| Sweep I bias-adjusted (2× for ofício) | 850 decided | ~7.8 % |
| 50-sample manual (2023, gold)         | 46 decided  | 8.0 % |

The 2023 vintage's true grant rate is consistent with the Bottino
baseline at ~8 %. The raw auto rate (3.88 %) is an artefact of the
ofício-pattern bug — not era drift, not parser failure at the
fetch level. All 883 HCs in scope parsed cleanly (0 failures).

### Implications for the analysis plan

- **Base rate assumption holds** — the "50–100 wins expected in
  sweep I" estimate in [§ Reality check](#reality-check-on-signal-strength)
  was correct in spirit. After the parser fix, we expect ~65–80 wins
  out of ~850 decided cases.
- **Ofício grants are a meaningful third category.** Roughly 4 % of
  HCs resolve with "não conheço MAS concedo de ofício" — the paciente
  gets relief without the formal HC being admitted. The who-wins
  analysis should count these as wins for the paciente but flag the
  lens: it's ex-officio relief, not advocate-driven victory.
- **κ = 0.84 on the decided-bucket task is acceptable for a first
  pass.** Publish raw analysis with a methodology footnote disclosing
  the κ and known under-count. Do NOT quote numbers to the nearest
  percentage point — state "~8 %", not "7.8 %".

### Recommended follow-up (not done here)

1. **Fix `derive_outcome` + `VERDICT_PATTERNS`** per the four bug
   classes above. Add unit tests under `tests/unit/` using the exact
   decision texts from the 6 disagreement cases as fixtures.
2. **Re-run the sweep-I outcome distribution** after the fix; expect
   the grant rate to rise from 3.88 % to ~7.5–8 %.
3. **Re-compute κ on a second 50-case sample** (stratified: oversample
   the win and pending buckets where agreement was weakest). Target
   κ ≥ 0.90 on both-decided subset after the fix.
4. **Promote the ofício-grant finding to [§ Known friction](#known-friction)**
   as a new item: "relief channels" (formal HC admission vs ofício)
   are distinct and matter for the advocate lens.

### Landis–Koch interpretation for reference

| κ range     | interpretation     |
|-------------|---------------------|
| < 0.00      | Poor                |
| 0.00–0.20   | Slight              |
| 0.21–0.40   | Fair                |
| 0.41–0.60   | Moderate            |
| 0.61–0.80   | Substantial         |
| 0.81–1.00   | Almost perfect      |

Our bucketed κ of 0.719 (all-50) and 0.840 (both-decided n=48) sit
at the top of "substantial" and the bottom of "almost perfect"
respectively. Acceptable for headline use; the bug fixes would
push both into "almost perfect".
