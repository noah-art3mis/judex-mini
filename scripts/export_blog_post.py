"""Exporta o relatório HC Famous Lawyers como post pronto para Ghost.

Lê ``analysis/reports/2026-04-19-hc-famous-lawyers.py``, reexecuta
apenas o pipeline de dados (consulta DuckDB + tabela pandas + gráfico
Plotly) e costura a prosa do notebook com o resultado em HTML/Markdown
blog-friendly.

Saída (``exports/hc_famous_lawyers_blog/``):

    post.md                          — narrativa em Markdown + marcadores
    assets/tabela_advogados.html     — tabela styled (great_tables)
    assets/fig_advogados.html        — fragmento Plotly interativo (div + CDN)
    assets/fig_advogados.png         — PNG estático do gráfico (kaleido)
    README.md                        — instruções de publicação

Para publicar no Ghost: crie um post novo, cole o conteúdo de ``post.md``
num *Markdown card*, e onde o arquivo tem marcadores ``GHOST-HTML-CARD``,
insira um *HTML card* com o conteúdo do arquivo referenciado.
"""

from __future__ import annotations

import os
import re
import shutil
import sys
import time
from pathlib import Path
from textwrap import dedent

import pandas as pd
import plotly.express as px
from great_tables import GT, html, loc, style

from judex.analysis.legal_vocab import FGV_FAVORABLE_OUTCOMES as FAV
from judex.warehouse.query import open_readonly

NOTEBOOK = Path("analysis/reports/2026-04-19-hc-famous-lawyers.py")
OUT_DIR = Path("exports/hc_famous_lawyers_blog")
ASSETS_DIR = OUT_DIR / "assets"

FAMOUS = {
    "Alberto Zacharias Toron":     "TORON",
    "Pierpaolo Cruz Bottini":      "PIERPAOLO",
    "Pedro M. de Almeida Castro":  "PEDRO MACHADO DE ALMEIDA CASTRO",
    "Augusto de Arruda Botelho":   "ARRUDA BOTELHO",
    "Marcelo Leonardo":            "MARCELO LEONARDO",
    "Nilo Batista":                "NILO BATISTA",
    "Celso Sanchez Vilardi":       "VILARDI",
    "Roberto Podval":              "PODVAL",
    "Rodrigo Mudrovitsch":         "MUDROVITSCH",
    "Gustavo Badaró":              "BADARO",
    "Daniel Gerber":               "DANIEL GERBER",
    "Tracy J. Reinaldet":          "TRACY JOSEPH REINALDET",
}

OUTCOME_COLS = [
    "concedido", "concedido_parcial", "provido",
    "denegado", "nao_provido",
    "prejudicado", "nao_conhecido",
]

GHOST_MARKER = (
    "<!-- GHOST-HTML-CARD · cole aqui o conteúdo de "
    "assets/fig_advogados.html dentro de um HTML card -->"
)


def extract_prose_cells(src: str) -> list[str]:
    """Puxa cada ``mo.md(r\"\"\"...\"\"\")`` literal do notebook."""
    pattern = re.compile(r'mo\.md\(r"""\n?(.*?)\n?\s*"""\)', re.DOTALL)
    return [dedent(block).strip() for block in pattern.findall(src)]


def build_summary() -> pd.DataFrame:
    con = open_readonly()
    df = con.execute(
        """
        SELECT  p.nome              AS raw_nome,
                c.processo_id       AS processo,
                c.outcome_verdict   AS desfecho
        FROM    cases c
        JOIN    partes p USING (classe, processo_id)
        WHERE   c.classe = 'HC' AND p.tipo = 'IMPTE.(S)'
        """
    ).df()

    rows: list[dict] = []
    for nome, _processo, desfecho in df.itertuples(index=False, name=None):
        up = (nome or "").upper()
        for label, needle in FAMOUS.items():
            if needle in up:
                rows.append({"advogado": label, "desfecho": desfecho})
                break

    cases = pd.DataFrame(rows)
    summary_rows: list[dict] = []
    for label in FAMOUS:
        sub = cases[cases["advogado"] == label]
        counts = sub["desfecho"].value_counts(dropna=False).to_dict()
        none_count = int(counts.pop(None, 0)) if None in counts else 0
        row: dict = {"advogado": label, "total": len(sub)}
        for c in OUTCOME_COLS:
            row[c] = int(counts.get(c, 0))
        row["pendente"] = none_count
        row["finais"] = row["total"] - none_count
        row["favoráveis"] = sum(row[c] for c in FAV if c in row)
        row["% procedência"] = (
            (100 * row["favoráveis"] / row["finais"]) if row["finais"] else float("nan")
        )
        summary_rows.append(row)

    return (
        pd.DataFrame(summary_rows)
        .sort_values("total", ascending=False)
        .reset_index(drop=True)
    )


