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

**Status as of 2026-05-02 20:37 BRT.** Corpus: **90,763** HC
cases. PDF cache 99,095 `.pdf.gz` (+38 from HC 2026 baixar) +
3,621 `.rtf.gz`, **109,777** `.txt.gz` (+3,956 from HC 2026
extract). 93,074 `.extractor` sidecars (gap of ~16k vs
`.txt.gz` is pre-sidecar-discipline residue, not a regression).
Warehouse rebuilt 2026-05-02 12:43 BRT (1.85 GB; DJe Phase 1
populated). Both HC backfill chains (2025 + 2021) **stopped at
user request 20:30-20:33 BRT** while in Stage C (extrair) — see
"Halt 2026-05-02 20:33 BRT" below for state snapshots + resume
commands. Now in flight: a `coletar`-orchestrator smoke test
(HC 245000-245099, exercises today's ADR-0004 commits).

## Open thread — Fly OCR cluster cost shape (2026-05-02 late evening)

**Why.** The first real Fly invoice landed (May 1+2 = $8.70 over
181.5 Machine-hours) and revealed two surprises: (a) the prior
`$0.0118/hr per Machine` quote in `fly/README.md` and
`tesseract_fly.py:cost()` was **4× under-anchored** because it
ignored the "Additional RAM" line item, and (b) RAM is **82% of
the per-Machine bill** at the old `[[vm]] memory = "4gb"`, not the
expected CPU-dominated split. The bill anchored a real per-hour
rate of $0.0479 / Machine-hour.

**Landed on `dev`.**

- `71e3d43 feat(fly): chunked rasterize + 2 GB Machine, bill-anchor cost surface`
  — `fly/server.py` switched from upfront `convert_from_bytes(pdf_bytes,
  dpi=200)` (peak RAM ≈ 11 MB × n_pages) to chunked
  `_RASTER_CHUNK_PAGES = 4` rasterization (peak RAM ≈ 50 MB regardless
  of page count). `[[vm]] memory: "4gb" → "2gb"`. Cost docstring
  rewritten with two-meter pricing model anchored to the real invoice.
  Per-Machine rate: $0.0479/hr → $0.0256/hr (**~47% reduction**).
- `62a1101 docs(fly): smoke-test report for streaming refactor + 1 GB Machine`
  — full report at `docs/reports/2026-05-02-fly-streaming-refactor-smoke-test.md`.

**Cluster state right now.**

| Field | Value |
|---|---|
| Branch | `dev` |
| Local `fly.toml` | `memory = "2gb"`, `shared-cpu-2x` |
| Live cluster | 10 Machines × shared-cpu-2x × 2 GB ✓ matches local |
| Live image | streaming refactor (chunked rasterize) ✓ matches local |
| Per-Machine rate | $0.0256/hr |
| Was scaled to | 100 Machines pre-test; **needs restore to 100** |

**Smoke-test results so far.** 1-page PDF: ✅ clean (~4 s wall,
991 chars, accents intact). 123-page PDF: server-side 200 OK at
~270 s wall but client got empty body — diagnosed as
`async def extract()` blocking the asyncio event loop during sync
OCR work, so `/healthz` fails and Fly's proxy drops the upstream
connection. **No OOM in logs**, so 2 GB is genuinely sufficient
for 123-page PDFs. 295-page PDF (`37ee397e8732…`, 5.4 MB gz):
**not yet run** — direct user concern about long-PDF handling.

**Open follow-ups (priority order).**

1. **Run 295-page PDF test** against the live 2 GB cluster to
   pin "very long PDFs handled correctly" empirically, not by
   design extrapolation.
2. **`async def` → `run_in_executor` one-liner** so long-request
   responses don't get dropped on the way back through the proxy.
   Pinned by re-running the 123-page PDF and getting clean text.
3. **Restore cluster to 100 Machines** (`flyctl scale count 100`)
   before any production sweep.
4. **Money optimization choices** still on the table — current
   $0.0256/hr; achievable lower bounds:
   - `shared-cpu-2x` + `memory = "1gb"`: $0.0143/hr (44% further
     cut). Headroom ~314 MB over peak ~710 MB working set — tight,
     silent-OOM risk on edge PDFs (Pillow large-image spikes).
   - `shared-cpu-4x` + `memory = "1gb"`: $0.0174/hr (39% cut)
     **and** 2× wall speedup on 3+ page PDFs (4 parallel Tesseract
     instances vs 2). Risk: 4 concurrent Tesseract working sets
     (~600 MB) plus baseline (~400 MB) ≈ 1 GB exact — needs the
     2 GB shape to be safe in practice.
   - Both options are shape-only — `server.py` reads
     `os.cpu_count()` so the worker pool auto-scales to whatever
     the deployed shape provides. No Python change required.
5. **Investigate health-check failures** on started Machines —
   noticed during smoke test that `1 critical` checks were
   common, possibly from `/healthz` being blocked during long
   OCRs (same async-blocking root cause as #2).

**Decision pending.** Whether to spend engineering effort on the
remaining ~$0.10–$0.20/ladder savings, or stop here. The headline
win (4 GB → 2 GB, 47% off the per-Machine rate) is locked in;
further cuts are diminishing returns.

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

setsid nohup bash -c '
# Pre-warm the Fly OCR cluster — eliminates the Stage-C cold-start 502
# storm without paying for an always-warm pool. ~$0.002/pulse; auto-stop
# returns Machines to $0 ~5 min after the run finishes.
fly machine start --select -a judex-ocr-tesseract-arcos || true
sleep 15

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
    --paralelo 10 --retomar --nao-perguntar
' > runs/active/backfill-hc<YYYY>-<date>/launcher-stdout.log 2>&1 < /dev/null &
disown
```

**Template invariants** (don't drop these — each one is a scar from a
real failure mode this session):

- `setsid nohup … </dev/null & disown` — full session detach. Plain
  `nohup` survives terminal SIGHUP but not WSL VM suspend (HC 2026
  original chain died this way ~2 hr in on 2026-05-01).
- **No `set -e`** in the wrapper. `baixar-pecas` exits non-zero when
  *any* failures occur (e.g. 10 stable surface-2 404s), and `set -e`
  would kill the chain before Stage C runs. Each stage's own
  `--retomar` makes re-launching after a manual stop safe.
- `fly machine start --select` pre-warm pulse before any extrair work.
  `--paralelo 10` matches the cluster's organic warm-up rate; pre-warm
  ensures the cluster is ready when the parallel barrage hits. Without
  pre-warm, even the new tenacity retry can't always catch all
  cold-start 502s when 10 requests fire against 0 warm Machines.
- `--paralelo 10` (not 60). The 60-parallel number was tuned for the
  always-warm Modal cluster; on Fly with `min_machines_running = 0`
  it overwhelms the wake-on-request capacity. 10 lets the proxy keep
  pace with demand. Trade: ~30 min wall vs ~11 min on HC 2026, but
  with a much higher final success rate.
- `|| true` on the pre-warm — a transient `fly` CLI failure shouldn't
  kill the chain. The retry layer in `tesseract_fly.py` will absorb
  the cold-start storm if pre-warm doesn't fire.

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

**Resumed 2026-05-02 12:44 BRT** after the original chain's parent
bash died ~19:42 (likely WSL VM suspend; nohup survives SIGHUP but
not VM exit). Used `setsid nohup … </dev/null & disown` for full
session detach this time. Stage B finished clean (downloaded=32,
cached=5,231, failed=10 — all 10 are stable 404s on
`digital.stf.jus.br/.../votos/<id>/conteudo.pdf` surface-2 IDs that
were captured in `sessao_virtual.documentos[].url` but no longer
resolve; harmless edge case, not a regression). Critical wrinkle:
the chain template's `set -e` interpreted `baixar-pecas`'s non-zero
exit (10 failures present) as a hard fail, so Stage C never ran via
the chain — had to launch standalone. **Followup**: either drop
`set -e` in the chain wrapper or change `baixar-pecas` to exit 0
when failures are present but capped (the failures live in
`pdfs.errors.jsonl` regardless).

Stage C (`extrair-pecas --provedor auto --paralelo 60`) launched
standalone at ~12:45 BRT. Auto router decided **pypdf=4,806 / 
tesseract_fly=446** (91% / 9% split) — `--provedor auto`
forecast: $0.03 / ~30 min, vs forced-`tesseract_fly` forecast of
$0.33 / ~262 min. Validates the auto router's value:
~11× cheaper, ~8× faster on this corpus shape.

**Known issue — Fly OCR 502s under cold-cluster load.** During
Stage C's first ~30 min, ~9% of OCR-routed requests
(~300 / ~3,500 attempted) returned `provider_error (HTTPError: 502
Bad Gateway)` from `judex-ocr-tesseract-arcos.fly.dev`. Diagnosis:
the cluster has `min_machines_running = 0` (`fly/fly.toml`), so all
60 Machines start `stopped`. Local `--paralelo 60` fires faster than
Fly's auto-start can warm Machines (5s cold-start), so the Fly edge
proxy routes some requests to Machines mid-boot and bounces them
with 502. Confirmed by Fly status during the run: cluster sat at
11-14 `started` Machines for most of Stage C, never warming the full
60 because `auto_stop_machines = "stop"` re-idles them as soon as a
batch wave passes. **502 is purely a transport signal** — the PDF
content is fine; verified by spot-opening source `.pdf.gz` for
several 502'd URLs (they parse cleanly outside the OCR path).

Stage C final tally (HC 2026, 2026-05-02 12:48-13:00 BRT, 11.3 min
wall): ok=4,869 (92.3%) / provider_error=383 (7.3%) / cached=11 /
no_bytes=10. **All 383 failures are Fly OCR transport, none are PDF
content** — auto-router routed 446 PDFs to `tesseract_fly`, only 63
succeeded (~14%). The other 383 = the entire OCR failure budget on
this run, all 502 / ReadTimeout from cold-start cluster.

Three mitigation paths, ordered by lift:

1. ✅ **Tenacity retry landed in `judex/scraping/ocr/tesseract_fly.py`**
   (2026-05-02). Wraps `_post_extract()` with retry-on-transient
   (502/503/504 + `requests.ConnectionError` + `requests.Timeout`,
   incl. ReadTimeout) at **5 attempts × `wait_exponential(2, 2, 30)`**
   (originally 3 × max=10; bumped after observing the in-flight
   retry pass needed more headroom against a 60-Machine cold cluster
   under `--paralelo 20`). 4xx (auth, malformed PDF) fails fast —
   no retry budget wasted. Pinned by 4 tests in
   `tests/unit/test_ocr_tesseract_fly.py` (suite 670 pass). With
   pre-warm pulse + `--paralelo 10` (chain template), the retry
   becomes the safety net for transient hits during the active run,
   not the primary cold-start mitigation. Expected post-fix failure
   budget on a re-run of HC 2026: **<5 PDFs (out of 446 OCR-routed)**,
   down from 383.
2. **Bump `min_machines_running = 20` in `fly/fly.toml`** before
   the next year's chain. Pre-warms a permanent pool, eliminating
   cold-start at the cost of ~$0.30/day idle billing. Right move
   for the upcoming HC 2025/2024/2023/2022 ladder where each year
   is 3-4× larger than 2026 — the retry alone gets us to ~95%, but
   pre-warming closes the rest.
3. **Drop `--paralelo 60 → --paralelo 20`** to match warm-cluster
   capacity. Lower throughput but higher reliability without infra
   changes. Useful as a stopgap if (2) doesn't ship.

Recommended sequencing: (1) shipped today; (2) is the next
follow-up before HC 2025 launches. (3) is a fallback knob, not a
permanent answer.

Failed 502 URLs are recoverable in-place via:

```bash
uv run judex extrair-pecas \
    --retentar-de runs/active/backfill-hc2026-2026-05-01/extrair/extracao.errors.jsonl \
    --provedor tesseract_fly \
    --saida runs/active/backfill-hc2026-2026-05-01/extrair-retry \
    --paralelo 20 --nao-perguntar
```

(Force `tesseract_fly` because `auto` would re-route the same way;
drop `--paralelo` to match warm capacity.)

**HC 2026 — closed out 2026-05-02 14:30 BRT.** Retry pass v2 (with
the new tenacity 5×30 retry + pre-warmed cluster + `--paralelo 10`)
processed 310 previously-failed URLs with **0 failures** (cost
$0.04, 3,453 pages OCR'd). Combined coverage: **5,179 ok / 10
legitimately-dead surface-2 voto IDs = 99.8% effective**, well
past the ≥99% close-out threshold. OCR quality validated by
8-sample ACÓRDÃO spot-check: EMENTA + ACÓRDÃO markers present in
100%, body text clean Portuguese, char counts plausible
(2.4k-23.7k range). Empirical validation that the four-layer
defense (pre-warm + paralelo 10 + tenacity 5×30 + auto router)
turns a 7.3% failure rate into 0% on the same workload.

**HC 2025 chain regression caught + fixed (commit `b5cd7d2`).**
First varrer-processos run since the Phase 1 parser fix
(`ae19d73`) surfaced an `AttributeError: 'NoneType' object has no
attribute 'encode'` on every redirect-form DJe entry —
`_resolve_publicacoes_dje:150` called `detail_fetcher(None)`
without checking. ~47% case error rate by record 1,300. Killed
the chain, fixed (skip the detail fetch when `detail_url is
None`), restarted from the same `--saida` (resume picked up the
~480 captured cases). Post-restart error rate: 0 in the first
2,750 records. HC 2026 didn't surface this because Stage A ran
2026-05-01 *before* the parser fix landed; the bug was latent
until the next varrer-processos invocation.

**Halt 2026-05-02 20:33 BRT — both backfill chains stopped at
user request.** Both chains had progressed Stage A (varrer) and
Stage B (baixar) cleanly and were in Stage C (extrair) at halt
time. SIGTERM was sent at 20:30 BRT; the `--paralelo 10`
extractors didn't drain in 10s (workers blocked on in-flight
`tesseract_fly` round-trips), so escalated to SIGKILL at 20:33.
State snapshots at halt:

| Chain    | Stage C progress              | Throughput / ETA              | State file mtime |
| -------- | ----------------------------- | ----------------------------- | ---------------- |
| HC 2025  | 13,512 / 28,261 (47.8%)       | 0.76 tgt/s · ETA ~323 min     | 20:33            |
| HC 2021  | 1,179  / 10,062 (~11.7%)      | early ramp                    | 20:32            |

HC 2025 ok=5,784 / cached=6,162 / no_bytes=11 / fail=1,543 at
halt — the ~11% running fail rate is well above HC 2026's
post-mitigation 0%, which would have been worth a regime probe
mid-run. SIGKILL is safe because `peca_store.py`'s atomic
write contract (tempfile + fsync + rename) means each
`pdfs.state.json` is either the prior or current snapshot,
never a half-write; `--retomar` resumes from the last flushed
record. Resume commands (Stage C only — Stages A + B are
fully done):

```bash
uv run judex extrair-pecas -c HC -i 250920 -f 267137 \
    --provedor auto --saida runs/active/backfill-hc2025-2026-05-02/extrair \
    --paralelo 10 --retomar --nao-perguntar

uv run judex extrair-pecas -c HC -i 198000 -f 210963 \
    --provedor auto --saida runs/active/backfill-hc2021-2026-05-02/extrair \
    --paralelo 10 --retomar --nao-perguntar
```

**`coletar`-orchestrator smoke test in flight** (PID 504746,
launched 20:22 BRT). Exercises today's three commits — `42f1d12
feat(coletar): orchestrator for the 6-stage pipeline (ADR-0004)`,
`53d3ce3 feat(replay): status-aware retry replay via
error_triage classifier`, `0abeef7 docs(adr): ADR-0004 coleta
orchestrator with status-aware retry`. Scope: HC 245000-245099
(100 cases, narrow slice of HC 2024 PID range). Run dir
`runs/active/coletar-smoke-2026-05-02/` with the orchestrator's
own `varrer/`, `baixar/`, `extrair/` sub-dirs (one launcher log
at the run root, not per-stage). At 20:37 BRT: extrair sub-stage
50/171 (29.2%) at 0.08 tgt/s, ETA ~24.6 min — slow rate worth
watching but plausible given the small denominator and the
`tesseract_fly` Modal hop dominating any non-pypdf doc.

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

- ✅ Ran `uv run judex atualizar-warehouse --classe HC` 2026-05-02 12:43 BRT (~6 min, atomic swap, 1.85 GB warehouse). Empirical close-out by year (HC, post-migration):

  | Year | `publicacoes_dje` coverage | Was | `decisoes_dje.rtf_url` |
  | ---- | --------------------------:| ---:| ----------------------:|
  | 2022 |                      74.5% | 74.5% (legacy era unchanged) | 10,128 (legacy) |
  | 2023 |                  **49.8%** | **0%** | 0 (Phase 2 deferred) |
  | 2024 |                  **57.0%** | **0%** | 0 (Phase 2 deferred) |
  | 2025 |                  **72.8%** | **0%** | 0 (Phase 2 deferred) |
  | 2026 |                  **73.0%** | **0%** | 0 (Phase 2 deferred) |

  Pub-entry counts match the renormalize report exactly for 2025 (22,328) and 2026 (4,727); 2023/2024 land within ~3% of the renormalize numbers (warehouse flatten/dedupe path). All-zero `decisoes_dje.rtf_url` for 2023+ is the literal storage manifestation of "Phase 2 deferred" (per ADR-0003).
- ✅ Commit Phase 1 to `dev` — landed as `ae19d73 feat(dje): capture post-migration redirect entries (ADR-0003 Phase 1)`.
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
