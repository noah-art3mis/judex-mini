# Setup — Proxies (ProxyScrape)

Operational setup for `--proxy-pool`. For *why* (WAF mechanics, two-
layer model), see [`docs/rate-limits.md`](rate-limits.md).

## When you need a pool

- **Direct IP** survives ~600–1000 cumulative requests on a fresh
  residential IP before the WAF layer-2 reputation counter forces
  long cooldowns.
- **Above that** (e.g. year-of-HC backfill, ~15k cases), pool
  rotation is structural — pacing alone won't substitute.
- **`baixar-pecas`** has its own counter on `sistemas.stf.jus.br`
  and tolerates more direct-IP volume; only proxy-route it for >5k
  PDFs.

## Sourcing — ProxyScrape

Sign up at https://proxyscrape.com/, pick **Residential** (not
Datacenter — STF fingerprints datacenter ASNs).

Sizing rule of thumb: **R$100 / 5 GB**, ~30–50 KB per case scrape →
**~100k scrapes per 5 GB**. PDF sweeps burn faster (5–50× larger
payloads).

In the dashboard's **Endpoint generator**:

- Auth: **User+Pass** (not IP-whitelist)
- Country: **Brazil** (lowest latency, least foreign fingerprint)
- Sticky session: **OFF** (driver rotates on its own cadence)
- Generate **at least 2× shard count** endpoints
- Export as **`http://user:pass@host:port`** form

Paste the lines into `config/proxies` (gitignored):

```
# config/proxies — one URL per line; blanks and `#` ignored
http://user:pass@gate.proxyscrape.com:7000
http://user:pass@gate.proxyscrape.com:7001
http://user:pass@gate.proxyscrape.com:7002
```

## Smoke test before launch

```bash
while read -r p; do
    [[ -z "$p" || "$p" =~ ^# ]] && continue
    code=$(curl -s -o /dev/null -w "%{http_code}" \
        --proxy "$p" --max-time 15 \
        -A "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36" \
        "https://portal.stf.jus.br/processos/detalhe.asp?incidente=5400729")
    echo "$code  $p"
done < config/proxies | sort | uniq -c -w3
```

Expected: all 200s. 403 = IP already hot (skip / rotate batch).
407 / timeout = auth or routing broken (fix before sweeping).

## Wire it into a sweep

```bash
# Monolithic
uv run judex executar --csv targets.csv \
    --saida runs/active/sweep --rotulo s1 \
    --proxy-pool config/proxies --retomar

# Sharded (launcher splits round-robin)
uv run judex executar --csv targets.csv \
    --saida runs/active/sweep --rotulo s1 \
    --shards 16 --proxy-pool config/proxies --retomar
```

Launcher refuses to start if pool < `--shards`. Sharded mode writes
per-shard slices to `<saida>/proxies/proxies.{a..p}.txt` at launch.

## Diagnosing a bad pool

| Symptom | Fix |
|---|---|
| Per-case wall escalates to `[regime] collapse` | Cool down ≥60 min, `--retomar`. If it collapses again, regenerate the entire batch from ProxyScrape. |
| 407 on every request | Check ProxyScrape bandwidth quota; regen creds if rotated |
| Connection timeouts | Drop bad lines, relaunch with `--retomar` |
| Mixed 200/403 from start | Smoke-test loop above to identify hot lines, comment them out |

If a 60-min cooldown doesn't recover the pool, the provider's ASN
is on STF's hot list — switch providers or accept partial via
direct-IP `--retentar-de`. See
[`docs/recovery-patterns.md`](recovery-patterns.md).

## Cross-references

- [`docs/rate-limits.md`](rate-limits.md) — WAF mechanics, two-layer
  model, "4-shard proxy-rotation validation" empirical anchor.
- README §7.3 — Portuguese quick-start for end users.
- `judex/scraping/proxy_pool.py` — pool semantics; rotation cadence
  lives in the driver callers (`run_sweep.py`, `download_driver.py`).
