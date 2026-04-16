# Handoff — judex-mini perf/bulk-data work

Branch: `experiment/perf-bulk-data`
Status: landed + pushed; 4 commits ahead of `main`.
PR: https://github.com/noah-art3mis/judex-mini/pull/new/experiment/perf-bulk-data

Start by reading `docs/perf-bulk-data.md` — it has the full investigation (DataJud dead-end, STF portal mechanics, the 5.7×/~20× perf claim with caveats). This note only covers what's unfinished and why.

## The one thing to decide before any more scraping

**STF's `robots.txt` disallows `/processos` for all user agents.** The scraper targets exactly that path. It's not illegal (LAI 12.527/2011 says court data is public), but it's an explicit machine-readable "please don't" from the site owners. Three postures to pick from:

1. **Minimum professional floor** — add a custom `User-Agent` identifying the project with a contact email, add a `NOTICE.md` explaining the legal basis (LAI) and user obligations (throttle, cache, don't republish personal data in violation of LGPD), keep scraping.
2. **Talk to STF first** — write the Ouvidoria explaining the research use case. Brazilian courts sometimes grant whitelisted access. Slowest path, safest result.
3. **Cache-first distribution** — ship the project as a parser, not a scraper. Users populate `.cache/` themselves; library never does large sweeps from one IP.

Talk to the user about this before adding concurrency or sweeping any larger ranges. This decision shapes what steps 3 and 4 below even look like.

## What works today

- `src/scraper_http.py` is an HTTP-only replacement for `src/scraper.py`. 4/5 ground-truth fixtures match field-for-field; the 5th (ACO 2652) has two known non-bug diffs (assuntos text drifted on the live site since the fixture was captured; the fixture's own `pautas` is `null` while the other four are `[]`).
- `scripts/validate_ground_truth.py` runs the HTTP path against all fixtures, diffs against the captured GT, tolerates growing reverse-chronological lists. Cache-hit wall clock: AI 772309 = 130 ms; ADI/ACO ~750 ms.
- `scripts/bench_http_vs_selenium.py` diffs HTTP vs. a Selenium run on a single process (requires pre-running Selenium into `output/bench/`).
- `.cache/html/{classe}_{processo}/{tab}.html.gz` is the on-disk cache. `incidente.txt` alongside lets cache hits skip the 300 ms `listarProcessos.asp` 302 lookup.
- Both CLI paths still exist. `main.py` still calls Selenium via `src/scraper.py`. Nothing in `main.py` knows about the HTTP path yet.

## Next steps, ordered

### 1. Wire `scrape_processo_http` into `main.py`

The HTTP path is proven at parity on 5 fixtures but isn't reachable from the CLI. Add a `--backend={selenium,http}` flag (or flip the default) so callers can actually use it. The HTTP path has no retry/backoff; wrap calls with `tenacity` before using it on large ranges. Look at `src/utils/driver.py:66-99` for the retry shape the Selenium path uses.

### 2. Port `sessao_virtual` properly

Currently `ex.extract_sessao_virtual()` returns `[]`. Reason in `extraction_http.py`: the `abaSessao.asp` fragment is largely a JavaScript template that calls `https://sistemas.stf.jus.br/repgeral/votacao?tema=…` (a separate JSON API) for the "Tema" branch. The "Sessão" branch requires simulating collapse/expand clicks. Both paths need bespoke work:

- **Tema branch**: fetch the JSON endpoint directly. Probe it first (`curl -sk 'https://sistemas.stf.jus.br/repgeral/votacao?tema=1020' | head -50`) to confirm the exact shape — the current `abaSessao.asp` JS shows the payload is `package.repercussaoGeral.processoLeadingCase`, with nested `placar.ministro` lists.
- **Sessão branch**: inspect the abaSessao fragment HTML on a process that has one (e.g. ADI 2820 has `sessao_virtual: 3` in its fixture). The JS click-expand may just be showing already-present HTML with `display:none` — if so, everything is already there to parse. If not, there's likely a third endpoint being hit.

Don't block on this — `sessao_virtual` currently drops out as a "skipped" field. Finishing it is a quality improvement, not a correctness fix.

### 3. Retire the Selenium path (once step 1 is done)

After the HTTP path is the default and a larger validation sweep passes:

- Delete `src/scraper.py`, `src/utils/driver.py`, `src/utils/get_element.py`.
- Drop `selenium` from `pyproject.toml`.
- In `src/extraction/`: several extractors are still Selenium-bound (`extract_andamentos.py`, `extract_assuntos.py`, `extract_deslocamentos.py`, `extract_peticoes.py`, `extract_recursos.py`, `extract_partes.py` old bs4 path, `extract_primeiro_autor.py`, `extract_sessao_virtual.py`, `extract_orgao_origem.py`, `extract_data_protocolo.py`, `extract_numero_origem.py`, `extract_volumes_folhas_apensos.py`, `extract_origem.py`, `extract_incidente.py`, `extract_badges.py`). The pure-soup ones (`extract_classe.py`, `extract_meio.py`, `extract_numero_unico.py`, `extract_publicidade.py`, `extract_relator.py`) are imported by `src/extraction_http.py` — keep those.
- Check `src/extraction/__init__.py` exports match what survives.

### 4. Larger validation sweep

5 fixtures isn't enough confidence. Before retiring Selenium, sweep 20–50 processes across classes (RE, AI, ADI, ACO, MI, HC) and sizes. The diff harness already supports it — extend `scripts/validate_ground_truth.py` to pull from a CSV of `(classe, processo)` pairs instead of globbing fixtures. Record any field that diverges more than once across the sample.

### 5. Pre-existing bugs in the Selenium side

Surfaced during the dedup review but not touched (Selenium path has no automated coverage, didn't want to silently change behavior):

- `src/extraction/extract_peticoes.py:28-30`: `data_match` is assigned from `bg-font-info` on line 28, then immediately overwritten by the `processo-detalhes` match on line 30. The first match is dead.
- `src/extraction/extract_deslocamentos.py:113-152`: `_clean_extracted_data` appears dead — `_clean_data_fields` is the one actually called from `_extract_single_deslocamento`. Confirm with `grep _clean_extracted_data src/`.
- `src/data/types.py:47-78`: commented-out dataclasses (`Parte`, `Andamento`, `Deslocamento`). Git remembers; delete.

Not blocking. Clean up if you're already in those files.

### 6. Per-process rate-limit aware retry

Once the HTTP path is on by default, add `tenacity` retries on 429/5xx. Pattern in `src/utils/driver.py:68-80` — use the same `ScraperConfig` constants so behavior is tunable. Pay attention to: STF progressively throttles on sustained sweeps, so on repeated 429s the right move is probably to slow down globally (lower per-process and cross-process concurrency), not to back off per-request.

## Non-obvious things I learned

- **The `abaX.asp` endpoints return 403 without three things**: a valid session cookie (`ASPSESSIONID…` + `AWSALB`), a `Referer: detalhe.asp?incidente=N`, and `X-Requested-With: XMLHttpRequest`. `requests.Session()` plus the two headers is enough — the user was asking about "authorization"; this is what that is.
- **STF serves UTF-8 without declaring a charset.** `requests` defaults to Latin-1 → mojibake. `scraper_http._decode` handles it; never bypass it.
- **`extract_partes` has two possible sources.** `abaPartes.asp` contains both `#todas-partes` (full list, including amici and advogados — 9 entries for ADI 2820) and `#partes-resumidas` (main parties only — 4 entries). The Selenium extractor reads from `#resumo-partes` on `detalhe.asp`, which jQuery populates from `#partes-resumidas`. For parity, always use `#partes-resumidas`. Initial HTTP port got this wrong.
- **Ground-truth fixtures are internally inconsistent.** `ACO_2652` has `"pautas": null`; the other four have `"pautas": []`. The current scraper emits `[]` to match 4/5. If you regenerate fixtures, pick one convention.
- **The ~5 s/item in the scraper's own `ProcessTimer` is the steady-state under no throttling. The `ScraperConfig` comment's 20 s/item is the *average* under sustained load including STF throttling.** Both numbers are real; they measure different regimes. The HTTP path's 5.7× win only applies to the unratelimited regime. On long sweeps, both paths converge to the server ceiling.
- **DataJud does not have STF.** `api_publica_stf` returns 404. Other tribunals (STJ, TST, TSE, STM) work with the same public API key. Don't spend time re-checking this.

## How to run things

```bash
# Ground-truth validation (source of truth for the HTTP path)
PYTHONPATH=. uv run python scripts/validate_ground_truth.py

# Single-process diff vs Selenium (needs Selenium output on disk first)
uv run python main.py -c AI -i 772309 -f 772309 -o json -d output/bench --overwrite
PYTHONPATH=. uv run python scripts/bench_http_vs_selenium.py AI 772309

# Wipe cache to force fresh fetches (gzipped .html.gz files under .cache/html/)
rm -rf .cache
```

## Files you probably need to touch first

- `src/scraper_http.py` — HTTP orchestrator + `fetch_process` + `scrape_processo_http`
- `src/extraction_http.py` — fragment parsers (re-exports Selenium pure-soup ones)
- `src/extraction/_shared.py` — regex patterns + helpers shared by both paths
- `src/utils/html_cache.py` — gzip + incidente cache
- `scripts/_diff.py` — shared field-by-field diff
- `main.py` — currently Selenium-only; needs a `--backend=http` flag

## Files that already work; don't break them

- `tests/ground_truth/*.json` — fixtures, used by `scripts/validate_ground_truth.py`
- `src/data/types.py` — `StfItem` TypedDict (fixed Optional types; don't make them non-Optional again)
- `src/data/export.py` — write paths for CSV/JSON/JSONL output
