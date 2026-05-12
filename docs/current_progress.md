# Current progress — judex-mini

Branch: `dev`. Prior cycle archived at
[`docs/progress_archive/2026-05-11_2130_chain-closeout-corpus-restore-lifecycle-cli.md`](progress_archive/2026-05-11_2130_chain-closeout-corpus-restore-lifecycle-cli.md)
— HC 2025/2024/2022/2021 fill-in chain v2 launch + paused-at-step-6
narrative, PR #16/#17 (recuperar v2 + `--loop` convergence), runs/active
housekeeping (74 → 40), `executar` flag-surface narrowing.

**Status as of 2026-05-12 ~18:00 BRT.** Today knocked out priority-queue
item #1 (May 4-5 chain delta re-run) and patched two real recuperar
bugs surfaced by the closeout. The progress narrative for today is in
`## Resolved this session — chain delta re-run + recuperar bugfix
(2026-05-12)` below. Status as of 2026-05-11 21:30 BRT (kept for
context — three things shipped that day):

1. **HC 2021 chain v2 step 6 closed cleanly.** Resume re-entered the
   paused-since-May-5 sweep against `runs/active/hc2021-fillin-20260504-v2/`,
   wall=30.3 s (98.6% cache-hit at the meta layer), drained the 351
   residual transient fetch_bytes, then `recuperar --loop --apply --nao-perguntar`
   one-pass-and-stopped on the 290 terminal `empty` peças (URLs that STF
   serves zero bytes for — irrecoverable). Final `report.md` quality
   grade **B** (text_ok 98.6%).
2. **Corpus restored from the May 3 backup zip.** Between May 5 and today
   somebody deleted `data/source/processos/HC/` (live tree); the local
   17.6 GB `runs/active/backups/judex-backup-20260503T054402Z.zip` was
   the recovery anchor. Restored 91,048 case JSONs + topped up bytes/text
   caches; warehouse rebuild back to 91,048 cases / 318,693 partes /
   1,247,234 andamentos / 28,822 substantive PDFs, all five build-time
   quality gates passing.
3. **Sweep-lifecycle CLI feature landed.** New `judex parar`, `judex
   retomar`, `executar --detach` plus a shared `_resolve_run_dir`
   default-to-newest helper applied uniformly across all five Coleta
   commands (`acompanhar`, `relatar`, `recuperar`, `parar`, `retomar`).
   +25 new tests (`tests/unit/test_cli_lifecycle.py` new file + extensions
   to `test_pipeline_state.py` and `test_pipeline_runner.py`). Tests now
   at **1,048 passing**.

---

## Resolved this session — chain delta re-run + recuperar bugfix (2026-05-12)

The May 4-5 chain delta re-run (priority-queue item #1 from the prior
notebook) is now closed for all four years. Wall + outcomes:

| # | Run                                         | n_targets | Status   | Wall    | Notes                            |
|---|---------------------------------------------|----------:|----------|---------|----------------------------------|
| 1 | `hc2024-delta`                              |    14,389 | finished | 1h 02m  | clean                            |
| 2 | `hc2025-pending-delta`                      |       744 | finished | 47m     | clean                            |
| 3 | `hc2022-delta`                              |    12,922 | finished | 1h 18m  | clean                            |
| 4 | `hc2021-delta`                              |    10,522 | stopped → recuperar | 12 h then 0.9 s + 3-pass loop | hit two recuperar bugs (see below) |

All four archived to `runs/archive/`. Warehouse rebuilt. The HC 2021
delta tail was a 12-hour drift into WAF collapse (`regime=collapse,
fail_rate=0.38, p95_wall=844 s`) — operator-stopped at processo 202710
with 9,150 ok meta + 19 SSL-storm `http_error` meta on a contiguous
range (HC-206779 to HC-206797) + 51 terminal `empty` peças. The
`empty` bytes are the same persistent-zero-bytes pattern from the
2026-05-11 chain v2 closeout (290 such peças then); STF's portal
serves 0 bytes on those URLs and they look transient by
classification but are terminal by data.

### Recuperar two-bug fix — commit `52b3fa8`

