# HC who-wins — computational social science literature review

Companion to `docs/hc-who-wins.md`. Surveys techniques from
quantitative legal studies and computational social science that
apply to the "who wins HC at STF?" analysis planned for sweep I
(HC 230000..230999) and the eventual 216k backfill.

Drafted 2026-04-17. Cited papers are real; entries flagged
"(citation needed)" are research leads, not established references.

## TL;DR — top 5 techniques by value-per-effort for the 1000-case slice

1. **Empirical Bayes / hierarchical-Bayesian shrinkage on lawyer grant rates.** For 5–10 % base rates and a long tail of 1–3-case lawyers, Wilson CIs are honest but dominated by partial pooling. A beta-binomial or logistic multilevel (lawyer random intercept) costs ~30 lines of PyMC/brms, produces shrunk posterior grant rates, and cleanly handles the "0-for-2" vs "0-for-20" distinction Wilson wraps but doesn't resolve. **Ship this.**
2. **Splink for impetrante dedup.** Fellegi-Sunter probabilistic linkage with blocking + Jaro-Winkler on surname tokens is the industry standard for messy personal-name data; the UK Ministry of Justice runs it on prison/court linkage at massive scale. Much more powerful than ad hoc surname grouping, and the library is pip-installable. Low effort, high quality uplift on the *primary* lens.
3. **Judge-leniency IV borrowed from Dobbie–Goldin–Yang (2018).** STF's RISTF-mandated electronic sorteio gives you the random-assignment premise the pretrial-detention literature needs. Compute leave-one-out minister grant rates, use as an instrument for "tough vs lenient bench" when estimating lawyer effects. This gives you a *causal* lawyer-effect estimator conditional on minister-mix, not just correlation. Medium effort; unusually clean identification for observational legal data.
4. **Coarsened Exact Matching on (orgao_origem × top-K assuntos × year).** At n=1000 this is strictly better than propensity scores, because CEM is monotonic-imbalance-bounding and needs almost no tuning. It lets you compare like-with-like cases across lawyers without the curse of high-dimensional propensity estimation. `cem` (R) or `cem` Python wrapper.
5. **Borrow the Arguelhes/Hartmann/Rosevear (2024) dissent dataset for a cross-check.** Their 2.23M-vote corpus covers 1988–2023 collegiate decisions. Even a lightweight merge by process number validates your parser's verdict labeling on a known fixture and gives you a population denominator for "how representative is our 2023 slice."

## 1. Repeat-player theory and Brazilian empirical tests

Galanter's 1974 "Why the 'Haves' Come Out Ahead" remains the canonical reference. The major empirical follow-ups are Kritzer & Silbey's edited volume *In Litigation: Do the "Haves" Still Come Out Ahead?* (Stanford UP, 2003) and Songer, Kuersten & Kaheny, "Why the Haves Don't Always Come Out Ahead" (*Political Research Quarterly*, 2000), which show that amicus support can offset repeat-player advantage at state supreme courts.

Brazil-specific work is thinner but exists. FGV's **Supremo em Números** project (coord. Ivar Hartmann) has published habeas-corpus-specific pieces — most directly Bottino et al., "Pesquisando Habeas Corpus nos Tribunais Superiores" (*REI*, 2019), which measured the STF's ~8 % HC grant rate vs STJ's ~28 % across 2008–2012. Asperti and others have revisited Galanter for Brazilian civil litigation (citation needed — "Why the Haves Come Out Ahead in Brazil" appears in Portuguese-language legal journals). Gen Jurídico / JOTA / Conjur have run practitioner-oriented pieces on "litigantes habituais" but none that I can find run a formal win-rate decomposition by impetrante. **This means your analysis, if done rigorously, is a genuine contribution** — not replication. Budget more care than you would for a me-too study.

Recommendation: explicitly cite Galanter, Kritzer-Silbey, and Bottino/Hartmann, and note your 2023 slice's grant rate against the 8 % historical baseline as a sanity check.

## 2. Name entity resolution for Portuguese lawyer data

The mature tooling:

- **Splink** (Ministry of Justice, UK) — Fellegi-Sunter model, Python, SQL-backend. Handles blocking (essential at scale), supports unsupervised EM training of m- and u-probabilities. Works well with Jaro-Winkler for names.
- **dedupe.io** (open-source) — active learning with user-labeled pairs; easier ramp for 1000 records.
- **recordlinkage** (Python) — more classical, less opinionated.

