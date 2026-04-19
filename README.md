# judex-mini

Extração automatizada de dados de processos do STF (Supremo Tribunal
Federal). Você passa uma **classe** (HC, ADI, RE, AI, …) e um **intervalo
de números de processo**; o programa acessa o portal do STF, extrai
metadados de cada processo (partes, andamentos, relator, decisão, URLs
dos PDFs anexados) e grava um arquivo `.json` por processo. Se quiser
o texto dos PDFs também, há dois comandos dedicados (`baixar-pdfs` +
`extrair-pdfs`) — descritos na seção 5.

Este README é o **guia prático para rodar a ferramenta**. Detalhes de
arquitetura, testes e convenções para quem contribui com o código estão
em [`CLAUDE.md`](CLAUDE.md).

---

## 1. Pré-requisitos

O projeto só roda em **Linux / macOS / WSL**. No Windows você precisa
do **WSL** (Windows Subsystem for Linux); Linux e macOS rodam direto no
terminal.

Você vai precisar de três coisas:

1. Um terminal Linux (Ubuntu via WSL no Windows, Terminal no macOS, seu
   emulador preferido no Linux).
2. O gerenciador Python **`uv`** — instalado abaixo, não precisa
   instalar Python antes.
3. `git` (geralmente já vem instalado; se não, `sudo apt install git`).

> **Atenção Windows:** toda a execução acontece **dentro do WSL**, nunca
> no PowerShell nem no CMD. Depois de instalar o WSL, abra o app
> "Ubuntu" no menu iniciar e rode os comandos lá.

---

## 2. Instalação (passo a passo)

### 2.1 (Só Windows) Instalar o WSL

No PowerShell **como administrador**:

```powershell
wsl --install
```

Reinicie o computador quando pedir. Depois abra o app **Ubuntu** que
apareceu no menu iniciar e crie um usuário/senha quando ele pedir. A
partir daí, todos os comandos deste guia são digitados **dentro do
Ubuntu**.

### 2.2 Instalar o `uv`

No terminal do Ubuntu (ou macOS/Linux):

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

**Depois de instalar, feche e reabra o terminal** — senão o comando
`uv` não vai ser encontrado. Para confirmar que funcionou:

```bash
uv --version
```