Running `judex recuperar --loop --apply --nao-perguntar` against the
stopped run **hung indefinitely**. Diagnosis surfaced two latent bugs
that only fire when recuperar is run against a *killed-mid-flight*
sweep (clean finishes never triggered them — that's why the bugs
survived in prior `recuperar v2` work):

**Bug 1 — REPLAY didn't materialise its `--retentar-de` payload.**
`_plan_replay_spawns` (judex/sweeps/recuperar.py:355–376) pointed the
child at `source_dir / executar.errors.jsonl` and wrote nothing,
relying on the file existing from a clean sweep finalize. Killed-mid-
flight runs have no `executar.errors.jsonl` (the finalize step at
`judex/pipeline/runner.py:430–438` never ran). The child opened the
absent file, `targets_from_errors_jsonl` returned zero rows, the
`resolve_targets` over-scoping guard exited 2 with "nenhum alvo
resolvido pelos parâmetros dados." The 89 ErrorRows recuperar's
classifier had identified lived only in the parent's memory.

The other two spawn planners (`_plan_provider_switch_spawns`,
`_plan_refetch_upstream_spawns`) **already materialised** their
inputs via `materialized_content`; REPLAY was the only one that
forgot. Fix: render the 89 rows into the canonical wire schema (same
shape as `judex.pipeline.log.derive_errors_file`) via a new
`_build_replay_errors_jsonl(rows)` helper and pass it through as
`materialized_content`. `execute_recoveries` writes it to disk at line
549–553 before spawning.

**Bug 2 — `wait_for_pids` couldn't detect zombies.** The original
implementation used `os.kill(pid, 0)` polling. On Linux that returns
silently for **zombie PIDs** (`State: Z` in `/proc/<pid>/status`) —
`ProcessLookupError` only fires once the PID is reaped. With
`start_new_session=True` on the child + no parent reaper, the
exit-2'd child became a zombie that nobody reaped, the poll spun
forever. Fix: new `_pid_is_active(pid)` helper reads
`/proc/<pid>/status` on Linux and treats `Z`/`X` as inactive; kill-
based probe as non-Linux fallback. Updated docstrings.

**Tests (+3 new, +1 refactor; suite now 1,073 passing in 26 s):**

| File                          | Test                                                   | What it pins                                                              |
|-------------------------------|--------------------------------------------------------|---------------------------------------------------------------------------|
| `tests/unit/test_recuperar.py`| `test_plan_replay_materialises_retentar_de_payload`    | REPLAY emits `materialized_content` with the right wire schema fields     |
| `tests/unit/test_recuperar.py`| `test_execute_recoveries_writes_replay_errors_file_to_disk` | The materialised content actually lands at `source_errors_file`          |
| `tests/unit/test_recuperar.py`| `test_wait_for_pids_detects_zombie_child`              | `os.fork`-based real zombie pid is detected within `poll_interval`        |
| `tests/unit/test_recuperar.py`| `test_wait_for_pids_returns_when_all_dead` (refactor)  | Mocks `_pid_is_active` instead of `os.kill` — behavioural, not syscall-coupled |

### Recuperar pass-by-pass after the fix

Real numbers from `runs/archive/20260512_011434-hc2021-delta/`:

```
recuperar pass 1: 89 actionable rows  →  child wall=0.9s  →  88 actionable after
recuperar pass 2: 63 actionable rows  →  child wall ~1s   →  63 actionable after
recuperar pass 3: 63 actionable rows  →  loop's no-progress guard exits
recuperar: stopped after 3 pass(es) — residual stopped shrinking
```

Stage-level shrinkage:

| Bucket                  | Pre-recuperar | Post-recuperar | Notes                                          |
|-------------------------|---------------:|---------------:|------------------------------------------------|
| `fetch_meta http_error` |             19 |             11 | 8 SSL-storm cases recovered                    |
| `fetch_meta unallocated_pid` |        1,353 |          1,358 | 5 of the SSL-failed turned out to be real 404s |
| `fetch_bytes http_error`|             19 |              0 | all recovered                                  |
| `fetch_bytes empty`     |             51 |             63 | net +12 — fresh empties discovered on retry    |
| `cap_burnt`             |              0 |              1 | safety valve dropping a perpetual-fail row     |

