# Current progress — judex-mini

Branch: `dev`. Prior cycle archived at
[`docs/progress_archive/2026-05-04_0842_hc-fillin-chain-cli-cleanup.md`](progress_archive/2026-05-04_0842_hc-fillin-chain-cli-cleanup.md)
— HC 2025 fill-in close-out, ADR-0006 state-journal landing, unified pipeline
v1 + Fly OCR promotes, executar CLI cleanup, plus the post-mortem on the
parallel-launch overnight failure that motivated the chain v2 below.

**Status as of 2026-05-04 08:50 BRT.** Corpus: **90,763** HC cases on disk.
Live work: a single detached chain re-running HC 2024 / 2022 / 2021 fill-in
verifications serially under one direct-IP WAF budget, then a warehouse
rebuild. HC 2024 is at ~PID 240237 of 250918 (~73%) at 44–46 cases/s with
~84% OCR-stage cache-hits — should close in a few minutes. All 924 unit
tests green; `judex/cli.py` carries an uncommitted CLI-narrowing edit.

---

## Open thread — HC fill-in chain v2 paused (2026-05-04 10:02 BRT)

**Status.** Chain stopped cleanly at operator request via SIGTERM. State
files written atomically; resume is `--saida`-cache-driven (no
`--retomar` flag needed; the unified pipeline's resume is implicit
through the on-disk JSON/bytes/text caches).

**Where it stopped — HC 2024 (year 1 of 3):**

| stage           | count                  |
|-----------------|------------------------|
| fetch_meta      | 14,389 / 14,389 (100%) |
| unallocated_pid | 2,087 (terminal)       |
| bytes           | 10,530                 |
| text            | 10,514                 |
| **remaining**   | **~1,772 substantive cases** |

**Plan when resuming.** Re-launch the same chain script — it'll cache-hit
through the 10,514 already-extracted cases on HC 2024 in seconds, drain
the remaining ~1,772, then proceed to HC 2022 + HC 2021 + warehouse
rebuild as originally queued.

```bash
setsid nohup bash runs/active/_hc-fillin-chain.sh \
    > runs/active/hc-fillin-chain-resume-$(date +%Y%m%d-%H%M).log \
    2>&1 < /dev/null &
disown
```

Original launch command + invariants — see prior session log
[`docs/progress_archive/2026-05-04_0842_hc-fillin-chain-cli-cleanup.md`](progress_archive/2026-05-04_0842_hc-fillin-chain-cli-cleanup.md).

```
HC 2024 (range 236530–250918, 14,389 IDs)  ← paused at ~88%
  └── HC 2022 (range 210964–223885, 12,922 IDs)  queued
        └── HC 2021 (range 196282–210963, 14,682 IDs)  queued
              └── judex atualizar-warehouse --classe HC  queued
```

**Why a v2.** The first attempt last night fired three years roughly in
parallel between 00:43 and 01:29 BRT. Direct-IP WAF reputation split three
ways: HC 2021 died at 11s, HC 2024 at 8 min, HC 2022 ground for 7 hours
before dying at 08:26 BRT. HC 2023 squeezed in cleanly (60 min, ✅) probably
because the others had already stalled. HC 2025 is verified twice
(2026-05-03 evening, plus an instant cache-hit re-run at 01:06 BRT).
Pattern is exactly what `## Working conventions` and the rate-limits doc
warn against. v1 dirs left in place for diagnostic reference; v2 dirs use
`-v2` suffix.

**Files.**
- Chain script: [`runs/active/_hc-fillin-chain.sh`](../runs/active/_hc-fillin-chain.sh)
- Master launcher log: `runs/active/hc-fillin-chain-20260504.log`
- Aborted-attempt log: `runs/active/hc-fillin-chain-20260504-aborted.log` (the
  pre-`--nao-perguntar` first try; the forecaster prompt was auto-aborted by
  closed stdin)
- Per-year run dirs: `runs/active/hc{2024,2022,2021}-fillin-20260504-v2/`

**Monitor.**

```bash
uv run judex acompanhar runs/active/hc2024-fillin-20260504-v2/
tail -f runs/active/hc-fillin-chain-20260504.log     # year-start/end stamps
pgrep -af 'judex executar'                            # liveness
```

**Stop cleanly:** `kill -TERM $(pgrep -f _hc-fillin-chain.sh)` — the
current `executar` finishes gracefully (atomic state writes mean a
re-launch into the same `--saida` resumes from the last flushed snapshot).

