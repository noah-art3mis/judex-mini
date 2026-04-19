# judex-mini

Extração automatizada de dados de processos do STF (Supremo Tribunal Federal). Você passa uma **classe** (HC, ADI, RE, AI, …) e um **intervalo de números de processo**; o programa acessa o portal do STF, extrai metadados de cada processo (partes, andamentos, relator, decisão, URLs dos PDFs anexados) e grava um arquivo `.json` por processo. Se quiser o texto dos PDFs também, há dois comandos dedicados (`baixar-pecas` + `extrair-pecas`) — descritos na seção 5.

Este README é o **guia prático para rodar a ferramenta**. Detalhes de arquitetura, testes e convenções para quem contribui com o código estão em [`CLAUDE.md`](CLAUDE.md).

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

> **Sempre use `uv run judex ...`** (ou `uv run python main.py ...`), nunca `python main.py` direto. O `uv run` garante que o Python certo e as bibliotecas certas estão sendo usados. Rodar `python main.py` sem `uv run` vai dar `ModuleNotFoundError` ou pior.
>
> A partir de 2026-04-18, o scraper virou o subcomando `varrer-processos` (o antigo `coletar` foi absorvido). Raspar um intervalo continua simples — `judex varrer-processos -c HC -i 135041 -f 135041` —, mas agora a mesma varredura escala para 100 mil processos via `--csv`, com retomada, disjuntor, rotação de proxy e relatório. O rótulo e o diretório de saída são auto-inferidos quando você passa só `-c/-i/-f`. Flags longas estão em português (`--classe`, `--processo-inicial`, `--saida`, `--rotulo` etc.); as curtas (`-c -i -f`) permanecem.

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

1. **`baixar-pecas`** — baixa os bytes dos PDFs para `data/cache/pdf/<hash>.pdf.gz`. É a única parte que volta a falar com o STF, mas vai para um domínio diferente (`sistemas.stf.jus.br`, não `portal.stf.jus.br`), com seu próprio orçamento de taxa — na prática, 403 aqui é bem mais raro que no `varrer-processos`, e o comando roda sempre direto (sem proxy).
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

O scraper rotaciona proativamente — cada IP é usado por `--proxy-rotacao-segundos` (padrão 270 s = 4,5 min), depois fica `--proxy-cooldown-minutos` (padrão 4,0 min) fora da fila. A janela bate com o tempo que o WAF precisa para "esquecer" um IP.

**Custo (referência prática).** Eu uso [ProxyScrape](https://proxyscrape.com/) residencial — **R$ 100 por 5 GB** de tráfego. Cada processo do STF custa ~30–50 KB de HTML, então 5 GB dão ordem de 100 k raspagens. Para rodar um processo isolado não compensa; para o backfill de uma classe inteira (HC ~216 k), compensa.

**`baixar-pecas` não usa proxy.** Vive em `sistemas.stf.jus.br` — domínio separado, contador de reputação próprio, bem mais tolerante que `portal.stf.jus.br`. Roda sempre direto.

### 7.4 Disjuntor (circuit breaker)

Para evitar queimar proxy e IP quando o WAF entra em regime de bloqueio total, `varrer-processos` embute um disjuntor:

- `--janela-circuit 50` (padrão) — janela rolante das últimas 50 raspagens.
- `--limiar-circuit 0.8` (padrão) — se ≥ 80 % das últimas 50 **não** deram `ok`, o sweep para limpo (escreve estado, sai com código 2).

Desligar: `--janela-circuit 0`. Regime mais agressivo (parar mais cedo): `--limiar-circuit 0.5`. Detalhes e classificação de regime WAF (healthy / approaching / engaged / collapse) em [`docs/rate-limits.md`](docs/rate-limits.md).

### 7.5 OCR pago: chaves de API e custo

`extrair-pecas` aceita quatro provedores. O padrão (`pypdf`) é local, grátis e tira proveito só da camada de texto — em PDFs escaneados devolve texto vazio ou sujo. Os três OCR exigem chave de API no ambiente:

| Provedor       | Variável de ambiente     | Onde obter                         |
|----------------|--------------------------|------------------------------------|
| `mistral`      | `MISTRAL_API_KEY`        | https://console.mistral.ai/        |
| `unstructured` | `UNSTRUCTURED_API_KEY`   | https://platform.unstructured.io/  |
| `chandra`      | `CHANDRA_API_KEY`        | dashboard Chandra                  |

**Custo por 1 000 páginas** (fonte: `src/scraping/ocr/dispatch.py`):

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

Você instalou o `uv` mas não reabriu o terminal. Feche e abra de novo. Se persistir:

```bash
source ~/.bashrc     # ou ~/.zshrc no macOS
```

### `ModuleNotFoundError` ou `No module named 'src'`

Você provavelmente rodou `python main.py` em vez de `uv run python main.py`. **Sempre use `uv run`**. Se ainda assim der erro, rode `uv sync` de novo de dentro da pasta `judex-mini`.

### Muitos erros `403 Forbidden`

O portal do STF bloqueia IPs que fazem requisições demais em pouco tempo. O bloqueio dura alguns minutos e libera sozinho. O que fazer:

- **Espere 5 a 10 minutos** e tente de novo.
- **Rode intervalos menores** (ex.: 50 processos por vez, não 1000).
- Para varreduras de milhares de processos, use rotação de proxy + disjuntor — receita completa em **[§ 7.3](#73-rotação-de-proxy)** e **[§ 7.4](#74-disjuntor-circuit-breaker)**. O `baixar-pecas` vive em outro domínio (`sistemas.stf.jus.br`) com contador próprio e, em geral, não precisa de proxy.
- Para detalhes técnicos (retry, pacing, regime WAF), ver [`docs/rate-limits.md`](docs/rate-limits.md) e [`CLAUDE.md`](CLAUDE.md).

### O arquivo de saída não aparece

Confira, nessa ordem:

1. Qual pasta você passou em `--saida` (quando omitida, `varrer-processos` gera automaticamente um diretório em `runs/coletas/<timestamp>-<rótulo>/`).
2. Se o processo existe mesmo no STF (tente abrir no navegador: `https://portal.stf.jus.br/processos/detalhe.asp?classe=HC&numero=135041`).
3. O arquivo de log em `data/logs/` — ele diz exatamente o que deu errado.

---

## 9. Para saber mais

- [`CLAUDE.md`](CLAUDE.md) — guia técnico para quem contribui: módulos, testes, convenções, arquitetura, pegadinhas do portal do STF, ferramentas de *sweep* em larga escala.
- [`docs/data-layout.md`](docs/data-layout.md) — mapa detalhado de onde cada arquivo mora e como se referenciam.
- [`docs/peca-sweep-conventions.md`](docs/peca-sweep-conventions.md) — convenções dos comandos `baixar-pecas` + `extrair-pecas` (modos de entrada, layout de saída, formato da prévia).
- [`docs/current_progress.md`](docs/current_progress.md) — estado atual do trabalho em andamento.
- [`docs/reports/`](docs/reports/) — relatórios de varreduras em larga escala (centenas/milhares de processos).
