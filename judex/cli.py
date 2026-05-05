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
    uv run judex limpar runs/active/<label>/ --apply           # residual recovery
    uv run judex atualizar-warehouse --classe HC               # rebuild DuckDB
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
    add_completion=False,
    help="judex-mini — hub do raspador + análise do STF.",
    no_args_is_help=True,
)

# Sub-app for inspection / validation / export utilities that aren't
# part of the everyday operator loop (`executar` → `acompanhar` →
# `relatar` + `limpar` + `atualizar-warehouse`). The legacy three-
# command chain (varrer / baixar / extrair / coletar) was removed
# from the CLI surface; the library code in `judex/sweeps/` stays for
# `pick_provider` and shared helpers used by the unified pipeline.
# Recoverable on the `archive/iteration-2-three-command-chain` branch.
debug_app = typer.Typer(
    add_completion=False,
    help="Utilitários auxiliares: inspeção, validação, comparação de "
         "provedores, backup e exportação. `judex executar` é o "
         "caminho primário do dia-a-dia.",
    no_args_is_help=True,
)
app.add_typer(debug_app, name="debug")


# ---------------------------------------------------------------------------
# helpers compartilhados


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
# `fazer-backup` — empacota data/source/processos + data/raw/pecas + data/derived/pecas-texto em um único .zip


