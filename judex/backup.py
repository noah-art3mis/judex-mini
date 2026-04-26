"""Local backup: bundle processo JSONs + peças into a single Windows-friendly ZIP.

The output is a regular ``.zip`` (ZIP64 when needed) so Windows Explorer
opens it natively — no tarball, no 7-Zip dependency.

Why per-entry compression: ``data/source/processos/*.json`` compresses
~4×, but ``data/raw/pecas/*.gz`` is already gzipped at write time (the
content-addressed peça quartet keyed on ``sha1(url)``), so deflating
again costs CPU for ~0% savings. We pick ``ZIP_DEFLATED`` for plain
text/JSON and ``ZIP_STORED`` for anything already-compressed (``.gz``,
``.zst``) or already-binary (``.pdf``, ``.rtf``, ``.duckdb``).

The write is atomic: the zip lands at ``<output>.tmp`` and is renamed to
``<output>`` only after the central directory is closed cleanly. A crash
mid-build leaves the partial file at the ``.tmp`` path — never at the
final destination — so a recipient never sees a torn archive.

Integrity check: the embedded ``MANIFEST.json`` records the file count
and creation timestamp; on top of that, every ZIP entry carries a CRC-32
checked by ``ZipFile.testzip()`` — that's enough to catch the
corruption modes a Drive round-trip might introduce.
"""

from __future__ import annotations

import json
import os
import time
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

DEFAULT_PROCESSOS_DIR = Path("data/source/processos")
DEFAULT_PECAS_DIR = Path("data/raw/pecas")
DEFAULT_PECAS_TEXTO_DIR = Path("data/derived/pecas-texto")
DEFAULT_WAREHOUSE_PATH = Path("data/derived/warehouse/judex.duckdb")

_STORED_SUFFIXES = frozenset(
    {".gz", ".zst", ".pdf", ".rtf", ".duckdb", ".png", ".jpg", ".jpeg"}
)


@dataclass
class BackupResult:
    output_path: Path
    bytes_written: int
    file_count: int
    elapsed_s: float
    manifest: dict = field(default_factory=dict)


def _compress_type_for(path: Path) -> int:
    return zipfile.ZIP_STORED if path.suffix.lower() in _STORED_SUFFIXES else zipfile.ZIP_DEFLATED


def _iter_entries(sources: list[tuple[Path, str]]) -> Iterator[tuple[Path, str, int]]:
    for root, arc_prefix in sources:
        if not root.exists():
            continue
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(root).as_posix()
            arcname = f"{arc_prefix}/{rel}" if rel else arc_prefix
            yield path, arcname, _compress_type_for(path)


def make_backup(
    output_path: Path,
    *,
    include_pecas: bool = True,
    include_warehouse: bool = False,
    classes: list[str] | None = None,
    processos_dir: Path = DEFAULT_PROCESSOS_DIR,
    pecas_dir: Path = DEFAULT_PECAS_DIR,
    pecas_texto_dir: Path = DEFAULT_PECAS_TEXTO_DIR,
    warehouse_path: Path = DEFAULT_WAREHOUSE_PATH,
    progress_every: int = 5000,
) -> BackupResult:
    """Build a single ZIP containing processo JSONs + (optionally) peças + warehouse.

    Parameters
    ----------
    output_path
        Final ``.zip`` destination. Parent directories are created if missing.
    include_pecas
        Bundle peça bytes (``data/raw/pecas/``) and extracted text
        (``data/derived/pecas-texto/``). Both subtrees ship together — the
        bytes alone aren't useful for downstream readers without the
        already-extracted text, and the text alone is useless without the
        provenance bytes you'd need for re-OCR.
    include_warehouse
        Bundle ``data/derived/warehouse/judex.duckdb``. Off by default —
        the warehouse is regenerable in minutes from processos + pecas-texto
        via ``atualizar-warehouse``.
    classes
        Restrict the processos tree to listed STF classes (e.g. ``["HC"]``).
        When ``None``, all classes under ``processos_dir`` are included.
        Note: peça caches are sha1-keyed and shared across classes, so the
        ``classes`` filter only narrows the processos subtree — peças always
        ship as a complete set.
    progress_every
        Print a progress line every N files. ``0`` disables progress output.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = output_path.with_suffix(output_path.suffix + ".tmp")
    if tmp_path.exists():
        tmp_path.unlink()

    sources: list[tuple[Path, str]] = []
    if classes:
        for cls in classes:
            sources.append((Path(processos_dir) / cls, f"data/source/processos/{cls}"))
    else:
        sources.append((Path(processos_dir), "data/source/processos"))
    if include_pecas:
        sources.append((Path(pecas_dir), "data/raw/pecas"))
        sources.append((Path(pecas_texto_dir), "data/derived/pecas-texto"))

    entries = list(_iter_entries(sources))
    if include_warehouse and Path(warehouse_path).exists():
        wp = Path(warehouse_path)
        entries.append((wp, f"data/derived/warehouse/{wp.name}", _compress_type_for(wp)))

    started = time.monotonic()
    manifest = {
        "schema": 2,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "include_pecas": include_pecas,
        "include_warehouse": include_warehouse,
        "classes": classes,
        "file_count": len(entries),
        "sources": [str(s) for s, _ in sources],
    }

    file_count = 0
    bytes_in = 0
    try:
        with zipfile.ZipFile(tmp_path, "w", allowZip64=True) as zf:
            zf.writestr("MANIFEST.json", json.dumps(manifest, indent=2, sort_keys=True))
            for path, arcname, ct in entries:
                zf.write(path, arcname=arcname, compress_type=ct)
                file_count += 1
                bytes_in += path.stat().st_size
                if progress_every and file_count % progress_every == 0:
                    elapsed = time.monotonic() - started
                    rate = file_count / elapsed if elapsed > 0 else 0
                    print(
                        f"  packed {file_count:,}/{len(entries):,} files "
                        f"({bytes_in / 1e9:.2f} GB read, {rate:.0f} files/s)",
                        flush=True,
                    )
    except BaseException:
        if tmp_path.exists():
            tmp_path.unlink()
        raise

    os.replace(tmp_path, output_path)

    return BackupResult(
        output_path=output_path,
        bytes_written=output_path.stat().st_size,
        file_count=file_count,
        elapsed_s=time.monotonic() - started,
        manifest=manifest,
    )
