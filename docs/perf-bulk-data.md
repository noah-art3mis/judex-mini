# Performance & bulk data — investigation and plan

Branch: `experiment/perf-bulk-data`
Date: 2026-04-16

## TL;DR

The scraper's slowness has **two** layers, and they have very different fixes:

1. **Per-request Selenium overhead.** Browser startup + JS + click-wait dominates when you're not being throttled. Replaceable by a plain-`requests` path: ~5 s/item → ~1 s/item on a cold request. Confirmed with a working andamentos prototype.
2. **Server-side rate limiting.** The STF portal progressively throttles over a sustained sweep; the ~20 s/item figure in `ScraperConfig` is an *average* that includes this throttling, not steady-state. A faster client does not beat this — it just burns through the quota faster. This is a ceiling, not a floor.

The practical implication: dropping Selenium is still worth doing (faster iteration, lower memory, simpler code), but the **primary production win is caching**, not raw per-request speed. Once a case's HTML is on disk, re-extraction is free, and that's where development time actually lives.

DataJud, contrary to initial hope, does **not** cover STF, so we cannot skip scraping entirely.

## What was investigated

Three hypotheses, three probes:

| # | Hypothesis | Verdict |
|---|------------|---------|
| 1 | STF publishes bulk data / open dataset replacing scraping | **Rejected.** `portal.stf.jus.br/hotsites/corteaberta/` exists but is aggregate-only (dashboards, not case-level). No `dadosabertos.stf.jus.br`. |
| 2 | CNJ DataJud public API covers STF cases | **Rejected.** `POST /api_publica_stf/_search` returns `index_not_found_exception (404)`. Other tribunals (STJ, TST, TSE, STM) work with the same API key — STF specifically is not indexed. |
| 3 | The page is scrapeable via plain HTTP without a browser | **Confirmed.** All fields reachable via `requests.Session()` with proper cookies/headers. |

Probe transcripts live in `/tmp/stf_*.html`, `/tmp/aba_*.html`, `/tmp/tab_*.html` on the workbench; the relevant evidence is reproduced below.

## How the STF portal actually works

### The URL flow

1. `GET /processos/listarProcessos.asp?classe=AI&numeroProcesso=772309`
   → **302** redirect to `/processos/detalhe.asp?incidente=3785234`.
   This is just a `(classe, numero) → incidente_id` resolver. ~300 ms.

2. `GET /processos/detalhe.asp?incidente=3785234`
   → **200**, ~69 KB of HTML. Contains the page chrome, the tab structure, and — critically — the `incidente` ID plus base metadata. ~500 ms.

3. The detail page loads each tab via jQuery AJAX. The calls are plain and visible in the HTML:
   ```js
   $('#abaAndamentos').load('abaAndamentos.asp?incidente=3785234&imprimir=')
   $('#abaPartes').load('abaPartes.asp?incidente=3785234')
   $('#abaDecisoes').load('abaDecisoes.asp?incidente=3785234')
   $('#abaSessao').load('abaSessao.asp?incidente=3785234&tema=')
   $('#abaDeslocamentos').load('abaDeslocamentos.asp?incidente=3785234')
   $('#abaPeticoes').load('abaPeticoes.asp?incidente=3785234')
   $('#abaRecursos').load('abaRecursos.asp?incidente=3785234')
   $('#abaPautas').load('abaPautas.asp?incidente=3785234')
   ```
   Each returns an HTML fragment you parse the same way you already parse the assembled DOM.

### The "authorization" that blocks direct tab access

Hitting `abaAndamentos.asp` with a raw curl call returns **403 Forbidden**. This is what shows up as the click-gated behavior. The cause is not real auth — there is no login, no token, no API key. What the server requires:

- A valid **session cookie** — `ASPSESSIONIDxxxxxxxx` (classic ASP) plus `AWSALB`/`AWSALBCORS` (the load-balancer sticky session). Both are set on the first GET to `detalhe.asp`.
- A **`Referer`** header pointing at `detalhe.asp?incidente=<N>`.
- An **`X-Requested-With: XMLHttpRequest`** header (jQuery adds this by default; its absence is what 403s most bare curl calls).

With those three, every tab returns 200:

| Tab                  | Status | Size    | Time   |
|----------------------|-------:|--------:|-------:|
| abaAndamentos        | 200    | 17.4 KB | 404 ms |
| abaPartes            | 200    |  1.8 KB | 404 ms |
| abaInformacoes       | 200    |  2.9 KB | 320 ms |
| abaDeslocamentos     | 200    |  3.5 KB | 649 ms |
| abaSessao            | 200    |  9.6 KB | 303 ms |
| abaDecisoes          | 200    |    57 B | 620 ms |
| abaPautas            | 200    |    57 B | 379 ms |
| abaPeticoes          | 200    |     0 B | 301 ms |
| abaRecursos          | 200    |     0 B | 1.8 s  |