For Portuguese specifically: ASCII-fold is non-negotiable (ç/ã/õ/é), but you should also strip honorifics ("DR.", "DRA."), handle OAB numbers as a strong unique key when present (parse from partes strings if they carry them — worth a grep pass), and normalize "FILHO"/"JUNIOR"/"NETO" suffixes. Sentence-transformer embeddings on `name + " " + firm` sound appealing but are overkill at n≈few-thousand distinct impetrantes and add a failure mode (two different lawyers at the same firm collapse).

**Brazilian legal-tech**: Jusbrasil, Escavador, and Digesto all run proprietary lawyer-identity resolution over public court data; none publish their pipeline. Jusbrasil's engineering blog on Medium has posts on legal NLP (Vianna, "Organizing Portuguese Legal Documents through Topic Discovery," SIGIR 2022). Nothing public I could find on their *dedup* approach specifically.

Recommendation: start with Splink, pre-blocked by surname-first-token, with Jaro-Winkler on full name + exact match on OAB/state if extractable. Keep the ASCII-fold preprocessing. Your simpler text_norm approach remains the fallback for sanity checks.

**Update 2026-04-17 (empirical):** OAB registrations ARE parsed from STF's partes HTML in the form `(NNNNNN/UF[, NNNNNN/UF]*)` right after the lawyer name. Measured across 867 cached HCs: **90.5 %** of IMPTE entries carry an OAB, 6.1 % are Defensoria Pública (institutional), and only 3.5 % are individuals without an OAB. This flips the recommendation: **Splink is overkill.** A three-tier rule-based pipeline handles 96.5 % cleanly — (1) regex `\b\d+(?:-[A-Z])?(?:/[A-Z])?/[A-Z]{2}\b` on primary OAB as the canonical key, (2) `DEFENSORIA_PUBLICA_{UF}` canonicalization for the 6.1 % institutional bucket, (3) `src/text_norm.surname_key` + Levenshtein for the 3.5 % residual. Keep Splink in reserve for the 216 k backfill if the OAB-missing tail grows era-dependently.

## 3. Small-N grant-rate estimation — empirical Bayes wins

Wilson 95 % CIs are *correct* but hide the key structural feature: you have many lawyers, and most have few cases. This is the classic baseball-batting-average setup; Efron–Morris (1975, 1977) showed that James-Stein shrinkage on 45-at-bat slices predicted full-season averages better than raw means. Modern pipelines:

- **Beta-binomial empirical Bayes.** Fit Beta prior to the pooled grant rate (~7 %), compute posterior Beta(α + wins, β + losses) per lawyer. Three lines in scipy. Robinson's "Introduction to Empirical Bayes" (2017, also the varianceexplained.org blog) is the canonical intro — uses batting averages, directly transferable.
- **Hierarchical logistic** with random intercept per lawyer, per minister, per orgao_origem. In Python: PyMC; in R: `brms`/`rstanarm`. The rstanarm vignette "Hierarchical Partial Pooling for Repeated Binary Trials" is exactly your use case. Partial pooling gives you shrunken posterior means with credible intervals that degrade gracefully to the grand mean as n→1.
- **James-Stein explicitly** — not really any easier than full empirical Bayes and gives worse calibration; skip.

Practical note: the cross-level shrinkage (lawyers within minister within assunto) matters more than the priors. Don't waste time tuning prior hyperparameters; use weakly-informative Half-Normal(0, 1) on SDs.

Recommendation: Wilson CIs in the headline plot (legible to lay readers); shrunken posterior means in a second panel labeled "adjusted for small-sample bias." This two-view presentation is now the norm in judicial-analytics visualizations.

## 4. Judge fixed-effects IV design — directly applicable

Dobbie, Goldin & Yang, "The Effects of Pretrial Detention on Conviction, Future Crime, and Employment: Evidence from Randomly Assigned Judges" (*AER* 2018) is the modern template; Kling (2006) is the precursor. The design: within-court random judge assignment → judge leniency as instrument for detention decisions → causal effect on downstream outcomes.

STF's RISTF specifies an automated sorteio; investigative journalism (Agência Pública, JOTA) has questioned whether it is *actually* random, but no published empirical rejection exists. Prevenção (related-case routing) accounts for only ~8 % of cases per STF reporting — set those aside as an exclusion restriction or drop them from the IV sample. Pauta (calendar control) is a separate channel but affects *timing*, not *assignment*, of a full collegiate HC.

**Applicable version of the design for your question:**
- Construct leave-one-out minister HC grant rate over a rolling window (the jackknife leniency measure from Dobbie–Goldin–Yang).
- First stage: regress HC win on minister leniency + lawyer FE + case-mix controls.
- Use minister leniency as instrument for "minister ideology" when trying to isolate lawyer effect.

