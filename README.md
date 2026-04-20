# judex-mini

Extração automatizada de dados de processos do STF (Supremo Tribunal Federal). Você passa uma **classe** (HC, ADI, RE, AI, …) e um **intervalo de números de processo**; o programa acessa o portal do STF, extrai metadados de cada processo (partes, andamentos, relator, decisão, URLs dos PDFs anexados) e grava um arquivo `.json` por processo. Se quiser o texto dos PDFs também, há dois comandos dedicados (`baixar-pecas` + `extrair-pecas`) — descritos na seção 5.

Este README é o **guia prático para rodar a ferramenta**. Detalhes de arquitetura, testes e convenções para quem contribui com o código estão em [`CLAUDE.md`](CLAUDE.md).

## Comandos

Subcomandos principais disponíveis via `uv run judex <comando>` (ajuda detalhada com `--help`):

| Comando                | O que faz                                                                  |
|------------------------|----------------------------------------------------------------------------|
| `varrer-processos`     | Raspa metadados de processos do STF (partes, andamentos, PDFs, etc.).      |
| `baixar-pecas`         | Baixa os bytes dos PDFs anexados para o cache local.                       |
| `extrair-pecas`        | Extrai texto dos PDFs em cache (pypdf / mistral / chandra / unstructured). |
| `atualizar-warehouse`  | Reconstrói o DuckDB analítico a partir dos JSONs + cache (zero HTTP).      |
| `relatorio-diario`     | Relatório diário de novas distribuições (watchlist opcional para diffs).   |

## Fluxo completo

Do zero a um warehouse consultável em SQL, cinco passos em ordem. Os dois primeiros falam com o STF; os três seguintes são locais (zero HTTP).

```text
  1. varrer-processos     ← HTTP (portal.stf.jus.br)
  2. baixar-pecas         ← HTTP (sistemas.stf.jus.br)
  3. extrair-pecas        ← local (lê bytes do cache, escreve texto)
  4. aggregate_dead_ids   ← local (compila sweep.state.json → cemitério)
  5. atualizar-warehouse  ← local (JSONs + cache → DuckDB)
```

| # | Comando                                                     | Pule se…                                                                    |
|---|-------------------------------------------------------------|-----------------------------------------------------------------------------|
| 1 | `judex varrer-processos`                                    | nunca — é a base de tudo                                                    |
| 2 | `judex baixar-pecas`                                        | só quer metadados                                                           |
| 3 | `judex extrair-pecas`                                       | baixou bytes mas o texto não importa                                        |
| 4 | `uv run python scripts/aggregate_dead_ids.py --classe HC`   | sweep pequeno; em sweeps de milhares, rode entre 1 e 5 — no próximo sweep passe `--excluir-mortos data/dead_ids/HC.txt` para pular IDs já confirmados como "não existem" no STF |
| 5 | `judex atualizar-warehouse`                                 | consulta os JSONs direto (raro)                                             |

O passo 4 agrega observações `NoIncidente` (o sinal canônico do STF de "este `processo_id` nunca foi alocado") de todos os sweeps já feitos e grava em `data/dead_ids/<classe>.txt` os IDs confirmados (≥ 2 observações com `body_head=""`). A tabela `<classe>.candidates.tsv` ao lado guarda a auditoria completa.

**Exemplo concreto para 2026** (HC, ids 267138..271138):

