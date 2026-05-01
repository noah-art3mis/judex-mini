"""Tests for the shared CLI scaffolding behind baixar-pecas + extrair-pecas.

Exercises the pieces that are easy to get wrong:
- Input-mode priority (retry > csv > range > filter).
- Non-TTY fail-closed on the confirmation prompt.
- Preview content (target count, cached-by-provider count, cost/wall).

The CLI wrappers (`baixar_pecas.py` / `extrair_pecas.py`) just call
``resolve_targets`` with typed kwargs and hand off to a driver, so
their integration is covered by the driver tests.
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest

from judex.sweeps import peca_cli as _pdf_cli
from judex.sweeps.peca_targets import PecaTarget
from judex.utils import peca_cache


@pytest.fixture(autouse=True)
def _isolated_pdf_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "peca_cache"
    monkeypatch.setattr("judex.utils.peca_cache.PECAS_ROOT", root)
    monkeypatch.setattr("judex.utils.peca_cache.TEXTO_ROOT", root)


def _write_case(
    path: Path, *, classe: str, processo_id: int, urls: list[tuple[str, str]]
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rec = {
        "classe": classe, "processo_id": processo_id, "relator": "X",
        "andamentos": [{"link": {"url": u, "tipo": t}} for u, t in urls],
    }
    path.write_text(json.dumps(rec))


# ----- resolve_targets input-mode priority ---------------------------------


def test_resolve_picks_retentar_de_first(tmp_path: Path) -> None:
    """Even if range/csv/filter args are set, --retentar-de wins."""
    errors = tmp_path / "pdfs.errors.jsonl"
    errors.write_text(json.dumps({"url": "https://x.test/retry.pdf"}) + "\n")
    _write_case(
        tmp_path / "HC" / "judex-mini_HC_100.json",
        classe="HC", processo_id=100,
        urls=[("https://x.test/range.pdf", "DECISÃO")],
    )

    targets, mode = _pdf_cli.resolve_targets(
        retentar_de=errors, csv=tmp_path / "ignored.csv",
        classe="HC", inicio=100, fim=100, roots=[tmp_path],
    )
    assert [t.url for t in targets] == ["https://x.test/retry.pdf"]
    assert "retry" in mode.lower() or "retentar" in mode.lower()


def test_resolve_picks_csv_before_range(tmp_path: Path) -> None:
    _write_case(
        tmp_path / "HC" / "judex-mini_HC_100.json",
        classe="HC", processo_id=100,
        urls=[("https://x.test/100.pdf", "DECISÃO")],
    )
    _write_case(
        tmp_path / "HC" / "judex-mini_HC_200.json",
        classe="HC", processo_id=200,
        urls=[("https://x.test/200.pdf", "DECISÃO")],
    )

    csv_path = tmp_path / "alvos.csv"
    csv_path.write_text("classe,processo\nHC,200\n")

    targets, mode = _pdf_cli.resolve_targets(
        csv=csv_path, classe="HC", inicio=100, fim=100, roots=[tmp_path],
    )
    assert [t.url for t in targets] == ["https://x.test/200.pdf"]
    assert "csv" in mode.lower()


def test_resolve_promotes_range_when_inicio_fim_set(tmp_path: Path) -> None:
    _write_case(
        tmp_path / "HC" / "judex-mini_HC_100.json",
        classe="HC", processo_id=100,
        urls=[("https://x.test/100.pdf", "DECISÃO")],
    )

    targets, mode = _pdf_cli.resolve_targets(
        classe="HC", inicio=100, fim=100, roots=[tmp_path],
    )
    assert [t.url for t in targets] == ["https://x.test/100.pdf"]
    assert "range" in mode.lower() or "intervalo" in mode.lower()


def test_resolve_falls_back_to_filter_when_no_direct_selector(tmp_path: Path) -> None:
    """Classe alone, with no --inicio/--fim, stays filter-mode."""
    _write_case(
        tmp_path / "HC" / "judex-mini_HC_100.json",
        classe="HC", processo_id=100,
        urls=[("https://x.test/a.pdf", "DECISÃO")],
    )

    targets, mode = _pdf_cli.resolve_targets(
        classe="HC", roots=[tmp_path],
    )
    assert [t.url for t in targets] == ["https://x.test/a.pdf"]
    assert "filtr" in mode.lower()


def test_resolve_raises_when_no_scope_specified(tmp_path: Path) -> None:
    """Bare invocation (no retentar / csv / range / filter) is forbidden.

    Walking the entire corpus to find targets has structural perf
    cliffs — `pdfs.state.json` atomic-rewrites cap throughput at
    ~0.13 rec/s on WSL2 once it hits ~50 MB, which puts a
    120k-record extract at ~9 days. The user must always specify a
    scope. See CLAUDE.md § Non-obvious gotchas. Pre-2026-04-30 the
    resolver fell through to corpus-wide enumeration; the guard
    moved that footgun to a refused error.
    """
    with pytest.raises(ValueError) as excinfo:
        _pdf_cli.resolve_targets(roots=[tmp_path])
    msg = str(excinfo.value).lower()
    assert "scope" in msg or "filtro" in msg or "csv" in msg or "--" in msg


def test_resolve_filter_with_only_impte_contem_is_allowed(tmp_path: Path) -> None:
    """Filter mode with at least one filter input is fine — only the
    no-input-at-all case is forbidden."""
    _write_case(
        tmp_path / "HC" / "judex-mini_HC_100.json",
        classe="HC", processo_id=100,
        urls=[("https://x.test/a.pdf", "DECISÃO")],
    )
    _, mode = _pdf_cli.resolve_targets(
        impte_contem="DEFENSORIA", roots=[tmp_path],
    )
    assert "filtr" in mode.lower()


# ----- confirm_or_exit -----------------------------------------------------


class _FakeStdin:
    """Minimal stdin stand-in with explicit `isatty` + `readline`."""

    def __init__(self, *, is_tty: bool, answer: str = "") -> None:
        self._tty = is_tty
        self._buf = io.StringIO(answer)

    def isatty(self) -> bool:
        return self._tty

    def readline(self) -> str:
        return self._buf.readline()


def test_confirm_exits_nonzero_on_non_tty_without_nao_perguntar(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """Unattended runs must opt in to proceeding; silence is never consent."""
    monkeypatch.setattr(sys, "stdin", _FakeStdin(is_tty=False))
    with pytest.raises(SystemExit) as excinfo:
        _pdf_cli.confirm_or_exit(nao_perguntar=False)
    assert excinfo.value.code == 2
    err = capsys.readouterr().err.lower()
    assert "nao-perguntar" in err or "não-perguntar" in err


def test_confirm_returns_silently_when_nao_perguntar_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """--nao-perguntar bypasses both TTY detection and the prompt."""
    monkeypatch.setattr(sys, "stdin", _FakeStdin(is_tty=False))
    _pdf_cli.confirm_or_exit(nao_perguntar=True)  # no raise


def test_confirm_exits_0_when_user_declines_on_tty(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """Anything other than s/sim/y/yes cancels cleanly (exit 0)."""
    monkeypatch.setattr(sys, "stdin", _FakeStdin(is_tty=True, answer="n\n"))
    with pytest.raises(SystemExit) as excinfo:
        _pdf_cli.confirm_or_exit(nao_perguntar=False)
    assert excinfo.value.code == 0


def test_confirm_proceeds_silently_on_sim(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "stdin", _FakeStdin(is_tty=True, answer="s\n"))
    _pdf_cli.confirm_or_exit(nao_perguntar=False)  # no raise


# ----- preview content -----------------------------------------------------


def test_download_preview_reports_already_on_disk_and_to_download() -> None:
    """Baixar preview splits targets into already-cached vs to-download
    using has_bytes. Drift here mis-estimates the sweep's remaining work.
    """
    peca_cache.write_bytes("https://x.test/cached.pdf", b"%PDF already here")
    targets = [
        PecaTarget(url="https://x.test/cached.pdf"),
        PecaTarget(url="https://x.test/new-1.pdf"),
        PecaTarget(url="https://x.test/new-2.pdf"),
    ]

    buf = io.StringIO()
    _pdf_cli.print_download_preview(
        targets, mode_label="filtros", stream=buf,
    )
    out = buf.getvalue()
    assert "3" in out  # total
    assert "1" in out  # already on disk
    assert "2" in out  # to download


def test_extract_preview_reports_no_bytes_and_sidecar_hits() -> None:
    """Extrair preview surfaces three classes: cached-by-provedor,
    no-local-bytes (will fail), to-extract. Missing any of these hides
    real cost.
    """
    peca_cache.write_bytes("https://x.test/hit.pdf", b"%PDF hit")
    peca_cache.write("https://x.test/hit.pdf", "prior", extractor="mistral")
    peca_cache.write_bytes("https://x.test/miss.pdf", b"%PDF miss")
    # "nobytes.pdf" — no bytes cached.
    targets = [
        PecaTarget(url="https://x.test/hit.pdf"),
        PecaTarget(url="https://x.test/miss.pdf"),
        PecaTarget(url="https://x.test/nobytes.pdf"),
    ]

    buf = io.StringIO()
    _pdf_cli.print_extract_preview(
        targets, mode_label="filtros", provedor="mistral", stream=buf,
    )
    out = buf.getvalue().lower()

    # Order-agnostic: we check each class is represented.
    assert "mistral" in out
    assert "já extraídos" in out
    assert "sem bytes" in out
    assert "a extrair" in out
    # Cost line must exist and be nonzero for mistral.
    assert "$" in out


def test_extract_preview_pypdf_reports_zero_cost() -> None:
    targets = [PecaTarget(url="https://x.test/a.pdf")]
    buf = io.StringIO()
    _pdf_cli.print_extract_preview(
        targets, mode_label="filtros", provedor="pypdf", stream=buf,
    )
    assert "$0.00" in buf.getvalue() or "0.00" in buf.getvalue()