Se aparecer algo como `uv 0.x.y`, está tudo certo. Se der
`command not found`, veja **[Problemas comuns](#7-problemas-comuns)**.

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

Isso baixa a versão certa do Python e todas as bibliotecas. Só precisa
ser feito uma vez (e a cada `git pull` que mexa nas dependências).

Para conferir que ficou tudo ok:

```bash
uv run judex --help
```

Deve aparecer o menu de subcomandos (`varrer-processos`,
`baixar-pdfs`, `extrair-pdfs`, `exportar`, `validar-gabarito`,
`sondar-densidade`).
Para
ver as opções de cada um: `uv run judex <comando> --help`. (O
comando longo `uv run python main.py …` também funciona — é
apenas um atalho para o mesmo hub.)

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

Se tudo deu certo, o arquivo do processo fica em
`runs/coletas/<timestamp>-<rótulo>/items/judex-mini_HC_135041-135041.json`.
O timestamp e o rótulo são inferidos quando você passa só `-c/-i/-f`;
para escolher, use `--saida caminho/` e `--rotulo meu-nome`.

> **Sempre use `uv run judex ...`** (ou `uv run python main.py ...`),
> nunca `python main.py` direto. O `uv run` garante que o Python certo
> e as bibliotecas certas estão sendo usados. Rodar `python main.py`
> sem `uv run` vai dar `ModuleNotFoundError` ou pior.
>
> A partir de 2026-04-18, o scraper virou o subcomando `varrer-processos`
> (o antigo `coletar` foi absorvido). Raspar um intervalo continua
> simples — `judex varrer-processos -c HC -i 135041 -f 135041` —, mas agora
> a mesma varredura escala para 100 mil processos via `--csv`, com
> retomada, disjuntor, rotação de proxy e relatório. O rótulo e o
> diretório de saída são auto-inferidos quando você passa só
> `-c/-i/-f`. Flags longas estão em português (`--classe`,
> `--processo-inicial`, `--saida`, `--rotulo` etc.); as curtas
> (`-c -i -f`) permanecem.

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

**Refazer uma extração**: cada execução grava em `runs/coletas/<timestamp>-<rótulo>/`,
então reusos não se atropelam — é só rodar de novo. Para retomar
uma varredura interrompida, aponte a mesma `--saida` e passe
`--retomar` (só os processos que ainda não deram `ok` são rerodados).

**Salvar direto no Desktop do Windows (só WSL)**:

```bash
uv run judex varrer-processos -c HC -i 135041 -f 135041 \
  --saida /mnt/c/Users/SeuUsuario/Desktop/judex-mini
```

Substitua `SeuUsuario` pelo seu nome de usuário do Windows. Os
arquivos aparecem no Desktop como se tivessem sido gerados pelo
próprio Windows.

**Ver todas as opções**:

```bash
uv run judex --help
```

---

## 5. Baixando e extraindo PDFs

O `varrer-processos` já coleta os **metadados** de cada processo,
incluindo as URLs dos PDFs anexados (decisões, acórdãos, manifestações
da PGR). Quando você quer o **texto** desses PDFs também, rode dois
comandos em sequência — eles são independentes de propósito:

1. **`baixar-pdfs`** — baixa os bytes dos PDFs para
   `data/cache/pdf/<hash>.pdf.gz`. Esta é a única parte que volta a
   falar com o portal do STF, então está sujeita aos mesmos limites de
   taxa do `varrer-processos`.
2. **`extrair-pdfs --provedor <X>`** — lê os bytes do disco e extrai
   o texto via o provedor escolhido. Nenhuma chamada ao STF.
   Provedores suportados: `pypdf` (local, grátis, camada de texto;
   padrão), `mistral`, `chandra`, `unstructured` (OCR pagos; exigem
   chave de API).

Exemplo típico para os HCs que você acabou de varrer:

```bash
# 1) Baixa os bytes (uma vez por URL — respeita o --forcar)
uv run judex baixar-pdfs -c HC -i 135041 -f 135041 --nao-perguntar

# 2) Extrai o texto com pypdf (rápido, grátis, zero HTTP)
uv run judex extrair-pdfs -c HC -i 135041 -f 135041 --nao-perguntar

# Depois, re-extrair com OCR melhor (sem baixar de novo):
export MISTRAL_API_KEY="..."
uv run judex extrair-pdfs -c HC -i 135041 -f 135041 \
  --provedor mistral --forcar --nao-perguntar
```

O texto extraído fica em `data/cache/pdf/<hash>.txt.gz`, com um
pequeno arquivo `.extractor` ao lado marcando **qual provedor**
produziu aquele texto. Na próxima execução com o mesmo `--provedor`,
a ferramenta pula os PDFs que já têm texto desse provedor; passe
`--forcar` para reextrair.

**Sempre use `--dry-run`** antes de uma extração paga (Mistral /
Chandra / Unstructured). A prévia mostra quantas páginas serão
processadas, custo estimado em dólares e tempo estimado. Detalhes
técnicos em [`docs/pdf-sweep-conventions.md`](docs/pdf-sweep-conventions.md).

---

## 6. Onde ficam os arquivos

A ferramenta mantém três categorias de arquivos. As duas primeiras
você apaga à vontade (regenerável); a terceira é o produto
científico e deve ser preservada.

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
├── active/                                ← saída de baixar/extrair-pdfs (em curso)
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
│       ├── <sha1>.pdf.gz                  (bytes crus — baixar-pdfs)
│       ├── <sha1>.txt.gz                  (texto extraído — extrair-pdfs)
│       ├── <sha1>.extractor               (qual provedor produziu o texto)
│       └── <sha1>.elements.json.gz        (elementos estruturados, OCR)
└── logs/                                  ← log detalhado por sessão
    └── scraper_YYYYMMDD_HHMMSS.log
```

- **`data/cases/`** é o que importa — um arquivo JSON por processo com
  todos os metadados (partes, andamentos, relator, decisão, etc.).
- **`runs/coletas/<timestamp>-<rótulo>/`** é o diretório operacional de
  cada execução de `varrer-processos`. Pode apagar depois que a
  varredura terminou e você moveu os JSONs para `data/cases/` (ou
  deixe em `runs/archive/` como histórico).
- **`data/cache/`** é cache regenerável. Se apagar (`rm -rf data/cache`),
  a próxima execução refaz — só fica mais lenta. Segunda-passagens com
  cache frio são ~60× mais lentas que com cache quente.
- **`data/logs/`** tem o log detalhado de cada sessão. Útil para
  reportar bugs.

Detalhes completos em [`docs/data-layout.md`](docs/data-layout.md).
Para mudar a pasta de saída, passe `--saida /caminho/da/pasta`.

---

## 7. Problemas comuns

### `command not found: uv`

Você instalou o `uv` mas não reabriu o terminal. Feche e abra de novo.
Se persistir:

```bash
source ~/.bashrc     # ou ~/.zshrc no macOS
```

### `ModuleNotFoundError` ou `No module named 'src'`

Você provavelmente rodou `python main.py` em vez de
`uv run python main.py`. **Sempre use `uv run`**. Se ainda assim der
erro, rode `uv sync` de novo de dentro da pasta `judex-mini`.

### Muitos erros `403 Forbidden`

O portal do STF bloqueia IPs que fazem requisições demais em pouco
tempo. O bloqueio dura alguns minutos e libera sozinho. O que fazer:

- **Espere 5 a 10 minutos** e tente de novo.
- **Rode intervalos menores** (ex.: 50 processos por vez, não 1000).
- Para extrações grandes (centenas ou milhares de processos), existem
  ferramentas de *sweep* com retry automático e pacing configurável —
  veja [`CLAUDE.md`](CLAUDE.md).

### O arquivo de saída não aparece

Confira, nessa ordem:

1. Qual pasta você passou em `--saida` (quando omitida, `varrer-processos`
   gera automaticamente um diretório em `runs/coletas/<timestamp>-<rótulo>/`).
2. Se o processo existe mesmo no STF (tente abrir no navegador:
   `https://portal.stf.jus.br/processos/detalhe.asp?classe=HC&numero=135041`).
3. O arquivo de log em `data/logs/` — ele diz exatamente o que deu
   errado.

---

## 8. Para saber mais

- [`CLAUDE.md`](CLAUDE.md) — guia técnico para quem contribui: módulos,
  testes, convenções, arquitetura, pegadinhas do portal do STF,
  ferramentas de *sweep* em larga escala.
- [`docs/data-layout.md`](docs/data-layout.md) — mapa detalhado de onde
  cada arquivo mora e como se referenciam.
- [`docs/pdf-sweep-conventions.md`](docs/pdf-sweep-conventions.md) —
  convenções dos comandos `baixar-pdfs` + `extrair-pdfs` (modos de
  entrada, layout de saída, formato da prévia).
- [`docs/current_progress.md`](docs/current_progress.md) — estado atual
  do trabalho em andamento.
- [`docs/reports/`](docs/reports/) — relatórios de varreduras em larga
  escala (centenas/milhares de processos).