**Outliers — queued for after the chain.** `hc2020-cap-recovery-v2`
finished with 8 oversized PDFs `outlier_skipped` (>1 MB cloud-OCR
threshold). The report's `outliers.csv` is empty (header-only) because
the errors.jsonl rows have `processo_id=null`, so use `--retentar-de`
instead:

```bash
uv run judex extrair-pecas \
    --retentar-de runs/active/hc2020-cap-recovery-v2/pdfs.errors.jsonl \
    --provedor tesseract --forcar \
    --saida runs/active/hc2020-outlier-local-tesseract-$(date +%Y%m%d)/
```

Run **after** the chain finishes — both share the direct-IP request budget
once `extrair-pecas` reaches its sistemas calls.

**HC 2025 pending-outcome recheck — also queued.** 744 HC 2025 cases sit
with `outcome=None` as of 2026-05-03 evening (5.6% pending vs 2.5–4%
steady-state for 2-3 yr-old cohorts). After the chain, rebuild the
pending CSV from on-disk JSONs and `--forcar` re-scrape — the empirical
answer to "how stale is our 2025 outcome data?". Recipe pinned in the
prior archive § HC 2025 fill-in.

---

## Resolved — `executar` CLI surface narrowed + Portuguese tightened (2026-05-04 08:42 BRT)

**What changed.** `judex executar` lost six options; the underlying
machinery is untouched (still works for `peca_cli` and library callers):

| Removed flag         | Kept where                                                  |
|----------------------|-------------------------------------------------------------|
| `--sem-dje`          | `run_pipeline(fetch_dje=True)` is the default               |
| `--impte-contem`     | `peca_cli` + `collect_peca_targets`; analysis layer prefers it |
| `--relator-contem`   | same                                                        |
| `--tipos-doc`        | same                                                        |
| `--excluir-tipos-doc`| same                                                        |
| `--limite`           | range / CSV mode already give exact target control          |

Portuguese cleanup on the surviving flags (representative — full diff in
[`judex/cli.py`](../judex/cli.py)): `[modo range]` → `[modo intervalo]`,
`Direct-IP: 1` → `IP direto: 1`, `case JSON` → `JSON do processo`,
`CPU-bound providers` → `Provedores limitados por CPU`, `Arquivo flat` →
`Arquivo simples`, `defaulta` → `assume`, `Auto-default` →
`Padrão automático`, `non-interactive` → `não-interativo`,
`bypass do skip-on-cache-match em handle_extract_text` → `ignora a
verificação de cache`, `[modo retry]` → `[modo nova tentativa]`,
`sharded mode` → `modo fragmentado`, `cost banner` → `painel de custo`.

**Verification.** All 924 unit tests pass. `uv run judex executar --help`
renders the cleaned surface. The live chain only uses
`-c/-i/-f/--saida/--nao-perguntar` — none of which were touched, so the
in-flight chain is unaffected and HC 2022 / 2021 will pick up the new
cli.py when they spawn fresh processes.

**Uncommitted.** `judex/cli.py` is `M` per `git status`. Commit after the
chain closes out (so any rollback during the chain doesn't tangle the
diff with the run state).

---

## Active task — HC year-ladder backfill (multi-cycle)

After this chain closes out and the warehouse rebuild lands:

1. **HC 2020 outlier-recovery** — 8 oversized PDFs via local Tesseract
   (recipe above). ~5 min.
2. **HC 2025 pending-outcome recheck** — 744 cases, `--forcar` (recipe
   above). ~30 min direct-IP.
3. **HC 2017–2019 fresh sweeps** — pre-2021 layer of the priority queue
   per [`docs/completion-tracker.md:131`](completion-tracker.md). HC 2020
   was scraped 2026-05-03 (sharded). HC 2017 is the natural next target
   per density × budget; HC 2018 / HC 2019 follow.
4. **ADR-0001 step 3 — surface 2 + 3 byte-gap backfill** for HC
   2017–2024 (~50–80k URLs across 8 years, direct-IP, ~5–10 hr/year).
   HC 2025 + HC 2026 surface-2 already done (10,002 ok / 27 http_errors
   / 0 WAF).

---

## Loose ends — consolidated from prior archives

Audited 2026-05-04 against `git log`. Items that already landed
(unified pipeline v1 promote `734c280`, ADR-0006 state journal,
ADR-0003 Phase 1 parser fix `ae19d73`, legacy three-command-chain
removal `0e874b3`) are dropped. What remains:

### Strategic — finalize the database (analysis-ready handoff)

The warehouse has been a moving target: schema v1 → v8, table layout
in flux, RTF/PDF separation pending, inline-text fields slated for
deletion. The goal is a **freeze-candidate** milestone where the schema
is declared closed for net-new fields, all known coverage gaps are
filled, and the doc surface matches the live shape. Workstreams:

