"""Behavioral tests for scripts/renormalize_cases.py.

Focus: the cache-read contract, not the extractor plumbing. The
extractors have their own tests; here we pin the split between
"required tabs" (missing → needs_rescrape) and "optional tabs"
(missing → empty-string placeholder so the extractor no-ops).

Context: TAB_PAUTAS + TAB_DECISOES landed in the v6 schema bump
(commit 1241d22). Any HTML cache archive written before that lacks
those members. A strict all-or-nothing `_read_all_cached` punts every
such case to `needs_rescrape` — even though partes/andamentos/sessão
are sitting in the archive, fully rebuildable.
"""

from __future__ import annotations

import pytest

from scripts import renormalize_cases as rc
from src.utils import html_cache


@pytest.fixture
def iso_cache(tmp_path, monkeypatch):
    """Redirect html_cache at a per-test tmp dir."""
    monkeypatch.setattr(html_cache, "CACHE_ROOT", tmp_path)
    return tmp_path


def _write_required(classe: str, processo: int) -> None:
    html_cache.write_case(
        classe, processo,
        tabs={
            rc.DETALHE: "<html>detalhe</html>",
            rc.TAB_INFORMACOES: "<html>info</html>",
            rc.TAB_PARTES: "<html>partes</html>",
            rc.TAB_ANDAMENTOS: "<html>andamentos</html>",
            rc.TAB_SESSAO: "<html>sessao</html>",
        },
        incidente=999,
    )


# ----- `_read_all_cached` required/optional split --------------------------

def test_read_all_cached_tolerates_missing_pautas(iso_cache):
    _write_required("HC", 1)
    # No abaPautas / abaDecisoes / abaRecursos / abaPeticoes / abaDeslocamentos.
    tabs = rc._read_all_cached("HC", 1)
    assert tabs is not None
    assert tabs[rc.TAB_PAUTAS] == ""
    assert tabs[rc.TAB_DECISOES] == ""
    assert tabs[rc.TAB_RECURSOS] == ""
    assert tabs[rc.TAB_PETICOES] == ""
    assert tabs[rc.TAB_DESLOCAMENTOS] == ""
    assert tabs[rc.DETALHE].startswith("<html>")
    assert tabs[rc.TAB_PARTES].startswith("<html>")


def test_read_all_cached_preserves_existing_optional_tabs(iso_cache):
    html_cache.write_case(
        "HC", 2,
        tabs={
            rc.DETALHE: "<html>detalhe</html>",
            rc.TAB_INFORMACOES: "<html>info</html>",
            rc.TAB_PARTES: "<html>partes</html>",
            rc.TAB_ANDAMENTOS: "<html>andamentos</html>",
            rc.TAB_SESSAO: "<html>sessao</html>",
            rc.TAB_PAUTAS: "<html>pautas real</html>",
        },
        incidente=999,
    )
    tabs = rc._read_all_cached("HC", 2)
    assert tabs is not None
    assert tabs[rc.TAB_PAUTAS] == "<html>pautas real</html>"


@pytest.mark.parametrize(
    "missing_tab",
    [rc.DETALHE, rc.TAB_INFORMACOES, rc.TAB_PARTES,
     rc.TAB_ANDAMENTOS, rc.TAB_SESSAO],
)
def test_read_all_cached_returns_none_when_required_tab_missing(
    iso_cache, missing_tab
):
    tabs = {
        rc.DETALHE: "x", rc.TAB_INFORMACOES: "x", rc.TAB_PARTES: "x",
        rc.TAB_ANDAMENTOS: "x", rc.TAB_SESSAO: "x",
    }
    del tabs[missing_tab]
    html_cache.write_case("HC", 3, tabs=tabs, incidente=999)
    assert rc._read_all_cached("HC", 3) is None


def test_read_all_cached_returns_none_when_archive_absent(iso_cache):
    assert rc._read_all_cached("HC", 404) is None
