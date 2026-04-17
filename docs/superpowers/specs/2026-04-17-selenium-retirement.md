# Selenium retirement — move to `deprecated/`, HTTP becomes default

Status: **draft**, not yet executed. Author: 2026-04-17.

## Goal

Make the HTTP backend the only first-class scraping path. Move all
Selenium-specific code into `deprecated/` as a frozen reference,
flip `main.py`'s default backend to `http`, and shrink the runtime
import graph (and the wheel) by dropping `selenium` from the default
dependency set.

This is the **move-and-freeze** version of `docs/handoff.md § Next
steps: 4. Retire the Selenium path`. That section proposed straight
deletion; the user prefers a deprecated folder so the legacy
extractors remain greppable as living documentation of what STF
actually emits at the DOM level.

## Non-goals

- **No new shim layer.** `deprecated/` is a destination, not a
  redirect. Nothing in the live code path imports from it. Per
  `CLAUDE.md` (no-backwards-compat-shims rule) we are NOT keeping a
  `from src.scraper import run_scraper` re-export at the old path.
- **No partial backend.** Either the run is HTTP or it errors. We do
  not silently fall back to Selenium when HTTP fails.
- **No edits to legacy code.** Bugs noted in `handoff.md § 5` (e.g.
  `extract_peticoes:28-30` dead assignment, `extract_deslocamentos:113`
  dead helper) stay as-is in the deprecated copy. Fixing them would
  imply we're still maintaining them.

## Current Selenium surface (audit, 2026-04-17)

**19 files import `selenium` directly:**

- Orchestrator + driver helpers (3):
  - `src/scraping/scraper.py`
  - `src/utils/driver.py`
  - `src/utils/get_element.py`

- Selenium-bound extractors (16, all under `src/scraping/extraction/`):
  - `extract_andamentos.py`
  - `extract_assuntos.py`
  - `extract_badges.py`
  - `extract_data_protocolo.py`
  - `extract_deslocamentos.py`
  - `extract_incidente.py`
  - `extract_liminar.py`
  - `extract_numero_origem.py`
  - `extract_orgao_origem.py`
  - `extract_origem.py`
  - `extract_partes.py`
  - `extract_peticoes.py`
  - `extract_primeiro_autor.py`
  - `extract_recursos.py`
  - `extract_sessao_virtual.py`
  - `extract_volumes_folhas_apensos.py`

**Stays in `src/scraping/extraction/` (pure-soup, imported by HTTP path):**

- `extract_classe.py`
- `extract_meio.py`
- `extract_numero_unico.py`
- `extract_publicidade.py`
- `extract_relator.py`
- `_shared.py` (regex patterns)
- `__init__.py` (intentionally empty per `CLAUDE.md`)

**Live entry points referencing Selenium:**

- `main.py:8` — `from src.scraper import run_scraper`
- `main.py:67-70` — `--backend` default `"selenium"`
- `main.py:94` — `logging.getLogger("selenium").setLevel(WARNING)`
- `main.py:119-128` — Selenium dispatch branch
- `pyproject.toml` — `selenium>=4.37.0` in default dependencies

**Tests:**

- `tests/unit/test_main_backend.py` — exercises both backends.
- `tests/unit/test_http_backend_no_selenium.py` — pins that
  `import src.scraper_http` loads zero `selenium.*` modules.

## Target layout

```
src/
  _deprecated/                       # new; private leading-underscore per src/sweeps/shared.py convention
    __init__.py                      # empty, signals "do not import from runtime code"
    README.md                        # 1-page note: why this exists, how to read it
    scraper.py                       # was src/scraping/scraper.py
    utils/
      driver.py
      get_element.py
    extraction/
      __init__.py                    # empty
      _shared.py                     # COPY of src/scraping/extraction/_shared.py if any selenium ext needs it
      extract_andamentos.py
      extract_assuntos.py
      extract_badges.py
      extract_data_protocolo.py
      extract_deslocamentos.py
      extract_incidente.py
      extract_liminar.py
      extract_numero_origem.py
      extract_orgao_origem.py
      extract_origem.py
      extract_partes.py
      extract_peticoes.py
      extract_primeiro_autor.py
      extract_recursos.py
      extract_sessao_virtual.py
      extract_volumes_folhas_apensos.py
  extraction/                        # shrinks to 5 pure-soup modules + _shared + __init__
    _shared.py
    __init__.py
    extract_classe.py
    extract_meio.py
    extract_numero_unico.py
    extract_publicidade.py
    extract_relator.py
  scraper_http.py                    # unchanged, now the only orchestrator
  ...                                # everything else unchanged
```

