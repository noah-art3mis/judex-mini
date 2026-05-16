"""judex-mini — hub do raspador + análise do STF.

Ponto de entrada único (Typer) para todas as operações do projeto.
Todos os subcomandos são nativos do Typer; quando a lógica subjacente
ainda vive em ``scripts/``, este módulo reconstrói um ``argv`` e chama
o ``main()`` do script — o que mantém os scripts utilizáveis de forma
autônoma e preserva toda a durabilidade de estado que eles oferecem.

Instalado como o console script ``judex`` via ``[project.scripts]`` no
``pyproject.toml`` — após ``uv sync``, todos os exemplos abaixo também
funcionam com ``uv run judex ...`` no lugar de
``uv run python main.py ...``.

Exemplos:

    uv run judex --help
    uv run judex executar --csv lista.csv --saida out/         # caminho primário (ADR-0005)
    uv run judex executar -c HC -i 250920 -f 267137            # range mode
    uv run judex recuperar runs/active/<label>/ --apply        # residual recovery
    uv run judex warehouse --classe HC                          # rebuild DuckDB
    uv run judex debug exportar --apenas hc_famous_lawyers     # marimo HTML export
"""

from __future__ import annotations

import csv as _csv
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import typer
from dotenv import load_dotenv

from judex.utils.validation import (
    validate_process_range,
    validate_stf_case_type,
)

# Load .env from the project root (or any parent of cwd) at CLI import.
# This is what makes ``judex executar --provedor tesseract_fly`` "just work"
# without an explicit ``export FLY_TESSERACT_URL=…`` — and, more importantly,
# is the path that lets each operator point the CLI at *their own* paid
# infrastructure (Fly endpoint, Datalab/Mistral/RunPod/Gemini API keys)
# without anyone's URL or token getting baked into the codebase. The
# ``.env.example`` at the repo root documents every variable the providers
# read; ``.env`` itself is gitignored so secrets never leave the operator's
# machine. Pattern matches ``scripts/wait_for_chandra_ready.py`` and friends,
# which already do the same. Silent no-op when no .env is found.
load_dotenv()

DEFAULT_NOTEBOOKS: tuple[str, ...] = (
    "hc_explorer",
    "hc_top_volume",
    "hc_famous_lawyers",
    "hc_admissibility",
    "hc_minister_archetypes",
)

app = typer.Typer(
    add_completion=True,
    help="judex-mini — hub do raspador + análise do STF.",
    no_args_is_help=True,
)

# Sub-app for inspection / validation / export utilities that aren't
# part of the everyday operator loop (`executar` → `acompanhar` →
# `relatar` + `recuperar` + `warehouse`). The legacy three-
# command chain (varrer / baixar / extrair / coletar) was removed
# from the CLI surface; the library code in `judex/sweeps/` stays for
# `pick_provider` and shared helpers used by the unified pipeline.
# Recoverable on the `archive/iteration-2-three-command-chain` branch.
debug_app = typer.Typer(
    add_completion=True,
    help="Utilitários auxiliares (inspeção, backup, exportação, validação).",
    no_args_is_help=True,
)
app.add_typer(debug_app, name="debug", rich_help_panel="Utilitários")


# ---------------------------------------------------------------------------
# helpers compartilhados


# ---------------------------------------------------------------------------
# Sweep lifecycle primitives (shared by `executar --detach`, `parar`, and
# `retomar`). Each helper is a thin pure function — the Typer wrappers
# below just compose them.
#
# The pid-file contract is: ``run_pipeline`` writes ``<saida>/executar.pid``
# at startup, deletes it in its finally block. Mono runs land here; sharded
# runs use ``<saida>/shards.pids`` (one PID per line, written by
# ``launch_sharded``). ``_read_pids`` prefers shards.pids when both exist —
# a sharded run has N children to signal, not one.


def _newest_run_dir(root: Path = Path("runs/active")) -> Optional[Path]:
    """Newest sub-directory under ``root`` by mtime, or ``None`` when the
    root is missing / empty. Used by every Coleta command that takes a
    ``<run_dir>`` argument: when the operator omits it, the resolver
    falls back to this so the natural "I just paused something, now do
    the next thing" workflow doesn't require re-typing the path."""
    if not root.exists() or not root.is_dir():
        return None
    candidates = [p for p in root.iterdir() if p.is_dir()]
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def _resolve_run_dir(explicit: Optional[Path]) -> Path:
    """Return ``explicit`` if provided; otherwise default to the newest
    sub-directory under ``runs/active/``. If neither is available,
    exit with a clear typer error. Every Coleta command shares this
    resolver so the "no arg → newest" sugar is uniform across
    ``parar``, ``retomar``, ``acompanhar``, ``relatar``, ``recuperar``.

    ``explicit`` can be a real path *or* a label (``rotulo`` or
    directory name). When it doesn't exist as a directory we fall
    through to ``find_by_label``: exact match wins, prefix match
    accepted when unambiguous, otherwise we error with the candidate
    list. This is the Modal/Heroku affordance — operators address
    runs by name, not coordinate.

    Echoes ``(default) run_dir = <path>`` on stderr when defaulting so
    the operator sees which run is being targeted — no silent
    assumptions about identity."""
    if explicit is not None:
        if explicit.is_dir():
            return explicit
        # Not an existing path: try interpreting as a label.
        from judex.pipeline.run_index import find_by_label
        matches = find_by_label(str(explicit))
        if not matches:
            typer.echo(
                f"erro: '{explicit}' não é um diretório existente nem um "
                "rótulo conhecido em runs/active|archive/.",
                err=True,
            )
            raise typer.Exit(code=2)
        # Exact match (rotulo or dir name) trumps prefix match.
        exact = [
            m for m in matches
            if m.rotulo == str(explicit) or m.saida.name == str(explicit)
        ]
        chosen_pool = exact or matches
        if len(chosen_pool) > 1:
            typer.echo(
                f"erro: '{explicit}' é ambíguo. Candidatos:",
                err=True,
            )
            for m in chosen_pool:
                typer.echo(f"  {m.saida}  ({m.status.value})", err=True)
            raise typer.Exit(code=2)
        resolved = chosen_pool[0].saida
        typer.echo(f"(rótulo) run_dir = {resolved}")
        return resolved

    chosen = _newest_run_dir()
    if chosen is None:
        typer.echo(
            "erro: nenhum diretório encontrado em runs/active/. "
            "Passe <run_dir> explícito.",
            err=True,
        )
        raise typer.Exit(code=2)
    typer.echo(f"(padrão) run_dir = {chosen}")
    return chosen


def _complete_run_label(incomplete: str) -> list[str]:
    """Typer shell-completion hook: enumerate run labels matching the
    partial input. Used on ``<run_dir>`` / ``<saida>`` arguments so
    ``judex parar hc<tab>`` expands to a real label.

    Imported lazily by Typer at completion-evaluation time; never
    runs in the hot path of a regular command invocation."""
    try:
        from judex.pipeline.run_index import label_candidates
        return label_candidates(incomplete)
    except Exception:
        # Completion must never crash the shell — return empty on any
        # error (e.g. a corrupt state.json mid-snapshot).
        return []


def _read_pids(saida: Path) -> list[int]:
    """Pids associated with ``<saida>``. Sharded layout wins when both
    files exist (a sharded run has N children — signalling only the mono
    pid would orphan the rest)."""
    shards_pids = saida / "shards.pids"
    if shards_pids.exists():
        return _parse_pid_file(shards_pids)
    mono_pid = saida / "executar.pid"
    if mono_pid.exists():
        return _parse_pid_file(mono_pid)
    return []


def _parse_pid_file(path: Path) -> list[int]:
    out: list[int] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(int(line))
        except ValueError:
            continue
    return out


