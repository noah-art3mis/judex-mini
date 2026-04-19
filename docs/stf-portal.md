# STF portal — how it actually works

Technical reference for the scraped endpoints: what URLs there are,
what they return, what headers/cookies they need, and what shows up
in which fragment. Nothing here is time-sensitive — it describes the
portal's contract with the scraper, not the state of the project.

See also:
- [`docs/data-layout.md`](data-layout.md) — where the scraped output lives.
- [`docs/rate-limits.md`](rate-limits.md) — how the WAF gates access.
- [`docs/performance.md`](performance.md) — HTTP-vs-Selenium timings.

## URL flow

A single process is fetched in three legs.

1. **`GET /processos/listarProcessos.asp?classe=AI&numeroProcesso=772309`** → **302** redirect to `/processos/detalhe.asp?incidente=3785234`. A `(classe, numero)` → `incidente_id` resolver. ~300 ms.

2. **`GET /processos/detalhe.asp?incidente=3785234`** → **200**, ~69 KB of HTML. Chrome + tab structure + the `incidente` ID + base metadata. ~500 ms. Also sets the session cookies used by the tab calls (see below).

3. **Tab fragments loaded via AJAX.** The detalhe page calls each tab via jQuery `load()`; the scraper replays the same calls directly. The list is visible in the detalhe HTML:

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

Per-tab sizes and latencies on AI 772309 (reference small case):

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

Empty responses reflect that this specific process has no peticoes /
recursos — normal, not an error.

## The auth triad — what `abaX.asp` actually requires

Hitting any `abaX.asp` endpoint with a raw curl returns **403
Forbidden**. There's no login, no token, no API key. The server
requires three things, and only three:

1. **Session cookies.** `ASPSESSIONID…` (classic ASP session) plus `AWSALB` / `AWSALBCORS` (load-balancer sticky session). Both are set on the first GET to `detalhe.asp`.
2. **`Referer: detalhe.asp?incidente=<N>`.** Any `Referer` pointing at the detalhe page for that incidente works; missing or mismatched Referer 403s.
3. **`X-Requested-With: XMLHttpRequest`.** jQuery adds this by default; its absence is what 403s most bare-curl probes.

A `requests.Session()` that has first GET'd `detalhe.asp`, plus those
two headers on subsequent calls, is sufficient. `src/scraping/http_session.py`
encapsulates the session + headers.

Non-browser User-Agents (`curl/*`, anything with "bot" or "python")
get a **permanent** 403 that isn't related to rate limiting. The
default Chrome UA in `ScraperConfig` passes unconditionally.

## The UTF-8 charset quirk

STF serves UTF-8 but **does not declare a charset** in the
`Content-Type` header. `requests` falls back to Latin-1 in that case,
which produces mojibake like `JosÃ©` instead of `José`. The fix is
explicit: set `r.encoding = "utf-8"` before reading `r.text`.
`src/scraping/scraper._decode` does this; never bypass it.

## Field → source map

All fields the scraper extracts live in one of the fragments above.
The parser layer (`src/scraping/extraction/http.py` + friends) takes
`BeautifulSoup` fragments, so the only thing that matters is which
tab each field comes from.

| Field                      | Source                             |
|----------------------------|------------------------------------|
| `incidente`                | `listarProcessos.asp` → Location header |
| `classe`, `processo_id`    | input                              |
| `numero_unico`             | `detalhe.asp`                      |
| `meio`, `publicidade`      | `detalhe.asp`                      |
| `badges`                   | `detalhe.asp`                      |
| `assuntos`                 | `detalhe.asp` / `abaInformacoes`   |
| `data_protocolo`           | `abaInformacoes`                   |
| `orgao_origem`, `origem`   | `abaInformacoes`                   |
| `numero_origem`            | `abaInformacoes`                   |
| `volumes`, `folhas`, `apensos` | `abaInformacoes`               |
| `relator`                  | `detalhe.asp`                      |
| `primeiro_autor`, `partes` | `abaPartes`                        |
| `andamentos`               | `abaAndamentos`                    |
| `sessao_virtual`           | `abaSessao` → repgeral JSON (see below) |
| `deslocamentos`            | `abaDeslocamentos`                 |
| `peticoes`                 | `abaPeticoes`                      |
| `recursos`                 | `abaRecursos`                      |
| `pautas`                   | `abaPautas`                        |