(Empty responses reflect that this specific process has no peticoes/recursos — normal, not an error.)

Sequential total for one process end-to-end via HTTP: **~5 s**. With the tabs fetched in parallel: **~2 s**, dominated by the slowest tab. Versus current Selenium: **~20 s per process** (per `ScraperConfig` comment: "100 itens demora 40min").

## Field coverage

All fields the scraper currently extracts are retrievable via the HTTP-only path, because the data lives in the same HTML the browser eventually renders — we just fetch the fragments directly instead of letting jQuery do it.

| Field                  | Source (HTTP path)             |
|------------------------|--------------------------------|
| incidente              | `listarProcessos.asp` → Location header |
| classe, processo_id    | input                          |
| numero_unico           | `detalhe.asp`                  |
| meio, publicidade      | `detalhe.asp`                  |
| badges                 | `detalhe.asp`                  |
| assuntos               | `detalhe.asp` / `abaInformacoes` |
| data_protocolo         | `abaInformacoes`               |
| orgao_origem, origem   | `abaInformacoes`               |
| numero_origem          | `abaInformacoes`               |
| volumes, folhas, apensos | `abaInformacoes`             |
| relator                | `detalhe.asp`                  |
| primeiro_autor, partes | `abaPartes`                    |
| andamentos             | `abaAndamentos`                |
| sessao_virtual         | `abaSessao`                    |
| deslocamentos          | `abaDeslocamentos`             |
| peticoes               | `abaPeticoes`                  |
| recursos               | `abaRecursos`                  |
| pautas                 | `abaPautas`                    |

`extract_*` functions can stay mostly as-is — they already parse `BeautifulSoup` fragments. The change is upstream: what feeds them.

## Proposed architecture

Replace the Selenium driver with an HTTP client session, keep the parser layer.

```
# per process
session = requests.Session()
session.headers.update({"User-Agent": UA})

# 1. resolve incidente (follow redirect)
r = session.get(LISTAR, params={"classe": classe, "numeroProcesso": num}, allow_redirects=False)
incidente = parse_incidente_from_redirect(r.headers["Location"])  # detalhe.asp?incidente=N

# 2. fetch detail page (sets session cookies)
detalhe_html = session.get(DETALHE, params={"incidente": incidente}).text

# 3. fetch all tabs in parallel
referer = f"{DETALHE}?incidente={incidente}"
ajax_headers = {"X-Requested-With": "XMLHttpRequest", "Referer": referer}
with ThreadPoolExecutor(max_workers=8) as ex:
    fragments = dict(zip(
        ABAS,
        ex.map(lambda a: session.get(f"{BASE}/{a}", params={"incidente": incidente},
                                      headers=ajax_headers).text, ABAS),
    ))

# 4. feed to existing extract_* functions
```

Selenium only stays as a fallback for any specific field we later find genuinely needs JS execution (so far: none).

## Measured HTTP prototype vs Selenium (AI 772309)

End-to-end comparison on the same process, `scripts/bench_http_vs_selenium.py`:

| Path                          | Wall clock | Notes                                     |
|-------------------------------|-----------:|-------------------------------------------|
| Selenium (from main.py)       | 18.00 s    | includes ~13 s one-time driver startup    |
| Selenium steady-state         |  4.98 s    | `ProcessTimer` — excludes driver startup  |
| HTTP fresh (no cache)         |  0.87 s    | resolve incidente + detalhe + 9 tabs (||8) |
| HTTP cache hit                |  0.27 s    | still does the 302 incidente lookup       |
| Andamentos parse only         |  3.5 ms    | from cached fragment                      |

**Andamentos output diff: MATCH** — `extract_andamentos_http` produced field-identical output (2/2 items, 7/7 fields each) to `extract_andamentos` on the same case. One encoding bug surfaced during diffing: STF serves UTF-8 without declaring a charset, so `requests` defaulted to Latin-1. Fixed by setting `response.encoding = "utf-8"` explicitly.

The HTTP path is **~5.7× faster than Selenium steady-state** on a *cold, unratelimited* request. This number does NOT extrapolate to a full sweep — STF rate-limits progressively over many requests, and the `ScraperConfig` "20s/item" figure is an average that includes throttled responses. Under sustained load, both Selenium and HTTP converge to whatever the server lets us do. The HTTP win is real on individual requests and small batches; on large sweeps the ceiling is the server, not the client. This moves the cache from "nice-to-have" to "the main production lever."