- **Coverage.** HC fill-in chain v2 (in flight) → HC 2020 outliers →
  HC 2025 pending-outcome recheck → HC 2017–2019 fresh sweeps →
  ADR-0001 step 3 surface 2+3 byte-gap backfill → HC 2024 text-coverage
  anomaly investigation. Each is already itemised below; this entry
  just notes they jointly gate the freeze.
- **Schema lock-in.** Declare `schema_version=8` final (no v9 without
  an ADR explaining why). Drop inline `andamentos.link_text` /
  `documentos.text` / `decisoes_dje.rtf_text` from the build path
  (queries already use the `pdfs_substantive` join). Rename `pdfs` →
  `pecas`. Rename bytes-cache suffix `.pdf.gz` → `.bytes.gz`. Promote
  `pdfs_substantive` to the canonical analysis entry-point view (and
  rename `pecas_substantive` if the table renames first).
- **Currency contract.** Run the HC 2025 pending-outcome recheck once
  to establish a snapshot-drift baseline; then write down the periodic
  recheck cadence (quarterly?) so callers know when "outcome=None"
  means "STF hasn't decided" vs "we haven't re-scraped".
- **Doc fidelity.** Bring [`docs/data-dictionary.md`](data-dictionary.md)
  and [`docs/warehouse-design.md`](warehouse-design.md) to match the
  locked schema. Make the "fields that will not change" guarantee
  explicit so downstream notebooks can rely on it.
- **Build determinism.** Builder is full-rebuild-only (good — atomic
  swap, zero HTTP). Pin the build-input hash (count + sha of source
  JSONs + text gzs) in the rebuild log so any output diff has a known
  upstream cause.

### Strategic — simplify the CLI surface

Today's `executar` flag removal (6 flags + Portuguese tightening) is
the first pass. Continue narrowing toward "every flag justifies its
existence":

- **Apply the same audit to `peca_cli`.** `baixar-pecas` and
  `extrair-pecas` still expose `--impte-contem`, `--relator-contem`,
  `--tipos-doc`, `--excluir-tipos-doc`, `--limite` — the same filter
  knobs we just removed from `executar`. Analysis filtering belongs in
  notebooks against the warehouse, not in the collection CLI. Keep the
  underlying machinery in `judex/sweeps/peca_targets.py` (used by the
  unified pipeline + library callers); drop the CLI-surface flags.
- **Audit `judex debug` subgroup.** `debug fazer-backup` is a real
  operator tool, not a debug primitive — promote to top-level.
  `debug providers` is a one-shot reference table that could live as
  `judex --providers` or a standalone script. Keep `debug analisar-regimes`,
  `debug probe`, `debug validar-gabarito`, `debug exportar`,
  `debug relatorio-diario` (genuinely diagnostic).
- **Help-text consistency across the whole CLI.** Today's pass cleaned
  `executar` only. Other commands still mix English jargon
  (`Direct-IP`, `case JSON`, `flat file`, `default`, `bypass`) into
  Portuguese helps. Consistent framing: every flag opens with what it
  *does*, not what it's "for"; English jargon translates to its
  established Portuguese equivalent or stays as-is when truly
  borderline (`pool`, `shard`, `proxy`, `cache`, `CSV`).
- **Hold the library-vs-CLI separation line.** Each CLI command is a
  thin Typer wrapper around a `run_X(**kwargs)` library function
  (current pattern). Don't accumulate logic in CLI entry points; logic
  goes in `judex/sweeps/` or `judex/pipeline/`. The CLI surface is a
  documentation artifact — fewer flags, clearer help text, every choice
  defensible.
