"""Per-case tar.gz HTML cache.

One archive per (classe, processo), members are raw HTML (plus
incidente.txt). The outer .tar.gz compresses across tabs, which
collapses the ~10 tiny gzipped files per case into a single archive
that's roughly the same apparent size but fits in one ext4 inode
instead of ten.
"""

from __future__ import annotations

import tarfile

import pytest

from src.utils import html_cache


def test_read_miss_returns_none(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(html_cache, "CACHE_ROOT", tmp_path)

    assert html_cache.read("HC", 1, "detalhe") is None
    assert html_cache.read_incidente("HC", 1) is None
    assert html_cache.has_case("HC", 1) is False


def test_write_case_round_trips_all_tabs(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(html_cache, "CACHE_ROOT", tmp_path)

    tabs = {
        "detalhe": "<html>detalhe</html>",
        "abaPartes": "<html>partes</html>",
        "abaAndamentos": "<html>andamentos</html>",
    }
    html_cache.write_case("HC", 42, tabs=tabs, incidente=98765)

    assert html_cache.has_case("HC", 42) is True
    assert html_cache.read("HC", 42, "detalhe") == "<html>detalhe</html>"
    assert html_cache.read("HC", 42, "abaPartes") == "<html>partes</html>"
    assert html_cache.read("HC", 42, "abaAndamentos") == "<html>andamentos</html>"
    assert html_cache.read_incidente("HC", 42) == 98765


def test_read_missing_tab_returns_none_when_case_exists(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(html_cache, "CACHE_ROOT", tmp_path)

    html_cache.write_case("HC", 42, tabs={"detalhe": "x"}, incidente=1)

    assert html_cache.read("HC", 42, "abaPartes") is None


def test_sessao_tabs_with_variable_suffix(tmp_path, monkeypatch) -> None:
    """Sessao JSON tabs embed a variable incidente-derived suffix."""
    monkeypatch.setattr(html_cache, "CACHE_ROOT", tmp_path)

    tabs = {
        "detalhe": "<html/>",
        "sessao_oi_4752531": '[{"sessao": 1}]',
        "sessao_sessaoVirtual_4752531": '{"votos": []}',
        "sessao_sessaoVirtual_6224780": '{"votos": [1]}',
    }
    html_cache.write_case("HC", 1, tabs=tabs, incidente=4752531)

    assert html_cache.read("HC", 1, "sessao_oi_4752531") == '[{"sessao": 1}]'
    assert html_cache.read("HC", 1, "sessao_sessaoVirtual_4752531") == '{"votos": []}'
    assert html_cache.read("HC", 1, "sessao_sessaoVirtual_6224780") == '{"votos": [1]}'


def test_write_case_replaces_prior_contents(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(html_cache, "CACHE_ROOT", tmp_path)

    html_cache.write_case("HC", 1, tabs={"detalhe": "old"}, incidente=1)
    html_cache.write_case("HC", 1, tabs={"detalhe": "new", "abaPartes": "x"}, incidente=2)

    assert html_cache.read("HC", 1, "detalhe") == "new"
    assert html_cache.read("HC", 1, "abaPartes") == "x"
    assert html_cache.read_incidente("HC", 1) == 2


def test_different_cases_stored_separately(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(html_cache, "CACHE_ROOT", tmp_path)

    html_cache.write_case("HC", 1, tabs={"detalhe": "A"}, incidente=1)
    html_cache.write_case("ADI", 1, tabs={"detalhe": "B"}, incidente=2)
    html_cache.write_case("HC", 2, tabs={"detalhe": "C"}, incidente=3)

    assert html_cache.read("HC", 1, "detalhe") == "A"
    assert html_cache.read("ADI", 1, "detalhe") == "B"
    assert html_cache.read("HC", 2, "detalhe") == "C"


def test_utf8_content_round_trips(tmp_path, monkeypatch) -> None:
    """STF content is UTF-8 (Portuguese diacritics, em-dashes, etc)."""
    monkeypatch.setattr(html_cache, "CACHE_ROOT", tmp_path)

    html = "<p>HABEAS CORPUS — impetrante João das Ações</p>"
    html_cache.write_case("HC", 1, tabs={"detalhe": html}, incidente=1)

    assert html_cache.read("HC", 1, "detalhe") == html


def test_archive_uses_tar_gz_format(tmp_path, monkeypatch) -> None:
    """The on-disk archive must be a real gzipped tar (backup-tool readable)."""
    monkeypatch.setattr(html_cache, "CACHE_ROOT", tmp_path)

    html_cache.write_case("HC", 42, tabs={"detalhe": "x"}, incidente=1)

    archive = tmp_path / "HC_42.tar.gz"
    assert archive.exists()
    with tarfile.open(archive, "r:gz") as tf:
        names = set(tf.getnames())
    assert "detalhe.html" in names
    assert "incidente.txt" in names


def test_no_temp_files_left_after_write(tmp_path, monkeypatch) -> None:
    """Atomic write uses tempfile → rename; no .tmp should survive."""
    monkeypatch.setattr(html_cache, "CACHE_ROOT", tmp_path)

    html_cache.write_case("HC", 1, tabs={"detalhe": "x"}, incidente=1)

    leftover = list(tmp_path.glob("*.tmp")) + list(tmp_path.glob(".*.tmp"))
    assert leftover == []
