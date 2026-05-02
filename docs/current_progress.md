# Current progress — judex-mini

Branch: `dev`. Prior cycle archived at
[`docs/progress_archive/2026-05-01_1750_cloud-ocr-fly-landing.md`](progress_archive/2026-05-01_1750_cloud-ocr-fly-landing.md)
— ACÓRDÃO re-extract diagnostics + Fly.io cloud-OCR pivot
(2026-05-01). Empirical close-out: local Tesseract structurally
unstable on the 4 GB WSL2 box (Pool deadlocks under OOM); landed
`tesseract_fly` provider + `--paralelo` thread-pool wrapper +
`fly/` deploy stack. Chosen path: Fly shared-cpu-2x × 60 Machines,
~$0.10 / 1k pages, ~1.8 hr per HC year-ladder. App deployed at
`judex-ocr-tesseract-arcos.fly.dev` (gru, 60 shared-cpu-2x
Machines, auto-stop-when-idle).

**Status as of 2026-05-01 evening.** Corpus: **90,763** cases.
PDF cache 99,057 `.pdf.gz` + 3,621 `.rtf.gz`, 105,821 `.txt.gz`.
Warehouse last rebuilt 2026-04-30 17:45 BRT — needs a refresh
once the HC 2026 chain closes.

## Active task — HC year-ladder backfill via 3-stage chain

**Why.** Iterate `varrer-processos → baixar-pecas → extrair-pecas`
per HC year, working backward from 2026, to close out the four-year
HC ladder (2022-2026) with current Fly-cloud OCR for ACÓRDÃOs and
correct EMENTAs corpus-wide.

**Chain shape (per year).** Sequential, idempotent (`set -e` +
`--retomar` everywhere). Run dir: `runs/active/backfill-hc<YYYY>-<date>/`.

```bash
export PATH="$HOME/.fly/bin:$PATH"
export FLY_TESSERACT_URL=https://judex-ocr-tesseract-arcos.fly.dev/extract
export JUDEX_AUTO_TESSERACT_PROVIDER=tesseract_fly

nohup bash -c '
set -e
uv run judex varrer-processos -c HC -i <PID_LO> -f <PID_HI> \
    --saida runs/active/backfill-hc<YYYY>-<date>/varrer \
    --diretorio-itens data/source/processos \
    --rotulo hc<YYYY>_backfill_<date> --retomar
uv run judex baixar-pecas -c HC -i <PID_LO> -f <PID_HI> \
    --saida runs/active/backfill-hc<YYYY>-<date>/baixar \
    --retomar --nao-perguntar
uv run judex extrair-pecas -c HC -i <PID_LO> -f <PID_HI> \
    --provedor auto \
    --saida runs/active/backfill-hc<YYYY>-<date>/extrair \
    --paralelo 60 --retomar --nao-perguntar
' > runs/active/backfill-hc<YYYY>-<date>/launcher-stdout.log 2>&1 &
```

**Per-year PID ranges** (from warehouse, refresh if corpus grows):

| Year | PID range          | Cases captured / total |
| ---- | ------------------ | ---------------------- |
| 2026 | 267,138 → 271,139  | 3,099 / 4,001          |
| 2025 | 250,920 → 267,137  | 13,365 / 16,200        |
| 2024 | 236,530 → 250,918  | 12,014 / 14,387        |
| 2023 | 223,886 → 236,833  | 11,129 / 12,644        |
| 2022 | 210,964 → 223,885  | 10,824 / 13,057        |

**HC 2026 chain in flight** (PID 1280502, launched 2026-05-01 17:40
BRT). Stage A (varrer) ~done (4001/4002 walked, 3097 ok + 903 dead
PIDs); stage B + C will auto-trigger via `&&`. Expected total
wall ~2.5 hr.

**Monitor.** Same pattern across all 3 stages:

```bash
tail -f runs/active/backfill-hc2026-2026-05-01/launcher-stdout.log
```

