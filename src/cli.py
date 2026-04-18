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
    uv run judex varrer-pdfs --saida out/ --classe HC --impte-contem TORON
    uv run judex varrer-pdfs --saida out/ --classe HC --ocr --min-caracteres 5000
    uv run judex exportar --apenas hc_famous_lawyers
    uv run judex sondar-densidade --classe HC --amostras 20
"""

from __future__ import annotations

import csv as _csv
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import typer

from src.utils.validation import (
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
    janela_circuit: int = typer.Option(
        50, "--janela-circuit",
        help="Janela rolante do disjuntor (circuit breaker). 0 desliga.",
    ),
    diretorio_itens: Optional[Path] = typer.Option(
        None, "--diretorio-itens",
        help="Grava um judex-mini_<CLASSE>_<n>-<n>.json por processo ok aqui.",
    ),
    limiar_circuit: float = typer.Option(
        0.8, "--limiar-circuit",
        help="Fração não-ok da janela que dispara o disjuntor.",
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
        help="Arquivo com uma URL de proxy por linha; habilita rotação proativa.",
    ),
    proxy_rotacao_segundos: float = typer.Option(
        270.0, "--proxy-rotacao-segundos",
        help="Segundos usando cada proxy antes de rotacionar (padrão 270 = 4,5 min).",
    ),
    proxy_cooldown_minutos: float = typer.Option(
        4.0, "--proxy-cooldown-minutos",
        help="Minutos que um proxy recém-usado permanece fora de rotação.",
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

        # Grava o CSV persistente dentro de --saida (não em /tmp): fica
        # auditável ao lado dos demais artefatos da varredura.
        tmp_csv = saida / "input.csv"
        with tmp_csv.open("w", encoding="utf-8", newline="") as fp:
            writer = _csv.writer(fp)
            writer.writerow(["classe", "processo"])
            for p in range(processo_inicial, processo_final + 1):
                writer.writerow([classe.upper(), p])
        csv = tmp_csv

        typer.echo(
            f"Modo range: {classe} {processo_inicial}..{processo_final} "
            f"({processo_final - processo_inicial + 1} processo(s)). "
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
    _push(argv, "--circuit-window", janela_circuit)
    _push(argv, "--items-dir", diretorio_itens)
    _push(argv, "--circuit-threshold", limiar_circuit)
    _push(argv, "--cliff-window", janela_cliff)
    _push(argv, "--no-stop-on-collapse", ignorar_collapse)
    _push(argv, "--proxy-pool", proxy_pool)
    _push(argv, "--proxy-rotate-seconds", proxy_rotacao_segundos)
    _push(argv, "--proxy-cooldown-minutes", proxy_cooldown_minutos)

    from scripts.run_sweep import main as _run_sweep_main

    raise typer.Exit(code=_run_sweep_main(argv))


# ---------------------------------------------------------------------------
# `pdfs` — baixa PDFs das peças; ``--ocr`` comuta para reextração via Unstructured


@app.command(name="varrer-pdfs")
def varrer_pdfs(
    saida: Path = typer.Option(
        ..., "--saida",
        help="Diretório de saída: pdfs.state.json, pdfs.log.jsonl, "
             "pdfs.errors.jsonl, requests.db, report.md.",
    ),
    ocr: bool = typer.Option(
        False, "--ocr",
        help="**Só OCR** (API Unstructured), sem passar pelo extrator "
             "padrão. Reextrai entradas de cache com texto menor que "
             "--min-caracteres; requer UNSTRUCTURED_API_KEY no ambiente. "
             "Mutuamente exclusivo com --ocr-resgate.",
    ),
    ocr_resgate: bool = typer.Option(
        True, "--ocr-resgate/--sem-ocr-resgate",
        help="**Duas passagens** (padrão): primeiro pypdf (baixa e extrai), "
             "depois OCR Unstructured nas entradas cujo texto ficou abaixo "
             "de --min-caracteres (decisões escaneadas). Use "
             "--sem-ocr-resgate para pular a segunda passagem e ficar só "
             "com o pypdf. Requer UNSTRUCTURED_API_KEY para a segunda "
             "passagem (sem a chave, a segunda passagem é pulada com aviso).",
    ),
    raizes: list[Path] = typer.Option(
        None, "--raizes",
        help="Diretórios varridos em busca de judex-mini_*.json. "
             "Padrão: data/output, data/output/sample.",
    ),
    classe: Optional[str] = typer.Option(
        None, "--classe",
        help='Casar classe exata, p.ex. "HC", "RE", "ADI".',
    ),
    impte_contem: str = typer.Option(
        "", "--impte-contem",
        help="Substrings separadas por vírgula (qualquer uma casa) para "
             'casar em partes[].nome onde tipo == "IMPTE.(S)".',
    ),
    tipos_doc: str = typer.Option(
        "", "--tipos-doc",
        help="Valores exatos de andamento.link_descricao, separados por "
             'vírgula (ex.: "DECISÃO MONOCRÁTICA,INTEIRO TEOR DO ACÓRDÃO"). '
             "Vazio = todos os tipos.",
    ),
    relator_contem: str = typer.Option(
        "", "--relator-contem",
        help="Substrings separadas por vírgula para casar em .relator.",
    ),
    excluir_tipos_doc: str = typer.Option(
        "", "--excluir-tipos-doc",
        help="Tipos de doc a pular, separados por vírgula. Aplicado depois "
             "de --tipos-doc.",
    ),
    sleep_throttle: float = typer.Option(
        2.0, "--sleep-throttle",
        help="Segundos entre GETs sucessivos.",
    ),
    limite: int = typer.Option(
        0, "--limite",
        help="Trunca a lista de alvos em N entradas (0 = sem limite).",
    ),
    retomar: bool = typer.Option(
        False, "--retomar",
        help="Pula alvos já marcados como status=ok.",
    ),
    retentar_de: Optional[Path] = typer.Option(
        None, "--retentar-de",
        help="Caminho para um pdfs.errors.jsonl existente; reroda só essas URLs.",
    ),
    janela_circuit: int = typer.Option(
        50, "--janela-circuit",
        help="Janela rolante do disjuntor (0 desliga).",
    ),
    limiar_circuit: float = typer.Option(
        0.8, "--limiar-circuit",
        help="Fração de erros na janela que dispara o disjuntor.",
    ),
    simular: bool = typer.Option(
        False, "--simular",
        help="Imprime contagem de alvos + breakdown por tipo de doc e sai.",
    ),
    # flags que só fazem sentido no modo padrão (pypdf):
    throttle_adaptativo: bool = typer.Option(
        True, "--throttle-adaptativo/--sem-throttle",
        help="[modo pypdf] Throttle adaptativo por host.",
    ),
    throttle_max_segundos: float = typer.Option(
        60.0, "--throttle-max-segundos",
        help="[modo pypdf] Teto do sleep adaptativo por GET.",
    ),
    verificar: bool = typer.Option(
        False, "--verificar",
        help="[modo pypdf] Relata cobertura de cache (cacheado vs. faltando) e sai.",
    ),
    # flags que só fazem sentido no modo OCR:
    min_caracteres: int = typer.Option(
        1000, "--min-caracteres",
        help="[modo --ocr] Reextrai entradas de cache com texto menor que "
             "este tamanho.",
    ),
    estrategia: str = typer.Option(
        "hi_res", "--estrategia",
        help="[modo --ocr] Estratégia do Unstructured: hi_res, ocr_only, "
             "fast ou auto.",
    ),
    forcar: bool = typer.Option(
        False, "--forcar",
        help="[modo --ocr] Reextrai mesmo quando o cache atual ≥ --min-caracteres.",
    ),
) -> None:
    """Baixa os PDFs das peças (decisão, acórdão, manifestação da PGR).

    Três modos:

    - **Padrão** (sem flag): **duas passagens**. Roda o ``pypdf``
      primeiro, filtrando pelos critérios (classe, impetrante,
      tipos de doc, relator); em seguida faz uma segunda passagem
      pela API Unstructured (``hi_res``) **só** nas entradas cujo
      texto extraído ficou abaixo de ``--min-caracteres`` — alvo
      clássico do OCR, as decisões escaneadas. Rápido por padrão,
      cai no OCR só quando precisa. Requer ``UNSTRUCTURED_API_KEY``
      no ambiente para a segunda passagem; sem a chave a segunda
      passagem é pulada com aviso e os resultados do ``pypdf``
      permanecem.

    - ``--sem-ocr-resgate``: **só pypdf**, uma passagem. Útil para
      sessões rápidas onde não faz sentido pagar OCR (ex.: só
      verificar cache, ou rodar com ``--simular``).

    - ``--ocr``: **só OCR**. Pula o ``pypdf`` e vai direto à
      reextração via Unstructured sobre as entradas de cache
      curtas. Útil quando o ``pypdf`` já rodou em uma sessão
      anterior e só as escaneadas faltam.

    O cache em ``data/pdf/<sha1(url)>.txt.gz`` é **monotônico por
    tamanho**: só sobrescreve quando a saída nova é maior que a
    atual. ``--ocr`` e ``--ocr-resgate`` são mutuamente exclusivos.
    """
    # valida combinações
    if ocr and ocr_resgate:
        raise typer.BadParameter(
            "--ocr (só OCR) e --ocr-resgate (pypdf + OCR) são mutuamente "
            "exclusivos. Escolha um."
        )
    if ocr and verificar:
        raise typer.BadParameter(
            "--verificar é do modo padrão (pypdf); não combina com --ocr."
        )
    if (ocr or ocr_resgate) and estrategia not in {"hi_res", "ocr_only", "fast", "auto"}:
        raise typer.BadParameter(
            f"estratégia inválida {estrategia!r}; "
            "escolha entre hi_res, ocr_only, fast, auto."
        )

    # argv comum aos dois extratores
    def _argv_comum() -> list[str]:
        a: list[str] = ["--out", str(saida)]
        if raizes:
            a.append("--roots")
            a.extend(str(r) for r in raizes)
        _push(a, "--classe", classe)
        _push(a, "--impte-contains", impte_contem)
        _push(a, "--doc-types", tipos_doc)
        _push(a, "--relator-contains", relator_contem)
        _push(a, "--exclude-doc-types", excluir_tipos_doc)
        _push(a, "--throttle-sleep", sleep_throttle)
        _push(a, "--limit", limite)
        _push(a, "--resume", retomar)
        _push(a, "--retry-from", retentar_de)
        _push(a, "--circuit-window", janela_circuit)
        _push(a, "--circuit-threshold", limiar_circuit)
        _push(a, "--dry-run", simular)
        return a

    # Modo só-OCR: pula pypdf, vai direto à reextração
    if ocr:
        argv = _argv_comum()
        _push(argv, "--min-chars", min_caracteres)
        _push(argv, "--strategy", estrategia)
        _push(argv, "--force", forcar)
        from scripts.reextract_unstructured import main as _reextract_main
        raise typer.Exit(code=_reextract_main(argv))

    # Modo padrão ou primeira passagem do resgate: pypdf
    argv_pypdf = _argv_comum()
    if not throttle_adaptativo:  # argparse do script usa --no-throttle
        argv_pypdf.append("--no-throttle")
    _push(argv_pypdf, "--throttle-max-delay", throttle_max_segundos)
    _push(argv_pypdf, "--check", verificar)

    from scripts.fetch_pdfs import main as _fetch_pdfs_main

    saida_pypdf = _fetch_pdfs_main(argv_pypdf)

    if not ocr_resgate:
        raise typer.Exit(code=saida_pypdf)

    # --ocr-resgate: segunda passagem OCR sobre as entradas curtas
    # (pula se a primeira foi dry-run ou falhou sem gerar cache)
    if simular:
        raise typer.Exit(code=saida_pypdf)

    # A segunda passagem depende da API da Unstructured. Se a chave não
    # está no ambiente (nem via .env), pulamos com aviso em vez de
    # deixar o script filho falhar com exit 2 — a primeira passagem já
    # produziu os artefatos duráveis em --saida.
    from dotenv import load_dotenv
    load_dotenv()
    if not os.environ.get("UNSTRUCTURED_API_KEY"):
        typer.secho(
            "\nAviso: UNSTRUCTURED_API_KEY não está no ambiente (nem via "
            f".env). Pulando o resgate OCR — os resultados do pypdf estão "
            f"preservados em {saida}. Para habilitar a segunda passagem, "
            "defina a chave; para silenciar este aviso, passe "
            "--sem-ocr-resgate.",
            fg=typer.colors.YELLOW,
        )
        raise typer.Exit(code=saida_pypdf)

    typer.echo(
        f"\n=== Resgate OCR: reextraindo entradas com texto < "
        f"{min_caracteres} caracteres ==="
    )
    argv_ocr = _argv_comum()
    _push(argv_ocr, "--min-chars", min_caracteres)
    _push(argv_ocr, "--strategy", estrategia)
    _push(argv_ocr, "--force", forcar)
    from scripts.reextract_unstructured import main as _reextract_main

    saida_ocr = _reextract_main(argv_ocr)

    raise typer.Exit(code=max(saida_pypdf, saida_ocr))


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
    from scripts.validate_ground_truth import main as _vgt_main

    raise typer.Exit(code=_vgt_main())


# ---------------------------------------------------------------------------
# `sondar-densidade` — sondagem estratificada de densidade de process_id


@app.command(name="sondar-densidade")
def sondar_densidade(
    classe: str = typer.Option(
        ..., "--classe",
        help="Código da classe do STF (HC, ADI, RE, ...).",
    ),
    teto: Optional[int] = typer.Option(
        None, "--teto",
        help="Maior process_id a considerar. Assume o teto conhecido para "
             "HC/ADI/RE; obrigatório para outras classes.",
    ),
    faixas: int = typer.Option(
        8, "--faixas",
        help="Número de faixas (bands).",
    ),
    amostras: int = typer.Option(
        15, "--amostras",
        help="Amostras aleatórias por faixa.",
    ),
    pacing: float = typer.Option(
        1.5, "--pacing",
        help="Segundos entre sondagens.",
    ),
    seed: int = typer.Option(20260416, "--seed"),
) -> None:
    """Sondagem estratificada de densidade de process_ids por classe do STF."""
    argv: list[str] = ["class_density_probe", "--classe", classe]
    _push(argv, "--ceiling", teto)
    _push(argv, "--bands", faixas)
    _push(argv, "--samples", amostras)
    _push(argv, "--pacing", pacing)
    _push(argv, "--seed", seed)

    from scripts import class_density_probe as _dp

    argv_original = sys.argv
    sys.argv = argv
    try:
        _dp.main()
    finally:
        sys.argv = argv_original


if __name__ == "__main__":
    app()
