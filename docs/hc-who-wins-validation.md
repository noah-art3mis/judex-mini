# HC who-wins — validation findings (tasks 2 & 3)

Dated 2026-04-17. Covers the κ study on `derive_outcome` (task 2)
and the baseline-match check against Bottino/FGV (task 3). Results
feed directly into `docs/hc-who-wins.md` § "Reality check on signal
strength" and `docs/hc-who-wins-lit-review.md` § 11 ("inter-rater
reliability").

Raw artefacts:
- `tests/sweep/hc_kappa_labels/raw.json` — 50 sampled HCs with
  andamentos + voto_relator text
- `tests/sweep/hc_kappa_labels/review.txt` — human-readable dump used
  for the labelling pass
- `tests/sweep/hc_kappa_labels/labels.csv` — 50 (hc_id, auto, manual,
  confidence, note) rows
- `tests/sweep/hc_kappa_labels/sweep_i_outcomes.json` — full sweep I
  outcome distribution (883 parsed HCs)

## Headlines

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

## Six disagreements (of 50)

| HC | auto | manual | category |
|-----|-------------------|------------------|-------------------------------|
| 230104 | nao_conhecido | extinto          | desistência homologada — no pattern; falls through to older "nego seguimento" |
| 230123 | None           | nao_conhecido   | bare "NÃO CONHECIDO(S)" andamento title with empty complemento — regex misses |
| 230473 | nao_conhecido | concedido       | "não conheço... concedo a ordem de ofício" — nao_conhecido priority wins |
| 230560 | nao_conhecido | concedido       | "nego seguimento... concedo a ordem de ofício" — ditto |
| 230784 | None           | extinto         | desistência homologada — no pattern |
| 230834 | nao_conhecido | nao_provido     | AgRg "não provido" in voto_relator unmatched (regex requires "recurso não provido") — falls through to older "nego seguimento" |

## Four classes of parser bug

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

## Grant-rate triangulation

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

## Implications for `docs/hc-who-wins.md` analysis plan

- **Base rate assumption holds** — the "50–100 wins expected in
  sweep I" estimate in `hc-who-wins.md` § "Reality check" was correct
  in spirit. After the parser fix, we expect ~65–80 wins out of
  ~850 decided cases.
- **Ofício grants are a meaningful third category.** Roughly 4 % of
  HCs resolve with "não conheço MAS concedo de ofício" — the paciente
  gets relief without the formal HC being admitted. The who-wins
  analysis should count these as wins for the paciente but flag the
  lens: it's ex-officio relief, not advocate-driven victory.
- **κ = 0.84 on the decided-bucket task is acceptable for a first
  pass.** Publish raw analysis with a methodology footnote disclosing
  the κ and known under-count. Do NOT quote numbers to the nearest
  percentage point — state "~8 %", not "7.8 %".

## Recommended follow-up (not done here)

1. **Fix `derive_outcome` + `VERDICT_PATTERNS`** per the four bug
   classes above. Add unit tests under `tests/unit/` using the exact
   decision texts from the 6 disagreement cases as fixtures.
2. **Re-run the sweep-I outcome distribution** after the fix; expect
   the grant rate to rise from 3.88 % to ~7.5–8 %.
3. **Re-compute κ on a second 50-case sample** (stratified: oversample
   the win and pending buckets where agreement was weakest). Target
   κ ≥ 0.90 on both-decided subset after the fix.
4. **Promote the ofício-grant finding to `docs/hc-who-wins.md`** § 4
   ("Known friction") as a new item: "relief channels" (formal HC
   admission vs ofício) are distinct and matter for the advocate lens.

## Landis–Koch interpretation for reference

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