`deprecated/` is named with a leading underscore for two reasons:

1. Matches the existing `src/sweeps/shared.py` private-module convention.
2. Linters / test discovery skip leading-underscore packages by
   default; CI doesn't try to import the deprecated tree.

`__init__.py` stays empty (no `from .scraper import *`) so the act of
adding `src._deprecated` to the import graph requires conscious code.

## Phased plan

### Phase 1 — Flip the default, move the files (one commit)

Single commit: `refactor: deprecate Selenium backend, default to HTTP`.

1. **Flip default in `main.py:67`:**
   ```python
   backend: str = typer.Option("http", "--backend", ...)
   ```
   And update the help string to reflect that `selenium` is
   deprecated and will be removed in a follow-up release.

2. **Drop the Selenium dispatch branch in `main.py:119-128`.** If
   `--backend selenium` is passed, error with a clear message:
   ```
   ERROR: --backend selenium is deprecated. The Selenium scraper has
   moved to deprecated/scraper.py. Use --backend http (the new
   default), or pin an older judex-mini release if you need Selenium.
   ```
   Validate this in `_validate_backend` before any work happens.

3. **Move 19 files** to `deprecated/` per the layout above. Use
   `git mv` so the history follows. Group the moves in the same
   commit as the main.py flip — the import graph would be broken
   between steps otherwise.

4. **Delete `from src.scraper import run_scraper`** from `main.py:8`.
   Drop the `selenium` logger silencer at line 94 (no longer
   imported, no logger to silence).

5. **Decide pyproject:** move `selenium>=4.37.0` from default
   dependencies to an `[selenium-legacy]` optional extra. This keeps
   `deprecated/` *importable* if a user installs the extra
   (`uv sync --extra selenium-legacy`), but the default install no
   longer pulls Chrome/chromedriver/selenium into the wheel. Update
   `pyproject.toml`:
   ```toml
   [project.optional-dependencies]
   selenium-legacy = ["selenium>=4.37.0"]
   ```

6. **Tests:**
   - **Move** `tests/unit/test_main_backend.py` → keep file name, but
     replace the Selenium-branch assertion with a test that
     `--backend selenium` raises `BadParameter` with a deprecation
     message.
   - **Strengthen** `tests/unit/test_http_backend_no_selenium.py` to
     also assert that `import main` loads zero `selenium.*` modules.
   - Verify `uv run pytest tests/unit/` still passes 152/152 (the
     full suite besides the moved test).
   - The deprecated tree is not exercised by any test; it is frozen.

7. **Update `CLAUDE.md`:**
   - "Two backends live side-by-side" → "HTTP is the only backend;
     the Selenium tree is frozen under `deprecated/`".
   - Update the `Scraping architecture` section.
   - Remove the `recursos[].id` vs `recursos[].index` gotcha — once
     Selenium is out of the dispatch path, the `index` emission can't
     happen. (`extract_recursos.py` is in `_deprecated/` and not
     imported.)
   - Update `# Don't break these` if needed.

8. **Update `docs/handoff.md`:** mark Step 4 (Retire the Selenium
   path) as Phase 1 done; promote remaining cleanup to Phase 2 below.

**Test gates for Phase 1:**

- `uv run pytest tests/unit/` — all green (152 + the new backend-error
  test = 153, minus whichever Selenium-only assertion got replaced).
- `PYTHONPATH=. uv run python scripts/validate_ground_truth.py` —
  4/5 MATCH (unchanged from current).
- `uv run python main.py -c ADI -i 2820 -f 2820 -o json -d output/test --overwrite`
  must succeed without `--backend http` (default flipped).
- `uv run python main.py --backend selenium -c ADI -i 2820 -f 2820 -o json -d output/test --overwrite`
  must error with the deprecation message and a non-zero exit.