```bash
# 1. Metadados — sharded com rotação de proxy (~60 min em 8 shards)
uv run judex varrer-processos -c HC -i 267138 -f 271138 \
  --rotulo hc_2026 --saida runs/active/hc-2026 \
  --diretorio-itens data/cases/HC \
  --shards 8 --proxy-pool-dir config/

# 2. Bytes dos PDFs — sharded (~30 min)
uv run judex baixar-pecas -c HC -i 267138 -f 271138 \
  --saida runs/active/hc-2026-bytes --nao-perguntar \
  --shards 8 --proxy-pool-dir config/

# 3. Texto via pypdf, zero HTTP (~10 min)
uv run judex extrair-pecas -c HC -i 267138 -f 271138 \
  --saida runs/active/hc-2026-text --nao-perguntar

# 4. Agrega IDs mortos de todos os sweeps já feitos (~5 s, local)
uv run python scripts/aggregate_dead_ids.py --classe HC
# → data/dead_ids/HC.txt + HC.candidates.tsv

# 5. Rebuild do warehouse (só 2026, swap atômico, ~5 s)
uv run judex atualizar-warehouse --ano 2026 --classe HC \
  --saida data/warehouse/judex-2026.duckdb
```

## Funcionalidades

- **Retry automático em 403** — backoff exponencial via tenacity; o WAF do STF usa 403 (não 429) como sinal de throttle, e a janela abre em minutos.
- **Rotação proativa de proxy** — troca de IP antes do WAF endurecer; cada proxy tem janela ativa e cooldown alinhados à memória do WAF.
- **Sweeps shardeados** — particiona um CSV em N processos paralelos, um pool de proxy por shard, arquivo de PIDs para monitor/stop.
- **Disjuntor (circuit breaker)** — janela rolante das últimas raspagens; quando a fração de falhas ultrapassa o limiar, o sweep para limpo (escreve estado e sai).
- **Classificação de regime WAF** — `CliffDetector` acompanha em tempo real `healthy` → `approaching_collapse` → `engaged` → `collapse`, e rotaciona preventivamente.
- **Retomada atômica** — `sweep.state.json` + arquivos por processo com renomeação atômica; `--retomar` pula o que já deu `ok`.
- **Retentar só as falhas** — `--retentar-de sweep.errors.jsonl` para re-atacar apenas os processos que falharam.
- **Cache de PDF versionado por provedor** — sidecar `.extractor` permite trocar OCR (pypdf → mistral → chandra) sem rebaixar bytes.
- **Prévia de custo** — `--dry-run` em `extrair-pecas` estima páginas, USD e tempo antes de queimar chave de API.
- **Validação contra gabarito** — fixtures hand-verified em `tests/ground_truth/` para evitar regressões em extractors.
- **Watchlist no relatório diário** — lista de processos monitorados com diff estruturado por rodada.

---

## 1. Pré-requisitos

O projeto só roda em **Linux / macOS / WSL**. No Windows você precisa do **WSL** (Windows Subsystem for Linux); Linux e macOS rodam direto no terminal.

Você vai precisar de três coisas:

1. Um terminal Linux (Ubuntu via WSL no Windows, Terminal no macOS, seu emulador preferido no Linux).
2. O gerenciador Python **`uv`** — instalado abaixo, não precisa instalar Python antes.
3. `git` (geralmente já vem instalado; se não, `sudo apt install git`).

> **Atenção Windows:** toda a execução acontece **dentro do WSL**, nunca no PowerShell nem no CMD. Depois de instalar o WSL, abra o app "Ubuntu" no menu iniciar e rode os comandos lá.

---

## 2. Instalação (passo a passo)