(Per CLAUDE.md § Conventions, this is the canonical live sweep
monitor — don't reach for anything fancier first.)

**Done when.** Stage C's `report.md` shows ≥99% ok across the
year's targets; spot-check 5–10 ACÓRDÃO `.txt.gz` files (`EXTRATO
DE ATA` and `RELATÓRIO`/`VOTO` markers should appear exactly once
per doc). Then move on to HC 2025, repeating the chain with the
next PID range. After all five years close out, rebuild the
warehouse: `uv run judex atualizar-warehouse --classe HC`.

## In-flight side-quest — ADR-0003 Phase 1 (DJe parser fix)

**Why.** Today's HC 2026 baixar-pecas / extrair-pecas pre-flight surfaced that surface 3 (`publicacoes_dje[]`) emits zero URLs for HC 2023+ in every case JSON since STF's DJe content-URL migration on **2022-12-19** (date pinned by STF's own footer — *"Até o dia 19/12/2022, o Supremo Tribunal Federal mantinha dois Diários de Justiça Eletrônicos com conteúdos distintos"*). Initial diagnosis (system-changes.md row 2026-04-21) blamed the new `digital.stf.jus.br` platform's AWS WAF and queued Playwright as the only fix. Reconnaissance today refuted that: **the legacy `listarDiarioJustica.asp` endpoint still serves the publication metadata** for every year — our `parse_dje_listing` parser was hard-requiring the `abreDetalheDiarioProcesso(...)` JS-callback shape that STF kept only for procedural Distribuição entries. Substantive entries (Decisão / Acórdão / Despacho) post-migration use plain redirect-anchor shape, which the parser silently dropped. ADR-0003 codifies the diagnosis + fix path.

**Phase 1 — landed (parser + tests + types + ADR + docs):**

- ✅ `judex/scraping/extraction/dje.py` — `_DJ_HEADER_RE` loosened to match *"DJ do dia DD/MM/YYYY"* without DJ number; new redirect-anchor branch in the parsing loop emits `PublicacaoDJe` entries with `external_redirect=https://digital.stf.jus.br/publico/publicacoes`, `detail_url=None`, `incidente_linked=None`.
- ✅ `judex/data/types.py` — `PublicacaoDJe.numero: int → Optional[int]`; `detail_url: str → Optional[str]`; `incidente_linked: int → Optional[int]`; new `external_redirect: Optional[str]`. Pre-migration entries unchanged in shape.
- ✅ `tests/unit/test_extract_dje.py` — 4 new tests against captured HC 236529 (HC 2024) + HC 267138 (HC 2026) listing fixtures. Existing 10 tests still pass. Full unit suite 665/665 pass.
- ✅ ADR-0003 (`docs/adr/0003-surface-3-dje-capture-path.md`) — full diagnosis + Phase 1 vs Phase 2 (deferred Playwright) + open questions.
- ✅ ADR-0001 — header updated to "step 3 validates 2 of 3 surfaces; surface 3 awaits ADR-0003".
- ✅ `docs/system-changes.md` row dated 2022-12-19 — corrected from "Playwright queued" to "Phase 1 in progress; Phase 2 deferred".

**Phase 1 — landed (renormalize HC 2023-2026 case JSONs, no STF traffic):**

- ✅ One-shot Python pass: read every HC 2023-2026 case JSON, extract `dje_listing.html` from per-case tar.gz cache at `data/raw/html/HC_<pid>.tar.gz`, run patched parser, atomic-write the case JSON when parser yields ≥1 entry. Conservative selection: skip cases with already-populated `publicacoes_dje[]` (preserves HC 2022's 18,585 legacy entries; explicit non-goal of Phase 1).
- ✅ Run summary (528s wall, ~76 files/s): **20,690 cases populated, 51,361 publication entries surfaced.** 14,933 cases unchanged (degenerate-cache HTML — page-shell with no result content). 299 cases without HTML cache. Year-by-year coverage: 2023 → 15,660 / 2024 → 19,588 / 2025 → 22,328 / 2026 → 4,727.
- ✅ Manual portal verification: HC 223889 (2023, 1 entry, `numero=None`, `data=2023-01-09`) matches what STF's browser page shows.

**Phase 1 — pending:**

- [ ] Run `uv run judex atualizar-warehouse --classe HC` to lift `publicacoes_dje` + `decisoes_dje` warehouse population rates from 0% to actual coverage on post-migration years. ~6 min.
- [ ] Commit Phase 1 to `dev`. Code+docs files are tracked; the ~20k case JSON rewrites under `data/source/processos/HC/` are gitignored.
- [ ] Field-coverage audit (Sampled 50-500 per year × 21 fields × cliff/always-empty/drop-recent flags) — looking for OTHER systematic gaps similar to the DJe regression. Slow scan (90k file glob + sample); previous attempts hit Bash buffering / timeout problems. **Park for a focused offline run** rather than fighting the tool plumbing live.

**Phase 2 — explicitly deferred** unless a downstream analysis demands DJe-only decision content text. The metadata layer (Phase 1) covers ~80% of DJe queries per system-changes.md note; full content recovery requires Playwright + AWS WAF challenge solving (1-2 day lift). Forcing question for later: *does any analysis need DJe-only content beyond what surfaces 1 + 2 already provide?* Owner: data-side comparison on HC 2022, the only year with both legacy DJe content and full surface-1/2 coverage.

**HC 2022 enrichment — open follow-up.** Phase 1's selection skipped HC 2022 (already populated, no regression risk). But the cached HTML for those cases has been refreshed since the original 2022 scrape (HC 210826 has 1 entry on disk, parser would emit 3 from current cache: 1 legacy + 2 redirect). Renormalizing HC 2022 with a *merge-not-replace* strategy could add ~2 redirect entries per case on top of existing legacy entries — strict gain, no data loss. Not blocked by anything; defer until Phase 1 ships and proves stable.

## Backlog (carried over from prior cycle)

1. **Urgent — DJe scraper regression** (post-2022 blackout).
   Path 1 (andamentos-side regex parse) is the cheap mitigation;
   Path 2 (Playwright against `digital.stf.jus.br`) is the proper
   fix. See archived cycle § "Urgent — DJe scraper regression"
   for the full diagnosis + 200-case empirical table.
2. **HC 2017–2021 case sweeps** — ~37k missing case widths combined,
   ordered by year-density. Once cases land, re-use the 3-stage
   chain above per year.
3. **Schema cleanup** — drop `andamentos.link_text` /
   `documentos.text` / `decisoes_dje.rtf_text` from the warehouse
   build path (queries already use `pdfs_substantive`'s join).
4. **`publicacoes_dje` → warehouse** — open warehouse gap noted in
   prior archive § Backlog.
5. **`pick_provider` env-var override** is in place
   (`JUDEX_AUTO_TESSERACT_PROVIDER`) but the auto-router default
   remains `"tesseract"` for unit-test stability. Consider flipping
   the default to `"tesseract_fly"` once the Fly path proves stable
   over a full year-ladder.

## Where things live (durable pointers)

- [`docs/data-layout.md`](data-layout.md) — file/store map.
- [`docs/stf-portal.md`](stf-portal.md) — URL flow, auth triad, field map.
- [`docs/system-changes.md`](system-changes.md) — STF-side timeline + schema history.
- [`docs/rate-limits.md`](rate-limits.md) — WAF behavior, validated defaults.
- [`docs/process-space.md`](process-space.md) — class sizes + density.
- [`docs/cost-estimates.md`](cost-estimates.md) — per-unit anchors.
- [`docs/warehouse-design.md`](warehouse-design.md) — DuckDB schema + build.
- [`docs/data-dictionary.md`](data-dictionary.md) — schema history v1→v8.
- [`docs/completion-tracker.md`](completion-tracker.md) — per-year coverage.
- [`docs/reports/`](reports/) — promoted narratives (validation sweeps, OCR bakeoff).
- [`docs/superpowers/specs/`](superpowers/specs/) — major-feature design specs.
- [`fly/`](../fly/) — Fly.io OCR app (Dockerfile + server.py + fly.toml + README).

## Working conventions

- **`analysis/`** — git-ignored scratch for this-session exploration.
- **`config/`** — git-ignored (credentials). Canonical proxy input is
  `config/proxies` (flat file).
- **All non-trivial arithmetic via `uv run python -c`** — never mental
  math. See `CLAUDE.md § Arithmetic`.
- **Sweeps write a directory**, not a file. Layout in
  [`docs/data-layout.md § Sweep run artifacts`](data-layout.md#sweep-run-artifacts).
- **Live sweep monitor**: `tail -f <run_dir>/launcher-stdout.log` is
  the canonical view across all 3 pipeline stages — see
  `CLAUDE.md § Conventions`. Don't roll bespoke monitor scripts.
- **Archive convention**: when the active task closes out or this file
  grows past ~500 lines, move it (or the cycle-specific portion) to
  `docs/progress_archive/YYYY-MM-DD_HHMM_<slug>.md`.
