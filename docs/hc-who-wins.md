# HC deep-dive — who wins cases at STF?

Scope note for the Habeas Corpus analysis. Drafted 2026-04-17 while
sweep I (HC 230000..230999, 2023 vintage) is in flight. Ties into
`docs/handoff.md` § "Next major goal — Habeas Corpus deep dive" and
`docs/sweep-results/2026-04-16-H-hc-last-100/` for the smoke result.

## Research question

Who, in the STF Habeas Corpus caseload, consistently obtains favourable
decisions? "Favourable" means the outcome label produced by
`src.extraction_http.derive_outcome`, specifically:

- **win**:   `concedido`, `concedido_parcial`
- **loss**:  `denegado`
- **procedural (neither)**: `nao_conhecido`, `prejudicado`, `extinto`
- **pending**: `None`

Ranking units must have enough mass in the "win" column to be
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
- **Outcome labels**: derived by `src.extraction_http.derive_outcome`,
  vocabulary in `src/legal_vocab.py::VERDICT_PATTERNS`. Known
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

## Open TODOs that block this

1. **Sweep driver should persist per-process JSON natively.** Right
   now `scripts/run_sweep.py` writes state / log / errors / report
   only. The notebook loader globs `output/`, so every sweep needs a
   post-hoc cache-replay to dump the JSONs. One-liner addition to the
   driver: on each ok result, `json.dump(item, ...)` under
   `<out>/items/HC_<n>.json`. Tracked informally; no ticket yet.
2. **Impetrante normalization module.** Put the ASCII-fold + surname
   grouper in `src/text_norm.py` (new file). Unit-test with a handful
   of known duplicate spellings pulled from the 2023 data.
3. **Wilson CI helper.** Three-line function; does not warrant a
   dependency on `statsmodels`. Inline in the notebook or
   `analysis/_stats.py`.

## Questions still to decide

- **Stratified follow-up sweep B** (100 HCs / year × 15 years) is
  still on the table. If the 2023 slice shows meaningful era drift
  against the sweep H parser sanity check, B becomes more valuable.
  Ranges are in `analysis/hc_calendar.py::year_to_id_range`.
- **Full HC backfill** (~216 k extant cases, ~215 h wall time per
  handoff § size estimate) is the long-term ask but not blocked on
  this analysis. The who-wins plot quality at 1000 cases will tell
  us whether the ceiling analysis needs 10 k or 100 k.
- **Robots.txt posture.** Unchanged from handoff § "The one thing
  still to decide". Not blocking; shapes whether we publish raw
  aggregate numbers vs. just methodology.
