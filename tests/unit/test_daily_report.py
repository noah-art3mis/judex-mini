"""Daily report renderer: list[StfItem-shaped dict] → markdown string.

Pins down: header format, empty-day placeholder, basic-info fields per
case (numero / incidente / relator / primeiro_autor / data_protocolo /
origem / partes / assuntos), stable ordering by processo_id, and graceful
handling of None-valued optional fields.
"""

from __future__ import annotations

from judex.reports.daily import WatchedCaseChange, render_daily_markdown
from judex.reports.watch_diff import WatchChange


def _bare_case(**overrides: object) -> dict:
    """Minimal StfItem-shaped dict with only fields the renderer reads.

    Real StfItem has ~25 fields; we only materialize what the renderer
    touches so tests stay legible.
    """
    base: dict = {
        "classe": "HC",
        "processo_id": 271140,
        "incidente": 7567814,
        "url": "https://portal.stf.jus.br/processos/detalhe.asp?incidente=7567814",
        "relator": "Min. Fulano de Tal",
        "primeiro_autor": "João da Silva",
        "data_protocolo": "2026-04-19",
        "origem": "TJSP",
        "assuntos": ["Direito Penal", "Habeas Corpus"],
        "partes": [
            {"index": 0, "tipo": "IMPTE", "nome": "Defensoria Pública"},
            {"index": 1, "tipo": "PACTE", "nome": "João da Silva"},
            {"index": 2, "tipo": "IMPTDO", "nome": "Relator do REsp no STJ"},
        ],
    }
    base.update(overrides)
    return base


def test_empty_day_renders_header_and_placeholder() -> None:
    md = render_daily_markdown(
        [],
        date="2026-04-20",
        classe="HC",
        stats={"n_probed": 20, "duration_s": 5.2},
    )

    assert "# STF HC Daily — 2026-04-20" in md
    assert "0" in md  # count of new filings
    # Some indication there's nothing to report — exact wording flexible
    # but must not silently produce a case-list.
    assert "no new filings" in md.lower() or "nenhum" in md.lower()


def test_renders_basic_info_for_single_filing() -> None:
    md = render_daily_markdown(
        [_bare_case()],
        date="2026-04-20",
        classe="HC",
        stats={},
    )

    # Identity
    assert "HC 271140" in md
    assert "7567814" in md  # incidente
    # Key people
    assert "Min. Fulano de Tal" in md
    assert "João da Silva" in md
    # Origin + date
    assert "TJSP" in md
    assert "2026-04-19" in md
    # At least one parte role is surfaced
    assert "IMPTE" in md or "Defensoria Pública" in md


def test_cases_sorted_by_processo_id_ascending() -> None:
    """Stable ordering — numero ascending — regardless of input order."""
    cases = [
        _bare_case(processo_id=271142, incidente=7567820),
        _bare_case(processo_id=271140, incidente=7567814),
        _bare_case(processo_id=271141, incidente=7567817),
    ]

    md = render_daily_markdown(cases, date="2026-04-20", classe="HC", stats={})

    i_140 = md.index("HC 271140")
    i_141 = md.index("HC 271141")
    i_142 = md.index("HC 271142")
    assert i_140 < i_141 < i_142


def test_handles_none_valued_optional_fields() -> None:
    """StfItem makes most fields Optional; renderer must not crash on None."""
    case = _bare_case(
        relator=None,
        primeiro_autor=None,
        data_protocolo=None,
        origem=None,
        assuntos=[],
        partes=[],
    )

    md = render_daily_markdown([case], date="2026-04-20", classe="HC", stats={})

    # Identity still present
    assert "HC 271140" in md
    # No crash implies graceful rendering; no assertion on exact placeholder
    # text since that's presentation, not behavior.


def test_watched_section_omitted_when_param_is_none() -> None:
    """Existing callers that don't pass watched_changes get no new section."""
    md = render_daily_markdown([], date="2026-04-20", classe="HC", stats={})
    assert "watched" not in md.lower()


def test_watched_section_shown_with_placeholder_when_empty_list() -> None:
    """Passing [] (empty but non-None) means 'we checked; nothing changed'."""
    md = render_daily_markdown(
        [], date="2026-04-20", classe="HC", stats={}, watched_changes=[]
    )
    assert "watched" in md.lower() or "monitorad" in md.lower()


def test_watched_section_lists_new_andamento() -> None:
    change = WatchChange(
        items_added={
            "andamentos": [
                {"index": 5, "data": "2026-04-19", "nome": "Decisão monocrática"}
            ]
        }
    )
    item = _bare_case(processo_id=158802, relator="Min. Fulano")
    md = render_daily_markdown(
        [], date="2026-04-20", classe="HC", stats={},
        watched_changes=[
            WatchedCaseChange(classe="HC", numero=158802, item=item, change=change)
        ],
    )

    assert "HC 158802" in md
    assert "Decisão monocrática" in md
    assert "2026-04-19" in md


def test_watched_section_shows_scalar_change() -> None:
    change = WatchChange(fields_changed={"relator": (None, "Min. Nova")})
    item = _bare_case(processo_id=158802, relator="Min. Nova")
    md = render_daily_markdown(
        [], date="2026-04-20", classe="HC", stats={},
        watched_changes=[
            WatchedCaseChange(classe="HC", numero=158802, item=item, change=change)
        ],
    )

    assert "Min. Nova" in md
    # Old → new arrow or similar transition marker
    assert "→" in md or "->" in md or "None" in md


def test_watched_first_time_case_labelled_new() -> None:
    change = WatchChange(is_new=True)
    item = _bare_case(processo_id=158802)
    md = render_daily_markdown(
        [], date="2026-04-20", classe="HC", stats={},
        watched_changes=[
            WatchedCaseChange(classe="HC", numero=158802, item=item, change=change)
        ],
    )

    assert "HC 158802" in md
    assert "new" in md.lower() or "novo" in md.lower() or "primeir" in md.lower()


def test_summary_section_includes_basic_stats() -> None:
    md = render_daily_markdown(
        [_bare_case()],
        date="2026-04-20",
        classe="HC",
        stats={"n_probed": 25, "duration_s": 12.4, "pdfs_downloaded": 3},
    )

    # Stats numbers appear somewhere in output; exact layout flexible.
    assert "25" in md       # n_probed
    assert "12.4" in md or "12" in md  # duration
    assert "3" in md        # pdfs_downloaded