The 63 stuck-empty residual is the false-transient class (classifier
correctly says retry, server says 0 bytes every time). The 3-pass
no-progress exit is the loop doing its job. This delta is at
effectively 100% coverage of the resolvable cases (9,165 ok /
(10,522 − 1,358 unallocated) = 99.99%).

---

## Resolved this session — HC 2021 chain v2 closed (2026-05-11)

The chain v2 launched 2026-05-04 22:03 BRT and paused 2026-05-05 09:18 BRT
at step 6 (HC 2021, range -i 196282 -f 210963, 12,702 / 14,682 ok_meta).
Resume command + close-out chain ran in three phases:

```
[step 1] resume executar          30.3 s   → 351 transient resolved
[step 2] recuperar --loop --apply  ~1 min  → 1 pass, no shrink, exit clean
[step 3] judex warehouse --classe HC  4m 40s → 91,048 cases / 1.9 GB DB
```

Final state of `runs/active/hc2021-fillin-20260504-v2/`:

- `cases: 14,682` (12,702 ok + 1,980 terminal `unallocated_pid`)
- `pecas: 20,203` (19,913 ok + 290 terminal `empty`)
- `text: 19,913 ok` (no missing — every ok-bytes row had its successor text)
- Quality grade **B**: text_ok 19,913 / 20,203 = 98.6%

The 290 `empty` peças are URLs where STF's `portal.stf.jus.br` /
`sistemas.stf.jus.br` serves 0 bytes (no document on the server-side).
Recuperar's loop correctly identified them as non-actionable on the second
classification pass — `stopped for no progress`. They are persistent and
won't unstick on retry.

**Why this finished so fast** (30 s for 14,682 cases): nearly the entire
case-meta layer was a state.json cache hit from the May 5 sweep — only
the 351 transient bytes residuals + the meta probes for the 1,980 newly-confirmed
`unallocated_pid` slots needed real network work. After the corpus restore
(below), the warehouse rebuild was the only sizeable wall-time cost.

---

## Resolved this session — corpus restored from May 3 backup (2026-05-11)

Mid-session the warehouse rebuild surfaced **0 cases** despite the chain
having processed 12,702 of them on May 5. Investigation showed
`data/source/processos/HC/` (the canonical case-JSON sink at
`judex/pipeline/handlers.py:176`) had been deleted from the live tree;
mtime of `data/` was 2026-05-05 00:39 BRT — the same wall-clock minute
as `~/projects/archive/` (the renamed previous incarnation of judex-mini).
That's almost certainly when somebody reshuffled the working tree and
the corpus dir got wiped in the move. `data/` is `.gitignore`'d so there
was no git history trail.

**Recovery anchor:** `runs/active/backups/judex-backup-20260503T054402Z.zip`
— 17.6 GB, 422,786 files, schema=2, integrity-verified via `unzip -t`
(all CRCs intact). MANIFEST.json claimed 91,048 HC case JSONs +
106,755 .pdf.gz + 115,640 .txt.gz at canonical paths. Mirror copies
existed at `/mnt/c/Users/noah_/My Drive/data science/`
(`judex-backup-20260426T153124Z.zip` 6.8 GB and
`judex-data-2026-04-19.tar.zst` 2.2 GB) — strictly older / less complete.

Restore via `unzip -n` (never overwrite) preserved the ~6k .pdf.gz and
~9k .txt.gz the May 4-5 chain had written *after* the May 3 backup point.
Final counts post-restore:

| Path                                          | Before | After    | Backup had |
|-----------------------------------------------|-------:|---------:|-----------:|
| `data/source/processos/HC/*.json`             |      0 | **91,048** | 91,048   |
| `data/raw/pecas/*.pdf.gz`                     |  6,055 | **112,791** | 106,755 |
| `data/derived/pecas-texto/*.txt.gz`           |  9,387 | **124,965** | 115,640 |

Disk usage net of the day: 451 GB used → 411 GB used. Restoration cost
+22 GB; cleanup recovered −27 GB (Synapse cache) −37 GB (archive/) on
top. Disk free now 546 GB / 1007 GB total (43% used).