- **Sweep lifecycle as three first-class commands: start / stop /
  resume.** Today only "start" exists (`judex executar`); stop is raw
  `pkill -TERM -f 'judex executar'`, resume is "re-run `executar` with
  the same `--saida` and trust the cache". Surfaced concretely
  2026-05-04 when pausing the in-flight chain required killing three
  PIDs by hand and the resume recipe took a 6-line shell snippet to
  describe. The triplet should be discoverable in `judex --help` and
  share a common `<saida>` argument shape:
  - **start** — `judex executar … [--detach]` (existing). Add
    `--detach` flag that forks via `setsid nohup` internally, prints
    `pid:` + `log:` lines to stdout, exits. Removes the boilerplate
    `setsid nohup … > log 2>&1 < /dev/null & disown` pattern from
    operator memory. Pre-req: `judex/pipeline/runner.py` writes
    `<saida>/executar.pid` with `os.getpid()` at startup; deletes on
    graceful exit.
  - **stop** — `judex parar [<saida>]`. Reads
    `<saida>/executar.pid` (or `<saida>/shards.pids` if sharded),
    sends SIGTERM, waits N seconds, verifies gone; `--forcar` to
    escalate to SIGKILL. Default `<saida>` = most-recently-modified
    run dir under `runs/active/`.
  - **resume** — `judex retomar [<saida>]`. Sugar over `executar`
    that needs only `<saida>`; range/CSV/`--retentar-de` mode
    inferred from the prior `executar.state.json`. Today's "re-run
    with same `--saida`" works but is undiscoverable; `retomar` makes
    the lifecycle explicit in `--help` and removes the burden of
    re-typing the original `-c HC -i X -f Y` invocation.

  Each is ~30 LOC of CLI + a tiny library helper. The chain wrapper
  pattern (`_hc-fillin-chain.sh`) collapses to three lines:
  `judex executar … --detach`, `judex acompanhar`, `judex retomar`
  next-day. Closes the ergonomic gap that "just kill the PID" papers
  over.

### Tactical CLI / observability fixes (small, well-scoped)

- **`executar.errors.jsonl` polluted with `unallocated_pid` rows.** HC
  2025 fill-in shipped 2,859 lines of which only 6 were real
  `fetch_bytes` errors; the other 2,853 are benign terminal
  `unallocated_pid`. Breaks `--retentar-de` (re-probes 2,853 known-empty
  slots) and inflates any operator scan. Fix shape: stop writing benign
  terminal statuses; classifier likely in `judex/pipeline/log.py`. Pin
  with a unit test asserting `unallocated_pid` never lands in
  errors.jsonl. — *archive § HC 2025 fill-in close-out*
- **`bytes` stage doesn't distinguish cached vs freshly downloaded.**
  `report.md` shows a single `bytes: ok=N` bucket while `text` already
  splits `ok=N + skipped_cached=M`. Operator can't tell whether 28k PDFs
  were re-fetched (~14 hr direct-IP) or 20.6k were cached and only ~7.7k
  hit `sistemas.stf.jus.br`. Fix shape: add `cached: bool` to
  `fetch_bytes` log, split `ok` → `ok_fresh` + `skipped_cached` in
  `report.md` to mirror the text stage. — *archive § HC 2025 fill-in*
- **404s on voto PDFs deserve a distinct error class.** 6 known-permanent
  404s on
  `digital.stf.jus.br/decisoes-monocraticas/api/public/votos/{id}/conteudo.pdf`
  (HC 252164, 264813, 266879) live as generic `http_error` and would be
  retried by `--retentar-de`. A `permanent_404` terminal status — emitted
  to errors.jsonl but skipped by retry — would make residuals honest.
  Pairs naturally with the `unallocated_pid` fix. — *archive § HC 2025*
- **Intra-case URL dedup in `handle_fetch_meta`.** 50-case unified-pipeline
  validation surfaced 3 intra-case duplicate peça URLs (same URL emitted
  from two surfaces). Cost is bookkeeping noise (cache absorbs), but ~3
  lines to fix. — *archive § Unified pipeline v1*
- **CliffDetector `--cliff-require-sustained K` flag.** Current detector
  trips on a single window-sample; `K=3` (regime collapse must be
  sustained over 3 consecutive observations) would absorb
  rotation-forgiveness patterns. Non-blocking. — *archive § Fly OCR
  cascade*

### Investigation / postmortem incomplete

- **2026-05-02 14:12–15:22 BRT — 13,747 case JSONs written to wrong
  path.** Sweep wrote to `data/source/processos/*.json` instead of
  `data/source/processos/HC/`. Operator moved them to canonical layout,
  but root cause untraced. Add verifier guard:
  `ls data/source/processos/*.json` must be 0. Grep launcher logs from
  that window to identify the offending sweep. — *archive § warehouse
  rebuild blocker*
- **HC 2024 text coverage anomaly — 80% vs 97–99% on 2023/2022.**
  ~3k-row gap. Cause unverified (provider failures? RTF mistypes?
  scanned originals?). Requires spot-check + a focused `--csv` retry
  with Chandra/Tesseract on the underperforming subset. — *archive §
  Next-cycle candidates (2026-05-01)*

### Architecture / spec work

- **ADR-0003 Phase 2 — Playwright fallback for surface 3 (`publicacoes_dje`).**
  Phase 1 (loosened parser + redirect-anchor branch) landed 2026-05-02
  (commit `ae19d73`) and recovers ~80% of the metadata. Phase 2 (full
  PDF fetch via Playwright past the AWS WAF JS challenge on
  `digital.stf.jus.br`) is deferred until empirical demand forces it.
  Estimated 1–2 days. — *archive § ADR-0003 side-quest*
