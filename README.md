# judex-mini

Extração automatizada de dados de processos do STF (Supremo Tribunal
Federal). Você passa uma **classe** (HC, ADI, RE, AI, …) e um **intervalo
de números de processo**; o programa acessa o portal do STF, extrai
metadados de cada processo (partes, andamentos, relator, decisão, PDFs
anexados) e grava um arquivo `.csv` ou `.json` por processo.

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
`command not found`, veja **[Problemas comuns](#6-problemas-comuns)**.

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
`varrer-pdfs`, `exportar`, `validar-gabarito`, `sondar-densidade`).
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
| `-o`  | formato de saída      | `csv`, `json`, `jsonl` |

Se tudo deu certo, o arquivo fica em
`data/output/judex-mini_HC_135041.json`.

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

**Salvar em um diretório específico**:

```bash
uv run judex varrer-processos -c HC -i 135041 -f 135041 \
  --saida /mnt/c/Users/SeuUsuario/Desktop/judex-mini
```

No WSL, essa saída aparece no Desktop do Windows como se tivesse
sido gerada lá mesmo.

Substitua `SeuUsuario` pelo seu nome de usuário do Windows. Os arquivos
aparecem no Desktop como se tivessem sido gerados pelo próprio Windows.

**Ver todas as opções**:

```bash
uv run judex --help
```

---

## 5. Onde ficam os arquivos

Por padrão a ferramenta cria estas pastas dentro do projeto:

```
data/
├── output/                        ← o que você quer ver
│   └── judex-mini_HC_135041.json     (um arquivo por processo)
├── html/                          ← cache interno (pode ignorar)
│   └── HC_135041/
│       ├── detalhe.html.gz
│       ├── abaPartes.html.gz
│       └── ...
├── pdf/                           ← cache de PDFs extraídos
│   └── <hash>.txt.gz
└── logs/                          ← log de cada execução
    └── scraper_YYYYMMDD_HHMMSS.log
```

- **`data/output/`** é o que importa — um arquivo por processo, com
  todos os metadados.
- **`data/html/`** e **`data/pdf/`** são caches. Se você rodar o mesmo
  processo de novo, a ferramenta reaproveita o cache e fica ~60× mais
  rápida. Pode apagar à vontade (`rm -rf data/html data/pdf`) — só vai
  demorar mais na próxima vez.
- **`data/logs/`** tem o registro detalhado de cada execução. Útil para
  reportar bugs.

Quer usar outra pasta para a saída? Passe `-d /caminho/da/pasta`.

---

## 6. Problemas comuns

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

### Caracteres quebrados nos nomes (ex.: `JosÃ©` em vez de `José`)

Não deveria acontecer — o programa já corrige o encoding do STF. Se
aparecer, abra uma *issue* anexando o log.

### O arquivo de saída não aparece

Confira, nessa ordem:

1. Qual pasta você passou em `-d` (padrão é `data/output/`).
2. Se o processo existe mesmo no STF (tente abrir no navegador:
   `https://portal.stf.jus.br/processos/detalhe.asp?classe=HC&numero=135041`).
3. O arquivo de log em `data/logs/` — ele diz exatamente o que deu
   errado.

### Como limpar tudo e começar do zero

```bash
rm -rf data
```

Isso apaga saída, caches e logs. Na próxima execução o programa recria
as pastas.

---

## 7. Para saber mais

- [`CLAUDE.md`](CLAUDE.md) — guia técnico para quem contribui: módulos,
  testes, convenções, arquitetura, pegadinhas do portal do STF,
  ferramentas de *sweep* em larga escala.
- [`docs/data-layout.md`](docs/data-layout.md) — mapa detalhado de onde
  cada arquivo mora e como se referenciam.
- [`docs/current_progress.md`](docs/current_progress.md) — estado atual do trabalho em
  andamento.
- [`docs/sweep-results/`](docs/sweep-results/) — relatórios de extrações
  em larga escala (centenas/milhares de processos).

Para relatar bugs ou sugerir melhorias, abra uma *issue* no GitHub.