**Off-host backup mirrored to Drive.** The 17.6 GB May 3 zip is now also
at `/mnt/c/Users/noah_/My Drive/data science/judex-backup-20260503T054402Z.zip`
(rsync `--inplace --partial`, ~3 min 40 s wall, source/dest byte-exact;
the earlier `cp` attempt failed with WSL2's drvfs `Cannot allocate memory`
on multi-GB writes — rsync's per-block I/O dodged it).

**Lesson pinned.** `.gitignore`'d `data/` paired with no host-level
canary check means a corpus deletion is silent. The MANIFEST.json inside
the backup zip was what made recovery a one-command operation (instead of
"is this archive intact? unzip and see"). Pattern worth keeping for any
future `judex arquivar`-style command.

**What's NOT in the May 3 backup** (will need re-fetch from STF if you
care about those rows): the ~12k new case JSONs the May 4-5 chain captured
fresh — HC 2024 fill-in resume + HC 2025 pending recheck + HC 2022 + HC
2021 metadata. The current warehouse therefore reflects the May 3 corpus
snapshot, not the May 4-5 chain's deltas. Re-running the May 4-5 chain
against the same `--saida` dirs would mostly cache-hit on bytes/text and
fetch the case-meta deltas (~3-5 hr direct-IP). Documented but not done
this session.

---

## Resolved this session — sweep-lifecycle CLI feature (2026-05-11)