### `partes` gotcha — two sources on `abaPartes.asp`

`abaPartes.asp` renders two party lists in the same fragment:
`#todas-partes` (full, e.g. 9 entries for ADI 2820 including amici
and advogados) and `#partes-resumidas` (main parties, 4 entries for
the same case). The HTTP extractor reads **`#partes-resumidas`** for
parity with Selenium's `#resumo-partes` (jQuery-populated from
`#partes-resumidas`).

### `abaDecisoes`, `abaPautas`

Fetched but not parsed. The Selenium path didn't emit these either,
so the HTTP path doesn't try to.

## `sessao_virtual` — not from `abaSessao`

`abaSessao.asp` is largely a JavaScript template. The actual session
data comes from a **separate origin**:

```
GET https://sistemas.stf.jus.br/repgeral/votacao?tema=<N>        → JSON listing
GET https://sistemas.stf.jus.br/repgeral/votacao/<id>             → JSON detail
```

Extraction happens in `src/scraping/extraction/sessao.py`
(`parse_oi_listing`, `parse_sessao_virtual`, `parse_tema`,
`extract_sessao_virtual_from_json`). Fetchers are dependency-injected
so the parsers are unit-testable against captured fixtures.

**Vote-category coverage is partial**: only `tipoVoto.codigo` 7
(diverge), 8 (acompanha-divergência), 9 (acompanha) land in the
final `votes` dict. Codes 3 (impedido), 10 (acompanha-ressalva),
11 (suspeito), 13 (acompanha-ressalva-ministro) drop out for parity
with the Selenium extractor's 5-category DOM scrape. Extend
`_VOTE_CATEGORY` in `sessao.py` if downstream analysis needs the
full set.

**Schema variance across fixtures**: `tests/ground_truth/*.json`
carry three shapes (MI/RE/AI: `{data,tipo,numero,relator,status,participantes}`;
ACO_2652: `{lista,relator,orgao_julgador,voto_texto,…}`;
ADI_2820_reread: `{metadata,voto_relator,votes,documentos,julgamento_item_titulo}`).
The HTTP path commits to the ADI shape. `sessao_virtual` is a SKIP
field in `src.sweeps.diff_harness.SKIP_FIELDS` — unit tests validate the
parsers instead.

## PDF origin — different hostname, different throttle

Andamento PDFs are referenced from the portal HTML but served from
**`sistemas.stf.jus.br`**, not `portal.stf.jus.br`. This matters for
rate-limit accounting: the two hosts have independent counters.
Interleaving PDF fetches between tab fetches naturally slows the
portal hit rate and can reduce WAF pressure — see
[`docs/rate-limits.md`](rate-limits.md).

URL-keyed text cache at `data/pdf/<sha1(url)>.txt.gz` — see
[`docs/data-layout.md`](data-layout.md) § "The three data stores".

## What doesn't exist

- **No `dadosabertos.stf.jus.br`.** `portal.stf.jus.br/hotsites/corteaberta/` exists but is aggregate-only (dashboards, not case-level).
- **CNJ DataJud does not index STF.** `POST /api_publica_stf/_search` returns `index_not_found_exception` (404). Other tribunals (STJ, TST, TSE, STM) work with the same API key. Do not re-check.
- **Commercial aggregators** (Escavador, JusBrasil, JUDIT) are paid and not appropriate for research scraping of specific ranges.

Scraping the portal directly is the only path.

## Reproducible probes

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

# STF: full andamentos tab via HTTP only (requires the auth triad)
JAR=/tmp/stf_cookies.txt
curl -skS -c $JAR -o /dev/null \
  "https://portal.stf.jus.br/processos/detalhe.asp?incidente=3785234"
curl -skS -b $JAR \
  -H "X-Requested-With: XMLHttpRequest" \
  -H "Referer: https://portal.stf.jus.br/processos/detalhe.asp?incidente=3785234" \
  "https://portal.stf.jus.br/processos/abaAndamentos.asp?incidente=3785234&imprimir="
# → 200, 17 KB of real andamentos data
```