Caveats: monocratic decisions short-circuit the collegiate vote, and your `derive_outcome` uses `voto_relator` + `andamentos`. If the relator decides alone, the IV degenerates to a reduced-form difference in grant rates by minister. That's still interpretable but is not the Dobbie-Goldin-Yang design. Document this clearly.

Recommendation: worth doing, but flag honestly that at n=1000 with ~15 ministers the IV first-stage F-statistic is borderline. Better at the 216k backfill stage.

## 5. Case-mix controls: CEM yes, causal forests no

- **Coarsened Exact Matching** (Iacus, King, Porro, 2011 *Political Analysis*). MIB property, no iterative tuning, works great at n=1000 when you have 3–5 discrete strata. Coarsen orgao_origem (3–4 buckets: STJ / TRF / TJ / other), assuntos (top-K or hierarchical first level), and year. You lose unmatched cases, which is honest and interpretable.
- **Propensity score matching** — avoid. Needs a well-specified propensity model, and at n=1000 the model is noisy.
- **Causal forests** (Wager & Athey 2018) — overkill below n≈10,000. Save for backfill.
- **Stratification** (what you have) — fine for descriptive splits, bad for aggregate lawyer effect comparison. CEM is the strict upgrade.

Recommendation: stratification for your notebook-level diagnostic panels; CEM for the *single* "lawyer X's cases vs matched controls" headline number.

## 6. Ideal-point estimation for STF ministers

Yes, this exists. Desposato, Ingram & Lannes, "How judges think in the Brazilian Supreme Court: Estimating ideal points and identifying dimensions" (*EconomiA* 2015) applied MCMC Bayesian ideal-point estimation to STF ADI votes 2002–2012. Key finding: the dominant dimension is *pro-Executive vs anti-Executive economic interest*, not left-right. More recently, Rosevear, Hartmann & Arguelhes, "Dissenting Votes on the Brazilian Supreme Court" (*Journal of Law and Courts* / SAGE, 2024) built a 2.23M-vote dataset covering 1988–2023 and ran dissent-pattern analysis (not strictly ideal-point but related).

Luciano Da Ros has a 2017 review article on STF empirical literature (citation needed — likely *Revista de Direito Administrativo* or similar). Arguelhes's book *O Supremo: Entre o Direito e a Política* (2022) is a qualitative overview useful for framing.

For HC: ideal-point scores are estimated on *merits* cases; their applicability to HC — which is predominantly criminal-procedure-individual-rights — is contested. Don't over-promise. Pull the Desposato et al. scores as a covariate for your minister lens and note limitations.

Recommendation: reference the literature, pull ideal-point values if obtainable, include as a covariate in the hierarchical model. Don't fit your own ideal points at n=1000.

## 7. Priest-Klein — largely does not apply to HC (and that's the finding)

Priest & Klein (1984) predicts ~50 % plaintiff win in *trial* data because easy cases settle. Lee & Klerman (*International Review of Law and Economics*, 2016) formalized the conditions. HC at STF fails the settlement assumption entirely: the state is a passive respondent, not a settling defendant. Selection is still present — only defendants file, and high-quality petitions are filtered *upstream* by STJ — but the 50 % hypothesis does not predict anything useful for HC grant rates.

The real selection concern for you: **repeat-player lawyers may select cases they expect to win**, inflating their apparent grant rate without reflecting advocacy quality. That's case-mix bias (§5), not Priest-Klein. Cite Priest-Klein briefly to show awareness, then pivot to the CEM / IV machinery that actually addresses your selection concern.

## 8. Topic modeling on assuntos

Short answer: trust STF's tag taxonomy for the headline slice; use BERTopic for sensitivity analysis.

- STF's assunto tags are CNJ-standardized, hierarchical, and reviewed by court staff. Quality varies but beats unsupervised clusters for interpretability.
- BERTopic on ementas (not tags) is well-validated for Portuguese legal text — Vianna (Jusbrasil, SIGIR 2022) "Organizing Portuguese Legal Documents through Topic Discovery" + Silveira et al. "Topic Modelling of Legal Documents via LEGAL-BERT1" (2021). Both use BERTimbau-family embeddings.
- **Legal-BERTimbau** (rufimelo, HuggingFace) and **JurisBERT** (UFMS; "JurisBERT: Transformer-based model for embedding legal texts") are the main Portuguese-legal fine-tunes. For classification you want LegalBert-pt (Viegas et al., 2023) or RoBERTaLexPT (PROPOR 2024). For clustering, BERTimbau-base + BERTopic is the mainline pipeline.

Recommendation: use STF's assuntos as-is. If you see anomalies (one "assunto" mixing multiple real topics), validate with BERTopic on the ementas as a second opinion. Don't sink weeks into fine-tuning embeddings for 1000 cases.

