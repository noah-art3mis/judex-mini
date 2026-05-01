# Current progress — judex-mini

Branch: `dev`. Prior cycle archived at
[`docs/progress_archive/2026-05-01_0016_ocr-bakeoff-tesseract-winner.md`](progress_archive/2026-05-01_0016_ocr-bakeoff-tesseract-winner.md)
— OCR provider bakeoff close-out (2026-04-30 → 2026-05-01). Tesseract
on Modal CPU replaces Mistral as production OCR (14× cheaper, beats
Mistral on every quality axis). Bakeoff narrative + per-provider
empirical findings promoted to
[`docs/reports/2026-04-30-ocr-bakeoff.md`](reports/2026-04-30-ocr-bakeoff.md).

**Status as of 2026-05-01.** Corpus: **90,763** cases. PDF cache
**99,057** `.pdf.gz` (+4,966 from HC 2025+2026 surface-2 backfill
closed today, see ADR-0001 step 3 below), 3,621 `.rtf.gz`, 105,821
`.txt.gz`. Warehouse rebuilt 2026-04-30 17:45 BRT (530s, 3.02 GB) —
not yet rebuilt against today's new bytes. HC 2022 peça sweep
closed 2026-04-30 (15,007 ok / 0 fails); HC 2024 + HC 2023 closed
earlier. Four-year HC peça ladder (2022–2025) at ≥97% text coverage
on direct IP.

**Active cycle (opened 2026-05-01):** characterised the pypdf
column-scramble bug on `INTEIRO TEOR DO ACÓRDÃO` PDFs (gold-CER ≈
90% via 1.86× content duplication from the iText cover-stream),
landed the `--provedor auto` doc_type-based router in
`extrair-pecas`, promoted `DECISÃO DE JULGAMENTO` from tier-C →
tier-B in `peca_classification.py`. Tesseract-on-ACÓRDÃO benchmarked
at 0.75% gold-CER (DPI 150, ~$0, 0.78 s/page); DPI sweep results in
`runs/active/2026-05-01-tesseract-sweep/sweep_report.md`. Closed
**HC 2025+2026 surface-2 backfill** (10,002 fresh `.pdf.gz` fetched
on direct IP from `digital.stf.jus.br` + `sistemas.stf.jus.br`,
27 http_errors, 0 WAF blocks). Confirmed empirically the **post-2022
DJe blackout** documented in the section below (0/200 cases for HC
2023-2026). Characterised local Tesseract instability on the 4 GB
WSL2 box (Pool-deadlock under OOM pressure); landed a Fly.io
HTTP-fanout prototype in `fly/` as the pivot path — see "Cloud OCR
direction" below. Bumped `_PER_WORKER_RAM_MB` 250 → 500 in
`judex/scraping/ocr/tesseract.py` (uncommitted) to give the local
auto-sizing more headroom on memory-constrained boxes.

## Active task — targeted ACÓRDÃO re-extract via auto-router

**Why.** Existing `.txt.gz` files for the 20,008 ACÓRDÃO PDFs were
all written by pypdf (per `.extractor` sidecar inventory: 67% pypdf,
21% pypdf_plain, 12% rtf, 0% OCR). The iText cover-stream
duplication makes them silently wrong — char count is plausible,
content is doubled. Tesseract reads only the rendered raster, so
its output matches gold to <1% CER on the same PDFs. Re-extracting
fixes EMENTAs (the legally-citable headnotes) corpus-wide.

**Scope.** Cases that contain at least one ACÓRDÃO. CSV at
`runs/active/extrair-acordaos-2026-05-01/cases.csv` (18,742 HC
processes). Forecast: 16,671 to-extract (12,930 via tesseract on
ACÓRDÃOs, 3,741 via pypdf on misc non-ACÓRDÃO docs in those cases),
$0 cost (both providers free/local). The docstring's "~11 hr
single-process wall" was anchored on a beefier box; on this 4 GB
WSL2 host the local-Tesseract path is **~2 days** at sustainable
parallelism (see Status below).