Prototype files:
- `src/scraper_http.py` — session, incidente resolution, tab fetching, `scrape_processo_http` orchestrator
- `src/extraction_http.py` — fragment-based ports of every extractor
- `src/utils/html_cache.py` — on-disk cache under `.cache/html/{classe}_{processo}/{tab}.html`
- `scripts/bench_http_vs_selenium.py` — single-process diff harness
- `scripts/validate_ground_truth.py` — runs HTTP path against every fixture in tests/ground_truth/

## Ground-truth validation (5 fixtures)

Ran `scripts/validate_ground_truth.py` end-to-end:

| Fixture              | Wall  | Result |
|----------------------|------:|--------|
| ACO_2652             | 0.81s | 2 diffs (both non-bugs, see below) |
| ADI_2820_reread      | 0.76s | MATCH |
| AI_772309            | 0.48s | MATCH |
| MI_12                | 0.49s | MATCH |
| RE_1234567           | 0.51s | MATCH |

The two ACO 2652 diffs are **not scraper bugs**:

1. **`assuntos` text drift**: live site has `'... CADIN/SPC/SERASA/SIAFI/CAUC'`, fixture captured `'... CADIN'`. STF updated the assunto taxonomy/text since the fixture was recorded.
2. **`pautas: [] vs null`**: fixture inconsistency — ACO has `null`, the other four have `[]`. Current Selenium produces `[]`, so we match Selenium behavior (and 4/5 fixtures).

Bugs surfaced and fixed during ground-truth validation:
- `extract_partes` initially used `#todas-partes` (9 entries for ADI 2820 incl. amici and advogados). Selenium reads from `#resumo-partes`, which jQuery populates from `#partes-resumidas` (4 entries — the "main" parties). Switched to `#partes-resumidas` for parity.
- `extract_recursos` returned field `index`; ground-truth schema uses `id`. Aligned.
- Orchestrator was coercing missing integer fields (volumes/folhas/apensos/numero_origem) to `0` / `[]`; ground truth expects `None`. Dropped the coercion.

## Known limitations

- **`sessao_virtual` is not yet parsed in the HTTP path.** Returns `[]`. The `abaSessao.asp` fragment is largely a JavaScript template that calls `sistemas.stf.jus.br/repgeral/votacao?tema=…` (a separate JSON endpoint) for the "Tema" branch, and the "Sessão" branch relies on collapse-expand interactions to reveal nested content. Porting it means either hitting that JSON API directly or finding a server-rendered variant of the fragment.
- **`abaDecisoes` and `abaPautas`** fetch but aren't parsed (Selenium also doesn't produce these fields).

## Measured baseline (current Selenium scraper)

Ran `main.py -c AI -i 772309 -f 772309` on this branch, fresh venv:

- **Wall clock end-to-end**: 18 s for a single process (from `JUDEX MINI START` to `Finished processing`).
- **Scraper-reported per-process**: 4.98 s (the `ProcessTimer` measurement — excludes driver startup).
- **Driver startup overhead**: ~13 s (amortized across a batch; effectively free for large ranges).
- **Extracted fields**: 27 top-level keys, 2 andamentos, 4 partes, 0 peticoes, 0 recursos.
- **Memory**: 190 MB RSS.
- **Note**: AI 772309 is a *small* process. The `ScraperConfig` comment asserts "itens demoram 20s cada" as the steady-state — consistent with more movement-heavy or click-gated cases hitting the `button_wait=10` timer.

## Expected speedup

| Approach                    | Per process (small) | Per process (heavy) | 100 processes | 1000 processes |
|-----------------------------|-------------:|-------------:|--------------:|---------------:|
| Current Selenium (measured) | 5 s          | ~20 s        | ~33 min       | ~5.5 h         |
| HTTP serial (probed)        | ~2.5 s       | ~5 s         | ~8 min        | ~1.4 h         |
| HTTP, tabs parallel         | ~1.5 s       | ~2 s         | ~3 min        | ~33 min        |
| HTTP, tabs + processes ||8  | ~0.2 s amort.| ~0.3 s amort.| ~25 s         | ~4 min         |

The **per-process speedup is larger on heavier cases** — the click-gated tabs (`andamentos`, `peticoes`, `recursos`) are where Selenium pays the `button_wait` penalty and where HTTP pays nothing. Small processes show a modest 2–3× win; processes with full docket depth should show 5–10×.

Real-world numbers will be worse (backoff on errors, the occasional slow response). Even the conservative end makes development iteration — not just production sweeps — dramatically faster.