> **Alternativa rápida — `pip` (requer Python 3.10+ já instalado):** se você já tem Python no sistema e quer só rodar o `judex` CLI sem clonar o repositório, `pip install git+https://github.com/noah-art3mis/judex-mini` — depois pule direto para a **[§ 3](#3-primeiro-uso)**. Para análise (notebooks Marimo, plots), use `pip install "git+https://github.com/noah-art3mis/judex-mini#egg=judex-mini[analysis]"`. O resto deste guia supõe instalação via `uv` (receita abaixo), que é o caminho recomendado para desenvolvimento e sweeps grandes.

### 2.1 (Só Windows) Instalar o WSL

No PowerShell **como administrador**:

```powershell
wsl --install
```

Reinicie o computador quando pedir. Depois abra o app **Ubuntu** que apareceu no menu iniciar e crie um usuário/senha quando ele pedir. A partir daí, todos os comandos deste guia são digitados **dentro do Ubuntu**.

### 2.2 Instalar o `uv`

No terminal do Ubuntu (ou macOS/Linux):

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

**Depois de instalar, feche e reabra o terminal** — senão o comando `uv` não vai ser encontrado. Para confirmar que funcionou:

```bash
uv --version
```

Se aparecer algo como `uv 0.x.y`, está tudo certo. Se der `command not found`, veja **[Problemas comuns](#8-problemas-comuns)**.

### 2.3 Clonar o repositório

```bash
git clone https://github.com/noah-art3mis/judex-mini
cd judex-mini
```

### 2.4 Instalar as dependências

Ainda dentro da pasta `judex-mini`:

```bash
uv sync
```

Isso baixa a versão certa do Python e todas as bibliotecas. Só precisa ser feito uma vez (e a cada `git pull` que mexa nas dependências).

Para conferir que ficou tudo ok:

```bash
uv run judex --help
```

Deve aparecer o menu de subcomandos (`varrer-processos`, `baixar-pecas`, `extrair-pecas`, `exportar`, `validar-gabarito`, `sondar-densidade`). Para ver as opções de cada um: `uv run judex <comando> --help`. (O comando longo `uv run python main.py …` também funciona — é apenas um atalho para o mesmo hub.)

---

## 3. Primeiro uso

Comando mínimo para baixar **um único processo** (ex.: `HC 135041`):

```bash
uv run judex varrer-processos -c HC -i 135041 -f 135041
```

O que cada pedaço significa:

| Flag  | Significa             | Exemplo                |
|-------|-----------------------|------------------------|
| `-c`  | **c**lasse processual | `HC`, `ADI`, `RE`, `AI`|
| `-i`  | número **i**nicial    | `135041`               |
| `-f`  | número **f**inal      | `135041`               |

Se tudo deu certo, o arquivo do processo fica em `runs/coletas/<timestamp>-<rótulo>/items/judex-mini_HC_135041-135041.json`. O timestamp e o rótulo são inferidos quando você passa só `-c/-i/-f`; para escolher, use `--saida caminho/` e `--rotulo meu-nome`.

---

## 4. Comandos comuns

**Baixar um intervalo de processos** (ex.: HC 135041 a 135050):

```bash
uv run judex varrer-processos -c HC -i 135041 -f 135050
```

**Salvar em uma pasta específica**:

```bash
uv run judex varrer-processos -c HC -i 135041 -f 135041 \
  --saida runs/coletas/meu_teste
```

**Refazer uma extração**: cada execução grava em `runs/coletas/<timestamp>-<rótulo>/`, então reusos não se atropelam — é só rodar de novo. Para retomar uma varredura interrompida, aponte a mesma `--saida` e passe `--retomar` (só os processos que ainda não deram `ok` são rerodados).

**Salvar direto no Desktop do Windows (só WSL)**:

```bash
uv run judex varrer-processos -c HC -i 135041 -f 135041 \
  --saida /mnt/c/Users/SeuUsuario/Desktop/judex-mini
```

Substitua `SeuUsuario` pelo seu nome de usuário do Windows. Os arquivos aparecem no Desktop como se tivessem sido gerados pelo próprio Windows.

**Ver todas as opções**:

```bash
uv run judex --help
```

---

## 5. Baixando e extraindo PDFs

O `varrer-processos` já coleta os **metadados** de cada processo, incluindo as URLs dos PDFs anexados (decisões, acórdãos, manifestações da PGR). Quando você quer o **texto** desses PDFs também, rode dois comandos em sequência — eles são independentes de propósito:

1. **`baixar-pecas`** — baixa os bytes dos PDFs para `data/cache/pdf/<hash>.pdf.gz`. É a única parte que volta a falar com o STF, mas vai para um domínio diferente (`sistemas.stf.jus.br`, não `portal.stf.jus.br`), com seu próprio orçamento de taxa — na prática, 403 aqui é bem mais raro que no `varrer-processos`. Aceita `--proxy-pool` e tem modo shardeado (`--shards`) para sweeps grandes.
2. **`extrair-pecas --provedor <X>`** — lê os bytes do disco e extrai o texto via o provedor escolhido. Nenhuma chamada ao STF. Provedores suportados: `pypdf` (local, grátis, camada de texto; padrão), `mistral`, `chandra`, `unstructured` (OCR pagos; exigem chave de API).

Exemplo típico para os HCs que você acabou de varrer:

```bash
# 1) Baixa os bytes (uma vez por URL — respeita o --forcar)
uv run judex baixar-pecas -c HC -i 135041 -f 135041 --nao-perguntar

# 2) Extrai o texto com pypdf (rápido, grátis, zero HTTP)
uv run judex extrair-pecas -c HC -i 135041 -f 135041 --nao-perguntar

# Depois, re-extrair com OCR melhor (sem baixar de novo):
export MISTRAL_API_KEY="..."
uv run judex extrair-pecas -c HC -i 135041 -f 135041 \
  --provedor mistral --forcar --nao-perguntar
```

O texto extraído fica em `data/cache/pdf/<hash>.txt.gz`, com um pequeno arquivo `.extractor` ao lado marcando **qual provedor** produziu aquele texto. Na próxima execução com o mesmo `--provedor`, a ferramenta pula os PDFs que já têm texto desse provedor; passe `--forcar` para reextrair.

**Sempre use `--dry-run`** antes de uma extração paga (Mistral / Chandra / Unstructured). A prévia mostra quantas páginas serão processadas, custo estimado em dólares e tempo estimado. Detalhes técnicos em [`docs/peca-sweep-conventions.md`](docs/peca-sweep-conventions.md).

---

## 6. Onde ficam os arquivos

A ferramenta mantém três categorias de arquivos. As duas primeiras você apaga à vontade (regenerável); a terceira é o produto científico e deve ser preservada.

```
runs/
├── coletas/                               ← saída de varrer-processos
│   └── <timestamp>-<rótulo>/
│       ├── items/
│       │   └── judex-mini_HC_135041-135041.json   (um por processo)
│       ├── sweep.state.json               (estado atômico, retomável)
│       ├── sweep.log.jsonl                (log append-only)
│       ├── sweep.errors.jsonl             (só as falhas — use com --retentar-de)
│       └── report.md                      (resumo humano)
├── active/                                ← saída de baixar/extrair-pecas (em curso)
└── archive/                               ← varreduras concluídas, arquivadas

data/
├── cases/<CLASSE>/                        ← produto final, um arquivo por processo
│   └── judex-mini_HC_135041-135041.json
├── cache/
│   ├── html/<CLASSE>_<N>/                 ← fragmentos HTML por processo
│   │   ├── detalhe.html.gz
│   │   ├── abaPartes.html.gz
│   │   ├── abaAndamentos.html.gz
│   │   └── ... (um .html.gz por aba + incidente.txt)
│   └── pdf/                               ← cache URL-keyed (sha1) dos PDFs
│       ├── <sha1>.pdf.gz                  (bytes crus — baixar-pecas)
│       ├── <sha1>.txt.gz                  (texto extraído — extrair-pecas)
│       ├── <sha1>.extractor               (qual provedor produziu o texto)
│       └── <sha1>.elements.json.gz        (elementos estruturados, OCR)
└── logs/                                  ← log detalhado por sessão
    └── scraper_YYYYMMDD_HHMMSS.log
```

- **`data/cases/`** é o que importa — um arquivo JSON por processo com todos os metadados (partes, andamentos, relator, decisão, etc.).
- **`runs/coletas/<timestamp>-<rótulo>/`** é o diretório operacional de cada execução de `varrer-processos`. Pode apagar depois que a varredura terminou e você moveu os JSONs para `data/cases/` (ou deixe em `runs/archive/` como histórico).
- **`data/cache/`** é cache regenerável. Se apagar (`rm -rf data/cache`), a próxima execução refaz — só fica mais lenta. Segunda-passagens com cache frio são ~60× mais lentas que com cache quente.
- **`data/logs/`** tem o log detalhado de cada sessão. Útil para reportar bugs.

Detalhes completos em [`docs/data-layout.md`](docs/data-layout.md). Para mudar a pasta de saída, passe `--saida /caminho/da/pasta`.

---

## 7. Uso avançado

Quando o `-c/-i/-f` não chega: sweeps de milhares de processos, OCR pago, rotação de proxy, retomada de erros e disjuntor. Cada sub-seção é independente — leia só o que precisar.

### 7.1 Sweeps grandes via CSV

Para raspar listas não-contíguas ou na casa dos milhares, passe um CSV em vez de `-c/-i/-f`. Formato (cabeçalho obrigatório):

```csv
classe,processo
HC,138706
HC,138707
ADI,4321
```

Invocação (no modo CSV `--saida` e `--rotulo` viram obrigatórios):

```bash
uv run judex varrer-processos \
  --csv runs/alvos.csv \
  --saida runs/coletas/meu_sweep \
  --rotulo hc-2025-backfill
```

Cada processo `ok` é escrito atomicamente em `runs/coletas/meu_sweep/items/` — não há ponto de falha que corrompe o diretório. Para retomar depois de uma queda, **aponte para o mesmo `--saida` e adicione `--retomar`**; ele pula todo processo já marcado como `status=ok` em `sweep.state.json`.

### 7.2 Retentar apenas os que falharam

Ao final de um sweep, os erros ficam em `sweep.errors.jsonl` dentro do diretório de saída. Para rerodar só esses:

```bash
uv run judex varrer-processos \
  --retentar-de runs/coletas/meu_sweep/sweep.errors.jsonl \
  --saida runs/coletas/meu_sweep \
  --rotulo hc-2025-backfill
```

Útil quando o WAF teve um mau momento no meio do sweep — a retomada completa a cobertura sem revisitar os já-`ok`.

### 7.3 Rotação de proxy

Sem proxy, um IP residencial típico aguenta ~600–1000 requisições ao portal do STF antes do WAF começar a devolver 403s em sequência (ver [`docs/rate-limits.md`](docs/rate-limits.md)). Para sweeps de milhares, rotação de IP é praticamente mandatória.

**Setup.** Crie um arquivo com uma URL de proxy por linha:

```
http://usuario:senha@proxy1.example.com:8080
http://usuario:senha@proxy2.example.com:8080
http://usuario:senha@proxy3.example.com:8080
```

E passe como `--proxy-pool`:

```bash
uv run judex varrer-processos --csv alvos.csv \
  --saida runs/coletas/sweep --rotulo sweep-1 \
  --proxy-pool runs/proxies.txt
```

O scraper rotaciona proativamente: cada IP é usado por ~4,5 min e fica ~4 min em cooldown, alinhado com o tempo que o WAF do STF leva para "esquecer" um IP.

**Custo (referência prática).** Eu uso [ProxyScrape](https://proxyscrape.com/) residencial — **R$ 100 por 5 GB** de tráfego. Cada processo do STF custa ~30–50 KB de HTML, então 5 GB dão ordem de 100 k raspagens. Para rodar um processo isolado não compensa; para o backfill de uma classe inteira (HC ~216 k), compensa.

**`baixar-pecas` também aceita `--proxy-pool`.** Vive em `sistemas.stf.jus.br` — domínio separado, contador de reputação próprio, bem mais tolerante que `portal.stf.jus.br`, então em volumes pequenos roda direto. Em sweeps grandes (milhares de PDFs), o modo shardeado (`--shards N --proxy-pool-dir D`) é o caminho: particiona o CSV e distribui um pool de proxies por shard.

**Convenção do diretório de proxies (modo shardeado).** O launcher espera um arquivo por shard, nomeado `proxies.<letra>.txt` e pega os **N primeiros em ordem alfabética**. Ou seja:

```
config/
├── proxies.a.txt        ← usado pelo shard-a
├── proxies.b.txt        ← shard-b
├── proxies.c.txt
...
└── proxies.p.txt        ← shard-p (16º)
```

Cada arquivo tem uma URL de proxy por linha (mesmo formato do `--proxy-pool`). Para `--shards 8` bastam `proxies.{a..h}.txt`; para `--shards 16`, adicione `proxies.{i..p}.txt`. O launcher falha limpo (`ProxyPoolShortage`) se o número de arquivos for menor que o número de shards pedido.

### 7.4 Disjuntor (circuit breaker)

Para evitar queimar proxy e IP quando o WAF entra em regime de bloqueio total, `varrer-processos` embute um disjuntor ligado por padrão: mantém uma janela rolante das últimas raspagens e, se a fração de falhas ultrapassa o limiar, o sweep para limpo (escreve estado, sai com código 2). Em paralelo, o `CliffDetector` classifica o regime WAF em tempo real (`healthy` / `approaching_collapse` / `engaged` / `collapse`) e dispara rotação preventiva de proxy antes da janela expirar. Detalhes em [`docs/rate-limits.md`](docs/rate-limits.md).

### 7.5 OCR pago: chaves de API e custo

`extrair-pecas` aceita quatro provedores. O padrão (`pypdf`) é local, grátis e tira proveito só da camada de texto — em PDFs escaneados devolve texto vazio ou sujo. Os três OCR exigem chave de API no ambiente:

| Provedor       | Variável de ambiente     | Onde obter                         |
|----------------|--------------------------|------------------------------------|
| `mistral`      | `MISTRAL_API_KEY`        | https://console.mistral.ai/        |
| `unstructured` | `UNSTRUCTURED_API_KEY`   | https://platform.unstructured.io/  |
| `chandra`      | `CHANDRA_API_KEY`        | https://www.datalab.to/            |

**Custo por 1 000 páginas** (fonte: `judex/scraping/ocr/dispatch.py`):

| Provedor       | Tier              | USD / 1k páginas |
|----------------|-------------------|------------------|
| `pypdf`        | local             | $0.00            |
| `mistral`      | batch             | $1.00            |
| `mistral`      | sync (padrão)     | $2.00            |
| `unstructured` | fast              | $1.00            |
| `unstructured` | hi_res            | $10.00           |
| `chandra`      | todas             | ~$3.00           |

Configure a chave no shell **de trabalho** (nunca commite) e rode primeiro com `--dry-run` para ver páginas, custo estimado em USD e tempo estimado:

```bash
export MISTRAL_API_KEY="sk-..."
uv run judex extrair-pecas -c HC -i 135041 -f 135041 \
  --provedor mistral --dry-run
```

**Sempre `--dry-run` antes.** Bote na ponta do lápis com o câmbio do dia antes de aprovar uma extração paga.

### 7.6 Outros subcomandos

Menos usados, mas úteis em contextos específicos:

- **`sondar-densidade`** — amostragem estratificada para estimar quantos `processo_id` de uma classe existem de verdade (antes de dimensionar um sweep). Ver [`docs/process-space.md`](docs/process-space.md).
- **`validar-gabarito`** — diff da saída do raspador contra os gabaritos conferidos à mão em `tests/ground_truth/`. Rodar depois de qualquer mudança em extractor.
- **`exportar`** — exporta os notebooks Marimo de HC como HTML autônomo para compartilhar resultados.

`uv run judex <comando> --help` em cada um para ver as flags.

---

## 8. Problemas comuns

### `command not found: uv`

Você instalou o `uv` mas não reabriu o terminal. Feche e abra de novo.

### `ModuleNotFoundError` ou `No module named 'src'`

Você provavelmente rodou `python main.py` em vez de `uv run python main.py`. **Sempre use `uv run`**. Se ainda assim der erro, rode `uv sync` de novo de dentro da pasta `judex-mini`.

### Muitos erros `403 Forbidden`

O portal do STF bloqueia IPs que fazem requisições demais em pouco tempo. O bloqueio dura alguns minutos e libera sozinho. O que fazer:

- **Espere 5 a 10 minutos** e tente de novo.
- **Rode intervalos menores** (ex.: 50 processos por vez, não 1000).
- Para varreduras de milhares de processos, use rotação de proxy + disjuntor — receita completa em **[§ 7.3](#73-rotação-de-proxy)** e **[§ 7.4](#74-disjuntor-circuit-breaker)**. O `baixar-pecas` vive em outro domínio (`sistemas.stf.jus.br`) com contador próprio e bem mais tolerante — em volumes pequenos roda direto; para milhares de PDFs, passe `--proxy-pool` ou use o modo shardeado.
- Para detalhes técnicos (retry, pacing, regime WAF), ver [`docs/rate-limits.md`](docs/rate-limits.md) e [`CLAUDE.md`](CLAUDE.md).

### Shards pararam antes do fim (`CliffDetector collapse`)

Em sweeps longos com rotação de proxy, o `CliffDetector` pode decidir que o regime WAF entrou em colapso e parar o shard limpo. Acontece principalmente quando o provedor de proxy tem a reputação degradada no STF (o próprio host/ASN é que está hot, não o seu IP). Sintomas:

- Tempos por caso escalam: 2 s → 30 s → 60 s → 100 s antes da parada
- Driver log termina com `[regime] warming → collapse` e `Stopping cleanly — cool down ≥60 min before --resume`
- `pgrep` para o shard parado retorna vazio; o `sweep.state.json` dele congela em X/500

O que fazer, em ordem de invasividade:

1. **Aguardar ≥60 min e relançar com `--retomar`.** Suficiente para o WAF "esquecer" a reputação na maioria dos casos.
2. **Trocar para IP direto.** Relance a varredura sem `--proxy-pool` — seu IP tem contador próprio, intocado pelo sweep que colapsou. Adequado para recuperar algumas centenas de IDs.
3. **Desligar o detector:** `--ignorar-collapse` mantém o sweep rodando apesar dos picos. Só vale em IP direto — em pool de proxy, o detector existe para proteger a reputação do pool.
4. **Trocar de provedor de proxy.** Se o provedor atual já queimou a reputação no STF, nenhum cooldown razoável recupera — precisa de outra ASN.

Depois de qualquer relançamento, rode `uv run python scripts/aggregate_dead_ids.py --classe HC` para o cemitério absorver as observações `NoIncidente` capturadas antes do colapso — isso acelera a próxima tentativa via `--excluir-mortos`.

---

## 9. Para saber mais

- [`CLAUDE.md`](CLAUDE.md) — guia técnico para quem contribui: módulos, testes, convenções, arquitetura, pegadinhas do portal do STF, ferramentas de *sweep* em larga escala.
- [`docs/data-layout.md`](docs/data-layout.md) — mapa detalhado de onde cada arquivo mora e como se referenciam.
- [`docs/peca-sweep-conventions.md`](docs/peca-sweep-conventions.md) — convenções dos comandos `baixar-pecas` + `extrair-pecas` (modos de entrada, layout de saída, formato da prévia).
- [`docs/current_progress.md`](docs/current_progress.md) — estado atual do trabalho em andamento.
- [`docs/reports/`](docs/reports/) — relatórios de varreduras em larga escala (centenas/milhares de processos).