def build_bar_chart(summary: pd.DataFrame):
    colors = {
        "procedência": "#2e7d32",
        "denegação de mérito": "#c62828",
        "óbice procedimental": "#757575",
        "pendente": "#bdbdbd",
    }
    category_order = [
        "procedência",
        "denegação de mérito",
        "óbice procedimental",
        "pendente",
    ]
    long = summary.assign(
        **{
            "procedência": lambda d: d["concedido"] + d["concedido_parcial"] + d["provido"],
            "denegação de mérito": lambda d: d["denegado"] + d["nao_provido"],
            "óbice procedimental": lambda d: d["nao_conhecido"] + d["prejudicado"],
        }
    )[[
        "advogado", "total",
        "procedência", "denegação de mérito",
        "óbice procedimental", "pendente",
    ]].melt(
        id_vars=["advogado", "total"],
        var_name="categoria",
        value_name="HCs",
    )
    order_asc = summary.sort_values("total")["advogado"].tolist()
    fig = px.bar(
        long,
        x="HCs",
        y="advogado",
        color="categoria",
        orientation="h",
        category_orders={"advogado": order_asc, "categoria": category_order},
        color_discrete_map=colors,
        title="Desfechos dos HCs por advogado (barra empilhada, contagem absoluta)",
    )
    fig.update_layout(
        barmode="stack",
        xaxis_title="número de HCs",
        yaxis_title="",
        legend_title="",
        height=440,
        margin=dict(l=10, r=10, t=60, b=40),
    )
    return fig


def _compact_summary(summary: pd.DataFrame) -> pd.DataFrame:
    """Reduz o famous_summary para as colunas usadas no post."""
    return summary.assign(
        **{
            "procedência": lambda d: d["concedido"] + d["concedido_parcial"] + d["provido"],
            "denegação": lambda d: d["denegado"] + d["nao_provido"],
            "óbice": lambda d: d["nao_conhecido"] + d["prejudicado"],
        }
    )[[
        "advogado", "total",
        "procedência", "denegação", "óbice",
        "pendente", "finais", "% procedência",
    ]].copy()


def _ghost_jwt(admin_key: str) -> str:
    """Gera um JWT HS256 curto para autenticar na Ghost Admin API.

    A chave vem no formato ``<id>:<secret_hex>``; o ``kid`` vai no
    header, e o payload exige ``aud='/admin/'`` e uma janela curta
    (Ghost rejeita tokens com ``exp`` > 5 min).
    """
    import jwt  # import local — só roda quando há GHOST_ADMIN_KEY configurado

    key_id, secret_hex = admin_key.split(":")
    secret_bytes = bytes.fromhex(secret_hex)
    iat = int(time.time())
    payload = {"iat": iat, "exp": iat + 5 * 60, "aud": "/admin/"}
    return jwt.encode(
        payload, secret_bytes, algorithm="HS256", headers={"kid": key_id}
    )


def upload_png_to_ghost(
    png_path: Path, admin_key: str, blog_url: str
) -> str | None:
    """POST a PNG em ``/admin/images/upload/``; devolve a URL do CDN ou ``None``.

    Falha graciosamente — qualquer exceção resulta em ``None`` + log em
    stderr, e o chamador pode manter o caminho relativo original no
    ``post.md``.
    """
    import requests

    try:
        token = _ghost_jwt(admin_key)
    except Exception as exc:  # noqa: BLE001
        print(f"  ghost jwt falhou: {exc}", file=sys.stderr)
        return None

    endpoint = f"{blog_url.rstrip('/')}/ghost/api/admin/images/upload/"
    headers = {"Authorization": f"Ghost {token}"}
    try:
        with png_path.open("rb") as fp:
            r = requests.post(
                endpoint,
                headers=headers,
                files={"file": (png_path.name, fp, "image/png")},
                data={"purpose": "image", "ref": png_path.name},
                timeout=30,
            )
        r.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        print(f"  ghost upload falhou: {exc}", file=sys.stderr)
        return None

    try:
        return r.json()["images"][0]["url"]
    except (KeyError, ValueError, IndexError) as exc:
        print(f"  ghost response malformado: {exc}", file=sys.stderr)
        return None


