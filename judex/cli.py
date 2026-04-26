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
    uv run judex varrer-processos -c HC -i 135041 -f 135041    # ad-hoc (range)
    uv run judex varrer-processos --csv lista.csv --rotulo foo --saida out/
    uv run judex baixar-pecas -c HC -i 252920 -f 253000        # download bytes
    uv run judex extrair-pecas -c HC -i 252920 -f 253000 \\
        --provedor mistral --nao-perguntar                     # OCR a partir do cache
    uv run judex atualizar-warehouse --classe HC               # rebuild DuckDB
    uv run judex exportar --apenas hc_famous_lawyers
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

from judex.utils.validation import (
    validate_process_range,
    validate_stf_case_type,
)

DEFAULT_NOTEBOOKS: tuple[str, ...] = (
    "hc_explorer",
    "hc_top_volume",
    "hc_famous_lawyers",
    "hc_admissibility",
    "hc_minister_archetypes",
)

app = typer.Typer(
    add_completion=False,
    help="judex-mini — hub do raspador + análise do STF.",
    no_args_is_help=True,
)


# ---------------------------------------------------------------------------
# helpers compartilhados


def _push(argv: list[str], flag: str, value: Any) -> None:
    """Empilha ``[flag, str(value)]`` em argv quando o valor é significativo.

    Ignora ``None`` e string vazia — para defaults do Typer não vazarem
    no argparse do script. Para ``bool``: anexa só o flag quando True,
    nada quando False (flags de negação têm tratamento manual no
    chamador).
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


@app.command(name="exportar")
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
    """Exporta os cinco notebooks Marimo de HC como HTML interativo autônomo."""
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
# `fazer-backup` — empacota data/cases + data/cache/pdf em um único .zip


@app.command(name="fazer-backup")
def fazer_backup(
    saida: Optional[Path] = typer.Option(
        None, "--saida", "-o",
        help="Caminho do .zip de saída. Default: "
             "runs/active/backups/judex-backup-<UTC>.zip.",
    ),
    sem_pecas: bool = typer.Option(
        False, "--sem-pecas",
        help="Não incluir data/cache/pdf (peças). Útil para um backup "
             "leve só de metadados.",
    ),
    incluir_warehouse: bool = typer.Option(
        False, "--incluir-warehouse",
        help="Inclui data/warehouse/judex.duckdb. Por padrão fica de fora "
             "— é artefato derivado, regenerável via `atualizar-warehouse`.",
    ),
    classe: Optional[list[str]] = typer.Option(
        None, "--classe",
        help="Restringe os processos a uma ou mais classes (HC, ADI, RE…). "
             "Repita para várias. Omita para incluir todas.",
    ),
    diretorio_casos: Path = typer.Option(
        Path("data/cases"), "--diretorio-casos",
        help="Raiz dos JSONs de caso (particionados por classe).",
    ),
    diretorio_cache_pdf: Path = typer.Option(
        Path("data/cache/pdf"), "--diretorio-cache-pdf",
        help="Cache de PDFs (.pdf.gz / .txt.gz / .extractor / .elements.json.gz).",
    ),
    caminho_warehouse: Path = typer.Option(
        Path("data/warehouse/judex.duckdb"), "--caminho-warehouse",
        help="Caminho do warehouse DuckDB (usado só com --incluir-warehouse).",
    ),
    progresso_cada: int = typer.Option(
        5000, "--progresso-cada",
        help="Frequência (em arquivos) das linhas de progresso. 0 desliga.",
    ),
) -> None:
    """Empacota data/cases + data/cache/pdf em um único .zip aberto pelo Windows.

    Saída atômica: grava em <saida>.tmp e renomeia ao final. Compressão é
    por entrada — JSON deflaciona, .gz/.pdf vão como ZIP_STORED.

    Para um backup completo (sources + warehouse):

        uv run judex fazer-backup --incluir-warehouse

    Para só metadados de HC (sem peças, sem warehouse):

        uv run judex fazer-backup --classe HC --sem-pecas
    """
    from judex.backup import make_backup

    if saida is None:
        stamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
        saida = Path("runs/active/backups") / f"judex-backup-{stamp}.zip"

    typer.echo(f"empacotando -> {saida}")
    typer.echo(f"  cases: {diretorio_casos}{f' (classes={classe})' if classe else ''}")
    typer.echo(f"  peças: {'pulando' if sem_pecas else diretorio_cache_pdf}")
    typer.echo(f"  warehouse: {'incluído (' + str(caminho_warehouse) + ')' if incluir_warehouse else 'pulando'}")

    result = make_backup(
        saida,
        include_pecas=not sem_pecas,
        include_warehouse=incluir_warehouse,
        classes=classe or None,
        cases_dir=diretorio_casos,
        pdf_cache_dir=diretorio_cache_pdf,
        warehouse_path=caminho_warehouse,
        progress_every=progresso_cada,
    )

    size_gb = result.bytes_written / 1e9
    typer.echo("")
    typer.echo(f"done in {result.elapsed_s:.1f}s")
    typer.echo(f"  {result.file_count:,} arquivos -> {size_gb:.2f} GB")
    typer.echo(f"  saída: {result.output_path}")


# ---------------------------------------------------------------------------
# `varrer-processos` — varredura em massa de processos (encaminha para scripts.run_sweep)


@app.command(name="varrer-processos")
def varrer_processos(
    # Três modos de entrada: range (-c/-i/-f), --csv ou --retentar-de.
    classe: Optional[str] = typer.Option(
        None, "-c", "--classe",
        help="[modo range] Classe processual (HC, RE, AI, ADI etc.). "
             "Combine com -i e -f para rodar um intervalo contíguo sem "
             "CSV.",
    ),
    processo_inicial: Optional[int] = typer.Option(
        None, "-i", "--processo-inicial",
        help="[modo range] Primeiro processo do intervalo (inclusivo).",
    ),
    processo_final: Optional[int] = typer.Option(
        None, "-f", "--processo-final",
        help="[modo range] Último processo do intervalo (inclusivo).",
    ),
    csv: Optional[Path] = typer.Option(
        None, "--csv",
        help="[modo CSV] CSV de entrada com pares (classe, processo).",
    ),
    rotulo: Optional[str] = typer.Option(
        None, "--rotulo",
        help="Rótulo curto identificando esta varredura. Obrigatório nos "
             "modos --csv / --retentar-de; em modo range é inferido como "
             "`{classe}_{i}-{f}`.",
    ),
    saida: Optional[Path] = typer.Option(
        None, "--saida",
        help="Diretório de saída (recebe sweep.log.jsonl, sweep.state.json, "
             "sweep.errors.jsonl, report.md). Obrigatório nos modos --csv "
             "/ --retentar-de; em modo range é inferido como "
             "`runs/coletas/{YYYYMMDD_HHMMSS}-{rotulo}/`.",
    ),
    gabarito_dir: Optional[Path] = typer.Option(
        None, "--gabarito-dir",
        help="Diretório de fixtures de gabarito para diff por processo.",
    ),
    paridade_csv: Optional[Path] = typer.Option(
        None, "--paridade-csv",
        help="CSV-baseline (p.ex. saída do Selenium) para comparação de paridade.",
    ),
    passagem_quente: bool = typer.Option(
        False, "--passagem-quente",
        help="Faz uma segunda passagem sobre a mesma lista sem limpar o cache.",
    ),
    limpar_cache: bool = typer.Option(
        False, "--limpar-cache",
        help="Remove data/html dos processos da varredura antes de iniciar.",
    ),
    retomar: bool = typer.Option(
        False, "--retomar",
        help="Pula processos já marcados como status=ok em sweep.state.json.",
    ),
    retentar_de: Optional[Path] = typer.Option(
        None, "--retentar-de",
        help="Caminho para um sweep.errors.jsonl existente; reroda só esses processos.",
    ),
    progresso_cada: int = typer.Option(
        25, "--progresso-cada",
        help="Imprime totais corridos a cada N processos.",
    ),
    retry_403: bool = typer.Option(
        True, "--retry-403/--no-retry-403",
        help="Retry em 403 (o WAF do STF usa 403, não 429, como sinal de throttle).",
    ),
    diretorio_itens: Optional[Path] = typer.Option(
        None, "--diretorio-itens",
        help="Grava um judex-mini_<CLASSE>_<n>-<n>.json por processo ok aqui.",
    ),
    janela_cliff: int = typer.Option(
        50, "--janela-cliff",
        help="Janela rolante do CliffDetector para classificar o regime.",
    ),
    ignorar_collapse: bool = typer.Option(
        False, "--ignorar-collapse",
        help="Continua raspando mesmo com regime=collapse (em vez de parar limpo).",
    ),
    proxy_pool: Optional[Path] = typer.Option(
        None, "--proxy-pool",
        help="Arquivo com uma URL de proxy por linha; habilita rotação "
             "proativa. Em modo monolítico vai direto para run_sweep; em "
             "modo sharded (--shards > 1) o launcher divide round-robin em "
             "N pools materializados em <saida>/proxies/proxies.<letra>.txt "
             "(linhas em branco e comentários '#' ignorados). Obrigatório "
             "em modo sharded.",
    ),
    shards: int = typer.Option(
        0, "--shards",
        help="Se > 1, particiona o CSV em N shards e dispara N processos "
             "paralelos (um por shard), cada um com sua fatia round-robin "
             "do --proxy-pool. Exige --csv, --saida, --rotulo e "
             "--proxy-pool.",
    ),
    excluir_mortos: Optional[Path] = typer.Option(
        None, "--excluir-mortos",
        help="Caminho para um arquivo <classe>.txt (um processo_id por "
             "linha) gerado por scripts/aggregate_dead_ids.py; IDs "
             "listados são omitidos da varredura. Aplicável em modo "
             "range — filtra o CSV sintetizado.",
    ),
    estrategia_shard: str = typer.Option(
        "interleave", "--estrategia-shard",
        help="Particionamento de CSV em modo sharded. 'interleave' "
             "(padrão) distribui linhas round-robin entre shards, "
             "equilibrando qualquer dimensão correlacionada com a "
             "ordem do CSV. 'range' mantém pids contíguos por shard.",
    ),
) -> None:
    """Varredura do backend HTTP do STF — serve para um processo, cem ou cem mil.

    Três modos de entrada (mutuamente exclusivos):

    - **Modo range** (``-c CLASSE -i N -f M``): raspa o intervalo
      contíguo ``[N..M]`` da classe. Forma ad-hoc, sem CSV. Rótulo
      e diretório de saída são inferidos se omitidos — basta
      ``judex varrer-processos -c HC -i 135041 -f 135041``.
    - **Modo CSV** (``--csv arquivo.csv``): lê pares ``(classe,
      processo)`` do arquivo; escala para dezenas de milhares de
      processos. Exige ``--rotulo`` e ``--saida``.
    - **Modo retentar** (``--retentar-de sweep.errors.jsonl``):
      reroda apenas os processos que falharam em uma varredura
      anterior. Exige ``--saida`` (apontando para o diretório da
      varredura original, em regra).

    Toda execução materializa ``sweep.log.jsonl`` (append-only),
    ``sweep.state.json`` (estado atômico compacto),
    ``sweep.errors.jsonl`` e ``report.md`` em ``--saida``. SIGINT /
    SIGTERM encerram de forma limpa depois que o processo em curso
    termina. Em modo range, um sub-diretório ``items/`` recebe
    ``judex-mini_<CLASSE>_<n>-<n>.json`` (um por processo) —
    substitui o comportamento do antigo ``coletar -o json``.
    """
    # Detecta e valida o modo de entrada
    range_flags_given = [
        f for f, v in
        [("-c", classe), ("-i", processo_inicial), ("-f", processo_final)]
        if v is not None
    ]
    range_mode = len(range_flags_given) > 0
    if range_mode and len(range_flags_given) != 3:
        raise typer.BadParameter(
            "Modo range exige os três: -c (classe), -i (inicial), -f (final). "
            f"Faltou: {[f for f in ('-c', '-i', '-f') if f not in range_flags_given]}."
        )

    n_modes = int(range_mode) + int(csv is not None) + int(retentar_de is not None)
    if n_modes == 0:
        raise typer.BadParameter(
            "Escolha um modo de entrada: range (-c/-i/-f), --csv ou "
            "--retentar-de."
        )
    if n_modes > 1:
        raise typer.BadParameter(
            "Modos de entrada mutuamente exclusivos: escolha apenas um "
            "entre range (-c/-i/-f), --csv ou --retentar-de."
        )

    # Modo range: sintetiza CSV temporário + auto-defaults de rótulo/saída
    tmp_csv: Optional[Path] = None
    if range_mode:
        assert classe is not None and processo_inicial is not None and processo_final is not None
        validate_stf_case_type(classe)
        validate_process_range(processo_inicial, processo_final)

        # Auto-default do rótulo: {CLASSE}_{i}-{f}
        if rotulo is None:
            rotulo = f"{classe.upper()}_{processo_inicial}-{processo_final}"
        # Auto-default da saída: runs/coletas/{timestamp}-{rotulo}/
        if saida is None:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            saida = Path("runs/coletas") / f"{ts}-{rotulo}"
        # Auto-default do --items-dir em modo range: saída/items/
        if diretorio_itens is None:
            diretorio_itens = saida / "items"

        saida.mkdir(parents=True, exist_ok=True)

        # Carrega dead-IDs se o usuário passou --excluir-mortos.
        if excluir_mortos is not None:
            from judex.utils.dead_ids import load_dead_ids
            dead = load_dead_ids(excluir_mortos)
        else:
            dead = set()

        # Grava o CSV persistente dentro de --saida (não em /tmp): fica
        # auditável ao lado dos demais artefatos da varredura.
        tmp_csv = saida / "input.csv"
        n_written = 0
        with tmp_csv.open("w", encoding="utf-8", newline="") as fp:
            writer = _csv.writer(fp)
            writer.writerow(["classe", "processo"])
            for p in range(processo_inicial, processo_final + 1):
                if p in dead:
                    continue
                writer.writerow([classe.upper(), p])
                n_written += 1
        csv = tmp_csv

        total = processo_final - processo_inicial + 1
        dead_msg = f", {total - n_written} morto(s) excluído(s)" if dead else ""
        typer.echo(
            f"Modo range: {classe} {processo_inicial}..{processo_final} "
            f"({n_written} processo(s){dead_msg}). "
            f"Rótulo={rotulo!r}, saída={saida}."
        )

    # Nos modos --csv / --retentar-de, rótulo e saída continuam obrigatórios
    if rotulo is None:
        raise typer.BadParameter(
            "--rotulo é obrigatório quando a entrada é --csv ou --retentar-de."
        )
    if saida is None:
        raise typer.BadParameter(
            "--saida é obrigatório quando a entrada é --csv ou --retentar-de."
        )

    # Modo shardeado: particiona o CSV em N e dispara N filhos detach.
    # Mesma forma que baixar-pecas --shards — inclusive PIDs/monitor.
    if shards > 1:
        if csv is None:
            raise typer.BadParameter(
                "--shards > 1 exige --csv (sharding particiona o CSV). "
                "Modo range já sintetizou um CSV; mas --shards + range "
                "só faz sentido acima de ~milhares de processos."
            )
        if proxy_pool is None:
            raise typer.BadParameter(
                "--shards > 1 exige --proxy-pool (arquivo flat com URLs; "
                "o launcher divide round-robin entre os shards)."
            )

        from judex.sweeps.shard_launcher import launch_sharded_sweep

        # Flags que valem a pena carregar para todos os shards. Tradução
        # Typer(pt) → argparse do run_sweep(en) acontece aqui — o launcher
        # fala a linguagem do script, não do Typer.
        extra: list[str] = []
        _push(extra, "--resume", retomar)
        _push(extra, "--items-dir", diretorio_itens)
        _push(extra, "--progress-every", progresso_cada)
        _push(extra, "--cliff-window", janela_cliff)
        _push(extra, "--no-stop-on-collapse", ignorar_collapse)
        if not retry_403:
            extra.append("--no-retry-403")

        if estrategia_shard not in ("interleave", "range"):
            raise typer.BadParameter(
                f"--estrategia-shard inválida: {estrategia_shard!r}. "
                "Use 'interleave' ou 'range'."
            )
        try:
            pids_path = launch_sharded_sweep(
                csv_path=csv,
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

    argv: list[str] = ["--label", rotulo, "--out", str(saida)]
    _push(argv, "--csv", csv)
    _push(argv, "--parity-dir", gabarito_dir)
    _push(argv, "--parity-csv", paridade_csv)
    _push(argv, "--warm-pass", passagem_quente)
    _push(argv, "--wipe-cache", limpar_cache)
    _push(argv, "--resume", retomar)
    _push(argv, "--retry-from", retentar_de)
    _push(argv, "--progress-every", progresso_cada)
    if not retry_403:  # argparse do script usa a negação --no-retry-403
        argv.append("--no-retry-403")
    _push(argv, "--items-dir", diretorio_itens)
    _push(argv, "--cliff-window", janela_cliff)
    _push(argv, "--no-stop-on-collapse", ignorar_collapse)
    _push(argv, "--proxy-pool", proxy_pool)

    from scripts.run_sweep import main as _run_sweep_main

    raise typer.Exit(code=_run_sweep_main(argv))


# ---------------------------------------------------------------------------
# `baixar-pecas` — baixa os PDFs brutos para o cache local
# `extrair-pecas` — extrai texto via provedor (pypdf, mistral, chandra, unstructured)


def _argv_pdf_common(
    *,
    classe: Optional[str], inicio: Optional[int], fim: Optional[int],
    csv: Optional[Path], retentar_de: Optional[Path],
    impte_contem: str, tipos_doc: str,
    relator_contem: str, excluir_tipos_doc: str, limite: int,
    saida: Optional[Path], dry_run: bool, nao_perguntar: bool,
    retomar: bool,
    apenas_substantivas: bool = True,
) -> list[str]:
    """Montar a parte comum de argv para baixar-pecas e extrair-pecas."""
    a: list[str] = []
    _push(a, "-c", classe)
    _push(a, "-i", inicio)
    _push(a, "-f", fim)
    _push(a, "--csv", csv)
    _push(a, "--retentar-de", retentar_de)
    _push(a, "--impte-contem", impte_contem)
    _push(a, "--tipos-doc", tipos_doc)
    _push(a, "--relator-contem", relator_contem)
    _push(a, "--excluir-tipos-doc", excluir_tipos_doc)
    _push(a, "--limite", limite)
    _push(a, "--saida", saida)
    _push(a, "--dry-run", dry_run)
    _push(a, "--nao-perguntar", nao_perguntar)
    _push(a, "--retomar", retomar)
    if apenas_substantivas:
        a.append("--apenas-substantivas")
    else:
        a.append("--todos-tipos")
    return a


@app.command(name="baixar-pecas")
def baixar_pecas(
    # Modos de entrada (prioridade: retentar-de > csv > range > filtros).
    classe: Optional[str] = typer.Option(
        None, "-c", "--classe",
        help='Classe (p.ex. "HC"). Sozinha → filtros. Com -i/-f → range.',
    ),
    inicio: Optional[int] = typer.Option(
        None, "-i", "--inicio",
        help="Primeiro processo do range (inclusive).",
    ),
    fim: Optional[int] = typer.Option(
        None, "-f", "--fim",
        help="Último processo do range (inclusive).",
    ),
    csv: Optional[Path] = typer.Option(
        None, "--csv",
        help="CSV de (classe, processo). Ganha de range e filtros.",
    ),
    retentar_de: Optional[Path] = typer.Option(
        None, "--retentar-de",
        help="Caminho de um pdfs.errors.jsonl anterior; reroda só essas URLs.",
    ),
    # Filtros (fallback).
    impte_contem: str = typer.Option(
        "", "--impte-contem",
        help='Filtro: substrings (qualquer uma) para IMPTE.(S).',
    ),
    tipos_doc: str = typer.Option(
        "", "--tipos-doc",
        help="Filtro: valores exatos de andamento.link.tipo.",
    ),
    relator_contem: str = typer.Option(
        "", "--relator-contem",
        help="Filtro: substrings em .relator.",
    ),
    excluir_tipos_doc: str = typer.Option(
        "", "--excluir-tipos-doc",
        help="Filtro: tipos de doc a pular (depois de --tipos-doc).",
    ),
    apenas_substantivas: bool = typer.Option(
        True, "--apenas-substantivas/--todos-tipos",
        help="Pula peças tier-C (certidões, termos, intimações) por padrão. "
             "Ver docs/peca-tipo-classification.md. Use --todos-tipos para "
             "desativar e baixar TODAS as peças.",
    ),
    limite: int = typer.Option(
        0, "--limite",
        help="Trunca em N alvos (0 = sem limite).",
    ),
    # Execução.
    saida: Optional[Path] = typer.Option(
        None, "--saida",
        help="Diretório de saída. Usa runs/active/baixar-adhoc se omitido.",
    ),
    forcar: bool = typer.Option(
        False, "--forcar",
        help="Rebaixar mesmo se os bytes já estiverem em disco.",
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run",
        help="Só prévia; não baixa nada.",
    ),
    nao_perguntar: bool = typer.Option(
        False, "--nao-perguntar",
        help="Pula o confirm. Obrigatório para não-TTY.",
    ),
    retomar: bool = typer.Option(
        False, "--retomar",
        help="Pula alvos já status=ok em pdfs.state.json.",
    ),
    proxy_pool: Optional[Path] = typer.Option(
        None, "--proxy-pool",
        help="Arquivo com uma URL de proxy por linha; habilita rotação "
             "proativa. Em modo monolítico vai direto para baixar_pecas; "
             "em modo sharded (--shards > 1) o launcher divide round-robin "
             "em N pools materializados em <saida>/proxies/proxies.<letra>.txt "
             "(linhas em branco e comentários '#' ignorados). Sem este "
             "flag em modo monolítico, baixa via IP direto. Obrigatório "
             "em modo sharded.",
    ),
    shards: int = typer.Option(
        0, "--shards",
        help="Se > 1, particiona o CSV em N shards e dispara N processos "
             "paralelos (um por shard), cada um com sua fatia round-robin "
             "do --proxy-pool. Exige --csv, --saida e --proxy-pool.",
    ),
    estrategia_shard: str = typer.Option(
        "interleave", "--estrategia-shard",
        help="Particionamento de CSV em modo sharded. 'interleave' "
             "(padrão) distribui linhas round-robin entre shards, "
             "equilibrando workloads correlacionados com a ordem do CSV "
             "(ex.: URLs já em cache vs. fresh). 'range' mantém pids "
             "contíguos por shard.",
    ),
) -> None:
    """Baixa PDFs do STF para o cache local de bytes.

    Metade do pipeline que fala com o portal STF; escreve bytes crus
    em ``data/cache/pdf/<sha1(url)>.pdf.gz``. A extração de texto é
    um comando separado (``extrair-pecas``).

    Prioridade de modos de entrada: ``--retentar-de`` > ``--csv`` >
    range (``-c`` + ``-i``/``-f``) > filtros.

    Rotação de proxy é opcional e espelha ``varrer-processos``: sem
    ``--proxy-pool``, roda em IP direto (comportamento padrão). Com
    ``--proxy-pool``, o driver troca de sessão/IP proativamente — janela
    alinhada com o tempo que o WAF do STF leva para esquecer um IP.
    """
    if shards > 1:
        if csv is None:
            raise typer.BadParameter(
                "--shards > 1 exige --csv (sharding particiona o CSV)."
            )
        if saida is None:
            raise typer.BadParameter(
                "--shards > 1 exige --saida (raiz das pastas por shard)."
            )
        if proxy_pool is None:
            raise typer.BadParameter(
                "--shards > 1 exige --proxy-pool (arquivo flat com URLs; "
                "o launcher divide round-robin entre os shards)."
            )

        from judex.sweeps.shard_launcher import launch_sharded_download

        extra: list[str] = []
        _push(extra, "--retomar", retomar)
        _push(extra, "--forcar", forcar)
        _push(extra, "--nao-perguntar", nao_perguntar)
        if apenas_substantivas:
            extra.append("--apenas-substantivas")
        else:
            extra.append("--todos-tipos")

        if estrategia_shard not in ("interleave", "range"):
            raise typer.BadParameter(
                f"--estrategia-shard inválida: {estrategia_shard!r}. "
                "Use 'interleave' ou 'range'."
            )
        try:
            pids_path = launch_sharded_download(
                csv_path=csv,
                shards=shards,
                proxy_pool=proxy_pool,
                saida_root=saida,
                extra_args=extra,
                strategy=estrategia_shard,  # type: ignore[arg-type]
            )
        except ValueError as e:
            raise typer.BadParameter(str(e))

        typer.echo(f"Lançou {shards} shards em background.")
        typer.echo(f"  PIDs:   {pids_path}")
        typer.echo(f"  Watch:  pgrep -af baixar_pecas")
        typer.echo(f"  Stop:   xargs -a {pids_path} kill -TERM")
        raise typer.Exit(code=0)

    argv = _argv_pdf_common(
        classe=classe, inicio=inicio, fim=fim, csv=csv,
        retentar_de=retentar_de,
        impte_contem=impte_contem, tipos_doc=tipos_doc,
        relator_contem=relator_contem, excluir_tipos_doc=excluir_tipos_doc,
        limite=limite, saida=saida, dry_run=dry_run,
        nao_perguntar=nao_perguntar, retomar=retomar,
        apenas_substantivas=apenas_substantivas,
    )
    _push(argv, "--forcar", forcar)
    _push(argv, "--proxy-pool", proxy_pool)

    from scripts.baixar_pecas import main as _baixar_main
    raise typer.Exit(code=_baixar_main(argv))


@app.command(name="extrair-pecas")
def extrair_pecas(
    # Modos de entrada (prioridade: retentar-de > csv > range > filtros).
    classe: Optional[str] = typer.Option(
        None, "-c", "--classe",
        help='Classe (p.ex. "HC"). Sozinha → filtros. Com -i/-f → range.',
    ),
    inicio: Optional[int] = typer.Option(
        None, "-i", "--inicio",
        help="Primeiro processo do range (inclusive).",
    ),
    fim: Optional[int] = typer.Option(
        None, "-f", "--fim",
        help="Último processo do range (inclusive).",
    ),
    csv: Optional[Path] = typer.Option(None, "--csv"),
    retentar_de: Optional[Path] = typer.Option(None, "--retentar-de"),
    # Filtros (fallback).
    impte_contem: str = typer.Option("", "--impte-contem"),
    tipos_doc: str = typer.Option("", "--tipos-doc"),
    relator_contem: str = typer.Option("", "--relator-contem"),
    excluir_tipos_doc: str = typer.Option("", "--excluir-tipos-doc"),
    apenas_substantivas: bool = typer.Option(
        True, "--apenas-substantivas/--todos-tipos",
        help="Pula peças tier-C (certidões, termos, intimações) por padrão. "
             "Ver docs/peca-tipo-classification.md.",
    ),
    limite: int = typer.Option(0, "--limite"),
    # Extrator.
    provedor: str = typer.Option(
        "pypdf", "--provedor",
        help="Extrator: pypdf | mistral | chandra | unstructured. "
             "Padrão: pypdf (local, grátis, camada de texto). OCR requer "
             "a chave de API correspondente no ambiente "
             "(MISTRAL_API_KEY / UNSTRUCTURED_API_KEY / CHANDRA_API_KEY).",
    ),
    forcar: bool = typer.Option(
        False, "--forcar",
        help="Re-extrai mesmo se o sidecar já for igual a --provedor.",
    ),
    # Execução.
    saida: Optional[Path] = typer.Option(None, "--saida"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    nao_perguntar: bool = typer.Option(False, "--nao-perguntar"),
    retomar: bool = typer.Option(False, "--retomar"),
) -> None:
    """Extrai texto dos PDFs já baixados em disco (zero HTTP).

    Lê bytes de ``data/cache/pdf/<sha1(url)>.pdf.gz``, despacha
    para o provedor pedido via ``src.scraping.ocr.extract_pdf``,
    escreve texto + sidecar ``.extractor`` de volta no cache. Pré-
    requisito: rodar ``baixar-pecas`` antes.

    Prioridade de modos de entrada igual a ``baixar-pecas``.
    """
    argv = _argv_pdf_common(
        classe=classe, inicio=inicio, fim=fim, csv=csv,
        retentar_de=retentar_de,
        impte_contem=impte_contem, tipos_doc=tipos_doc,
        relator_contem=relator_contem, excluir_tipos_doc=excluir_tipos_doc,
        limite=limite, saida=saida, dry_run=dry_run,
        nao_perguntar=nao_perguntar, retomar=retomar,
        apenas_substantivas=apenas_substantivas,
    )
    _push(argv, "--provedor", provedor)
    _push(argv, "--forcar", forcar)

    from scripts.extrair_pecas import main as _extrair_main
    raise typer.Exit(code=_extrair_main(argv))


# ---------------------------------------------------------------------------
# `atualizar-warehouse` — reconstrói o DuckDB derivado dos JSONs + cache


@app.command(name="atualizar-warehouse")
def atualizar_warehouse(
    diretorio_casos: Path = typer.Option(
        Path("data/cases"), "--diretorio-casos",
        help="Raiz dos JSONs de caso (particionados por classe).",
    ),
    diretorio_cache_pdf: Path = typer.Option(
        Path("data/cache/pdf"), "--diretorio-cache-pdf",
        help="Cache de PDFs (.txt.gz / .elements.json.gz / .extractor).",
    ),
    saida: Path = typer.Option(
        Path("data/warehouse/judex.duckdb"), "--saida",
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
) -> None:
    """Reconstrói o warehouse DuckDB a partir dos JSONs + cache de PDFs.

    Full-rebuild com swap atômico — não há modo incremental. Os JSONs
    em ``data/cases/`` continuam sendo a fonte de verdade; o warehouse
    é um artefato derivado, regenerável. Custo típico: ~2–3 min para
    ~55k casos, ~15–20 min para 350k.

    O comando não fala com a rede — é puro scan local de JSON + gzip.
    Rode depois de ``varrer-processos`` / ``extrair-pecas`` sempre que
    quiser ver os dados novos nos notebooks / em SQL.
    """
    from scripts.build_warehouse import run_build_warehouse

    raise typer.Exit(code=run_build_warehouse(
        cases_root=diretorio_casos,
        pdf_cache_root=diretorio_cache_pdf,
        output=saida,
        classe=classe,
        year=ano,
        progress_every=progresso_cada,
        strict=estrito,
    ))


# ---------------------------------------------------------------------------
# `probe` — visão unificada do progresso de uma varredura sharded


@app.command(name="probe")
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
    """Mostra o progresso de uma varredura sharded em tempo real.

    Lê `shard-*/sweep.state.json` sob `--out-root` e renderiza uma
    tabela rich com done/target, throughput por shard, regime de WAF
    (colorido) e ETA agregada. Com `--watch N` redesenha a tela a cada
    N segundos (Ctrl-C para sair).

    A fonte de verdade de `target` é `<out-root>/shards/*.shard.N.csv`
    — gerado automaticamente pelo launcher de `varrer-processos
    --shards`.
    """
    from scripts.probe_sharded import run_probe

    raise typer.Exit(code=run_probe(out_root=out_root, watch=watch))


# ---------------------------------------------------------------------------
# `analisar-regimes` — análise post-hoc da trajetória do CliffDetector


@app.command(name="analisar-regimes")
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
    """Reconstrói a trajetória de regime de um sweep a partir de seu log.

    Lê ``sweep.log.jsonl`` (varrer-processos) ou ``pdfs.log.jsonl``
    (baixar-pecas) — auto-detectado — e responde duas perguntas
    operacionais sem ``jq``:

    1. **Quando o regime mudou?** Lista as transições com ``fail_rate``,
       ``p95`` e qual eixo (A=fail-rate / B=p95) promoveu cada banda.
    2. **Onde a queda começou?** Para cada banda severa
       (``l2_engaged`` / ``approaching_collapse`` / ``collapse``),
       o primeiro registro que a atingiu.

    Distingue-se de ``probe`` (que lê o snapshot ``*.state.json`` para
    monitoramento ao vivo) por ler o log append-only e responder
    perguntas históricas.
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


@app.command(name="validar-gabarito")
def validar_gabarito() -> None:
    """Diff da saída do raspador contra os gabaritos conferidos à mão.

    Lê cada fixture em ``tests/ground_truth/*.json``, raspa o processo
    correspondente pelo backend HTTP e imprime os diffs por fixture e
    o resumo final. Atinge o portal do STF na primeira execução; o
    cache HTML absorve as chamadas seguintes.
    """
    from scripts.validate_ground_truth import run_validate_ground_truth

    raise typer.Exit(code=run_validate_ground_truth())


# ---------------------------------------------------------------------------
# `relatorio-diario` — sondagem de novas distribuições + Markdown


@app.command(name="relatorio-diario")
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
