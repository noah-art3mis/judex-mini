# Cost estimates

How much does a sweep cost in money and wall time? Per-unit anchors,
year-of-HC projections, and headline numbers for the three sweep
passes (`varrer-processos`, `baixar-pecas`, `extrair-pecas`).

All numbers below are **data-anchored** (sweep measurements + the
codebase's canonical walkers, not handrolled scans). The modelled
estimate path lives in `judex/utils/pricing.py` and prints a
`cost: ~$X` line at the end of every sweep — see § Live cost reporting.

## TL;DR

A year of HC (~12k cases + **~15.7k substantive peças** + **~74k OCR
pages**) costs:

| Recipe | Wall | Money @ R$ 20/GB + Mistral batch |
|---|---:|---:|
| Direct IP everywhere + Mistral batch | ~1.8 days | **R$ 371** (only OCR is billed) |
| 16-shard proxy + Mistral batch | ~3.4 hours | **R$ 427** |

Cases R$ 11 · peças R$ 45 · **OCR R$ 371**. OCR is ~87% of the bill.

## Per-unit anchors

| Anchor | Value | Source |
|---|---:|---|
| Wire bytes / case (`varrer-processos`) | **47 KB** blended | `docs/rate-limits.md:213` (sweep V, 2026-04-17, 170k HCs) |
| Wire bytes / peça (`baixar-pecas`) | **143 KB** | Mean of 70,832 cached `.pdf.gz` in `data/raw/pecas/` |
| Pages / peça | **4.71** | `pypdf` sample of 476 cached PDFs (median 3, p90 12, p99 23) |
| Total peça URLs / HC | **3.04** | `collect_peca_targets(roots, classe='HC')` over the full corpus, URL-deduped |
| Substantive peças / HC | **1.33** corpus / **~1.35** recent | After `filter_substantive` (drops tier-C). Cross-checks `docs/completion-tracker.md:129` 2024 fresh-URL count within rounding. |
| Substantive retention | **43.7%** kept | i.e. `filter_substantive` drops ~56% as procedural boilerplate (CERTIDÃO, INTIMAÇÃO, etc.) |

**Measurement chain** (HC corpus, 90,763 cases): raw andamento PDF refs **280,838** → URL-deduped across cases **275,902** (4,936 cross-case duplicates removed; PDFs referenced from consolidated cases via apenso/conexão) → substantive after tier-C drop **120,587**. The cache is `sha1(url)`-keyed so cross-case duplicates only download once; the deduped count is what the runner sees.

Use the codebase's canonical walkers, not handrolled JSON scans:

```python
from judex.sweeps.peca_targets import collect_peca_targets
from judex.sweeps.peca_classification import filter_substantive

all_targets = collect_peca_targets(roots=[...], classe="HC")    # andamentos[].link, deduped
substantive = filter_substantive(all_targets)                    # tier-C dropped
```

### What `baixar-pecas` actually walks

Only `andamentos[].link.url` (PDF / RTF, filtered by `_is_supported_doc_url`).
The two other URL surfaces in the source JSON are populated *at scrape
time* by `varrer-processos` and never re-fetched by the peça sweep:

| Field | Walked by `baixar-pecas`? | Notes |
|---|---|---|
| `andamentos[].link.url` | **yes** | `judex/sweeps/peca_targets.py:170` (`_iter_case_pdf_targets`). 88% of all PDF URLs in the source JSON. |
| `sessao_virtual[].documentos[].url` | no | Captured during scrape; not re-walked. |
| `publicacoes_dje[].decisoes[].rtf.url` | no | Resolved + cached during scrape (`_resolve_publicacoes_dje`); zero marginal peça-sweep cost. |

### Why `scripts/run_sweep.py:1055`'s 200 KB is stale

The code constant is a coarse pre-sweep-V estimate (4 HTTP GETs × ~50 KB).
Sweep V's blended measurement is 4× lower because abas are small JSON
fragments, not full HTML pages. **Use 47 KB.** Override the live cost
line via `PROCESS_AVG_BYTES=47000` (`run_sweep.py:1057`).

## Year of HC: volumes

| Year | Cases | Substantive peças | sub/case | OCR pages |
|---|---:|---:|---:|---:|
| 2025 | 13,365 | 17,615 | 1.32 | 82,967 |
| 2024 | 12,014 | 15,997 | 1.33 | 75,346 |
| 2023 | 11,129 | 15,392 | 1.38 | 72,496 |
| 2022 | 10,824 | 15,014 | 1.39 | 70,716 |
| **2022–2025 mean** | **11,833** | **~15,737** | **~1.35** | **~74,121** |

Per-year produced by `collect_peca_targets + filter_substantive`,
filtered to single-year case files. Pages = peças × 4.71.

For a year of HC at the means above:

- **Cases:** 11,833 × 47 KB = **0.56 GB**
- **Peças (substantive):** 15,737 × 143 KB = **2.25 GB**
- **OCR pages:** **74,121**

## Cost & time per pass

Default proxy rate: **R$ 20/GB** (= 100 BRL / 5 GB). OCR rate:
**R$ 5/1k pages** (Mistral batch $1/1k @ 5 BRL/USD).

| Pass | Mode | Wall | GB | R$ |
|---|---|---:|---:|---:|
| **`varrer-processos`** | direct IP, 1 worker | 17.6 h | 0.56 | 0.00 |
| | proxy, 4 shards (validated) | 4.4 h | 0.56 | 11.12 |
| | proxy, 16 shards (extrapolated) | ~1.1 h | 0.56 | 11.12 |
| **`baixar-pecas` (substantive)** | direct IP, 1 worker | ~23.5 h | 2.25 | 0.00 |
| | proxy, 4 shards | ~3.9 h | 2.25 | 45.01 |
| | proxy, 16 shards | ~1.0 h | 2.25 | 45.01 |
| **`extrair-pecas`** (Mistral) | sync, 1 in flight | 13.1 h | 0.00 | 370.61 |
| | batch, ~10 parallel | ~1.3 h | 0.00 | 370.61 |

### Throughput sources

| Throughput | Source |
|---|---|
| 1-shard direct: 670 cases/h | `docs/rate-limits.md:213` (170k / 253h) |
| 4-shard proxy: 2,698 cases/h | `docs/rate-limits.md:213` (170k / 63h, validated 20.1h continuous) |
| 16-shard proxy: 10,625 cases/h | `docs/rate-limits.md:213` (extrapolated, **untested above 4×**) |
| Peça throughput | **Estimated** as 1.5× cases/shard (1 GET/peça vs 4 GETs/case). Not separately measured. |
| Mistral OCR: ~3 s/PDF sync | `docs/performance.md:75` |
| Mistral pricing: $1/1k pages batch | `judex/utils/pricing.py:29` (`_DEFAULT_MISTRAL_USD_PER_1K_PAGES`) |

## Per-1k reference

| Unit | GB | R$ @ 20/GB |
|---|---:|---:|
| 1k cases | 0.047 | **R$ 0.94** |
| 1k peças (substantive) | 0.143 | **R$ 2.86** |
| 1k OCR pages (Mistral batch) | — | **R$ 5.00** |

## Bigger projections

### All-classes year (rough, ~5× HC volume)

| Pass | Volume | GB | R$ @ 20/GB |
|---|---|---:|---:|
| Cases | 59,165 | 2.78 | R$ 55.62 |
| Substantive peças | 78,683 | 11.25 | R$ 225.06 |
| OCR (Mistral batch) | 370,599 pages | — | R$ 1,853.00 |
| **Total** | | **14.04** | **R$ 2,133.68** |

5× factor is a process-space rule of thumb — see `docs/process-space.md`.

### Whole-corpus re-scrape (current state, hypothetical)

| Pass | Volume | GB | R$ @ 20/GB |
|---|---|---:|---:|
| All cases | 90,763 | 4.27 | R$ 85.32 |
| All substantive peças | 120,587 | 17.24 | R$ 344.88 |
| OCR all substantive (Mistral batch) | 567,965 pages | — | R$ 2,839.83 |
| **Total** | | **21.51** | **R$ 3,270.03** |

Disaster-recovery sizing — corpus is mostly cached already.

### Rate sensitivity (year-of-HC at 2.81 GB total bandwidth)

| Proxy rate | Annual bandwidth |
|---:|---:|
| R$ 10/GB | R$ 28.07 |
| R$ 15/GB | R$ 42.10 |
| **R$ 20/GB (current)** | **R$ 56.13** |
| R$ 30/GB | R$ 84.20 |
| R$ 40/GB ($8/GB default) | R$ 112.27 |

OCR cost (R$ 371) is unaffected by the proxy rate.

## Live cost reporting

Both download passes print a one-line cost summary at the end (source:
`judex/utils/pricing.py`, `ProxyCost.summary_line` at line 46,
`OcrCost.summary_line` at line 68). Numbers are USD because the env-var
contract is USD.

To make the live numbers match your bill:

```bash
PROXY_PRICE_USD_PER_GB=4.00                  uv run judex varrer-processos ...
PROXY_PRICE_USD_PER_GB=4.00                  uv run judex baixar-pecas ...
OCR_PRICE_MISTRAL_USD_PER_1K_PAGES=1.00      uv run judex extrair-pecas --provedor mistral ...
OCR_PRICE_CHANDRA_USD_PER_1K_PAGES=2.00      uv run judex extrair-pecas --provedor chandra ...
OCR_PRICE_UNSTRUCTURED_USD_PER_1K_PAGES=10.0 uv run judex extrair-pecas --provedor unstructured ...
PROCESS_AVG_BYTES=47000                      uv run judex varrer-processos ...
```

All env vars read at sweep start; mid-run changes don't take effect.

## OCR provider tradeoffs

74,121 pages/year (year-of-HC):

| Provider | $/1k pages | Year cost | Notes |
|---|---:|---:|---|
| `pypdf` | $0.00 | **R$ 0** | Free, local. Returns ~3k chars of header garbage on scanned PDFs (`docs/performance.md:89-94`). |
| `mistral` | $1.00 | **R$ 370.61** | **Default.** 12× faster, 10× cheaper than Unstructured per 2026-04-19 bakeoff. |
| `chandra` | $2.00 | R$ 741.21 | 2× Mistral. |
| `unstructured` | $10.00 | R$ 3,706.05 | 10× Mistral. Superseded. |

`extrair-pecas` is HTTP-free — reads cached bytes from
`data/raw/pecas/<sha1>.pdf.gz`, writes text + `<sha1>.extractor`
sidecar. Switching providers does **not** require re-downloading.

## Caveats

- **`baixar-pecas` walks `andamentos[].link` only.** The 1.33 substantive
  peças/case is what the runner actually downloads; it does not include
  `sessao_virtual.documentos[].url` or `publicacoes_dje[].decisoes[].rtf.url`
  (both populated at scrape time and re-fetching them isn't part of the
  default flow). A `--full-surface` future flag could add ~0.4
  peças/case.
- **Peça throughput is estimated, not measured.** Direct-IP 670/h and
  4-shard ~4,000/h extrapolate from the cases-side characterisation.
  Peças hit `sistemas.stf.jus.br` (separate WAF counter per
  `docs/rate-limits.md:20`); could be more forgiving. A 1k-peça
  calibration sweep would tighten the table.
- **16-shard is arithmetic, not validated.** Per `docs/rate-limits.md:220-228`,
  4× holds zero-403 over 20.1h continuous; 8×/16× linearly extrapolate
  but a higher-level aggregate WAF signal across proxy IPs may surface.
  Run a bounded smoke test (~1k records) before committing a full year.
- **BRL↔USD is load-bearing.** All env-var rates are USD; this doc
  assumes 5.0 BRL/USD. At 5.5, set `PROXY_PRICE_USD_PER_GB=3.64`.
  Refresh at sweep time.
- **Direct IP isn't free, it's slow.** R$ 371 at 1.8 days vs R$ 427 at
  3.4 h: paying R$ 56 buys back ~40 hours of wall. Direct IP only
  makes sense for one-off cases (HC 189844: $0 in 1.56s).