def _is_pid_alive(pid: int) -> bool:
    """``os.kill(pid, 0)`` is the POSIX "process exists?" probe — sends
    no signal but raises ``ProcessLookupError`` when the pid is gone."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # We can't signal it but it exists.
        return True
    return True


def _build_retomar_argv(
    saida: Path,
    args: dict,
    *,
    nao_perguntar: bool,
    detach: bool,
) -> list[str]:
    """Reconstruct an ``executar`` argv from a state-journal args block.

    Pure / total — easy to test independently of subprocess plumbing.
    """
    argv: list[str] = ["executar"]
    if args.get("classe"):
        argv.extend(["-c", str(args["classe"])])
    if args.get("inicio") is not None:
        argv.extend(["-i", str(args["inicio"])])
    if args.get("fim") is not None:
        argv.extend(["-f", str(args["fim"])])
    if args.get("csv"):
        argv.extend(["--csv", str(args["csv"])])
    if args.get("retentar_de"):
        argv.extend(["--retentar-de", str(args["retentar_de"])])
    argv.extend(["--saida", str(saida)])
    if args.get("rotulo"):
        argv.extend(["--rotulo", str(args["rotulo"])])
    if args.get("provedor") and args["provedor"] != "pypdf":
        argv.extend(["--provedor", str(args["provedor"])])
    if args.get("forcar"):
        argv.append("--forcar")
    if args.get("proxy_pool"):
        argv.extend(["--proxy-pool", str(args["proxy_pool"])])
    if args.get("portal_concurrencia") not in (None, 1):
        argv.extend(["--portal-concurrencia", str(args["portal_concurrencia"])])
    if args.get("sistemas_concurrencia") not in (None, 1):
        argv.extend(["--sistemas-concurrencia", str(args["sistemas_concurrencia"])])
    if args.get("ocr_concurrencia") not in (None, 4):
        argv.extend(["--ocr-concurrencia", str(args["ocr_concurrencia"])])
    if nao_perguntar:
        argv.append("--nao-perguntar")
    if detach:
        argv.append("--detach")
    return argv


def _executar_kwargs_for_state(
    *,
    classe: Optional[str],
    inicio: Optional[int],
    fim: Optional[int],
    csv: Optional[Path],
    retentar_de: Optional[Path],
    rotulo: Optional[str],
    provedor: str,
    forcar: bool,
    portal_concurrencia: int,
    sistemas_concurrencia: int,
    ocr_concurrencia: int,
    proxy_pool: Optional[Path],
) -> dict:
    """Pack the executar invocation's args into a JSON-serializable
    dict ready to persist via ``state.set_original_args``. Paths get
    str()-ified so they survive a snapshot round-trip."""
    return {
        "classe": classe,
        "inicio": inicio,
        "fim": fim,
        "csv": str(csv) if csv else None,
        "retentar_de": str(retentar_de) if retentar_de else None,
        "rotulo": rotulo,
        "provedor": provedor,
        "forcar": forcar,
        "portal_concurrencia": portal_concurrencia,
        "sistemas_concurrencia": sistemas_concurrencia,
        "ocr_concurrencia": ocr_concurrencia,
        "proxy_pool": str(proxy_pool) if proxy_pool else None,
    }


def _push(argv: list[str], flag: str, value: Any) -> None:
    """Empilha ``[flag, str(value)]`` em argv quando o valor é significativo.

    Ignora ``None`` e string vazia — para defaults do Typer não vazarem
    para o subprocesso filho (que também é Typer). Para ``bool``: anexa
    só o flag quando True, nada quando False (flags de negação têm
    tratamento manual no chamador).
    """
    if value is None or value == "":
        return
    if isinstance(value, bool):
        if value:
            argv.append(flag)
        return
    argv.extend([flag, str(value)])


# ---------------------------------------------------------------------------
# `exportar` — notebooks Marimo → HTML interativo autônomo


def _find_marimo() -> list[str]:
    if shutil.which("marimo"):
        return ["marimo"]
    if shutil.which("uv"):
        return ["uv", "run", "marimo"]
    raise typer.BadParameter(
        "Nem `marimo` nem `uv` estão no PATH. Instale as dependências do "
        "projeto com `uv sync` e tente de novo."
    )


@debug_app.command(name="exportar")
def exportar(
    diretorio_saida: Path = typer.Option(
        Path("exports/html"), "--diretorio-saida", "-o",
        help="Diretório onde os HTMLs serão gravados (criado se não existir).",
    ),
    diretorio_notebooks: Path = typer.Option(
        Path("analysis"), "--diretorio-notebooks",
        help="Diretório onde vivem os notebooks (.py) do Marimo.",
    ),
    apenas: list[str] = typer.Option(
        None, "--apenas",
        help="Exporta somente o(s) notebook(s) nomeado(s) (sem `.py`). "
             "Repita para selecionar vários. Omita para exportar todos.",
    ),
) -> None:
    """Exporta os notebooks de análise como HTML interativo."""
    diretorio_saida.mkdir(parents=True, exist_ok=True)

    selecionados = tuple(apenas) if apenas else DEFAULT_NOTEBOOKS
    desconhecidos = [n for n in selecionados if n not in DEFAULT_NOTEBOOKS]
    if desconhecidos:
        raise typer.BadParameter(
            f"Notebook(s) desconhecido(s): {desconhecidos}. "
            f"Disponíveis: {list(DEFAULT_NOTEBOOKS)}."
        )

    marimo_cmd = _find_marimo()
    falhas: list[str] = []

    for nome in selecionados:
        fonte = diretorio_notebooks / f"{nome}.py"
        destino = diretorio_saida / f"{nome}.html"
        if not fonte.exists():
            typer.secho(f"PULA    {fonte} (não encontrado)", fg=typer.colors.YELLOW)
            continue
        typer.echo(f"EXPORTA {fonte} -> {destino}")
        result = subprocess.run(
            [*marimo_cmd, "export", "html", "--force", str(fonte), "-o", str(destino)],
            check=False,
        )
        if result.returncode != 0:
            typer.secho(
                f"   falhou (exit {result.returncode})", fg=typer.colors.RED
            )
            falhas.append(nome)

    typer.echo()
    typer.echo(f"Concluído. HTMLs em {diretorio_saida}/:")
    for html in sorted(diretorio_saida.glob("*.html")):
        tamanho_kb = html.stat().st_size / 1024
        typer.echo(f"  {tamanho_kb:>7.1f} KB  {html.name}")

    if falhas:
        typer.secho(
            f"\n{len(falhas)} exportação(ões) falharam: {falhas}",
            fg=typer.colors.RED,
        )
        raise typer.Exit(code=1)


# ---------------------------------------------------------------------------
# `fazer-backup` — empacota data/source/processos + data/raw/pecas + data/derived/pecas-texto em um único .zip


@debug_app.command(name="fazer-backup")
def fazer_backup(
    saida: Optional[Path] = typer.Option(
        None, "--saida", "-o",
        help="Caminho do .zip de saída. Default: "
             "runs/backups/judex-backup-<UTC>.zip.",
    ),
    sem_pecas: bool = typer.Option(
        False, "--sem-pecas",
        help="Não incluir as peças (bytes em data/raw/pecas/ + texto em "
             "data/derived/pecas-texto/). Útil para um backup leve só de "
             "metadados.",
    ),
    incluir_warehouse: bool = typer.Option(
        False, "--incluir-warehouse",
        help="Inclui data/derived/warehouse/judex.duckdb. Por padrão fica "
             "de fora — é artefato derivado, regenerável via "
             "`warehouse`.",
    ),
    classe: Optional[list[str]] = typer.Option(
        None, "--classe",
        help="Restringe os processos a uma ou mais classes (HC, ADI, RE…). "
             "Repita para várias. Omita para incluir todas.",
    ),
    diretorio_processos: Path = typer.Option(
        Path("data/source/processos"), "--diretorio-processos",
        help="Raiz dos JSONs de processo (particionados por classe).",
    ),
    diretorio_pecas: Path = typer.Option(
        Path("data/raw/pecas"), "--diretorio-pecas",
        help="Bytes brutos das peças (.pdf.gz, .rtf.gz, …; sha1(url)-keyed).",
    ),
    diretorio_pecas_texto: Path = typer.Option(
        Path("data/derived/pecas-texto"), "--diretorio-pecas-texto",
        help="Texto extraído das peças (.txt.gz / .extractor / .elements.json.gz).",
    ),
    caminho_warehouse: Path = typer.Option(
        Path("data/derived/warehouse/judex.duckdb"), "--caminho-warehouse",
        help="Caminho do warehouse DuckDB (usado só com --incluir-warehouse).",
    ),
    progresso_cada: int = typer.Option(
        5000, "--progresso-cada",
        help="Frequência (em arquivos) das linhas de progresso. 0 desliga.",
    ),
) -> None:
    """Empacota o corpus num .zip que abre direto no Windows.

    Saída atômica (grava em ``.tmp`` e renomeia ao final).

    Exemplos:

        uv run judex debug fazer-backup --incluir-warehouse
        uv run judex debug fazer-backup --classe HC --sem-pecas
    """
    from judex.backup import make_backup

    if saida is None:
        stamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
        saida = Path("runs/backups") / f"judex-backup-{stamp}.zip"

    typer.echo(f"empacotando -> {saida}")
    typer.echo(f"  processos:    {diretorio_processos}{f' (classes={classe})' if classe else ''}")
    typer.echo(f"  peças bytes:  {'pulando' if sem_pecas else diretorio_pecas}")
    typer.echo(f"  peças texto:  {'pulando' if sem_pecas else diretorio_pecas_texto}")
    typer.echo(f"  warehouse:    {'incluído (' + str(caminho_warehouse) + ')' if incluir_warehouse else 'pulando'}")

    result = make_backup(
        saida,
        include_pecas=not sem_pecas,
        include_warehouse=incluir_warehouse,
        classes=classe or None,
        processos_dir=diretorio_processos,
        pecas_dir=diretorio_pecas,
        pecas_texto_dir=diretorio_pecas_texto,
        warehouse_path=caminho_warehouse,
        progress_every=progresso_cada,
    )

    size_gb = result.bytes_written / 1e9
    typer.echo("")
    typer.echo(f"done in {result.elapsed_s:.1f}s")
    typer.echo(f"  {result.file_count:,} arquivos -> {size_gb:.2f} GB")
    typer.echo(f"  saída: {result.output_path}")


# ---------------------------------------------------------------------------
# `executar` — pipeline unificado fire-and-forget (varrer + baixar + extrair
#              num único processo asyncio com três pools concorrentes)


@app.command(name="executar", rich_help_panel="Coleta")
def executar(
    # Modos de entrada (mutuamente exclusivos): range, --csv ou --retentar-de.
    classe: Optional[str] = typer.Option(
        None, "-c", "--classe",
        help="[modo intervalo] Classe processual (HC, RE, AI, ADI etc.). "
             "Combine com -i e -f para rodar um intervalo contíguo sem CSV.",
    ),
    inicio: Optional[int] = typer.Option(
        None, "-i", "--inicio",
        help="[modo intervalo] Primeiro processo do intervalo (inclusivo).",
    ),
    fim: Optional[int] = typer.Option(
        None, "-f", "--fim",
        help="[modo intervalo] Último processo do intervalo (inclusivo).",
    ),
    csv: Optional[Path] = typer.Option(
        None, "--csv",
        help="[modo CSV] Arquivo com colunas 'classe,processo' (ou 'processo_id'). "
             "Cada linha é um alvo a processar.",
    ),
    retentar_de: Optional[Path] = typer.Option(
        None, "--retentar-de",
        help="[modo nova tentativa] Caminho para um executar.errors.jsonl "
             "existente; executa novamente apenas os pares (classe, processo) "
             "com falha transitória.",
    ),
    rotulo: Optional[str] = typer.Option(
        None, "--rotulo",
        help="Rótulo curto identificando esta execução. Em modo intervalo, "
             "assume `{CLASSE}_{i}-{f}` quando omitido. Quando definido sem "
             "--saida, --saida assume `runs/active/{ts}-{rotulo}/`.",
    ),
    saida: Optional[Path] = typer.Option(
        None, "--saida",
        help="Diretório da execução. Recebe executar.state.json, "
             "executar.log.jsonl, executar.errors.jsonl, report.md. "
             "Padrão automático em modo intervalo (ou com --rotulo): "
             "runs/active/{ts}-{rotulo}/.",
    ),
    provedor: str = typer.Option(
        "pypdf", "--provedor",
        help="Extrator de texto: pypdf | tesseract | tesseract_modal | "
             "tesseract_fly | mistral | chandra | unstructured | auto. "
             "Padrão: pypdf (local, gratuito).",
    ),
    forcar: bool = typer.Option(
        False, "--forcar",
        help="Re-extrai o texto mesmo quando o sidecar já indica o mesmo "
             "provedor (ignora a verificação de cache).",
    ),
    portal_concurrencia: int = typer.Option(
        1, "--portal-concurrencia",
        help="Concorrência do pool portal (JSON do processo). IP direto: 1.",
    ),
    sistemas_concurrencia: int = typer.Option(
        1, "--sistemas-concurrencia",
        help="Concorrência do pool sistemas (bytes do PDF). IP direto: 1.",
    ),
    ocr_concurrencia: int = typer.Option(
        4, "--ocr-concurrencia",
        help="Concorrência do pool OCR. Provedores limitados por CPU: 4. "
             "Provedores limitados por API (mistral/chandra/tesseract_fly): 8+.",
    ),
    proxy_pool: Optional[Path] = typer.Option(
        None, "--proxy-pool",
        help="Arquivo simples com URLs de proxy (uma por linha). Cada "
             "handler HTTP roteia proxies de forma independente. Sem esta "
             "opção: IP direto. Obrigatório em modo fragmentado "
             "(--shards > 1).",
    ),
    shards: int = typer.Option(
        0, "--shards",
        help="Se > 1, particiona o CSV em N fragmentos e dispara N "
             "processos paralelos (um por fragmento). Cada fragmento "
             "recebe sua fatia round-robin do --proxy-pool. Exige --csv "
             "(ou intervalo), --rotulo e --proxy-pool.",
    ),
    estrategia_shard: str = typer.Option(
        "interleave", "--estrategia-shard",
        help="Particionamento do CSV em modo fragmentado. 'interleave' "
             "(padrão) ou 'range'.",
    ),
    prever: bool = typer.Option(
        False, "--prever",
        help="Mostra previsão de custo e tempo (varrer + baixar + extrair) "
             "e encerra, sem materializar nada além do CSV temporário.",
    ),
    nao_perguntar: bool = typer.Option(
        False, "--nao-perguntar",
        help="Pula o prompt de confirmação após o painel de custo. "
             "Necessário para uso não-interativo (cron, nohup).",
    ),
    detach: bool = typer.Option(
        False, "--detach", "-d",
        help="Roda em background: re-executa este mesmo comando como "
             "filho num novo grupo de sessão, redireciona stdout/stderr "
             "para ``<saida>/launcher.log``, imprime PID + log e sai 0. "
             "Substitui o ritual ``setsid nohup … & disown``.",
    ),
) -> None:
    """Inicia uma Coleta: metadados + peças + texto de um intervalo (ou CSV) de processos.

    Cada Coleta produz um diretório de run com log, estado e relatório
    consolidado. Três modos de entrada (mutuamente exclusivos):

      - intervalo:  ``-c HC -i 250000 -f 250100``
      - CSV:        ``--csv alvos.csv``
      - retomada:   ``--retentar-de runs/.../executar.errors.jsonl``

    Retomada é automática — re-rodar com o mesmo ``--saida`` pula o
    trabalho já concluído e processa só o que falta. SIGTERM/SIGINT
    encerram de forma limpa, deixando o estado retomável em disco
    (use ``judex parar`` para encerrar, ``judex retomar`` para continuar).
    """
    # ----- Mode resolution -----
    range_flags = [
        f for f, v in
        [("-c", classe), ("-i", inicio), ("-f", fim)]
        if v is not None
    ]
    range_mode = len(range_flags) > 0
    if range_mode and len(range_flags) != 3:
        raise typer.BadParameter(
            "Modo range exige os três: -c (classe), -i (inicial), -f (final). "
            f"Faltou: {[f for f in ('-c', '-i', '-f') if f not in range_flags]}."
        )

    n_modes = int(range_mode) + int(csv is not None) + int(retentar_de is not None)
    if n_modes == 0:
        raise typer.BadParameter(
            "Escolha um modo de entrada: range (-c/-i/-f), --csv, ou --retentar-de."
        )
    if n_modes > 1:
        raise typer.BadParameter(
            "Modos de entrada mutuamente exclusivos: escolha apenas um "
            "entre range (-c/-i/-f), --csv, ou --retentar-de."
        )

    # ----- Auto-default rotulo + --saida (hoisted so --detach can fire
    # before target resolution — the detached child re-enters and
    # re-derives targets itself) -----
    if range_mode and rotulo is None:
        assert classe is not None and inicio is not None and fim is not None
        rotulo = f"{classe.upper()}_{inicio}-{fim}"

    if saida is None:
        if rotulo is None:
            raise typer.BadParameter(
                "--saida é obrigatório quando nem --rotulo nem modo range "
                "estão setados (sem rótulo não há nome para o auto-saida)."
            )
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        saida = Path("runs/active") / f"{ts}-{rotulo}"
        typer.echo(f"--saida não fornecido; usando padrão automático {saida}")

    # ----- --detach: re-exec self in a new session, exit parent -----
    if detach:
        # Strip --detach + force --nao-perguntar in the child: a detached
        # parent can't answer a confirmation prompt. The child re-enters
        # this same function with detach=False and falls through to the
        # normal in-process run.
        saida.mkdir(parents=True, exist_ok=True)
        log_path = saida / "launcher.log"
        child_argv = [a for a in sys.argv if a not in ("--detach", "-d")]
        if "--nao-perguntar" not in child_argv:
            child_argv.append("--nao-perguntar")
        with log_path.open("w", encoding="utf-8") as log_f:
            child = subprocess.Popen(
                child_argv,
                stdin=subprocess.DEVNULL,
                stdout=log_f,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        # Poll briefly for the child to write its pid file — that's the
        # PID the operator wants (the inner judex process), not the
        # outer ``uv run`` shim which may be a different pid.
        import time as _time
        pid_path = saida / "executar.pid"
        deadline = _time.monotonic() + 5.0
        while _time.monotonic() < deadline:
            if pid_path.exists():
                break
            if child.poll() is not None:
                # Child died before writing the pid file.
                typer.echo(
                    f"erro: filho saiu cedo (rc={child.returncode}). "
                    f"Veja {log_path}.",
                    err=True,
                )
                raise typer.Exit(code=1)
            _time.sleep(0.1)
        if pid_path.exists():
            inner_pid = pid_path.read_text(encoding="utf-8").strip()
        else:
            inner_pid = f"~{child.pid} (filho não escreveu executar.pid em 5s)"
        typer.echo(f"pid: {inner_pid}")
        typer.echo(f"log: {log_path}")
        typer.echo(f"saida: {saida}")
        typer.echo(f"parar: judex parar {saida}")
        raise typer.Exit(code=0)

    # ----- Build the (classe, processo) target list -----
    from judex.pipeline.runner import (
        read_targets_csv,
        run_pipeline,
        targets_from_errors_jsonl,
        targets_from_range,
    )

    if range_mode:
        assert classe is not None and inicio is not None and fim is not None
        validate_stf_case_type(classe)
        validate_process_range(inicio, fim)
        targets = targets_from_range(classe, inicio, fim)
    elif csv is not None:
        targets = read_targets_csv(csv)
    else:
        assert retentar_de is not None
        targets = targets_from_errors_jsonl(retentar_de)

    if not targets:
        typer.echo("ERROR: nenhum alvo resolvido pelos parâmetros dados.", err=True)
        raise typer.Exit(code=2)

    # ----- --prever: forecast + early-exit -----
    if prever:
        _print_executar_forecast(
            n_targets=len(targets),
            provedor=provedor,
            shards=shards,
        )
        raise typer.Exit(code=0)

    # ----- Cost banner + confirmation prompt (skipped under --nao-perguntar) -----
    if not nao_perguntar:
        _print_executar_forecast(
            n_targets=len(targets),
            provedor=provedor,
            shards=shards,
        )
        if not typer.confirm(
            f"Confirmar execução de {len(targets)} alvo(s) em {saida}?",
            default=True,
        ):
            typer.echo("Abortado pelo usuário.")
            raise typer.Exit(code=2)

    # ----- Sharded mode: partition + spawn N detached children -----
    if shards > 1:
        if proxy_pool is None:
            raise typer.BadParameter(
                "--shards > 1 exige --proxy-pool (round-robin entre os shards)."
            )
        if rotulo is None:
            raise typer.BadParameter(
                "--shards > 1 exige --rotulo (cada shard carrega "
                "`<rotulo>_shard_<letra>` para pgrep)."
            )

        # Materialize the resolved targets as a CSV the launcher can
        # partition. Even in retentar-de mode we write a fresh CSV so
        # each shard sees a stable, shareable input file.
        saida.mkdir(parents=True, exist_ok=True)
        shard_input_csv = saida / "input.csv"
        with shard_input_csv.open("w", encoding="utf-8", newline="") as fp:
            w = _csv.writer(fp)
            w.writerow(["classe", "processo"])
            for c, p in targets:
                w.writerow([c, p])

        from judex.sweeps.shard_launcher import launch_sharded

        extra: list[str] = ["--nao-perguntar"]
        _push(extra, "--provedor", provedor)
        _push(extra, "--portal-concurrencia", portal_concurrencia)
        _push(extra, "--sistemas-concurrencia", sistemas_concurrencia)
        _push(extra, "--ocr-concurrencia", ocr_concurrencia)
        _push(extra, "--forcar", forcar)

        if estrategia_shard not in ("interleave", "range"):
            raise typer.BadParameter(
                f"--estrategia-shard inválida: {estrategia_shard!r}. "
                "Use 'interleave' ou 'range'."
            )
        try:
            pids_path = launch_sharded(
                command="executar",
                csv_path=shard_input_csv,
                shards=shards,
                proxy_pool=proxy_pool,
                saida_root=saida,
                label_prefix=rotulo,
                extra_args=extra,
                strategy=estrategia_shard,  # type: ignore[arg-type]
            )
        except ValueError as e:
            raise typer.BadParameter(str(e))

        typer.echo(f"Lançou {shards} shards em background.")
        typer.echo(f"  PIDs:   {pids_path}")
        typer.echo(f"  Watch:  pgrep -af {rotulo}_shard_")
        typer.echo(f"  Stop:   xargs -a {pids_path} kill -TERM")
        raise typer.Exit(code=0)

    # ----- Mono mode: run in-process -----
    rc = run_pipeline(
        targets=targets,
        saida=saida,
        provedor=provedor,
        portal_concurrencia=portal_concurrencia,
        sistemas_concurrencia=sistemas_concurrencia,
        ocr_concurrencia=ocr_concurrencia,
        proxy_pool=proxy_pool,
        forcar=forcar,
        # Captured into ``executar.state.json`` so ``judex retomar``
        # can rebuild the operator's first command on resume.
        original_args=_executar_kwargs_for_state(
            classe=classe, inicio=inicio, fim=fim,
            csv=csv, retentar_de=retentar_de,
            rotulo=rotulo, provedor=provedor, forcar=forcar,
            portal_concurrencia=portal_concurrencia,
            sistemas_concurrencia=sistemas_concurrencia,
            ocr_concurrencia=ocr_concurrencia,
            proxy_pool=proxy_pool,
        ),
    )
    raise typer.Exit(code=rc)


def _print_executar_forecast(
    *, n_targets: int, provedor: str, shards: int,
) -> None:
    """Print a combined varrer+baixar+extrair forecast for executar.

    The unified pipeline runs all three legacy stages in one process,
    so the operator-facing forecast is the *sum* of their walls + costs.
    Wall is approximate — pipelining overlaps stages — but the cost is
    exact (every byte downloaded + every page OCR'd is the same as
    legacy). Anchored constants live in ``judex/utils/cost.py``.
    """
    from judex.utils.cost import (
        forecast_baixar_pecas,
        forecast_extrair_pecas,
        forecast_varrer_processos,
        render_forecast_table,
    )

    # The unified pipeline has roughly 1.33 substantive peças per case
    # (CLAUDE.md anchor for the HC corpus); use that as the
    # case→peça multiplier when pricing the bytes + extract sides.
    n_pecas = max(1, int(n_targets * 1.33))

    typer.echo(f"\n=== Previsão executar — {n_targets:,} cases / ~{n_pecas:,} peças ===\n")

    typer.echo(render_forecast_table(
        forecast_varrer_processos(n_targets),
        n_units=n_targets, unit_label="cases (varrer)",
    ))
    typer.echo(render_forecast_table(
        forecast_baixar_pecas(n_pecas),
        n_units=n_pecas, unit_label="peças (baixar)",
    ))
    typer.echo(render_forecast_table(
        forecast_extrair_pecas(n_pecas, provedor),
        n_units=n_pecas, unit_label=f"peças (extrair via {provedor})",
    ))
    if shards > 1:
        typer.echo(
            f"\nNota: --shards {shards} aplica o speedup de proxy "
            "(linha '16 shards + proxy' acima); custo de proxy é "
            "varrer+baixar; OCR não é afetado por sharding (não passa pelo WAF).\n"
        )


# ---------------------------------------------------------------------------
# `listar` — descobre quais Coletas existem (e quais estão vivas).
# Placed before the Manutenção do corpus block so its ``Observação``
# rich_help_panel registers earlier than ``Manutenção do corpus`` —
# Typer/rich orders panels by first-occurrence in source.


@app.command(name="listar", rich_help_panel="Observação")
def listar(
    root: Path = typer.Option(
        Path("runs/active"), "--root",
        help="Diretório-raiz para varrer. Padrão: runs/active/.",
    ),
    incluir_arquivo: bool = typer.Option(
        False, "--incluir-arquivo",
        help="Também varre runs/archive/ — útil para 'onde foi parar o "
             "run da semana passada?'.",
    ),
    apenas: Optional[str] = typer.Option(
        None, "--apenas",
        help="Filtra por status: running | stale | finished | unknown.",
    ),
    podar_pids: bool = typer.Option(
        False, "--podar-pids",
        help="Apaga executar.pid / shards.pids de runs em status `stale` "
             "(resíduo de SIGKILL — `parar` não consegue limpar sozinho).",
    ),
    json_out: bool = typer.Option(
        False, "--json",
        help="Saída JSON (uma linha por run) em vez de tabela.",
    ),
) -> None:
    """Lista Coletas em runs/active/ com status (running/stale/finished/unknown).

    Lê o pid file (``executar.pid`` / ``shards.pids``) para liveness e o
    snapshot ``executar.state.json`` para rótulo, timestamps e contagem
    de alvos. Não grepa logs.

    ``--apenas running`` é o filtro de uso mais comum (responde "o que
    está rodando agora?"). ``--podar-pids`` é o cleanup pareado com o
    estado ``stale`` — sem ele, ``parar`` no diretório fica no-op
    porque o PID listado já não existe. ``--incluir-arquivo`` extende a
    varredura para ``runs/archive/``.
    """
    from judex.pipeline.run_index import (
        RunStatus,
        format_elapsed,
        list_runs as _list_runs,
        prune_stale_pid_files,
    )

    if podar_pids:
        removed = prune_stale_pid_files(root)
        for p in removed:
            typer.echo(f"removed: {p}")
        typer.echo(f"podou {len(removed)} pid file(s) stale.")
        return

    summaries = _list_runs(root, include_archive=incluir_arquivo)

    if apenas:
        try:
            wanted = RunStatus(apenas)
        except ValueError:
            raise typer.BadParameter(
                f"--apenas={apenas!r} inválido. Use: "
                f"{', '.join(s.value for s in RunStatus)}."
            )
        summaries = [s for s in summaries if s.status == wanted]

    if json_out:
        import json as _json
        for s in summaries:
            typer.echo(_json.dumps({
                "saida": str(s.saida),
                "status": s.status.value,
                "pids": s.pids,
                "rotulo": s.rotulo,
                "classe": s.classe,
                "started_at": s.started_at,
                "snapshot_at": s.snapshot_at,
                "elapsed_seconds": s.elapsed_seconds(),
                "n_targets": s.n_targets,
            }))
        return

    if not summaries:
        scope = (
            f"{root} e runs/archive/" if incluir_arquivo else str(root)
        )
        typer.echo(f"(nenhuma Coleta em {scope})")
        return

    from rich.console import Console
    from rich.table import Table

    status_style = {
        RunStatus.RUNNING: "green",
        RunStatus.STALE: "yellow",
        RunStatus.FINISHED: "dim",
        RunStatus.UNKNOWN: "red",
    }

    table = Table(show_header=True, header_style="bold")
    table.add_column("saida")
    table.add_column("status")
    table.add_column("classe")
    table.add_column("rotulo")
    table.add_column("alvos", justify="right")
    table.add_column("duração", justify="right")
    table.add_column("pids")

    for s in summaries:
        table.add_row(
            s.saida.name,
            f"[{status_style[s.status]}]{s.status.value}[/]",
            s.classe or "—",
            s.rotulo or "—",
            str(s.n_targets) if s.n_targets is not None else "—",
            format_elapsed(s.elapsed_seconds()),
            ",".join(str(p) for p in s.pids) or "—",
        )
    Console().print(table)


# ---------------------------------------------------------------------------
# `atualizar` — varre os processos novos até o leading edge atual da STF


@app.command(name="atualizar", rich_help_panel="Manutenção do corpus")
def atualizar_corpus(
    classe: str = typer.Argument(
        ...,
        help="Classe a varrer (HC, ADI, ADPF, RE, …). Obrigatório — "
             "não há padrão; cada classe tem uma fronteira de avanço "
             "(leading edge) própria.",
    ),
    paradas_apos_misses: int = typer.Option(
        20, "--paradas-apos-misses",
        help="Quantos case-ids não-alocados consecutivos param a "
             "sondagem. STF tem buracos legítimos de 1-3 IDs no meio "
             "de cada classe; 20 IDs vazios contíguos é sinal forte de "
             "ter passado o leading edge.",
    ),
    max_probes: int = typer.Option(
        2000, "--max-probes",
        help="Cap de segurança: nunca probar mais que isto. "
             "2000 IDs = ~25-30 dias de HC.",
    ),
    saida: Optional[Path] = typer.Option(
        None, "--saida",
        help="Run dir; padrão runs/active/<classe>-atualizar-YYYYMMDD/.",
    ),
    provedor_ocr: str = typer.Option(
        "auto", "--provedor-ocr",
        help="Provedor OCR (padrão ``auto`` = roteamento pypdf↔tesseract_fly).",
    ),
    portal_concurrencia: int = typer.Option(
        1, "--portal-concurrencia",
        help="Concorrência do pool portal. IP direto: 1.",
    ),
    sistemas_concurrencia: int = typer.Option(
        1, "--sistemas-concurrencia",
        help="Concorrência do pool sistemas. IP direto: 1.",
    ),
    ocr_concurrencia: int = typer.Option(
        4, "--ocr-concurrencia",
        help="Concorrência do pool OCR.",
    ),
) -> None:
    """Adiciona ao corpus os processos novos publicados pela STF para uma classe.

    Pega o último processo_id já raspado em ``data/source/processos/<classe>/``,
    sonda processos mais recentes pelo portal, e raspa só os que aparecerem
    como vivos. Comando idempotente — re-rodar pula o que já está em disco.

    Exemplos:

        uv run judex atualizar HC
        uv run judex atualizar ADI --paradas-apos-misses 50
    """
    from datetime import datetime
    from judex.config import ScraperConfig
    from judex.pipeline.runner import run_pipeline
    from judex.scraping.http_session import new_session
    from judex.scraping.scraper import resolve_incidente
    from judex.sweeps.discovery import discover_new_numeros

    source_dir = Path(f"data/source/processos/{classe}")
    if not source_dir.exists():
        typer.echo(
            f"erro: nada em {source_dir} — primeira passada precisa de "
            f"um intervalo manual via ``judex executar -c {classe} -i N -f M``.",
            err=True,
        )
        raise typer.Exit(2)

    max_id = 0
    for f in source_dir.glob(f"judex-mini_{classe}_*.json"):
        try:
            n = int(f.stem.split("_")[-1].split("-")[-1])
            if n > max_id:
                max_id = n
        except (ValueError, IndexError):
            continue

    if max_id == 0:
        typer.echo(
            f"erro: nenhum {classe} válido em {source_dir}.", err=True,
        )
        raise typer.Exit(2)

    typer.echo(f"max em disco: {classe} {max_id}")
    typer.echo(
        f"sondando até hit {paradas_apos_misses} IDs vazios contíguos…"
    )

    session = new_session()
    config = ScraperConfig()

    def resolver(c: str, n: int) -> int:
        return resolve_incidente(session, c, n, config=config)

    discovered = discover_new_numeros(
        classe,
        start=max_id,
        resolver=resolver,
        stop_after_misses=paradas_apos_misses,
        max_probes=max_probes,
    )

    if not discovered:
        typer.echo(
            f"nenhum {classe} novo desde {max_id} — corpus está atualizado."
        )
        raise typer.Exit(0)

    max_new = discovered[-1].numero
    typer.echo(
        f"descobertos: {len(discovered)} novos ({classe} {max_id+1}-{max_new})"
    )

    if saida is None:
        date_str = datetime.now().strftime("%Y%m%d")
        saida = Path(f"runs/active/{classe.lower()}-atualizar-{date_str}")

    typer.echo(f"saída: {saida}\n")

    targets = [(classe, d.numero) for d in discovered]

    rc = run_pipeline(
        targets=targets,
        saida=saida,
        provedor=provedor_ocr,
        portal_concurrencia=portal_concurrencia,
        sistemas_concurrencia=sistemas_concurrencia,
        ocr_concurrencia=ocr_concurrencia,
    )
    raise typer.Exit(code=rc)


# ---------------------------------------------------------------------------
# `warehouse` — reconstrói o DuckDB derivado dos JSONs + cache de texto.
# (anteriormente ``atualizar-warehouse``; ver alias deprecado abaixo).


def _run_warehouse(
    diretorio_processos: Path,
    diretorio_pecas_texto: Path,
    saida: Path,
    classe: Optional[list[str]],
    ano: Optional[int],
    progresso_cada: int,
    estrito: bool,
    runs_root: Optional[Path] = None,
    bytes_root: Optional[Path] = None,
) -> int:
    """Shared body for the canonical ``warehouse`` command and its
    deprecated ``atualizar-warehouse`` alias. Returns the exit code from
    :func:`judex.sweeps.build_warehouse.run_build_warehouse`.

    When ``runs_root`` is non-None and exists, the build also populates
    the ``peca_issues`` cross-run registry. Default ``None`` keeps the
    deprecated alias (and tests) on the lighter pre-registry build path.
    """
    from judex.sweeps.build_warehouse import run_build_warehouse

    effective_runs_root = (
        runs_root if (runs_root is not None and runs_root.exists()) else None
    )
    return run_build_warehouse(
        cases_root=diretorio_processos,
        pecas_texto_root=diretorio_pecas_texto,
        output=saida,
        classe=classe,
        year=ano,
        progress_every=progresso_cada,
        strict=estrito,
        runs_root=effective_runs_root,
        bytes_root=bytes_root,
    )


@app.command(name="warehouse", rich_help_panel="Manutenção do corpus")
def warehouse(
    diretorio_processos: Path = typer.Option(
        Path("data/source/processos"), "--diretorio-processos",
        help="Raiz dos JSONs de processo (particionados por classe).",
    ),
    diretorio_pecas_texto: Path = typer.Option(
        Path("data/derived/pecas-texto"), "--diretorio-pecas-texto",
        help="Cache de texto extraído (.txt.gz / .elements.json.gz / .extractor).",
    ),
    saida: Path = typer.Option(
        Path("data/derived/warehouse/judex.duckdb"), "--saida",
        help="Caminho do arquivo .duckdb de saída (swap atômico).",
    ),
    classe: Optional[list[str]] = typer.Option(
        None, "--classe",
        help="Restringe a ingestão a uma ou mais classes (repita p/ várias).",
    ),
    ano: Optional[int] = typer.Option(
        None, "--ano",
        help="Filtra para um ano de HC via hc_calendar (exige --classe HC).",
    ),
    progresso_cada: int = typer.Option(
        10_000, "--progresso-cada",
        help="Frequência (em processos) das linhas de progresso no stdout.",
    ),
    estrito: bool = typer.Option(
        False, "--estrito",
        help="Sai com código ≠ 0 se alguma taxa de população de campo "
             "(partes, andamentos, pautas, sessao_virtual, publicacoes_dje) "
             "cair abaixo do limiar esperado — usado em CI para pegar "
             "regressões silenciosas do scraper. O arquivo .duckdb ainda "
             "é gravado para inspeção manual; só o exit code muda.",
    ),
    runs_root: Path = typer.Option(
        Path("runs"), "--runs-root",
        help="Raiz dos run dirs. Walked para popular as três registries "
             "transversais (``peca_issues`` per-URL, ``case_issues`` per-"
             "case, ``unallocated_pids``). Default ``runs/`` cobre tanto "
             "``active/`` quanto ``archive/``. Se a pasta não existe, as "
             "tabelas ficam vazias — não é erro.",
    ),
    bytes_root: Path = typer.Option(
        Path("data/raw/pecas"), "--bytes-root",
        help="Raiz dos bytes-cache (``.pdf.gz``). Snapshotada em "
             "``disk_bytes`` e usada pelas views ``missing_bytes`` / "
             "``orphan_cache_files``. Se a pasta não existe, as views "
             "ficam vazias — não é erro.",
    ),
) -> None:
    """Reconstrói o banco DuckDB a partir dos dados raspados.

    Usado para análise em SQL ou nos notebooks em ``analysis/``. Rebuild
    completo com swap atômico — não há modo incremental. Não fala com a
    rede; é puro scan local. Custo típico: ~2-3 min para 55 k processos,
    ~15-20 min para 350 k.

    Rode depois de ``executar`` para refletir os dados novos.
    """
    raise typer.Exit(code=_run_warehouse(
        diretorio_processos, diretorio_pecas_texto, saida,
        classe, ano, progresso_cada, estrito,
        runs_root=runs_root,
        bytes_root=bytes_root,
    ))


@app.command(name="atualizar-warehouse", hidden=True, rich_help_panel="Manutenção do corpus")
def atualizar_warehouse(
    diretorio_processos: Path = typer.Option(
        Path("data/source/processos"), "--diretorio-processos",
    ),
    diretorio_pecas_texto: Path = typer.Option(
        Path("data/derived/pecas-texto"), "--diretorio-pecas-texto",
    ),
    saida: Path = typer.Option(
        Path("data/derived/warehouse/judex.duckdb"), "--saida",
    ),
    classe: Optional[list[str]] = typer.Option(None, "--classe"),
    ano: Optional[int] = typer.Option(None, "--ano"),
    progresso_cada: int = typer.Option(10_000, "--progresso-cada"),
    estrito: bool = typer.Option(False, "--estrito"),
) -> None:
    """[DEPRECADO] Use ``judex warehouse``. Mantido como alias enquanto
    scripts antigos (chains, jobs) usam o nome anterior."""
    import sys
    print(
        "[deprecation] use `judex warehouse` — `atualizar-warehouse` "
        "is a transition alias and will be removed",
        file=sys.stderr,
    )
    raise typer.Exit(code=_run_warehouse(
        diretorio_processos, diretorio_pecas_texto, saida,
        classe, ano, progresso_cada, estrito,
        runs_root=Path("runs"),
        bytes_root=Path("data/raw/pecas"),
    ))


# ---------------------------------------------------------------------------
# `re-extrair` — URL-scoped re-extraction (no fetch, no case-walker)


@app.command(name="re-extrair", rich_help_panel="Peças individuais")
def re_extrair_cmd(
    arquivo_urls: Path = typer.Argument(
        ..., exists=True, dir_okay=False, readable=True,
        help="Arquivo simples com uma URL por linha. Linhas em branco e "
             "comentários (#) são ignoradas.",
    ),
    provedor: str = typer.Option(
        "tesseract", "--provedor",
        help="Provedor de OCR: pypdf | tesseract | tesseract_modal | "
             "tesseract_fly | mistral | chandra | unstructured.",
    ),
    forcar: bool = typer.Option(
        False, "--forcar",
        help="Re-extrai mesmo quando o sidecar já indica o mesmo provedor "
             "(ignora a verificação de cache).",
    ),
) -> None:
    """Re-extrai o texto de peças específicas com o provedor escolhido.

    O alvo é uma lista de URLs (uma por linha). Para cada URL, lê os
    bytes do cache de peças, roda o provedor de novo, e regrava o texto.
    Não fala com a STF — os bytes precisam já estar em cache (rode
    ``judex executar`` antes); URLs sem bytes em cache contam para
    ``missing_bytes`` no relatório.

    Caso de uso típico: re-OCR pontual de peças que estouraram o cap de
    body do OCR em cloud, com ``--provedor tesseract`` local — sem
    re-extrair as outras peças do mesmo processo.
    """
    from judex.sweeps.re_extrair import run_re_extrair

    result = run_re_extrair(arquivo_urls, provedor=provedor, forcar=forcar)
    typer.echo(
        f"re-extrair: ok={result.n_ok} · skipped={result.n_skipped} · "
        f"missing_bytes={result.n_missing_bytes} · fail={result.n_fail} · "
        f"wall={result.wall_s:.1f}s"
    )
    if result.n_fail > 0:
        raise typer.Exit(code=1)


# ---------------------------------------------------------------------------
# `peca-spot-check` — sample peças from the warehouse for quality inspection


@app.command(name="peca-spot-check", rich_help_panel="Peças individuais")
def peca_spot_check_cmd(
    classe: Optional[str] = typer.Option(
        None, "--classe",
        help="Filtra para uma classe processual (HC, ADI, RE, …).",
    ),
    ano: Optional[int] = typer.Option(
        None, "--ano",
        help="Filtra para um ano de protocolo do processo.",
    ),
    doc_type: Optional[str] = typer.Option(
        None, "--doc-type",
        help='Filtra por tipo de peça (ex.: "DECISÃO MONOCRÁTICA", "VOTO").',
    ),
    n: int = typer.Option(
        10, "-n", "--n",
        help="Quantas peças amostrar (padrão 10).",
    ),
    seed: Optional[int] = typer.Option(
        None, "--seed",
        help="Fixa a aleatoriedade — mesma seed re-produz a mesma amostra.",
    ),
) -> None:
    """Amostra N peças do warehouse e mostra o texto extraído.

    Usado para auditar qualidade da extração — cada amostra exibe
    classe, processo, tipo, contagem de chars e um preview. Peças
    suspeitas-curtas (provavelmente falha silenciosa do pypdf — chars
    > 0 mas só com cabeçalho) são marcadas com ⚠.

    Pré-requisito: o warehouse precisa estar construído (``judex
    warehouse``).
    """
    from judex.analysis.peca_spot_check import render_samples, sample_pecas
    from judex.warehouse.query import open_readonly

    con = open_readonly()
    samples = sample_pecas(
        con, classe=classe, year=ano, doc_type=doc_type, n=n, seed=seed,
    )
    typer.echo(render_samples(samples), nl=False)


# ---------------------------------------------------------------------------
# `peca-dismiss` / `peca-undismiss` — operator-set "stop retrying this URL"


@app.command(name="peca-dismiss", rich_help_panel="Peças individuais")
def peca_dismiss_cmd(
    url: str = typer.Argument(..., help="URL da peça a dispensar."),
    motivo: str = typer.Option(
        ..., "--motivo",
        help="Razão legível para a dispensa (ex.: 'PDF retirado da STF', "
             "'OCR pesado pra valer a pena', 'duplicata de <X>').",
    ),
) -> None:
    """Marca uma URL como conhecida-quebrada para parar de tentar.

    URLs dispensadas são silenciosamente puladas pelo ``judex recuperar``
    e não consomem orçamento de retry. Persiste em
    ``data/derived/pecas-texto/<sha1>.dismissed.json`` (atravessa
    rebuilds do warehouse).
    """
    from judex.utils import peca_cache
    peca_cache.write_dismissal(url, reason=motivo)
    typer.echo(f"dispensada: {url}")
    typer.echo(f"  motivo: {motivo}")


@app.command(name="peca-undismiss", rich_help_panel="Peças individuais")
def peca_undismiss_cmd(
    url: str = typer.Argument(..., help="URL da peça a re-habilitar."),
) -> None:
    """Remove a marca de dispensa de uma URL — volta a entrar no retry."""
    from judex.utils import peca_cache
    cleared = peca_cache.clear_dismissal(url)
    if cleared:
        typer.echo(f"re-habilitada: {url}")
    else:
        typer.echo(f"nada a fazer (não estava dispensada): {url}")


# ---------------------------------------------------------------------------
# `providers` — comparison table built from each OCR provider's SPEC


@debug_app.command(name="providers")
def providers_cmd(
    n_pdfs: int = typer.Option(
        1, "--pdfs",
        help="Workload size in PDFs for the wall-time column. "
             "Defaults to 1 (per-PDF view).",
    ),
    n_pages: int = typer.Option(
        5, "--pages",
        help="Workload size in pages for the cost column. Defaults "
             "to 5 (rough average page count per peça).",
    ),
    batch: bool = typer.Option(
        False, "--batch/--no-batch",
        help="Use batch pricing where the provider supports it "
             "(Mistral, Gemini). Default off — batch wall reflects "
             "submission time, not the ~24h turnaround, so default-on "
             "is misleading. Pass --batch to see batch cost (with the "
             "wall caveat).",
    ),
) -> None:
    """Compara custo e velocidade dos provedores de OCR para um volume.

    Mostra uma tabela ordenada por custo, com USD por mil páginas e
    wall estimado para o volume informado. Provedores sem âncora de
    wall medida exibem ``—``.
    """
    from judex.scraping.ocr.dispatch import render_provider_table
    typer.echo(render_provider_table(
        n_pdfs=n_pdfs, n_pages=n_pages, batch_ok=batch,
    ))


# ---------------------------------------------------------------------------
# `acompanhar` — tail unificado mono + sharded com auto-encerramento


@app.command(name="acompanhar", rich_help_panel="Observação")
def acompanhar(
    run_dir: Optional[Path] = typer.Argument(
        None,
        help="Diretório do run. Sem argumento, usa o mais recente em "
             "runs/active/ por mtime. Auto-detecta layout: sharded "
             "(shard-*/driver.log) ou monolítico (driver.log / "
             "launcher.log no topo).",
    ),
    n: int = typer.Option(
        20, "-n",
        help="Linhas iniciais antes do follow.",
    ),
    agg_interval: float = typer.Option(
        30.0, "--agg-interval",
        help="Intervalo (segundos) entre as linhas agregadas "
             "``─── … ───`` (sharded) e entre as checagens de "
             "fim-de-run (mono e sharded).",
    ),
    persistir: bool = typer.Option(
        False, "--persistir",
        help="Continua tailando após todos os shards terem registrado "
             "``executar: done`` (comportamento legado). Padrão é "
             "encerrar com um ``relatar`` consolidado.",
    ),
) -> None:
    """Acompanha uma Coleta ao vivo e mostra o relatório final quando termina.

    Detecta automaticamente o fim da Coleta e imprime um resumo
    consolidado (mesmo formato de ``judex relatar``). Em Coletas
    paralelizadas (shards), agrega o progresso dos vários shards em
    uma linha por intervalo — sem 16 logs idênticos disputando a tela.
    Use ``--persistir`` para continuar acompanhando em vez de encerrar.
    """
    run_dir = _resolve_run_dir(run_dir)
    from scripts.follow_run import run_follow
    raise typer.Exit(code=run_follow(
        run_dir, n=n, agg_interval=agg_interval, persistir=persistir,
    ))


# ---------------------------------------------------------------------------
# `parar` — encerra de forma limpa uma Coleta em curso


@app.command(name="parar", rich_help_panel="Coleta")
def parar(
    saida: Optional[Path] = typer.Argument(
        None,
        help="Diretório do run ou rótulo. Sem argumento, usa o run mais "
             "recente em runs/active/ por mtime.",
        autocompletion=_complete_run_label,
    ),
    timeout: float = typer.Option(
        30.0, "--timeout", "-t",
        help="Segundos para esperar SIGTERM ser respeitado antes de "
             "reportar processo travado.",
    ),
    forcar: bool = typer.Option(
        False, "--forcar", "-f",
        help="Escalar para SIGKILL após --timeout. Padrão: reporta e "
             "sai com código 1 sem forçar.",
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run",
        help="Mostra os PIDs que seriam encerrados, mas não envia sinal. "
             "Sai com código 0. Útil antes de matar 16 shards de uma vez.",
    ),
) -> None:
    """Encerra de forma limpa uma Coleta em curso (``judex executar`` rodando).

    Lê ``<saida>/executar.pid`` (mono) ou ``<saida>/shards.pids``
    (fragmentado), envia SIGTERM, e aguarda cada processo encerrar até
    o ``--timeout``. Com ``--forcar``, escalona para SIGKILL após o
    timeout. O diário de estado (ADR-0006) garante que SIGTERM no meio
    de uma Coleta deixa o estado retomável em disco — re-rodar
    ``judex executar`` no mesmo ``--saida`` (ou ``judex retomar
    <saida>``) continua de onde parou.
    """
    import signal
    import time

    saida = _resolve_run_dir(saida)

    pids = _read_pids(saida)
    if not pids:
        typer.echo(
            f"erro: nem executar.pid nem shards.pids em {saida}. "
            "Coleta já encerrou (limpamente)? Veja `judex relatar {saida}`.",
            err=True,
        )
        raise typer.Exit(code=2)

    if dry_run:
        typer.echo(f"(dry-run) SIGTERM -> {pids}")
        typer.echo("(dry-run) nada foi enviado. Re-rode sem --dry-run para encerrar.")
        raise typer.Exit(code=0)

    typer.echo(f"SIGTERM -> {pids}")
    alive = []
    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
            alive.append(pid)
        except ProcessLookupError:
            typer.echo(f"  pid {pid} já não existe; pulando")

    deadline = time.monotonic() + timeout
    while alive and time.monotonic() < deadline:
        alive = [p for p in alive if _is_pid_alive(p)]
        if alive:
            time.sleep(1.0)

    if not alive:
        typer.echo(f"OK: {len(pids)} processo(s) encerraram em <{timeout:.0f}s.")
        raise typer.Exit(code=0)

    if forcar:
        typer.echo(f"SIGKILL -> {alive} (após {timeout:.0f}s sem encerrar)")
        for p in alive:
            try:
                os.kill(p, signal.SIGKILL)
            except ProcessLookupError:
                pass
        raise typer.Exit(code=0)

    typer.echo(
        f"erro: {alive} ainda vivo(s) após {timeout:.0f}s. "
        "Use --forcar para SIGKILL.",
        err=True,
    )
    raise typer.Exit(code=1)


# ---------------------------------------------------------------------------
# `retomar` — re-dispatch executar with the original args


@app.command(name="retomar", rich_help_panel="Coleta")
def retomar(
    saida: Optional[Path] = typer.Argument(
        None,
        help="Diretório do run. Sem argumento, usa o run mais recente "
             "em runs/active/ por mtime.",
    ),
    nao_perguntar: bool = typer.Option(
        False, "--nao-perguntar",
        help="Passa --nao-perguntar para o executar reaberto (skip "
             "do painel de custo + prompt).",
    ),
    detach: bool = typer.Option(
        False, "--detach", "-d",
        help="Passa --detach para o executar reaberto: roda em "
             "background, imprime PID + log e sai.",
    ),
) -> None:
    """Retoma uma Coleta interrompida, inferindo os argumentos originais.

    Lê o bloco ``args`` de ``<saida>/executar.state.json`` (capturado
    no primeiro ``judex executar`` contra esse ``--saida``) e despacha
    ``executar`` com a mesma argv. O operador não precisa re-digitar
    ``-c HC -i 196282 -f 210963 --saida …`` — a Coleta lembra do que
    foi.

    Falha de forma limpa se o diário de estado não tem o bloco ``args``
    (Coleta iniciada antes do suporte a ``retomar``) — nesse caso basta
    re-executar o ``executar`` original.
    """
    import json as _json

    saida = _resolve_run_dir(saida)
    state_path = saida / "executar.state.json"
    if not state_path.exists():
        typer.echo(
            f"erro: {state_path} não existe; este diretório não é uma "
            "Coleta do `judex executar`.",
            err=True,
        )
        raise typer.Exit(code=2)

    raw = _json.loads(state_path.read_text(encoding="utf-8"))
    args = raw.get("args")
    if not args:
        typer.echo(
            f"erro: {state_path} não tem o bloco `args` (Coleta iniciada "
            "antes do suporte a `retomar`). Re-execute com o `executar` "
            "original — algo como:\n"
            f"  uv run judex executar -c <CLASSE> -i <X> -f <Y> "
            f"--saida {saida} --nao-perguntar",
            err=True,
        )
        raise typer.Exit(code=2)

    argv = _build_retomar_argv(
        saida, args, nao_perguntar=nao_perguntar, detach=detach,
    )
    typer.echo(f"retomar -> judex {' '.join(argv)}")

    # Re-enter the same Typer app instead of execvp — os.execvp would
    # replace the test process during ``CliRunner.invoke``, which makes
    # this command untestable; calling ``app(argv)`` keeps the call in
    # the same Python process and lets the existing executar wrapper
    # do its own kwarg handling, prompt-skip, and run_pipeline call.
    # ``app()`` raises SystemExit per the Typer/Click convention; let
    # it propagate (the runner / shell sees the exit code).
    app(argv, standalone_mode=True)


# ---------------------------------------------------------------------------
# `relatar` — consolidação pós-run (residuals + próximos passos)


@app.command(name="relatar", rich_help_panel="Observação")
def relatar(
    run_dir: Optional[Path] = typer.Argument(
        None,
        help="Diretório do run ou rótulo. Sem argumento, usa o mais "
             "recente em runs/active/ por mtime. Funciona tanto para "
             "run em curso quanto para run finalizado.",
        autocompletion=_complete_run_label,
    ),
    json_out: bool = typer.Option(
        False, "--json",
        help="Serializa o RunSummary como JSON em vez do texto humano. "
             "Pareia com jq / dashboards.",
    ),
) -> None:
    """Resume o estado de uma Coleta num relatório consolidado.

    Mostra status, mix por Pool (processos / peças / texto),
    wall-clock, custo de OCR, lista de erros agrupados por causa, e
    próximos passos copy-paste para recuperar o que ainda dá. Funciona
    em Coleta em curso ou já finalizada — somente leitura, idempotente,
    roda em menos de 1 s.
    """
    run_dir = _resolve_run_dir(run_dir)
    from judex.sweeps.run_summary import render_summary, summarize_run
    summary = summarize_run(run_dir)
    if json_out:
        import json as _json
        from dataclasses import asdict
        payload = asdict(summary)
        # Coerce non-JSON-native fields: Path → str, Enum → its value.
        payload["run_dir"] = str(payload["run_dir"])
        payload["state"] = summary.state.value
        typer.echo(_json.dumps(payload, indent=2))
        return
    typer.echo(render_summary(summary), nl=False)


# ---------------------------------------------------------------------------
# `recuperar` — close a finished run's residual in one command


@app.command(name="recuperar", rich_help_panel="Coleta")
def recuperar(
    run_dir: Optional[Path] = typer.Argument(
        None,
        help="Diretório de um run finalizado de ``judex executar``. "
             "Sem argumento, usa o mais recente em runs/active/ por "
             "mtime. Auto-detecta layout: sharded (shard-*/) ou "
             "monolítico (executar.errors.jsonl no topo).",
    ),
    apply: bool = typer.Option(
        False, "--apply",
        help="Dispara as recuperações planejadas. Sem este flag, o comando "
             "imprime o plano (``would-recover: …``) e sai sem efeito "
             "colateral — simulação é o padrão seguro.",
    ),
    provedor: str = typer.Option(
        "auto", "--provedor",
        help="Provedor passado para os ``judex executar --retentar-de`` "
             "filhos despachados em background. Padrão ``auto`` "
             "(roteamento por tier pypdf↔OCR).",
    ),
    nao_perguntar: bool = typer.Option(
        False, "--nao-perguntar",
        help="Pula o prompt de confirmação sob ``--apply``. Necessário "
             "para invocações não-interativas (cron, nohup).",
    ),
    loop: bool = typer.Option(
        False, "--loop",
        help="Repete o ciclo (aplicar → aguardar → reclassificar) até os "
             "resíduos pararem de encolher ou ``--max-passes`` ser "
             "atingido. Bloqueia até cada passe completar — diferente "
             "do ``--apply`` simples, que despacha em background e sai.",
    ),
    max_passes: int = typer.Option(
        3, "--max-passes",
        help="Teto de passes em ``--loop`` (padrão 3). Trava de "
             "segurança para o caso patológico em que cada passe "
             "encolhe o resíduo mas a convergência demora demais.",
    ),
    poll_interval: float = typer.Option(
        5.0, "--poll-interval",
        help="Frequência (s) com que o loop verifica se os filhos "
             "detached terminaram. 5 s é razoável para Coletas de "
             "minutos; baixe para sub-segundo só em testes.",
    ),
) -> None:
    """Recupera os erros que sobraram depois de uma Coleta (``executar``).

    Classifica os erros da Coleta em buckets (transientes, cap-burnt,
    troca de provedor, refetch, terminais) e dispara as recuperações
    cabíveis: ``executar --retentar-de`` para transientes, ``re-extrair``
    para troca de provedor, ``executar --csv`` para refetch de bytes
    faltantes.

    Por padrão é dry-run — mostra o plano (``would-recover: …``) e sai.
    ``--apply`` despacha um pass detached. ``--loop`` repete até
    convergir (resíduo zera) ou estagnar (não encolhe entre passes).

    Exit codes: ``0`` = OK · ``2`` = args inválidos · ``3`` = nada a
    recuperar.
    """
    from judex.sweeps.recuperar import (
        classify_residual,
        discover_run_dirs,
        execute_recoveries,
        format_summary,
        plan_recoveries,
        run_until_stable,
    )

    run_dir = _resolve_run_dir(run_dir)
    if not run_dir.exists():
        typer.echo(f"ERROR: run_dir {run_dir} não existe.", err=True)
        raise typer.Exit(code=2)

    dirs = discover_run_dirs(run_dir)
    if not dirs:
        typer.echo(
            f"recuperar: nada a recuperar em {run_dir} "
            f"(nenhum executar.errors.jsonl encontrado)."
        )
        raise typer.Exit(code=3)

    buckets = classify_residual(dirs)
    summary = format_summary(buckets, dry_run=not (apply or loop))
    typer.echo(summary)

    if not apply and not loop:
        plan = plan_recoveries(buckets, provedor=provedor)
        if plan:
            total_replay = sum(s.n_replay_rows for s in plan)
            typer.echo(
                f"plan: would dispatch {len(plan)} child(ren) "
                f"({total_replay} replay row(s) total) under --apply."
            )
        raise typer.Exit(code=0)

    plan = plan_recoveries(buckets, provedor=provedor)
    if not plan:
        typer.echo("recuperar: nenhum bucket transiente — nada a despachar.")
        raise typer.Exit(code=0)

    if not nao_perguntar:
        prompt_label = "loop" if loop else "dispatch"
        if not typer.confirm(
            f"Confirmar {prompt_label} de {len(plan)} child(ren) detached em "
            f"{run_dir}?",
            default=True,
        ):
            typer.echo("Abortado pelo usuário.")
            raise typer.Exit(code=2)

    if loop:
        def _on_pass_start(n: int, actionable: int) -> None:
            typer.echo(f"recuperar pass {n}: {actionable} actionable rows")

        def _on_pass_end(n: int, n_dispatched: int, pids: list[int]) -> None:
            typer.echo(
                f"recuperar pass {n}: dispatched {n_dispatched} child(ren) "
                f"(PIDs: {pids}); waiting for completion…"
            )

        def _on_pass_complete(n: int, wall_s: float) -> None:
            typer.echo(
                f"recuperar pass {n}: ✓ child done in {wall_s:.1f}s"
            )

        result = run_until_stable(
            run_dir,
            provedor=provedor,
            max_passes=max_passes,
            poll_interval=poll_interval,
            on_pass_start=_on_pass_start,
            on_pass_end=_on_pass_end,
            on_pass_complete=_on_pass_complete,
        )
        final_summary = format_summary(result.final_buckets, dry_run=False)
        typer.echo(final_summary)
        if result.converged:
            typer.echo(
                f"recuperar: converged in {result.passes_run} pass(es)"
            )
        elif result.stopped_for_no_progress:
            typer.echo(
                f"recuperar: stopped after {result.passes_run} pass(es) — "
                f"residual stopped shrinking"
            )
        else:
            typer.echo(
                f"recuperar: stopped at --max-passes={max_passes} — "
                f"residual still actionable"
            )
        raise typer.Exit(code=0)

    pids_path = run_dir / "recuperar.pids"
    result = execute_recoveries(plan, pids_path)
    typer.echo(
        f"recuperar: spawned {len(result.pids)} child(ren); "
        f"PIDs em {pids_path}. Acompanhe com `judex acompanhar {run_dir}`."
    )
    raise typer.Exit(code=0)


# ---------------------------------------------------------------------------
# `arquivar` — move uma Coleta finalizada para runs/archive/


@app.command(name="arquivar", rich_help_panel="Coleta")
def arquivar(
    saida: Optional[Path] = typer.Argument(
        None,
        help="Diretório do run ou rótulo. Sem argumento, usa o run mais "
             "recente em runs/active/ por mtime.",
        autocompletion=_complete_run_label,
    ),
    destino: Path = typer.Option(
        Path("runs/archive"), "--destino",
        help="Diretório-raiz para onde mover. Padrão: runs/archive/.",
    ),
    forcar: bool = typer.Option(
        False, "--forcar", "-f",
        help="Arquiva mesmo se o status for `running` ou `stale`. Use "
             "com cuidado: arquivar um run vivo deixa o PID apontando "
             "para um caminho que não vai mais existir.",
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run",
        help="Mostra o que seria movido, mas não move. Sai com código 0.",
    ),
) -> None:
    """Arquiva uma Coleta finalizada (move para ``runs/archive/``).

    Verifica o status via ``list_runs`` antes de mover: ``running`` /
    ``stale`` exigem ``--forcar`` (arquivar um run vivo deixa o pid
    file apontando para um caminho inválido). Colisão de nome no
    destino é um erro — o operador resolve renomeando.

    Pareia naturalmente com ``judex listar --apenas finished`` para
    descobrir candidatos. A inversa (``desarquivar``) é um ``mv`` na
    mão; não automatizamos porque é incomum o suficiente.
    """
    from judex.pipeline.run_index import summarize_run

    saida = _resolve_run_dir(saida)
    if not saida.is_dir():
        typer.echo(f"erro: {saida} não é um diretório.", err=True)
        raise typer.Exit(code=2)

    summary = summarize_run(saida)
    if summary.status.value in ("running", "stale") and not forcar:
        typer.echo(
            f"erro: status={summary.status.value}. Use --forcar para "
            "arquivar mesmo assim (cuidado: pid file vira ponteiro inválido).",
            err=True,
        )
        raise typer.Exit(code=2)

    target = destino / saida.name
    if target.exists():
        typer.echo(
            f"erro: {target} já existe. Renomeie um dos dois e tente de novo.",
            err=True,
        )
        raise typer.Exit(code=2)

    if dry_run:
        typer.echo(f"(dry-run) {saida} -> {target}")
        raise typer.Exit(code=0)

    destino.mkdir(parents=True, exist_ok=True)
    saida.rename(target)
    typer.echo(f"arquivado: {saida} -> {target}")


# ---------------------------------------------------------------------------
# `probe` — tabela rich de progresso shard-a-shard


@debug_app.command(name="probe")
def probe_cmd(
    out_root: Path = typer.Option(
        ..., "--out-root",
        help="Diretório da varredura sharded (contém shard-*/sweep.state.json).",
    ),
    watch: int = typer.Option(
        0, "--watch",
        help="Intervalo de atualização em segundos (0 = mostra uma vez e sai).",
    ),
) -> None:
    """Mostra ao vivo o progresso de uma Coleta paralelizada (shards).

    Renderiza uma tabela com done/target, throughput por shard, regime
    da WAF (colorido) e ETA agregada. Com ``--watch N`` redesenha a
    cada N segundos (Ctrl-C sai).
    """
    from scripts.probe_sharded import run_probe

    raise typer.Exit(code=run_probe(out_root=out_root, watch=watch))


# ---------------------------------------------------------------------------
# `analisar-regimes` — análise post-hoc da trajetória do CliffDetector


@debug_app.command(name="analisar-regimes")
def analisar_regimes(
    run_dir: Path = typer.Argument(
        ...,
        help="Diretório da varredura (contém sweep.log.jsonl ou pdfs.log.jsonl).",
    ),
    apenas_transicoes: bool = typer.Option(
        False, "--apenas-transicoes",
        help="Mostra só os eventos onde o regime muda. Recomendado para "
             "varreduras grandes — o stream completo cabe melhor em --json.",
    ),
    filtrar: Optional[str] = typer.Option(
        None, "--filtrar",
        help="Filtra para um único rótulo de regime (ex.: approaching_collapse).",
    ),
    limite: int = typer.Option(
        50, "--limite",
        help="Máximo de transições renderizadas na tabela humana.",
    ),
    json_out: bool = typer.Option(
        False, "--json",
        help="Emite uma linha JSON por evento (jq-compatível). "
             "Stream completo por padrão; combine com --apenas-transicoes "
             "para obter só as mudanças.",
    ),
) -> None:
    """Diagnostica o histórico de throughput de uma Coleta terminada.

    Reconstrói as transições de regime (``warming`` →
    ``approaching_collapse`` → ``collapse``) a partir do log da Coleta
    e responde:

    1. **Quando o regime mudou?** Lista cada transição com ``fail_rate``
       e ``p95``, mostrando qual métrica disparou.
    2. **Onde a queda (cliff) começou?** Primeiro registro a atingir
       cada banda severa.

    Use ``--apenas-transicoes`` para Coletas grandes (só as mudanças).
    """
    from scripts.analyze_regimes import run_analyze_regimes

    raise typer.Exit(code=run_analyze_regimes(
        run_dir=run_dir,
        apenas_transicoes=apenas_transicoes,
        filtrar=filtrar,
        limite=limite,
        json_out=json_out,
    ))


# ---------------------------------------------------------------------------
# `validar-gabarito` — diff contra as fixtures de gabarito


@debug_app.command(name="validar-gabarito")
def validar_gabarito() -> None:
    """Compara o raspador com os gabaritos conferidos à mão.

    Lê ``tests/ground_truth/*.json``, raspa cada processo via HTTP e
    imprime os diffs por fixture mais o resumo. Atinge o portal STF
    apenas na primeira execução; o cache HTML absorve o resto.
    """
    from scripts.validate_ground_truth import run_validate_ground_truth

    raise typer.Exit(code=run_validate_ground_truth())


# ---------------------------------------------------------------------------
# `relatorio-diario` — sondagem de novas distribuições + Markdown


@debug_app.command(name="relatorio-diario")
def relatorio_diario(
    classe: str = typer.Option(
        "HC", "--classe",
        help="Classe a rastrear (HC, ADI, ADPF, RE, …).",
    ),
    arquivo_estado: Path = typer.Option(
        Path("state/daily_report.json"), "--arquivo-estado",
        help="JSON com a marca d'água por classe.",
    ),
    saida: Path = typer.Option(
        Path("docs/reports/daily"), "--saida",
        help="Diretório onde YYYY-MM-DD.md é escrito.",
    ),
    proxy_pool: Optional[Path] = typer.Option(
        None, "--proxy-pool",
        help="Arquivo com URLs de proxy, uma por linha.",
    ),
    paradas_apos_misses: int = typer.Option(
        20, "--paradas-apos-misses",
        help="Quantos misses contíguos param a sondagem.",
    ),
    semente_warehouse: bool = typer.Option(
        False, "--semente-warehouse",
        help="Na 1ª execução para uma classe, usa MAX(processo_id) do warehouse.",
    ),
    arquivo_lista: Optional[Path] = typer.Option(
        None, "--arquivo-lista",
        help="TXT com uma linha 'CLASSE NUMERO' por processo monitorado; diff a cada rodada.",
    ),
    raiz_snapshots: Path = typer.Option(
        Path("state/watchlist"), "--raiz-snapshots",
        help="Diretório onde os snapshots por processo monitorado são guardados.",
    ),
) -> None:
    """Gera o relatório diário de novas distribuições."""
    from scripts.daily_report import run_daily_report

    raise typer.Exit(code=run_daily_report(
        classe=classe,
        state_file=arquivo_estado,
        out_dir=saida,
        proxy_pool=proxy_pool,
        stop_after_misses=paradas_apos_misses,
        seed_from_warehouse=semente_warehouse,
        watchlist=arquivo_lista,
        snapshot_root=raiz_snapshots,
    ) or 0)


if __name__ == "__main__":
    app()