### Phase 2 — Audit and shrink (separate commit, optional)

After Phase 1 stabilises (~1 week), evaluate:

1. **`tests/ground_truth/*.json` provenance.** Five fixtures, all
   captured via Selenium. Re-capture under HTTP and diff. If MATCH,
   no action. If DIFF, decide whether the HTTP shape is the new
   ground truth (likely yes — `recursos[].id` already differs; see
   handoff). Commit re-captured fixtures.

2. **`extract_recursos.py` `index` vs `id` cleanup.** Already moot
   after Phase 1 (Selenium extractor is in `_deprecated/`), but the
   ground-truth fixtures may need re-capture to remove the field
   confusion.

3. **`_deprecated/extraction/_shared.py` duplication.** If any
   Selenium extractor in `_deprecated/` references a regex still live
   in `src/scraping/extraction/_shared.py`, copy that regex into
   `_deprecated/extraction/_shared.py` so the deprecated tree is
   self-contained (no live ↔ deprecated dependency edge).

4. **Hard-remove decision.** If a year passes with no one running
   `--backend selenium` (check telemetry / git log of the deprecated
   tree), delete `deprecated/` entirely and drop the
   `[selenium-legacy]` extra. Until then, keep it as documentation.

### Phase 3 — Stretch: nothing imports from `deprecated/`

Add a CI check (single shell line, in `pyproject.toml` or a
`Makefile`):

```bash
! grep -rE "^(import|from)\s+src\._deprecated" src/ scripts/ tests/ main.py
```

Fails the build if any live file ever reaches into the deprecated
tree. Pins the architectural boundary.

## Risk assessment

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| HTTP backend has a parity bug not yet surfaced | Medium | High | Phase 2 ground-truth re-capture catches it; sweep E shows 429/429 ok at scale; 4/5 fixtures already MATCH. |
| External user has hardcoded `--backend selenium` | Low | Low | Phase 1 keeps the flag, just errors clearly. They install `[selenium-legacy]` and pin an older release if they need to keep running it. |
| `src/scraping/extraction/_shared.py` regex used only by deprecated extractors | Low | Low | Phase 2 step 3 audits and copies. Worst case: live code drops a now-dead regex. |
| `tests/ground_truth/*.json` were captured under Selenium and their `recursos[].index` shape becomes the asymmetric ground truth | Already known | Medium | Phase 2 step 1 re-captures. Until then, `validate_ground_truth.py` already SKIPs `sessao_virtual` and tolerates the `recursos` diff. |
| `selenium-legacy` extra isn't installed → user can't import `deprecated/scraper` even if they want to read it | By design | None | The point of the extra is exactly this: deprecated code is greppable but not runnable without an opt-in install. |

## Estimated effort

- **Phase 1:** ~45 min total. ~10 min for the moves, ~10 min for the
  main.py flip + test updates, ~15 min for CLAUDE.md + handoff.md
  updates, ~10 min running the test gates.
- **Phase 2:** ~30 min (ground-truth re-capture is the longest piece;
  one process per fixture under HTTP).
- **Phase 3:** ~5 min (one-line CI check).

## Open questions

1. **Does anything else in the repo import `src.scraper` besides
   `main.py`?** Quick check: `grep -rE "from src\.scraper " --include='*.py'`
   reports `main.py:8` only. Nothing else does. Safe to move.

2. **Marimo notebooks under `analysis/` (git-ignored) — do any of
   them import the Selenium tree?** They're not in version control;
   if the user has local notebooks that import `src.extraction.extract_andamentos`,
   they'll need a one-liner update to `src._deprecated.extraction.extract_andamentos`
   (and an `[selenium-legacy]` install). This is the user's local
   problem, not a repo concern.

3. **Should we promote `src/analysis/andamentos.py` (the
   andamentos-classifier port) into the HTTP path *before* Phase 1?**
   See `docs/andamentos-classifier-gaps.md` — the port is partial.
   Probably orthogonal: the classifier consumes andamentos JSON
   regardless of which backend produced it.

## Reversal

Phase 1 is one commit. `git revert <sha>` puts everything back. No
data migrations, no schema changes, no external state. Phase 2 is
also one (or a small handful) of revertable commits. Phase 3 is a
build-script line.