@debug_app.command(name="fazer-backup")
def fazer_backup(
    saida: Optional[Path] = typer.Option(
        None, "--saida", "-o",
        help="Caminho do .zip de saída. Default: "
             "runs/active/backups/judex-backup-<UTC>.zip.",
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
             "`atualizar-warehouse`.",
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
    """Empacota processos + peças num único .zip aberto pelo Windows.

    Saída atômica: grava em <saida>.tmp e renomeia ao final. Compressão é
    por entrada — JSON deflaciona, .gz/.pdf/.rtf vão como ZIP_STORED.

    Para um backup completo (processos + peças + warehouse):

        uv run judex fazer-backup --incluir-warehouse

    Para só metadados de HC (sem peças, sem warehouse):

        uv run judex fazer-backup --classe HC --sem-pecas
    """
    from judex.backup import make_backup

    if saida is None:
        stamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
        saida = Path("runs/active/backups") / f"judex-backup-{stamp}.zip"

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


@app.command(name="executar")
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
             "--saida, --saida assume `runs/coletas/{ts}-{rotulo}/`.",
    ),
    saida: Optional[Path] = typer.Option(
        None, "--saida",
        help="Diretório da execução. Recebe executar.state.json, "
             "executar.log.jsonl, executar.errors.jsonl, report.md. "
             "Padrão automático em modo intervalo (ou com --rotulo): "
             "runs/coletas/{ts}-{rotulo}/.",
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
) -> None:
    """Pipeline unificado: varrer + baixar + extrair num único processo.

    Substitui a chain ``varrer-processos`` → ``baixar-pecas`` →
    ``extrair-pecas`` (e o orquestrador ``coletar``) por uma única
    invocação fire-and-forget. Três asyncio.Queues alimentam três
    coroutines de pool (``portal``, ``sistemas``, ``ocr``); cada
    tarefa emite suas sucessoras ao terminar.

    **Modos de entrada (escolha um):**
      - range: ``-c HC -i 250000 -f 250100``
      - CSV:   ``--csv alvos.csv``
      - retry: ``--retentar-de runs/.../executar.errors.jsonl``

    Estado persistido em ``<saida>/executar.state.json`` (snapshot
    atômico, periódico) + ``<saida>/executar.log.jsonl`` (append-only,
    fsynced por linha — durável contra SIGKILL / OOM / VM suspend).
    Resume é automático: re-rodar com a mesma ``--saida`` requeue só
    o trabalho não-ok. SIGTERM/SIGINT acionam shutdown gracioso.

    Spec: ``docs/superpowers/specs/2026-05-02-unified-pipeline.md``.
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
        if rotulo is None:
            rotulo = f"{classe.upper()}_{inicio}-{fim}"
    elif csv is not None:
        targets = read_targets_csv(csv)
    else:
        assert retentar_de is not None
        targets = targets_from_errors_jsonl(retentar_de)

    if not targets:
        typer.echo("ERROR: nenhum alvo resolvido pelos parâmetros dados.", err=True)
        raise typer.Exit(code=2)

    # ----- Auto-default --saida from --rotulo when omitted -----
    if saida is None:
        if rotulo is None:
            raise typer.BadParameter(
                "--saida é obrigatório quando nem --rotulo nem modo range "
                "estão setados (sem rótulo não há nome para o auto-saida)."
            )
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        saida = Path("runs/coletas") / f"{ts}-{rotulo}"
        typer.echo(f"--saida não fornecido; usando auto-default {saida}")

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
# `atualizar` — varre os processos novos até o leading edge atual da STF


@app.command(name="atualizar")
def atualizar_corpus(
    classe: str = typer.Argument(
        ...,
        help="Classe a varrer (HC, ADI, ADPF, RE, …). Obrigatório — "
             "não há default; cada classe tem um leading edge próprio.",
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
        help="Provedor OCR (default 'auto' = router pypdf↔tesseract_fly).",
    ),
    portal_concurrencia: int = typer.Option(
        1, "--portal-concurrencia",
        help="Concorrência do pool portal. Direct-IP: 1.",
    ),
    sistemas_concurrencia: int = typer.Option(
        1, "--sistemas-concurrencia",
        help="Concorrência do pool sistemas. Direct-IP: 1.",
    ),
    ocr_concurrencia: int = typer.Option(
        4, "--ocr-concurrencia",
        help="Concorrência do pool OCR.",
    ),
) -> None:
    """Atualiza o corpus de uma classe até o leading edge atual da STF.

    1. Glob ``data/source/processos/<classe>/`` para o maior processo_id
       já scrapeado.
    2. Sonda case-ids acima dele um a um via portal, parando após
       ``--paradas-apos-misses`` IDs não-alocados consecutivos (sinal
       de ter passado o leading edge da STF para essa classe).
    3. Roda o pipeline completo (meta + bytes + text) só nos case-ids
       descobertos como vivos — pula automaticamente os buracos.

    Comando idempotente — re-rodar pula o que já foi puxado via
    ``skipped_cached``.

    Exemplo:

        uv run judex atualizar HC                       # default
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
# `atualizar-warehouse` — reconstrói o DuckDB derivado dos JSONs + cache


@app.command(name="atualizar-warehouse")
def atualizar_warehouse(
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
) -> None:
    """Reconstrói o warehouse DuckDB a partir dos JSONs + cache de texto.

    Full-rebuild com swap atômico — não há modo incremental. Os JSONs
    em ``data/source/processos/`` continuam sendo a fonte de verdade;
    o warehouse é um artefato derivado, regenerável. Custo típico:
    ~2–3 min para ~55k processos, ~15–20 min para 350k.

    O comando não fala com a rede — é puro scan local de JSON + gzip.
    Rode depois de ``varrer-processos`` / ``extrair-pecas`` sempre que
    quiser ver os dados novos nos notebooks / em SQL.
    """
    from judex.sweeps.build_warehouse import run_build_warehouse

    raise typer.Exit(code=run_build_warehouse(
        cases_root=diretorio_processos,
        pecas_texto_root=diretorio_pecas_texto,
        output=saida,
        classe=classe,
        year=ano,
        progress_every=progresso_cada,
        strict=estrito,
    ))


# ---------------------------------------------------------------------------
# `extrair-urls` — URL-scoped re-extraction (no fetch, no case-walker)


@app.command(name="extrair-urls")
def extrair_urls_cmd(
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
    """Re-extrai texto para URLs específicas usando um provedor escolhido.

    Recovery escopada por URL — bypassa o case-walker. Os bytes precisam
    estar no cache de peças (escreva-os com ``judex executar`` antes);
    URLs sem bytes em cache contam para ``missing_bytes`` no relatório.

    Caso de uso típico: re-OCR pontual de outliers (PDFs que estouraram o
    cap de body do OCR em cloud) com ``--provedor tesseract`` local, sem
    re-extrair as outras peças do caso.
    """
    from judex.sweeps.extrair_urls import run_extrair_urls

    result = run_extrair_urls(arquivo_urls, provedor=provedor, forcar=forcar)
    typer.echo(
        f"extrair-urls: ok={result.n_ok} · skipped={result.n_skipped} · "
        f"missing_bytes={result.n_missing_bytes} · fail={result.n_fail} · "
        f"wall={result.wall_s:.1f}s"
    )
    if result.n_fail > 0:
        raise typer.Exit(code=1)


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
    """Print the OCR provider comparison table for a given workload size.

    Reads each provider's ``SPEC: ProviderSpec`` from
    ``judex/scraping/ocr/<provider>.py``, asks for cost(n_pages) and
    wall(n_pdfs), prints sorted by cost. Providers whose ``wall``
    anchor isn't measured yet show ``—`` in the minutes column.

    The numbers come from the same SPECs ``extrair-pecas --prever``
    consults, so this view and the per-sweep forecast are always
    consistent.
    """
    from judex.scraping.ocr.dispatch import render_provider_table
    typer.echo(render_provider_table(
        n_pdfs=n_pdfs, n_pages=n_pages, batch_ok=batch,
    ))


# ---------------------------------------------------------------------------
# `limpar` — close a finished run's residual in one command


@app.command(name="limpar")
def limpar(
    run_dir: Path = typer.Argument(
        ...,
        help="Diretório de um run finalizado de ``judex executar``. "
             "Auto-detecta layout: sharded (shard-*/) ou monolítico "
             "(executar.errors.jsonl no topo).",
    ),
    apply: bool = typer.Option(
        False, "--apply",
        help="Dispara as recoveries planejadas. Sem este flag, o comando "
             "imprime o plano (``would-recover: …``) e sai sem efeito "
             "colateral — dry-run é o default seguro.",
    ),
    provedor: str = typer.Option(
        "auto", "--provedor",
        help="Provedor passado para os ``judex executar --retentar-de`` "
             "filhos detached. Padrão `auto` (tier-routing pypdf↔OCR).",
    ),
    nao_perguntar: bool = typer.Option(
        False, "--nao-perguntar",
        help="Pula o prompt de confirmação sob ``--apply``. Necessário "
             "para invocações non-interactive (cron, nohup).",
    ),
) -> None:
    """One-command residual recovery for finished ``judex executar`` runs.

    Walks ``<run_dir>`` (mono ou sharded — auto-detecta), classifica
    cada linha de ``executar.errors.jsonl`` em buckets via
    ``judex.pipeline.log.classify_unified_error``, e dispara um
    ``judex executar --retentar-de`` detached por shard com pelo menos
    uma linha transiente. Buckets terminais (``unallocated_pid``,
    ``empty``, ``no_bytes``) são contados e reportados — não
    auto-dispatchados em v1.

    Default é dry-run (imprime ``would-recover: …`` e sai). Para
    realmente executar, ``--apply``. Para non-interactive (cron/nohup),
    combine com ``--nao-perguntar``.

    Spec: ``docs/superpowers/specs/2026-05-03-judex-limpar.md``.
    Exit codes:

    - ``0`` — plano computado (e sob ``--apply``, todos os spawns OK).
    - ``2`` — args inválidos (``run_dir`` não existe).
    - ``3`` — resíduo vazio (nenhum ``executar.errors.jsonl`` encontrado).
    """
    from judex.sweeps.limpar import (
        classify_residual,
        discover_run_dirs,
        execute_recoveries,
        format_summary,
        plan_recoveries,
    )

    if not run_dir.exists():
        typer.echo(f"ERROR: run_dir {run_dir} não existe.", err=True)
        raise typer.Exit(code=2)

    dirs = discover_run_dirs(run_dir)
    if not dirs:
        typer.echo(
            f"limpar: nada a recuperar em {run_dir} "
            f"(nenhum executar.errors.jsonl encontrado)."
        )
        raise typer.Exit(code=3)

    buckets = classify_residual(dirs)
    summary = format_summary(buckets, dry_run=not apply)
    typer.echo(summary)

    if not apply:
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
        typer.echo("limpar: nenhum bucket transiente — nada a despachar.")
        raise typer.Exit(code=0)

    if not nao_perguntar:
        if not typer.confirm(
            f"Confirmar dispatch de {len(plan)} child(ren) detached em "
            f"{run_dir}?",
            default=True,
        ):
            typer.echo("Abortado pelo usuário.")
            raise typer.Exit(code=2)

    pids_path = run_dir / "limpar.pids"
    result = execute_recoveries(plan, pids_path)
    typer.echo(
        f"limpar: spawned {len(result.pids)} child(ren); "
        f"PIDs em {pids_path}. Acompanhe com `judex acompanhar {run_dir}`."
    )
    raise typer.Exit(code=0)


# ---------------------------------------------------------------------------
# `acompanhar` — tail unificado mono + sharded com auto-encerramento


@app.command(name="acompanhar")
def acompanhar(
    run_dir: Path = typer.Argument(
        ...,
        help="Diretório do run. Auto-detecta layout: sharded "
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
    """Tail unificado para runs monolíticos e shardeados, com
    encerramento automático ao final do run.

    Padrão: tail + auto-detect de fim-de-run + ``relatar`` consolidado.
    A linha-âncora é ``executar: done`` (emitida por
    ``judex/pipeline/runner.py``). Quando todos os shards (ou o log
    monolítico) registram pelo menos uma, o ``acompanhar`` para o
    multitail, imprime o resumo e sai com código 0. Use ``--persistir``
    para o comportamento legado de tailar indefinidamente.

    **Mono** e **sharded** rodam o mesmo loop Python — sem ``execvp`` —
    para que a detecção de fim-de-run funcione em ambos os layouts.
    Ctrl-C também é capturado limpo, sem stack-trace de Python.

    Em sharded, a saída é compactada de duas formas:

      1. Cabeçalhos ``==> shard-X/driver.log <==`` viram prefixo
         compacto ``[X]`` por linha.
      2. As linhas ``─── 571/571 (100%) … ───`` de cada shard são
         suprimidas (16 idênticas a cada intervalo é puro ruído).
         Uma thread agregadora emite UMA linha cluster-wide com
         counts reais (``provider_error``, ``unallocated_pid``, …).
    """
    from scripts.follow_run import run_follow
    raise typer.Exit(code=run_follow(
        run_dir, n=n, agg_interval=agg_interval, persistir=persistir,
    ))


# ---------------------------------------------------------------------------
# `relatar` — consolidação pós-run (residuals + próximos passos)


@app.command(name="relatar")
def relatar(
    run_dir: Path = typer.Argument(
        ...,
        help="Diretório do run (mono ou sharded). "
             "Funciona tanto para run em curso quanto para run finalizado.",
    ),
) -> None:
    """Consolida o estado de um run de ``executar`` em um relatório único.

    Caminha por ``shard-*/executar.state.json``,
    ``shard-*/executar.errors.jsonl`` e ``shard-*/report.md`` (ou seus
    equivalentes top-level em mono) e renderiza:

    - banner de status (``DONE``/``RUNNING``/``EMPTY``);
    - mix de status por estágio (processos / pecas / text);
    - wall-clock (maior shard + soma) e custo de OCR (USD);
    - residuals classificados por ``(kind, status)``, com label
      humano e contagem;
    - próximos passos copy-paste (loops ``--retentar-de`` por shard
      para classes retryable; classes terminais ficam só listadas).

    Idempotente, somente-leitura, executa em <1 s em runs finalizados.
    Pareado com ``acompanhar`` (que chama o mesmo renderer ao detectar
    fim-de-run).
    """
    from judex.sweeps.run_summary import render_summary, summarize_run
    typer.echo(render_summary(summarize_run(run_dir)), nl=False)


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


@debug_app.command(name="validar-gabarito")
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