**Status (2026-05-01).** **573 OK extractions landed** (sidecar-
protected — they won't re-OCR on next launch via `--retomar`). Run
currently alive at PID 1138139 producing OKs at ~265/hr sustained
once (b)'s memory contention cleared. Two failure modes characterised
during today's launches:

1. **`multiprocessing.Pool` deadlock under OOM.** With the bumped
   `_PER_WORKER_RAM_MB = 500` constant, auto-sizing picks 4-6 inner
   Pool workers per PDF. On long ACÓRDÃOs (200+ pages) the
   rasterization+OCR overlap can briefly exceed the static cap,
   triggering WSL2's OOM heuristic on a tesseract subprocess; the
   killed subprocess leaves the Pool's `pool.map()` hung indefinitely
   waiting for results, master process catches its own SIGTERM but
   sits *outside* the OCR call so graceful-shutdown also hangs. Fix
   in flight is environmental (no concurrent memory-heavy jobs);
   structural fix needs the Modal/Fly path.
2. **Orphan reaping after force-kill.** `SIGKILL` on the master
   leaves tesseract subprocesses reparented to `/init` (PPID 705701
   on this WSL2). They keep running with full memory + CPU until
   manually reaped by PPID — `pkill -9 -P <init> -f tesseract` is the
   reliable cleanup. Tracked: extending `iterate_with_guards` to
   propagate signals into the inner Pool would prevent this.

**Pivot — Fly.io HTTP fanout (prototype landed 2026-05-01).** New
directory `fly/` carries Dockerfile + FastAPI server (`server.py`) +
`fly.toml` configured for `shared-cpu-2x` / 4 GB / São Paulo. The
service exposes `POST /extract` (raw PDF body → text JSON);
`auto_start_machines = true` + `auto_stop_machines = "stop"` means
idle = $0. Cost projection for the 12,930-ACÓRDÃO ladder × ~5 s OCR
at 30-way client thread fanout: **~36 min wall, ~$0.21**, ~10×
cheaper than Modal's $2.27 estimate for the same work. See
`fly/README.md` for deploy + smoke-test instructions; provider
integration (`tesseract_fly` in `judex/scraping/ocr/`) and the
client-side thread pool refactor in `extract_driver.py` are deferred
until the smoke test confirms the deploy path works. Prerequisites:
`flyctl` install (one-line curl) + `flyctl auth login` (browser).

**Done when.** Either (a) full ladder finishes locally — possible
but ~2 days, low priority since (b) is faster and cheaper — or
(b) Fly.io path validates and finishes the ladder, then `report.md`
shows ≈ 12,930 tesseract + ≈ 3,741 pypdf extractions, zero failures.
Spot-check 5–10 ACÓRDÃO `.txt.gz` files: `EXTRATO DE ATA` and
`RELATÓRIO`/`VOTO` markers should appear exactly once per doc (vs
~2× in pypdf-broken output). Then rebuild the warehouse:
`uv run judex atualizar-warehouse --classe HC`.

**Re-launch (idempotent, local path):**

```bash
nohup uv run judex extrair-pecas \
    --csv runs/active/extrair-acordaos-2026-05-01/cases.csv \
    --provedor auto \
    --saida runs/active/extrair-acordaos-2026-05-01 \
    --nao-perguntar --retomar \
  > runs/active/extrair-acordaos-2026-05-01/launcher-stdout.log 2>&1 &
echo $! > runs/active/extrair-acordaos-2026-05-01/launcher.pid
```

- `--retomar` skips already-OK targets via per-target sidecar match.
- On this 4 GB box, expect ~265 OK/hr **only** with no other
  memory-heavy jobs running. Concurrent (b)-style work tanks the rate
  to ~30/hr and risks Pool-deadlock within 1-2 hr.
- Monitor: `tail -f .../launcher-stdout.log` plus
  `jq '[.[] | .status] | group_by(.) | map({s:.[0],n:length})'
  .../pdfs.state.json` for the status histogram.

## Urgent — DJe scraper regression: 2023+ blackout (3+ yrs of HC data)

**Status.** Diagnosed 2026-04-21 (logged in
[`docs/system-changes.md`](system-changes.md) under the **2022-12-19
DJe platform migration** row), re-confirmed empirically 2026-05-01
during ADR-0001 follow-up. Not yet fixed.

**What's broken.** `judex/scraping/scraper_dje.py:48` calls
`portal.stf.jus.br/servicos/dje/listarDiarioJustica.asp?incidente=N`.
STF migrated post-2022-12-19 DJe content to
`digital.stf.jus.br/publico/publicacoes`; the old endpoint now serves
migration-redirect stubs for any case after that date. The scraper
parses the empty listing and writes `publicacoes_dje = []`, silently.

**Empirical hit (2026-05-01, 200-case sample per year):**

| Year | Cases w/ publicacoes_dje | Decisoes total | Notes                                  |
| ---- | ------------------------ | -------------- | -------------------------------------- |
| 2026 | 0 / 200                  | 0              | post-migration                         |
| 2025 | 0 / 200                  | 0              | post-migration                         |
| 2024 | 0 / 200                  | 0              | post-migration                         |
| 2023 | 0 / 200                  | 0              | post-migration (full year)             |
| 2022 | 144 / 200 (72%)          | 205            | last year before migration             |
| 2020 | 2 / 200 (1%)             | 15             | sparse pre-existing                    |

The 2023→2022 cliff is the migration date showing through the data;
the field itself is missing on post-2022 records (not capture-gap
nulls). The corpus today is 90,763 cases — the post-2022 portion is
the active research window, so this is a corpus-wide silent gap, not
a backfill curio.

**Mitigations available.**

1. **Path 1 (cheap, ~1–2 h):** andamentos-side DJe metadata regex —
   `andamentos[].descricao` carries `"PUBLICADO O ACÓRDÃO, DJE N° X,
   DIVULG DD/MM/YYYY, PUBLIC DD/MM/YYYY"` as structured rows.
   Parsing those into `publicacoes_dje` recovers ~80% of DJe-level
   metadata (issue number, dates, secao) *without* fetching the
   migrated content. No HTTP, no WAF.
2. **Path 2 (1–2 d):** Playwright against `digital.stf.jus.br` past
   the `token.awswaf.com` JS challenge. Recovers full DJe text. New
   browser-automation surface; no current Playwright infra in repo.
3. **Path 3:** AWS WAF reverse-engineering — explicitly *don't*
   per `system-changes.md`.

**Recommendation.** Path 1 first when this cycle opens — covers the
common "which DJe issue carried this acórdão?" query for the whole
post-2022 window at near-zero cost, and pins
`publicacoes_dje > 0%` again so the warehouse build-stats validator
stops flagging it as a regression. Path 2 stays open for any
analysis that genuinely needs DJe full text (rare today; 97% peça
text coverage covers most "what did this case say?" queries via
sessao_virtual + andamento PDFs).

**Pre-launch checks.** Before doing Path 1, sample ~20 post-2022 HC
andamentos with `descricao` containing `DJE` to confirm the regex
shape is stable across years (STF templating drift is the usual
gotcha). Then add unit tests in `tests/unit/test_extract_andamentos.py`
pinning the parsed shape against fixtures — same pattern as the
existing extractor tests.

**Done when.** A re-scrape of any 200-case post-2022 HC sample shows
`publicacoes_dje` populated on ≥80% of cases via the andamento-side
parser, and `judex/scraping/scraper_dje.py` is marked deprecated (or
the call is gated on `data_protocolo < 2022-12-19`) so it stops
hitting a known-empty endpoint and burning request budget.

## Backlog — ADR-0001 step 3: bytes-first backfill for surfaces 2 + 3

**Status.** ADR steps 1 + 2 landed (`bc04799` + the bytes-first
`varrer-processos` refactor). Step 3 partially closed 2026-05-01:
HC 2025+2026 surface-2 backfill done (10,002 ok / 27 http_errors /
0 WAF blocks via direct IP); HC 2017–2024 surface-2 + the small
HC 2022 surface-3 residual still pending. See
[`docs/adr/0001-unify-peca-fetch-under-bytes-first-model.md`](adr/0001-unify-peca-fetch-under-bytes-first-model.md).

**HC 2025+2026 surface-2 close-out (2026-05-01).** Run dir
`runs/active/baixar-surface23-hc2025-2026-05-01/` (CSV: 4,021 cases,
8,688 surface-2 byte-gap URLs scoped via
`peca_targets.targets_from_range(inicio=250920, fim=271139)`). The
sweep auto-included surface-1 stragglers in those cases; total target
count post-substantive-filter was 20,496 → 10,466 already cached →
**10,030 fresh fetches → 10,002 ok / 1 empty_response / 27
http_error**. Wall: 5h 53m direct IP, no proxies, no shards, no
breaker trips. `digital.stf.jus.br` sustained ~2.5 req/s, well above
the `_AVG_REQ_WALL_S_DIRECT = 3.0` s/req anchor in `judex/utils/cost.py`
— **digital.stf is materially less WAF-aggressive than
portal.stf**, worth re-anchoring the cost module against this run.

**Surface-3 (DJe rtf.url) confirmed effectively zero for HC 2023+.**
Empirical verification 2026-05-01 (200-case samples): HC 2026/2025/
2024/2023 all have **0/200 cases with `publicacoes_dje` populated**;
HC 2022 has 144/200 (72%). The field itself is missing on
post-2022 records — not capture-gap nulls. This is the same DJe
scraper regression flagged in the **Urgent — DJe scraper regression**
section above. Consequence for ADR-0001 step 3: surface-3 backfill
is irrelevant for HC 2023+ (no URLs to fetch); the residual surface-3
work is HC 2022's ~150 decisoes-per-200-cases × ~13k cases, modest.

**Remaining for full step 3.** HC 2017-2024 surface-2 byte-gap (per
`completion-tracker.md` ladder, ~3-4k ACÓRDÃO cases per year × ~2.6
sessao_virtual URLs/case post-substantive-filter ≈ ~50-80k URLs
across the 8 years). Fetching pattern is the same as today's run:
direct IP against `digital.stf.jus.br`, ~2.5 req/s, no proxies needed.
Estimated wall at single-IP: ~5-10 hr per year; could shard via
`judex baixar-pecas --shards N --proxy-pool …` if a single overnight
window matters, but direct-IP solo finishes in 1-2 days.

**Why it matters now.** Without the byte-side backfill, three
follow-on capabilities are blocked:

1. **Re-extracting Voto / Relatório sections via tesseract.** The
   auto-router's "tesseract for ACÓRDÃO" rule fires only when bytes
   exist. Without them, the section sub-rows in `pdfs_substantive`
   keep their pypdf-era text indefinitely.
2. **Provider switch parity.** ADR-0001's stated goal — "every peça
   re-extractable" — only holds once bytes exist on every surface.
3. **Honest forecasting.** `judex/utils/cost.py`'s
   `_AVG_REQ_WALL_S_DIRECT` was anchored on andamento-only sweeps;
   today's run anchors it for the digital.stf endpoint — refresh
   the constant against the new evidence.

**Re-launch pattern (for any year):**

```bash
mkdir -p runs/active/baixar-surface2-hc<YYYY>-<date>
uv run python -c "
from pathlib import Path
import csv
from judex.sweeps.peca_targets import targets_from_range
from judex.utils.peca_cache import _find_bytes_path
# pid range from completion-tracker.md per-year table
targets = targets_from_range(classe='HC', inicio=<MIN_PID>, fim=<MAX_PID>,
                             roots=[Path('data/source/processos')])
s23_gap = [t for t in targets if t.surface in {'sessao_virtual','dje'}
           and _find_bytes_path(t.url) is None]
cases = sorted({(t.classe, t.processo_id) for t in s23_gap})
out = Path('runs/active/baixar-surface2-hc<YYYY>-<date>/cases.csv')
with out.open('w', newline='') as f:
    w = csv.writer(f); w.writerow(['classe','processo'])
    for c, p in cases: w.writerow([c, p])
"
nohup uv run judex baixar-pecas \
    --csv runs/active/baixar-surface2-hc<YYYY>-<date>/cases.csv \
    --saida runs/active/baixar-surface2-hc<YYYY>-<date> \
    --retomar --nao-perguntar \
  > runs/active/baixar-surface2-hc<YYYY>-<date>/launcher-stdout.log 2>&1 &
```

## Cloud OCR direction — Fly.io prototype + alternatives surveyed

**Why this exists.** The local-Tesseract path on this 4 GB WSL2 box
hit two structural problems on 2026-05-01 (Pool deadlock under OOM,
multi-day wall at sustainable parallelism). Modal already exists as
a backstop (`judex/scraping/ocr/modal_app.py`'s `tesseract_extract`
endpoint, fronted by `tesseract_modal` provider) but is the most
expensive per-CPU-second of the platforms surveyed. This section
records the alternatives + the prototype landed today.

**Prototype: Fly.io HTTP fanout (`fly/`).**

- `fly/Dockerfile` — Tesseract + Portuguese language pack +
  poppler-utils + FastAPI, ~250 MB image. Mirrors `modal_app.py`'s
  tesseract image so OCR output is byte-identical between Modal and
  Fly variants.
- `fly/server.py` — single endpoint `POST /extract` (raw PDF body →
  text JSON). In-PDF page parallelism via `ThreadPoolExecutor(
  max_workers=os.cpu_count())` — Tesseract releases the GIL during
  the C-extension call, threads (not processes) avoid the
  Pool-deadlock failure mode that bites locally.
- `fly/fly.toml` — `shared-cpu-2x` / 4 GB / `gru` (São Paulo).
  `auto_start_machines = true` + `auto_stop_machines = "stop"` +
  `min_machines_running = 0` → idle = $0; Machines wake on first
  HTTPS request (~5 s cold start), scale to zero when idle.
- `fly/README.md` — deploy + smoke test + integration sketch.

**Empirical platform comparison (2026 rates, focused on this
codebase's needs).**

CPU options (Tesseract is CPU-only, no GPU benefit):

| Platform                | Comparable shape           | Hourly      | 12,930-PDF projected cost | Notes                                                  |
| ----------------------- | -------------------------- | ----------- | ------------------------- | ------------------------------------------------------ |
| Modal (current)         | cpu=2, mem=4GB             | ~$0.13/hr   | ~$2.27                    | Drop-in via existing `tesseract_modal` provider.       |
| **Fly.io (prototype)**  | shared-cpu-2x / 4 GB       | $0.0118/hr  | **~$0.21**                | Per-second billing, free egress, ~5s cold start.       |
| Hetzner CPX21           | 4 vCPU AMD / 8 GB          | $0.013/hr   | ~$0.07                    | Hourly minimum; SSH-style ops, more setup.             |
| RunPod CPU pod          | 1 vCPU / 4 GB              | from $0.04  | ~$0.20                    | Container-first; per-second billing, 60-90 s start.    |
| AWS Lambda              | 4 GB                       | per-invoke  | ~$10-50                   | Per-invoke overhead kills it at this scale.            |

Fly.io wins on: per-second billing + free egress + lowest cpu-hr
rate of any container-first platform + ~5 s cold start. The
Hetzner number is theoretically lower but requires building the
"spawn ephemeral VPS, run, tear down" tool from scratch — not
worth $0.14 for a one-shot.

GPU options (only relevant if switching engines to surya/paddle/
chandra; the bakeoff already ranked Tesseract above these on
combined cost+quality):

| Engine + Platform              | Hardware            | Hourly      | Per-1k pages | Notes                                              |
| ------------------------------ | ------------------- | ----------- | ------------ | -------------------------------------------------- |
| Datalab Chandra (hosted API)   | n/a                 | n/a         | $3.00        | Current `chandra` provider; expensive at scale.    |
| **Self-host Chandra v2 (4B)**  | RTX 4090 / A100     | ~$0.20-1.10 | **~$0.05-0.55** | Weights public on HF (`datalab-to/chandra-ocr-2`); OpenRAIL-M license + Apache code; 50× cheaper than hosted API. |
| Modal Surya (current bakeoff)  | L40S                | $1.95/hr    | ~$0.30       | Already in `modal_app.py`.                          |
| Vast.ai RTX 4090 spot          | RTX 4090 (24 GB)    | ~$0.20      | varies       | Cheapest GPU spot; interruptible, needs restart logic. |
| RunPod RTX 4090 (Secure)       | RTX 4090            | ~$0.34      | varies       | Reliable spot alternative.                          |

Chandra v2 specs from research: 4B params, BF16, fits RTX 4090
(24 GB) tight via flash-attn or comfortably on A100 40 GB; ~1.44
pages/sec on H100 with vLLM (~2 pages/sec real-world); license is
OpenRAIL-M weights + Apache code with a "non-competitive use"
clause and a $2M revenue cap on free use — internal STF document
extraction qualifies, but worth a careful read before committing.
Closest fully-permissive alternative is Marker (also Datalab,
GPL-3.0, slightly lower quality on the olmOCR benchmark: 76.5 vs
83.1).

**Decision tree.**

- **If today's local sweep finishes** (~2 days) → ship that, defer
  the Fly.io path until the next sweep.
- **If you want it tonight** → install `flyctl` + smoke-test the Fly
  prototype + add a 30-line `tesseract_fly.py` provider mirroring
  `tesseract_modal.py` + add a `--paralelo N` flag wrapping
  `dispatch_fn` in `extract_driver.py` with a thread pool. ~1-2 hr
  total work, ~36 min sweep wall, ~$0.21 spend.
- **If quality matters more than cost** (e.g. for legal-citation
  ementas) → self-host Chandra v2 on Modal A100 80GB (~$80 for the
  full ladder, the highest-quality OCR available per the bakeoff).
  This needs a new `@app.function(gpu="A100-80GB", image=
  chandra_image)` in `modal_app.py` plus a `chandra_modal` provider.
- **Skip permanently:** Datalab hosted Chandra API at this scale
  ($1,164 for 12,930 PDFs). Self-hosting is 50× cheaper.

**Empirical results — Fly deploy + tests (2026-05-01 evening).**
Provider `tesseract_fly` landed in `judex/scraping/ocr/`; `--paralelo
N` flag landed in `extract_driver.py` (pure-add, sequential path
unchanged; `paralelo=1` default → existing tests all pass). App
deployed at `judex-ocr-tesseract-arcos.fly.dev` (gru region, 16
Machines pre-scaled). Two 30-target benchmark runs against HC 2024
ACÓRDÃOs at `--paralelo 16 --forcar`:

|                       | shared-cpu-2x | performance-2x |
| --------------------- | ------------- | -------------- |
| Hourly per Machine    | $0.0118       | $0.057         |
| Mean wall / PDF       | 27.8 s        | 32.0 s         |
| P90 wall / PDF        | 55 s          | 70 s           |
| Max wall / PDF        | 110 s         | 78 s           |
| Test wall (30 tgt)    | 5:27          | 1:30           |
| Failure rate          | 8% (300 s timeouts) | 12% (mid-resize 502s) |

**Headline.** Per-PDF mean is ~similar; performance-2x's win is the
**absence of long-tail 300 s timeouts** under sustained 16-Machine
load (shared-CPU contention on Fly hosts when many Machines run hot
simultaneously). Bill is invariant to `--paralelo` for a given
Machine size — you optimise paralelism purely for wall.

**Full-ladder projections (12,930 ACÓRDÃOs).**

| Path                       | Wall   | Bill  | Retries? |
| -------------------------- | ------ | ----- | -------- |
| Fly shared-cpu-2x × 30     | 3.6 hr | $1.28 | ~8% (1k PDFs) |
| Fly shared-cpu-2x × 60     | 1.8 hr | $1.28 | ~8% (1k PDFs) |
| Fly performance-2x × 30    | 3.8 hr | $6.55 | 0        |
| Fly performance-2x × 60    | 1.9 hr | $6.55 | 0        |
| Modal tesseract_modal      | ~17 hr | $2.27 | 0        |
| Local on this 4 GB box     | ~18 d  | $0    | n/a      |

**Picked path** (pending operator go): shared-cpu-2x × 60 at
`--paralelo 60`, accepting the retry tail. ~1.8 hr wall + ~30 min
retry pass via `--retentar-de pdfs.errors.jsonl`, ~$1.30 total.
Operationally: `flyctl scale vm shared-cpu-2x --vm-memory 4096` to
reverse today's perf-2x resize, `flyctl scale count 60`, then launch
`extrair-pecas --provedor tesseract_fly --paralelo 60`.

## Next-cycle candidates (carried over from prior backlog)

1. **Cut over `extrair-pecas` default to Tesseract** — wire the new
   Modal-hosted provider into the `--provedor` flag and update
   `judex/cli.py` defaults. Optional ~30-line regex post-process to
   close the residual 1.04% gap (`§ → 8`, ellipsis-period drops,
   auth-code character-class swaps). Detail in the bakeoff report.
2. **HC 2024 extract second pass** — text coverage at 80% vs 97-99%
   on 2023/2022. Investigate ~3k-row gap (provider failures, RTF
   mistypes, scanned originals?) and run a focused
   `extrair-pecas --csv` retry, possibly with chandra/tesseract.
3. **HC 2017–2021 case sweeps** — ~37k missing case widths combined,
   ordered by year-density. Once cases land, peça sweeps follow in
   the proven 15k-URL/year shape.
4. **Schema cleanup** — drop `andamentos.link_text` /
   `documentos.text` / `decisoes_dje.rtf_text` from the warehouse
   build path (queries already use `pdfs_substantive`'s join). Lets
   `_CHUNK_SIZE` climb back toward 5000 + halves warehouse build
   peak RAM.
5. **`publicacoes_dje` → warehouse** — open warehouse gap noted in
   prior archive § Backlog.

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

## Working conventions

- **`analysis/`** — git-ignored scratch for this-session exploration.
- **`config/`** — git-ignored (credentials). Canonical proxy input is
  `config/proxies` (flat file).
- **All non-trivial arithmetic via `uv run python -c`** — never mental
  math. See `CLAUDE.md § Arithmetic`.
- **Sweeps write a directory**, not a file. Layout in
  [`docs/data-layout.md § Sweep run artifacts`](data-layout.md#sweep-run-artifacts).
- **Archive convention**: when the active task closes out or this file
  grows past ~500 lines, move it (or the cycle-specific portion) to
  `docs/progress_archive/YYYY-MM-DD_HHMM_<slug>.md`.
- **Live sweep monitor**: `tail -f <run_dir>/launcher-stdout.log` is
  the canonical view across all 3 stages — see CLAUDE.md § Conventions.
  Don't roll bespoke monitor scripts.
