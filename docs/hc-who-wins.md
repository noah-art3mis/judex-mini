# HC deep-dive — who wins cases at STF?

Scope note for the Habeas Corpus analysis. Drafted 2026-04-17 while
sweep I (HC 230000..230999, 2023 vintage) is in flight. Ties into
`docs/current_progress.md` § "Next major goal — Habeas Corpus deep dive" and
`docs/sweep-results/2026-04-16-H-hc-last-100/` for the smoke result.

## Research question

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

### Why adopt FGV's definition rather than defining our own

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

## Three lenses

| lens | field | what it isolates |
|------|-------|------------------|
| lawyers (impetrantes) | `partes[i].nome` where `tipo == "IMPTE"` | The repeat-player effect: advocates / firms with a consistent win rate. Highest-signal lens. |
| ministers (relators) | `relator` | Which of the ~15 justices grant more often, controlling for case mix. |
| pacientes | `primeiro_autor` | Who benefits — usually individuals; low repeat-player density so low signal per identity. |

Primary target: **lawyers**. Secondary control: **relator**. Pacientes
mostly inform the case-mix narrative.

## Reality check on signal strength

STF's historical HC grant rate sits at roughly 5–10 %. Smoke sweep H
(100 fresh HCs filed 13–15 Apr 2026) yielded **zero** concedidos; all
decided cases were `nao_conhecido` (27) or `denegado` (5). Too fresh
to inform win-rate analysis.

Sweep I (1000 HCs from the 2023 vintage, matured) should yield 50–100
wins. That is enough to rank the top 5–10 repeat-player impetrantes and
all ~15 ministers with modest confidence intervals. Rarer buckets
(e.g. `concedido_parcial`, per-assunto slices) will be thin.

## Known friction

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

## Data inputs

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

## Analysis plan

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

## Notebook layout — investigation strands (2026-04-17)

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

## Open TODOs that block this

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

## Questions still to decide

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