def summary_to_gt_html(summary: pd.DataFrame) -> str:
    """Renderiza a tabela como HTML styled via great_tables."""
    compact = _compact_summary(summary)
    total = int(compact["total"].sum())
    finais = int(compact["finais"].sum())
    favor = int((compact["procedência"]).sum())
    overall_pct = 100 * favor / finais if finais else float("nan")

    gt = (
        GT(compact)
        .tab_header(
            title=html(
                "<span style='font-weight:600'>Desfechos dos HCs por advogado</span>"
            ),
            subtitle=(
                f"{len(compact)} advogados · {total} HCs no recorte · "
                f"{favor}/{finais} favoráveis = {overall_pct:.1f}%"
            ),
        )
        .cols_label(
            advogado="",
            total="total",
            procedência="procedência",
            denegação="denegação",
            **{"óbice": "óbice"},
            pendente="pendente",
            finais="finais",
            **{"% procedência": "% proc."},
        )
        .tab_spanner(label="volume", columns=["total", "finais", "pendente"])
        .tab_spanner(
            label="desfechos (contagem bruta)",
            columns=["procedência", "denegação", "óbice"],
        )
        .fmt_number(
            columns=["total", "procedência", "denegação", "óbice", "pendente", "finais"],
            decimals=0,
        )
        .fmt_percent(
            columns=["% procedência"],
            scale_values=False,
            decimals=1,
        )
        .sub_missing(columns=["% procedência"], missing_text="—")
        .data_color(
            columns=["% procedência"],
            palette=["#ffffff", "#c8e6c9", "#2e7d32"],
            domain=[0, 25],
            na_color="#ffffff",
        )
        .tab_style(
            style=style.text(weight="bold"),
            locations=loc.body(columns=["advogado"]),
        )
        .tab_source_note(
            source_note=html(
                "Fonte: <code>data/warehouse/judex.duckdb</code> · "
                "consulta <code>cases ⋈ partes</code> onde "
                "<code>tipo = 'IMPTE.(S)'</code>. "
                "<code>procedência</code> soma "
                "<code>concedido + concedido_parcial + provido</code>; "
                "<code>óbice</code> soma "
                "<code>não_conhecido + prejudicado</code>. "
                "<code>% proc.</code> = favoráveis ÷ finais (exclui pendentes)."
            ),
        )
        .tab_source_note(
            source_note=html(
                "Nota: HC 138.862 (Toron/Patriota) entra como "
                "<code>concedido</code> no parser mas é ajuste sumular de "
                "regime, não vitória defensiva clássica — a coluna "
                "<b>% proc.</b> está inflada nessa linha."
            ),
        )
        .opt_table_font(font="system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif")
        .opt_horizontal_padding(scale=1.2)
    )
    return gt.as_raw_html()


