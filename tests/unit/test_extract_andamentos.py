"""Tests for `extract_andamentos` — specifically the link shape.

Andamento links now carry both URL and (nullable) OCR text, matching
the `sessao_virtual.documentos` shape: `{"url": str, "text": str | None}`
when a PDF anchor is present, or `None` when the row has no link.
"""

from __future__ import annotations

from src.scraping.extraction.tables import extract_andamentos


SINGLE_ROW_WITH_LINK = """
<div class="processo-andamentos">
  <div class="andamento-item">
    <div class="andamento-inner">
      <div class="message-head">
        <div class="andamento-detalhe">
          <div class="col-md-3 p-l-0">
            <div class="andamento-data">17/08/2020</div>
          </div>
          <div class="col-md-5 p-l-0">
            <h5 class="andamento-nome">PUBLICADO ACÓRDÃO, DJE</h5>
          </div>
          <div class="col-md-4 andamento-docs">
            <a href="downloadPeca.asp?id=15344016231&ext=.pdf" target="_blank">
              <i class="far fa-file-alt"></i> Inteiro Teor do Acórdão
            </a>
          </div>
          <div class="col-md-9 p-0">DATA DE PUBLICAÇÃO DJE 17/08/2020</div>
        </div>
      </div>
    </div>
  </div>
</div>
"""

SINGLE_ROW_NO_LINK = """
<div class="processo-andamentos">
  <div class="andamento-item">
    <div class="andamento-inner">
      <div class="message-head">
        <div class="andamento-detalhe">
          <div class="col-md-3 p-l-0">
            <div class="andamento-data">20/08/2020</div>
          </div>
          <div class="col-md-5 p-l-0">
            <h5 class="andamento-nome">PETIÇÃO</h5>
          </div>
          <div class="col-md-4 andamento-docs"></div>
          <div class="col-md-9 p-0">PROCURADOR-GERAL DA REPÚBLICA</div>
        </div>
      </div>
    </div>
  </div>
</div>
"""


def test_extract_andamentos_link_has_url_and_null_text_when_present():
    [row] = extract_andamentos(SINGLE_ROW_WITH_LINK)
    assert row["link"] == {
        "url": "https://portal.stf.jus.br/processos/downloadPeca.asp?id=15344016231&ext=.pdf",
        "text": None,
    }
    # Human-readable anchor text is kept in link_descricao as before.
    assert row["link_descricao"] == "INTEIRO TEOR DO ACÓRDÃO"


def test_extract_andamentos_link_is_none_when_no_anchor():
    [row] = extract_andamentos(SINGLE_ROW_NO_LINK)
    assert row["link"] is None
    assert row["link_descricao"] is None