## 9. Network analysis

Katz and Bommarito's body of work (computationallegalstudies.com) is the canonical computational-legal-networks reference — Bommarito, Katz & Zelner (2009) on SCOTUS citation networks, and Fowler et al. (*Political Analysis* 2007) "Network Analysis and the Law." Centrality, path-based importance, and community detection are the workhorse tools. The Christenson & Box-Steffensmeier chapter in the *Oxford Handbook of Political Networks* on judicial networks is a good entry point.

For your HC data: a bipartite **lawyer × minister** network is feasible. Metrics that would actually say something:
- **Assortativity** — do "tough" ministers get more cases from a specific cluster of lawyers? Weak evidence of directed submission or docket-shopping.
- **Degree/centrality of lawyers** — biggest repeat players.
- **Homophily between firms** — co-counsel patterns in multi-IMPTE petitions.

What *doesn't* travel well: citation-network metrics (your data has no citations parsed), and most diffusion-style models need directed edges.

Recommendation: defer networks to a second-pass analysis. The three-lenses question is cleaner as a per-actor regression. Networks belong in a richer follow-up.

## 10. Ethics / privacy — LGPD and the French shadow

France's **LOI 2019-222 art. 33** criminalized (up to 5 years, €300k) publication of "données d'identité des magistrats… dont la réutilisation a pour objet ou pour effet d'évaluer, d'analyser, de comparer ou de prédire leurs pratiques professionnelles réelles ou supposées." It does *not* ban internal use or press reporting; it targets automated analytics services naming judges. There is **no Brazilian analogue.** STF decisions are public, minister names are public, and LGPD's art. 4º, II exempts data processing for "fins exclusivamente jornalísticos e artísticos" and art. 7º permits processing based on legitimate interest for public-interest research. OAB has no general prohibition on publishing lawyer-specific win-rate statistics, though commercial analytics services (Escavador, Jusbrasil) have been sued by individual lawyers under honra/imagem theories (citation needed — specific cases).

Emerging norms in the judicial-analytics community (informal, not codified):
- Minimum cell size **k ≥ 5** before naming; CNJ's "Grandes Litigantes" dashboard uses similar thresholds.
- Differential privacy is overkill for named public figures acting in public capacity.
- Per-minister statistics are defensible under public-figure precedent; per-lawyer statistics are contestable if the lawyer is obscure and the sample is tiny (n < 10).

Recommendation: adopt n ≥ 5 for named lawyer statistics and n ≥ 10 before publishing anywhere non-academic. Publish minister stats freely — they are public officials in public roles. Keep a standing policy note in `docs/` so future contributors don't have to re-derive this.

## 11. What else a PhD in empirical legal studies would reach for

- **Audit studies / correspondence experiments** — not applicable here (you're observational).
- **Sentencing-disparity literature** (Rehavi & Starr; Yang) — transferable methods for disentangling race/gender disparities if partes data includes demographics, which it doesn't for STF HC. Skip.
- **Regression discontinuity on filing dates / procedural cutoffs** — if any STF rule changed mid-window (e.g. new RISTF article, new summary rule), a sharp RDD on filing date could identify its effect. Worth checking the 2023 timeline for rule changes.
- **Survival analysis / duration models** — time-to-decision by lawyer or minister. Cox proportional hazards on your `andamentos` timeline is a natural extension. Possibly the highest-value under-used angle given that your parsed data already has the procedural-step dates.
- **Outcome concordance / inter-rater reliability on `derive_outcome`.** Before anyone cites the win-rate numbers, hand-label 50 random cases and compute Cohen's κ against the automated label. This is standard practice in empirical legal studies and will forestall the "your labels are wrong" critique.

## Concrete next steps for judex-mini

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

## Open questions for a Brazilian expert

- **Does STF distribution truly satisfy Dobbie-Goldin-Yang's "quasi-random" assumption?** JOTA/Agência Pública have raised concerns about sorteio opacity. A Brazilian IPEA/FGV researcher could say whether the empirical balance tests (covariate balance across ministers conditional on class+date) have been done.
- **OAB rule 34 / CED interpretation** — is publishing a named lawyer's per-minister win rate considered *publicidade indevida* or aggregated public-interest journalism? Practice varies.
- **Availability of OAB number in partes strings** — if OAB is parseable from any HC, name dedup becomes trivial and Splink is overkill. Worth a grep sweep of the raw HTML.
- **Coverage of the Rosevear/Hartmann/Arguelhes 2.23M-vote dataset for HC** — their paper focuses on collegiate dissent; does their public release include HC monocratic decisions, or only plenário/turma votes? A direct email to Hartmann (FGV) would answer this in a day.

## Sources

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