## What this does NOT fix

- **Server-side rate limiting.** If STF throttles per-IP, parallel workers hit that ceiling faster, not past it. Starting point: 3–5 workers, back off on 429/5xx.
- **PDF parsing cost.** Wherever `pypdf` is used to extract text from linked PDFs, that work is unchanged.
- **Site ToS and courtesy.** Faster scraping is more polite only if we also implement proper caching; otherwise it's just the same load concentrated in time. See "Cache" below.

## Concrete next steps (in order)

1. **Add an HTML cache.** Lowest-risk win independent of everything else. Store raw HTML (landing page + every tab fragment) keyed by `{classe}_{processo}_{incidente}/{tab}.html`. Re-extraction becomes a pure local loop — no scraping, no rate-limit exposure, instant iteration on parser changes. Extend the ground-truth test suite to run against cached HTML.
2. **Prototype the HTTP client** in `src/scraper_http.py` alongside the existing Selenium one. Run both against the same small range; diff the outputs. Fields that don't match go into a "needs investigation" list before the Selenium path is removed.
3. **Rewire `extract_processo`** to take HTML fragments by tab name instead of a single `BeautifulSoup` + `driver`. Most extractors already take `soup`; those that currently reach into `driver` for click-loaded content become the ones that receive the corresponding tab fragment. This is a refactor-in-place — no new extractors needed.
4. **Parallelize.** First tabs-within-a-process, then processes-within-a-range. Wrap both in `tenacity` retries the same way the current driver path is. Cap concurrency conservatively; bump only if the server tolerates it.
5. **Delete the Selenium path** once the HTTP path reaches parity on ground-truth cases. Drop `selenium` from deps, delete `src/utils/driver.py` and `src/utils/get_element.py`. Keep `button_wait` out of the new config.
6. **Follow-up diagnostics.** Log per-tab latencies explicitly. This is where we'll first see rate-limit pressure if it materializes.

## What to explicitly NOT do

- Don't switch Selenium → Playwright. Both drive a real browser; the floor cost (browser startup, full page render) is the same. Playwright gives maybe 1.5–2×, not the 10× we see from going HTTP-only. If we ever need a browser fallback, either works equally well and Selenium is already there.
- Don't rotate IPs or spoof user agents to evade rate limits. Gray-area legally, brittle technically, and our single-IP throughput after the refactor should be more than enough.
- Don't invest more time looking for a bulk dataset. STF is not on DataJud, Corte Aberta is aggregates-only, and the commercial aggregators (Escavador, JusBrasil, JUDIT) are paid and not appropriate for research scraping of specific ranges.

## Open questions (resolve before step 2)

- Does the 302 redirect always come from `listarProcessos.asp`, or can the portal return the detail page inline for some classes? Probe a few `classe` types (RE, ADI, MI, ACO) to confirm the flow.
- Does `abaAndamentos` contain embedded links to PDFs the same way the rendered DOM does? The current `extract_andamentos` pulls PDF URLs and downloads them — need to confirm those URLs are in the fragment as-is.
- For processes with many movements, does `abaAndamentos` paginate, or return everything at once? (The 17 KB fragment for `AI 772309` suggests "all at once", but verify on a high-volume case.)

## Evidence — reproducible probes

```bash
# DataJud: STF not present (STJ works with same key)
curl -skS -X POST "https://api-publica.datajud.cnj.jus.br/api_publica_stf/_search" \
  -H "Authorization: APIKey cDZHYzlZa0JadVREZDJCendQbXY6SkJlTzNjLV9TRENyQk1RdnFKZGRQdw==" \
  -H "Content-Type: application/json" \
  -d '{"size":1}'
# → 404 index_not_found_exception

# STF: incidente resolution
curl -skS -o /dev/null -w "%{http_code} %{redirect_url}\n" \
  "https://portal.stf.jus.br/processos/listarProcessos.asp?classe=AI&numeroProcesso=772309"
# → 302 detalhe.asp?incidente=3785234

# STF: full andamentos tab via HTTP only
JAR=/tmp/stf_cookies.txt
curl -skS -c $JAR -o /dev/null \
  "https://portal.stf.jus.br/processos/detalhe.asp?incidente=3785234"
curl -skS -b $JAR \
  -H "X-Requested-With: XMLHttpRequest" \
  -H "Referer: https://portal.stf.jus.br/processos/detalhe.asp?incidente=3785234" \
  "https://portal.stf.jus.br/processos/abaAndamentos.asp?incidente=3785234&imprimir="
# → 200, 17 KB of real andamentos data
```