- **ACÓRDÃO re-extract corpus-wide via auto-router.** HC 2026 closed out
  with Fly Tesseract (5,179 ok / 10 dead surface-2 IDs = 99.8% effective,
  EMENTA validated 100% in spot-check). HC 2017–2025 ACÓRDÃO files still
  hold pypdf text from before the column-scramble bug was diagnosed —
  silent gold-CER ~12%, vs Tesseract's 0.75%. Re-extract those years to
  unblock EMENTA queries corpus-wide. Per-year wall ≈ 1.8 hr × Fly
  shared-cpu-2x × 60 ≈ $0.10 / 1k pages.

### Cost / performance / warehouse hygiene

- **Re-anchor `judex/utils/cost.py` for new Fly shape (shared-cpu-4x @
  2gb).** Currently anchored to old 2x @ 4gb ($0.0479/Machine-hr). New
  empirical shape: $0.0286/Machine-hr, 0.55 s/page mean, ~$0.0011 / 1k
  pages (vs Modal's $0.140). Tests use ±10% bounds — non-breaking.
  — *archive § Fly OCR cluster cost shape*
- **Drop inline text fields from warehouse build path.** Drop
  `andamentos.link_text` / `documentos.text` / `decisoes_dje.rtf_text`
  (queries already use the `pdfs_substantive` join). Lets `_CHUNK_SIZE`
  climb back to 5,000, halves peak RAM during rebuild. — *archive §
  Next-cycle candidates*
- **Warehouse table rename `pdfs` → `pecas`.** Table holds all peças
  (PDF + RTF); name is a v3-era artifact. Queue for next full rebuild.
  — *archive § Backlog (multi-cycle)*
- **Bytes-cache suffix rename `.pdf.gz` → `.bytes.gz`.** 5-step
  migration script exists. Safe to run between sweeps. — *archive §
  Backlog*
- **Fly OCR — 143-page+ PDFs hit shared-CPU credit ceiling and time out
  at 900 s.** 1 MB compressed-bytes outlier threshold gates them out of
  production today (0.016% of corpus). CPU-credit hypothesis plausible
  but unproven. Decision: park further optimisation; fall back to local
  Tesseract for the gated tail. — *archive § Fly OCR cascade*

### Doc / observability drift

- **Completion tracker stale.** Doesn't reflect HC 2020–2021 bytes/text
  or today's chain. Auto-resolves once `judex atualizar-warehouse` at
  the chain tail rebuilds and the next refresh of
  [`docs/completion-tracker.md`](completion-tracker.md) runs.
- **System-changes timeline current** — DJe row at 2022-12-19 was
  corrected from "Playwright queued" to "Phase 1 in progress; Phase 2
  deferred" in the prior cycle. No drift to fix.

---

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
- [`docs/recovery-patterns.md`](recovery-patterns.md) — multi-step residual recovery.
- [`docs/agent-sweeps.md`](agent-sweeps.md) — context-window pitfalls + detached pattern.
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
- **Live sweep monitor**: `judex acompanhar <run_dir>` is canonical (auto-detects
  monolithic vs sharded). Don't roll bespoke monitor scripts. See
  `CLAUDE.md § Conventions`.
- **Run direct-IP sweeps serially.** One judex process == one WAF
  reputation budget. Stacking parallel direct-IP runs splits the budget
  and trips the 403 cliff. Use a chained shell wrapper (`&&`) when a
  multi-year backfill is needed.
- **Archive convention**: when the active task closes out or this file
  grows past ~500 lines, move it to
  `docs/progress_archive/YYYY-MM-DD_HHMM_<slug>.md` and start a fresh
  notebook carrying the live threads + a consolidated loose-ends list.
- **Per-thread status convention.** Every top-level section uses one of:
  - `## Open thread — <slug> (<date>)` — active, still load-bearing.
  - `## Resolved — <slug> (<date>)` — closed but kept short-term for
    next-session resume context. Archive at the *next* session
    boundary, not the moment of resolution.
  - `## Active task — <slug>` / `## In-flight side-quest — <slug>` —
    multi-cycle work. Stays at the top.

  When all `## Open thread` and `## Resolved` sections drain (or the
  file passes ~500 lines), apply the archive convention above. The flip
  from `Open thread` → `Resolved` is the load-bearing signal — it makes
  "what's still alive in this notebook" greppable without reading every
  section.