README_BODY = """# hc_famous_lawyers — pacote blog-ready

Exportado por `scripts/export_blog_post.py`. Contém:

- `post.md` — narrativa em Markdown. Tem dois marcadores
  `GHOST-HTML-CARD` indicando onde inserir HTML cards.
- `assets/tabela_advogados.html` — tabela styled (great_tables).
- `assets/fig_advogados.html` — gráfico Plotly interativo (CDN).
- `assets/fig_advogados.png` — PNG estático do gráfico (fallback).

## Publicando no Ghost

1. Post novo → *Markdown card* com o conteúdo de `post.md`.
2. No primeiro marcador: *HTML card* com `assets/tabela_advogados.html`.
3. No segundo marcador: *HTML card* com `assets/fig_advogados.html`.
4. **PNG do gráfico** — a referência em `post.md` depende de como a
   exportação rodou:
   - **Se `GHOST_ADMIN_KEY` + `GHOST_URL` estavam no ambiente**, o
     script fez upload do PNG via Ghost Admin API antes de gravar o
     `post.md`; a referência Markdown já aponta para a URL de CDN
     (`https://<blog>/content/images/.../fig_advogados.png`) e a imagem
     renderiza direto.
   - **Sem as credenciais**, a referência é relativa
     (`assets/fig_advogados.png`), que Ghost não resolve. Fluxo manual:
     clicar no ícone quebrado → upload → Ghost devolve uma URL de CDN
     → a referência Markdown se autocorrige. Alternativa: apagar a
     linha se só o gráfico interativo interessar.

Os dois arquivos `.html` de `assets/` são fragmentos auto-suficientes —
CSS inline na tabela, Plotly via CDN no gráfico. Não há dependências
externas além de JS do Plotly (e essa só para o plot interativo).

## Pré-linkando o PNG

Ghost Admin API exige um staff API key
(`Settings → Integrations → Add custom integration`). Formato da chave:
`<id>:<secret_hex>`. Exportar antes de rodar o script:

    export GHOST_ADMIN_KEY='abc123:d4e5f6...'
    export GHOST_URL='https://seublog.ghost.io'
    uv run python scripts/export_blog_post.py

O script imprime `ghost upload  ok → <url>` quando o upload funciona.
Em caso de falha (JWT inválido, 401, timeout) mantém o caminho
relativo — o fluxo manual acima continua funcionando como fallback.
"""


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)

    src = NOTEBOOK.read_text(encoding="utf-8")
    prose = extract_prose_cells(src)
    if len(prose) != 6:
        raise SystemExit(
            f"esperava 6 blocos mo.md(r\"\"\"...\"\"\"), encontrei {len(prose)} "
            f"em {NOTEBOOK}. Algum bloco foi reescrito?"
        )

    summary = build_summary()
    fig = build_bar_chart(summary)

    # Números vivos do warehouse para a nota metodológica — o snapshot
    # congelado no texto é de 2026-04-18 (53.816 HCs, 183 na banca).
    con = open_readonly()
    live_total_hcs = con.execute(
        "SELECT COUNT(*) FROM cases WHERE classe='HC'"
    ).fetchone()[0]
    live_banca_hcs = int(summary["total"].sum())

    # Tabela styled (great_tables) — HTML card fragment
    table_html_path = ASSETS_DIR / "tabela_advogados.html"
    table_html_path.write_text(summary_to_gt_html(summary), encoding="utf-8")

    # Gráfico interativo (Plotly + CDN) — HTML card fragment
    fig_html_path = ASSETS_DIR / "fig_advogados.html"
    fig_html_path.write_text(
        fig.to_html(include_plotlyjs="cdn", full_html=False, div_id="fig-advogados"),
        encoding="utf-8",
    )

    # PNG fallback (kaleido). Falha graciosamente se o kaleido não conseguir
    # iniciar o Chromium — o fragmento HTML interativo continua sendo o ativo
    # primário.
    fig_png_path = ASSETS_DIR / "fig_advogados.png"
    try:
        fig.write_image(fig_png_path, width=960, height=540, scale=2)
        png_note = f"{fig_png_path.stat().st_size / 1024:.1f} KB"
    except Exception as exc:  # noqa: BLE001
        png_note = f"falhou ({type(exc).__name__}: {exc})"
        fig_png_path = None  # não referenciar no post.md se falhou

    total_casos = int(summary["total"].sum())

    table_block = (
        "\n\n---\n\n"
        "## Tabela por advogado (build ao vivo)\n\n"
        f"*Total de HCs no recorte: {total_casos}. Tabela gerada por "
        f"`great_tables` — cor de fundo na última coluna é heatmap da "
        f"taxa de procedência (0 % branco → 25 % verde).*\n\n"
        f"{GHOST_MARKER}\n\n"
        "> **Tabela 1.** Distribuição de desfechos por advogado. Versão\n"
        "> styled em `assets/tabela_advogados.html` — colar num *HTML card*\n"
        "> do Ghost.\n"
    )

    if fig_png_path is not None:
        fig_block = (
            "\n\n---\n\n"
            "## Gráfico interativo\n\n"
            f"{GHOST_MARKER}\n\n"
            "> **Figura 1.** Desfechos dos HCs por advogado — barra\n"
            "> horizontal empilhada, ordenada por volume. Versão interativa\n"
            "> em `assets/fig_advogados.html` (Plotly via CDN, mantém\n"
            "> hover/zoom/seleção na legenda). PNG estático de fallback:\n"
            f"> `assets/{fig_png_path.name}`.\n\n"
            f"![Desfechos dos HCs por advogado](assets/{fig_png_path.name})\n"
        )
    else:
        fig_block = (
            "\n\n---\n\n"
            "## Gráfico interativo\n\n"
            f"{GHOST_MARKER}\n\n"
            "> **Figura 1.** Desfechos dos HCs por advogado. Versão\n"
            "> interativa em `assets/fig_advogados.html` — colar num\n"
            "> *HTML card* do Ghost.\n"
        )

    # Número PT-BR: 79742 → "79.742" (troca vírgula do locale en-US por ponto)
    live_total_fmt = f"{live_total_hcs:,}".replace(",", ".")
    methodology_callout = (
        "> **Nota metodológica.** A leitura interpretativa abaixo foi redigida\n"
        "> no snapshot de **2026-04-18 (53.816 HCs no corpus, 183 no recorte\n"
        "> da banca)**. A tabela e o gráfico são reconsultados ao vivo contra\n"
        f"> o warehouse atual (**{live_total_fmt} HCs no corpus, "
        f"{live_banca_hcs} no recorte**) — os números exatos no texto podem\n"
        "> divergir da tabela. As diferenças em geral *reforçam* as conclusões\n"
        "> qualitativas (ver rodapé da tabela para a ressalva do HC 138.862).\n"
    )

    parts = [
        methodology_callout, # ← callout no topo (live/frozen asymmetry)
        prose[0],            # intro + conclusão executiva
        table_block,         # ← tabela styled
        fig_block,           # ← gráfico interativo (+ PNG fallback)
        prose[1],            # perfil de desfechos
        prose[2],            # três agrupamentos
        prose[3],            # Toron vs. Pierpaolo
        prose[4],            # leituras selecionadas
        prose[5],            # links das peças
    ]
    post_path = OUT_DIR / "post.md"
    post_path.write_text("\n\n".join(parts).rstrip() + "\n", encoding="utf-8")

    (OUT_DIR / "README.md").write_text(README_BODY, encoding="utf-8")

    # Upload opcional do PNG para Ghost, se credenciais presentes. Quando
    # funciona, reescreve a referência Markdown do PNG em post.md com a
    # URL do CDN devolvida pela Ghost Admin API — a imagem já aparece
    # pré-linkada no post, sem precisar do ritual "clicar na imagem
    # quebrada → upload → URL se autocorrige".
    admin_key = os.environ.get("GHOST_ADMIN_KEY", "").strip()
    blog_url = os.environ.get("GHOST_URL", "").strip()
    ghost_note = "pulado (sem GHOST_ADMIN_KEY / GHOST_URL)"
    if admin_key and blog_url and fig_png_path is not None:
        cdn_url = upload_png_to_ghost(fig_png_path, admin_key, blog_url)
        if cdn_url:
            post_text = post_path.read_text(encoding="utf-8")
            relative_ref = f"assets/{fig_png_path.name}"
            if relative_ref in post_text:
                post_path.write_text(
                    post_text.replace(relative_ref, cdn_url), encoding="utf-8"
                )
                ghost_note = f"ok → {cdn_url}"
            else:
                ghost_note = (
                    f"upload ok mas referência '{relative_ref}' não "
                    "encontrada em post.md"
                )
        else:
            ghost_note = "falhou (ver stderr); caminho relativo mantido"

    # Zip do bundle inteiro para envio manual. shutil.make_archive devolve
    # o caminho com a extensão já embutida.
    zip_base = OUT_DIR.parent / OUT_DIR.name
    zip_path = Path(
        shutil.make_archive(
            base_name=str(zip_base),
            format="zip",
            root_dir=str(OUT_DIR.parent),
            base_dir=OUT_DIR.name,
        )
    )

    def _kb(p: Path) -> str:
        return f"{p.stat().st_size / 1024:.1f} KB"

    print(f"post.md                       {_kb(post_path)}")
    print(f"assets/tabela_advogados.html  {_kb(table_html_path)}")
    print(f"assets/fig_advogados.html     {_kb(fig_html_path)}")
    print(f"assets/fig_advogados.png      {png_note}")
    print(f"README.md                     {_kb(OUT_DIR / 'README.md')}")
    print(f"{zip_path.name:<30}{_kb(zip_path)}")
    print(f"ghost upload                  {ghost_note}")
    print(f"tabela: {len(summary)} advogados · {len(prose)} blocos de prosa.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
