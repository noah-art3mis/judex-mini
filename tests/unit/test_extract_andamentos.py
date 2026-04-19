"""Tests for `extract_andamentos` — specifically the link shape.

Schema v5 unifies the andamento link shape with `Documento`:
`{"tipo": str | None, "url": str | None, "text": str | None,
"extractor": str | None}` when a PDF anchor is present, or `None`
when the row has no anchor at all. `link_descricao` as a sibling
field is gone — the anchor label lives in `link.tipo`. Under
option 2 of the v5 design, anchors with visible text but no href
still materialise a link dict (url=None) so the tipo info is not
lost on broken STF markup.
"""

from __future__ import annotations

from judex.scraping.extraction.tables import extract_andamentos


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


def test_extract_andamentos_link_has_tipo_url_null_text_when_present():
    [row] = extract_andamentos(SINGLE_ROW_WITH_LINK)
    # v5: tipo (the anchor label) lives inside link; no sibling field.
    assert row["link"] == {
        "tipo":      "INTEIRO TEOR DO ACÓRDÃO",
        "url":       "https://portal.stf.jus.br/processos/downloadPeca.asp?id=15344016231&ext=.pdf",
        "text":      None,
        "extractor": None,
    }
    assert "link_descricao" not in row


def test_extract_andamentos_link_is_none_when_no_anchor():
    [row] = extract_andamentos(SINGLE_ROW_NO_LINK)
    assert row["link"] is None
    assert "link_descricao" not in row


def test_extract_andamentos_link_tipo_without_url_when_anchor_has_no_href():
    """Option 2: an anchor with visible text but no href still round-trips.

    STF sometimes renders anchors without href (broken markup). The v5
    shape keeps `tipo` usable by materialising the link dict with
    url=None — losing the label would be strictly worse than carrying
    a null url.
    """
    html = """
    <div class="processo-andamentos">
      <div class="andamento-item">
        <div class="andamento-detalhe">
          <div class="andamento-data">01/01/2020</div>
          <h5 class="andamento-nome">DESPACHO</h5>
          <div class="col-md-4 andamento-docs">
            <a><i class="far fa-file-alt"></i> Inteiro Teor</a>
          </div>
        </div>
      </div>
    </div>
    """
    [row] = extract_andamentos(html)
    assert row["link"] == {
        "tipo":      "INTEIRO TEOR",
        "url":       None,
        "text":      None,
        "extractor": None,
    }


def test_extract_andamentos_emits_iso_date_in_data_field():
    # v6: the raw DD/MM/YYYY display string is gone; the plain `data`
    # field now carries ISO 8601 directly (no `data_iso` companion).
    [row] = extract_andamentos(SINGLE_ROW_WITH_LINK)
    assert row["data"] == "2020-08-17"
    assert "data_iso" not in row
