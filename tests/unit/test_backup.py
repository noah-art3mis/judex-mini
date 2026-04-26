"""Behavioral tests for `judex.backup.make_backup`.

Covers the load-bearing contracts a backup recipient relies on:
  * scope flags (processos-only vs +peças vs class-restricted) actually
    filter what ends up in the zip
  * the peça quartet split lands at the right arc-prefixes (bytes under
    data/raw/pecas/, derived under data/derived/pecas-texto/)
  * MANIFEST.json is embedded and records the scope
  * the zip round-trips (no torn central directory)
  * a mid-build crash never leaves a partial file at the final path
"""

from __future__ import annotations

import gzip
import json
import zipfile
from pathlib import Path

import pytest

from judex.backup import make_backup


@pytest.fixture
def fake_tree(tmp_path: Path) -> dict[str, Path]:
    """Lay down minimal source/processos + raw/pecas + derived/pecas-texto fixtures."""
    processos = tmp_path / "data" / "source" / "processos"
    pecas = tmp_path / "data" / "raw" / "pecas"
    pecas_texto = tmp_path / "data" / "derived" / "pecas-texto"
    (processos / "HC").mkdir(parents=True)
    (processos / "RE").mkdir(parents=True)
    pecas.mkdir(parents=True)
    pecas_texto.mkdir(parents=True)

    (processos / "HC" / "judex-mini_HC_135041-135041.json").write_text(
        json.dumps({"classe": "HC", "processo": 135041})
    )
    (processos / "HC" / "judex-mini_HC_135042-135042.json").write_text(
        json.dumps({"classe": "HC", "processo": 135042})
    )
    (processos / "RE" / "judex-mini_RE_999-999.json").write_text(
        json.dumps({"classe": "RE", "processo": 999})
    )

    sha_pdf = "a" * 40
    sha_txt = "b" * 40
    with gzip.open(pecas / f"{sha_pdf}.pdf.gz", "wb") as f:
        f.write(b"%PDF-1.4 fake\n")
    with gzip.open(pecas_texto / f"{sha_txt}.txt.gz", "wb") as f:
        f.write(b"extracted text\n")
    (pecas_texto / f"{sha_pdf}.extractor").write_text("pypdf\n")

    return {
        "root": tmp_path,
        "processos": processos,
        "pecas": pecas,
        "pecas_texto": pecas_texto,
    }


def _entries(zip_path: Path) -> list[str]:
    with zipfile.ZipFile(zip_path) as zf:
        return sorted(zf.namelist())


def test_processos_plus_pecas_includes_all_three_subtrees(
    fake_tree: dict[str, Path], tmp_path: Path
) -> None:
    out = tmp_path / "backup.zip"
    make_backup(
        out,
        processos_dir=fake_tree["processos"],
        pecas_dir=fake_tree["pecas"],
        pecas_texto_dir=fake_tree["pecas_texto"],
        include_pecas=True,
        progress_every=0,
    )
    entries = _entries(out)
    assert any(e.startswith("data/source/processos/HC/") for e in entries)
    assert any(e.startswith("data/raw/pecas/") for e in entries)
    assert any(e.startswith("data/derived/pecas-texto/") for e in entries)


def test_sem_pecas_excludes_both_peca_subtrees(
    fake_tree: dict[str, Path], tmp_path: Path
) -> None:
    out = tmp_path / "backup.zip"
    make_backup(
        out,
        processos_dir=fake_tree["processos"],
        pecas_dir=fake_tree["pecas"],
        pecas_texto_dir=fake_tree["pecas_texto"],
        include_pecas=False,
        progress_every=0,
    )
    entries = _entries(out)
    assert any(e.startswith("data/source/processos/") for e in entries)
    assert not any(e.startswith("data/raw/pecas/") for e in entries)
    assert not any(e.startswith("data/derived/pecas-texto/") for e in entries)


def test_class_filter_drops_other_classes(
    fake_tree: dict[str, Path], tmp_path: Path
) -> None:
    out = tmp_path / "backup.zip"
    make_backup(
        out,
        processos_dir=fake_tree["processos"],
        pecas_dir=fake_tree["pecas"],
        pecas_texto_dir=fake_tree["pecas_texto"],
        include_pecas=False,
        classes=["HC"],
        progress_every=0,
    )
    entries = _entries(out)
    assert any("HC_135041" in e for e in entries)
    assert not any("RE_999" in e for e in entries)


def test_manifest_records_scope(fake_tree: dict[str, Path], tmp_path: Path) -> None:
    out = tmp_path / "backup.zip"
    make_backup(
        out,
        processos_dir=fake_tree["processos"],
        pecas_dir=fake_tree["pecas"],
        pecas_texto_dir=fake_tree["pecas_texto"],
        include_pecas=True,
        classes=["HC"],
        progress_every=0,
    )
    with zipfile.ZipFile(out) as zf:
        manifest = json.loads(zf.read("MANIFEST.json"))
    assert manifest["include_pecas"] is True
    assert manifest["classes"] == ["HC"]
    assert "created_at" in manifest
    assert manifest["file_count"] >= 1


def test_zip_roundtrips_without_corruption(
    fake_tree: dict[str, Path], tmp_path: Path
) -> None:
    out = tmp_path / "backup.zip"
    make_backup(
        out,
        processos_dir=fake_tree["processos"],
        pecas_dir=fake_tree["pecas"],
        pecas_texto_dir=fake_tree["pecas_texto"],
        include_pecas=True,
        progress_every=0,
    )
    with zipfile.ZipFile(out) as zf:
        assert zf.testzip() is None
        processo_names = [
            n for n in zf.namelist()
            if n.endswith(".json") and "processos" in n
        ]
        for name in processo_names:
            payload = json.loads(zf.read(name))
            assert "classe" in payload


def test_no_partial_zip_at_final_path_on_failure(
    fake_tree: dict[str, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Atomic write: a mid-build crash must not leave a half-written `.zip` at the final path."""
    out = tmp_path / "backup.zip"

    real_write = zipfile.ZipFile.write
    call_count = {"n": 0}

    def crash_after_first_file(self: zipfile.ZipFile, *args: object, **kwargs: object) -> None:
        call_count["n"] += 1
        if call_count["n"] >= 2:
            raise RuntimeError("simulated crash mid-zip")
        real_write(self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(zipfile.ZipFile, "write", crash_after_first_file)

    with pytest.raises(RuntimeError, match="simulated crash"):
        make_backup(
            out,
            processos_dir=fake_tree["processos"],
            pecas_dir=fake_tree["pecas"],
            pecas_texto_dir=fake_tree["pecas_texto"],
            include_pecas=False,
            progress_every=0,
        )
    assert not out.exists()