Closed the documented gap (prior archive § "Strategic — simplify the CLI
surface · Sweep lifecycle as three first-class commands"). What landed:

### New + extended commands

| Command / flag                       | What it does                                                                                              | Source                |
|--------------------------------------|-----------------------------------------------------------------------------------------------------------|-----------------------|
| `judex executar --detach / -d`       | Forks the parent into a new session with stdout/stderr → `<saida>/launcher.log`, prints `pid:`/`log:`/`parar:` advice, exits 0. Replaces `setsid nohup … & disown`. | `judex/cli.py`        |
| `judex parar [run_dir]`              | SIGTERM all pids from `executar.pid` (mono) or `shards.pids` (sharded), poll until gone or `--timeout` (default 30 s). `--forcar` escalates to SIGKILL. | `judex/cli.py`        |
| `judex retomar [run_dir]`            | Reads the `args` block now persisted on `executar.state.json` and re-dispatches `executar` with the operator's original argv. Falls back to a clean exit-2 if the run pre-dates the args block. | `judex/cli.py`        |
| **default-to-newest** on `[run_dir]` | All five Coleta commands (`acompanhar`, `relatar`, `recuperar`, `parar`, `retomar`) now default to the most-recently-touched dir under `runs/active/`. Echoes `(default) run_dir = <path>` on stderr. | `_resolve_run_dir` shared helper |

### Primitives that made it possible (lower layer)

| Change                                              | Source                          | Why                                                                  |
|-----------------------------------------------------|---------------------------------|----------------------------------------------------------------------|
| `<saida>/executar.pid` written on `run_pipeline` entry, removed in its `finally` block | `judex/pipeline/runner.py`     | `parar` needs a pid to signal; mono runs didn't write one before     |
| New `state.original_args` field (additive, no schema bump) + `state.set_original_args` (one-way idempotent setter) | `judex/pipeline/state.py`       | `retomar` reads this; legacy state files load with `original_args=None` and get a clean error message from `retomar` |
| `run_pipeline` gained `original_args: Optional[dict]` kwarg; `executar` Typer wrapper packs its kwargs into it | `judex/pipeline/runner.py` + `judex/cli.py` | Captures the operator's first invocation so `retomar` can rebuild the argv |
| `_resolve_run_dir(explicit: Optional[Path]) -> Path` helper | `judex/cli.py`                  | One place where "no arg → newest" lives — five commands inherit it instantly |

### Tests (+25, total 1,048 passing)

| File                                  | New tests | Highlights                                                                                                  |
|---------------------------------------|----------:|-------------------------------------------------------------------------------------------------------------|
| `tests/unit/test_pipeline_state.py`   | +3        | `original_args` round-trip, idempotent on resume, legacy-state defaults None                                |
| `tests/unit/test_pipeline_runner.py`  | +2        | pid file present mid-run + removed on graceful exit; args captured into state journal                       |
| `tests/unit/test_cli_lifecycle.py` (new) | +20    | Helper unit tests + end-to-end `parar` against real PIDs (mono + sharded + stale-pid) + retomar argv reconstruction + `--detach` integration + uniform-surface contract pinned across all five Coleta commands |

**Pinned in `test_cli_lifecycle.py::test_acompanhar_relatar_recuperar_default_to_newest_run_dir`**: iterates over the command names; if anyone adds a sixth Coleta command and forgets to call `_resolve_run_dir`, the test breaks. That's the load-bearing one for the uniform-surface contract.

**Non-obvious gotcha pinned in the runner pid-file test**: zombie semantics. The end-to-end `parar` test against a spawned child needed a background daemon-thread reaper because subprocess.Popen leaves SIGTERM'd children as zombies (`os.kill(pid, 0)` still succeeds for zombies) — which doesn't reproduce in production where parar isn't the parent of the executar process. Documented in `_spawn_sleeper_with_reaper`'s docstring so the next person reading the test knows why it's not just `Popen + parar`.

### What's intentionally NOT done

The PRD in the archive (§ "Sweep lifecycle as three first-class commands")
also mentioned shell-completion via `Typer`'s `--completion` hook so
`judex parar <tab>` enumerates real run names. Not done — would need a
`shell_complete=` callback on the `<run_dir>` arg pointing at
`judex.pipeline.run_index.label_candidates` (already exists). Filed as a
loose end below.

---

## Resolved this session — housekeeping

- **Synapse cache deleted** (27 GB recovered). `~/.synapseCache/` held a
  clinical EEG dataset from `syn50614821` (123 subjects × ~470 MB BioSemi
  `.bdf` recordings, downloaded Feb 2025 for the dormant `~/lis/right-word-eeg/`
  project). Manifest preserved at
  `~/lis/right-word-eeg/manifest_1739892945834266839.csv` — re-downloadable
  from Synapse with credentials when needed.
- **`~/projects/archive/` deleted** (37 GB recovered). A frozen
  pre-cleanup snapshot of judex-mini (had `.venv/`, `.mypy_cache/`,
  `dist/`, `data/` mirroring the canonical tree, no source code, no git
  history). All data superseded by the May 3 backup restore; the only
  unique content was ~300 KB of `hc_famous_lawyers.{md,pdf,_blog.zip}`
  rendered outputs which are regeneratable from
  `analysis/reports/2026-04-19-hc-famous-lawyers.py` if needed.

---

## Active task — HC year-ladder backfill (multi-cycle)

Items #1 (May 4-5 chain delta re-run), #2 (HC 2020 outlier recovery)
both closed today by direct work. Item #3 (HC 2024 text coverage
anomaly) **auto-closed as a side effect of the delta re-run** — the
2026-05-12 warehouse rebuild shows HC 2024 text at 99.9% (was 80%
in the 2026-04-30 snapshot). The data-coverage anomaly resolved
itself without a targeted retry; what remains is a *quality*
spot-check, which is much cheaper than the original "find and
re-extract ~3k underperforming PDFs" plan. See
`docs/completion-tracker.md` for the refreshed per-year table.
Remaining priority queue:

1. ~~**HC 2020 outlier-recovery byte re-fetch** — done 2026-05-12 ✓~~
   Closed today: 4/8 outliers OCR'd via local Tesseract (3 already-cached
   + 1 re-fetched via 2-case `judex executar` run, archived at
   `runs/archive/hc2020-outlier-bytes-refetch/`). **4/8 permanently
   lost / unrecoverable**: 3 are orphan-URLs from the corpus deletion
   event (`id=15346588384` / `15353487630` / `15346093660` — owning
   cases were among the ~12k case-JSON deltas the May 3 backup
   doesn't have; not surfaced anywhere in the restored HC corpus);
   1 is a persistent server-side empty (`id=15347614538` in HC 193726
   — STF serves 0 bytes for that URL today, same pattern as the 63
   stuck-empties in HC 2021 delta). Going forward, the same residual
   class would be drained automatically by `recuperar --loop --apply`
   via the PROVIDER_SWITCH `outlier_skipped → tesseract` route
   (`recuperar.py:172`) — today's manual fix was specifically a
   pre-recuperar-v2 cleanup. Cache state after today:
   `_extract-hc2020-outliers-direct.py` is idempotent so a future
   re-run only processes new arrivals.
2. ~~**HC 2024 text coverage anomaly** — auto-closed 2026-05-12 ✓~~
   Text coverage is now 21,889/21,904 = 99.9% (vs the 80% baseline
   from the 2026-04-30 snapshot that originally surfaced the anomaly).
   The delta re-run's case-meta refetches + bytes/text caches catching
   up filled the gap without any targeted retry. **Quality spot-check
   still recommended** — sample 5-10 `.txt.gz` files from HC 2024 to
   confirm the text content is usable (not pypdf-mojibake / silent-
   whitespace failures). 10-min task. If quality holds, this item
   closes entirely.
3. **HC 2023 bytes coverage hole** — 14,456 / 21,453 = 67% on bytes
   while text is at 97%. Surfaced 2026-05-12 by the post-delta
   warehouse snapshot; the 2026-04-30 baseline had 2023 bytes at
   70%. Likely URL-set churn between the bytes sweep and the latest
   warehouse rebuild — a targeted `executar --csv` over the affected
   cases (or `baixar-pecas`) should close the gap cheaply.
4. **HC 2017–2019 fresh sweeps** — pre-2021 layer of the priority queue
   per [`docs/completion-tracker.md`](completion-tracker.md). HC 2017 is
   the natural next density × budget target.
5. **ADR-0001 step 3 — surface 2 + 3 byte-gap backfill** for HC
   2017–2024 (~50–80k URLs, direct-IP, ~5-10 hr/year). HC 2025 + 2026
   already done.

---

## Loose ends — consolidated from prior archives

Items that landed this session (sweep-lifecycle triplet, recuperar
v2, `--loop` convergence, `unallocated_pid`-filter, args-capture state
schema) are dropped. What remains:

### Strategic — finalize the database (analysis-ready handoff)

The warehouse has been a moving target: schema v1 → v8, table layout
in flux, RTF/PDF separation pending, inline-text fields slated for
deletion. The goal is a **freeze-candidate** milestone where the schema
is declared closed for net-new fields, all known coverage gaps are
filled, and the doc surface matches the live shape. Workstreams:

- **Coverage.** Today's restore is at the May 3 corpus level. The May
  4-5 chain delta re-run (above) + HC 2020 outlier OCR + HC 2025
  pending recheck + HC 2017–2019 fresh sweeps + ADR-0001 step 3 jointly
  gate the freeze.
- **Schema lock-in.** Declare `schema_version=8` final (no v9 without
  an ADR). Drop inline `andamentos.link_text` / `documentos.text` /
  `decisoes_dje.rtf_text` from the build path (queries already use the
  `pdfs_substantive` join). Rename `pdfs` → `pecas`. Rename bytes-cache
  suffix `.pdf.gz` → `.bytes.gz`. Promote `pdfs_substantive` to canonical
  analysis entry-point view.
- **Currency contract.** After the May 4-5 delta re-run, write down a
  periodic recheck cadence (quarterly?) so callers know when
  `outcome=None` means "STF hasn't decided" vs "we haven't re-scraped".
- **Doc fidelity.** Bring `docs/data-dictionary.md` and
  `docs/warehouse-design.md` to match the locked schema.
- **Build determinism.** Pin the build-input hash (count + sha of
  source JSONs + text gzs) in the rebuild log so any output diff has a
  known upstream cause. **Today's rebuild was a soft data point**:
  91,048 cases / 1.9 GB DB after the May 3 restore. Pin this as the
  May-restore baseline.

### Strategic — operator survivability against silent corpus loss

Surfaced by today's data-loss postmortem (corpus wipe between May 5 and
May 11 with no audit trail because `/data/` is `.gitignore`'d):

- **`judex debug fazer-backup` should be scheduleable.** Today it's
  manual. A `judex schedule fazer-backup --weekly` or a cron snippet in
  README would have meant today's corpus state was already on Drive
  before the wipe. The schedule skill exists; one entry would close
  this.
- **Host-level canary on `data/source/processos/<classe>/`.** A simple
  shell guard run on `executar` startup: "if the canonical source dir
  exists but is empty for a class that has cases in state.json, that's
  a corpus-deletion event — refuse to write fresh JSONs there until the
  operator confirms". Catches accidental wipes before they propagate
  through a sweep.
- **MANIFEST.json convention is load-bearing.** Today the manifest
  inside the backup zip is what made recovery a one-command operation
  (file_count + sources + created_at). Keep the pattern for any future
  `judex arquivar`-style command.

### Strategic — simplify the CLI surface (continued)

Lifecycle triplet ✅ landed today. What remains from the prior list:

- **Apply the flag audit to `peca_cli`** (`baixar-pecas` + `extrair-pecas`
  still expose `--impte-contem`, `--relator-contem`, `--tipos-doc`,
  `--excluir-tipos-doc`, `--limite` — the same filter knobs we removed
  from `executar`).
- **Audit `judex debug` subgroup.** `debug fazer-backup` is a real
  operator tool — promote to top-level. `debug providers` could be
  `judex --providers` or a standalone script. Keep `debug
  analisar-regimes`, `debug probe`, `debug validar-gabarito`,
  `debug exportar`, `debug relatorio-diario`.
- **Help-text consistency across the whole CLI.** Today's
  Portuguese-tightening pass cleaned only `executar`. Other commands
  still mix English jargon (`Direct-IP`, `case JSON`, `flat file`,
  `default`, `bypass`) into Portuguese helps.
- **Shell-completion on `<run_dir>` arguments.** Hook the existing
  `judex.pipeline.run_index.label_candidates` into Typer's
  `shell_complete=` callback so `judex parar <tab>` enumerates real run
  names. ~20 LOC.

### Tactical CLI / observability fixes

- **`bytes` stage doesn't distinguish cached vs freshly downloaded.**
  `report.md` shows a single `bytes: ok=N` bucket while `text` already
  splits `ok=N + skipped_cached=M`. Add `cached: bool` to
  `fetch_bytes` log; split `ok` → `ok_fresh` + `skipped_cached` in
  `report.md`.
- **404s on voto PDFs deserve a distinct error class.** 6 known-permanent
  404s on `digital.stf.jus.br/decisoes-monocraticas/api/public/votos/{id}/conteudo.pdf`
  live as generic `http_error`. A `permanent_404` terminal status would
  let `--retentar-de` skip them. Pairs with the `unallocated_pid` filter
  (already shipped in PR #16).
- **Intra-case URL dedup in `handle_fetch_meta`.** 50-case validation
  surfaced 3 intra-case duplicate peça URLs. Cost is bookkeeping noise;
  ~3 lines to fix.
- **CliffDetector `--cliff-require-sustained K` flag.** Current detector
  trips on a single window-sample; K=3 would absorb rotation-forgiveness
  patterns. Non-blocking.

### Investigation / postmortem incomplete

- **2026-05-02 14:12–15:22 BRT — 13,747 case JSONs written to wrong
  path.** Sweep wrote to `data/source/processos/*.json` instead of
  `data/source/processos/HC/`. Operator moved them; root cause untraced.
  Add verifier guard: `ls data/source/processos/*.json` must be 0. Grep
  launcher logs from that window to identify the offending sweep.
- **HC 2024 text coverage anomaly — 80% vs 97–99% on 2023/2022.**
  ~3k-row gap. Cause unverified (provider failures? RTF mistypes?
  scanned originals?). Spot-check + focused `--csv` retry with
  chandra/tesseract on the underperforming subset.
- **2026-05-05 / 2026-05-11 corpus deletion event.** When exactly was
  `data/source/processos/HC/` wiped from the live tree? Dir mtime on
  `~/projects/archive/` was 2026-05-05 00:39 — same minute as `data/`
  mtime. Probably during a directory shuffle that produced `archive/`,
  but the operator-side actions are uncorrelated. Filed for the
  survivability strategic item above.

### Architecture / spec work

- **ADR-0003 Phase 2 — Playwright fallback for surface 3
  (`publicacoes_dje`).** Phase 1 (loosened parser + redirect-anchor
  branch) landed 2026-05-02 (`ae19d73`). Phase 2 (full PDF fetch via
  Playwright past the AWS WAF JS challenge on `digital.stf.jus.br`) is
  deferred until empirical demand forces it.
- **ACÓRDÃO re-extract corpus-wide via auto-router.** HC 2026 closed out
  with Fly Tesseract (5,179 ok / 10 dead surface-2 IDs = 99.8%
  effective, EMENTA validated 100% in spot-check). HC 2017–2025 ACÓRDÃO
  files still hold pypdf text from before the column-scramble bug was
  diagnosed — silent gold-CER ~12%, vs Tesseract's 0.75%. Per-year wall
  ≈ 1.8 hr × Fly shared-cpu-2x × 60 ≈ $0.10 / 1k pages.

### Cost / performance / warehouse hygiene

- **Re-anchor `judex/utils/cost.py` for new Fly shape (shared-cpu-4x @ 2 gb).**
  Currently anchored to old 2x @ 4 gb. New empirical shape:
  $0.0286/Machine-hr, 0.55 s/page mean, ~$0.0011 / 1k pages (vs Modal's
  $0.140). Tests use ±10% bounds — non-breaking.
- **Drop inline text fields from warehouse build path** (`andamentos.link_text`
  / `documentos.text` / `decisoes_dje.rtf_text`).
- **Warehouse table rename `pdfs` → `pecas`.** Holds all peças (PDF + RTF);
  name is a v3-era artifact.
- **Bytes-cache suffix rename `.pdf.gz` → `.bytes.gz`.** 5-step migration
  script exists.
- **Fly OCR — 143-page+ PDFs hit shared-CPU credit ceiling.** 1 MB
  compressed-bytes threshold gates them out of production today (0.016%
  of corpus). Decision: park further optimisation; fall back to local
  Tesseract for the tail.

### Doc / observability drift

- **Completion tracker refreshed today** (post-restore + warehouse
  rebuild). Reflects the May 3 corpus snapshot; will need another
  refresh after the May 4-5 chain delta re-run.

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
- [`fly/`](../fly/) — Fly.io OCR app.

## Working conventions

- **`analysis/`** — git-ignored scratch for this-session exploration.
- **`config/`** — git-ignored (credentials).
- **All non-trivial arithmetic via `uv run python -c`** — never mental math.
- **Sweeps write a directory**, not a file. Layout in
  [`docs/data-layout.md § Sweep run artifacts`](data-layout.md#sweep-run-artifacts).
- **Live sweep monitor**: `judex acompanhar [run_dir]` is canonical
  (auto-detects mono vs sharded; defaults to newest under `runs/active/`).
- **Sweep lifecycle**: `judex executar --detach` → `judex acompanhar` →
  `judex parar` → `judex retomar` → `judex relatar` → `judex recuperar
  --loop --apply --nao-perguntar`. All commands default to the newest
  `runs/active/` dir when invoked without an argument.
- **Run direct-IP sweeps serially.** One judex process == one WAF
  reputation budget. Stacking parallel direct-IP runs splits the budget
  and trips the 403 cliff.
- **Archive convention**: when this file grows past ~500 lines or all
  Open/Resolved sections drain, move it to
  `docs/progress_archive/YYYY-MM-DD_HHMM_<slug>.md` and start a fresh
  notebook carrying the live threads + a consolidated loose-ends list.
- **Per-thread status convention.** Top-level sections use one of:
  - `## Open thread — <slug> (<date>)` — active, still load-bearing.
  - `## Resolved — <slug> (<date>)` — closed but kept short-term.
  - `## Active task — <slug>` / `## In-flight side-quest — <slug>` —
    multi-cycle work. Stays at the top.
