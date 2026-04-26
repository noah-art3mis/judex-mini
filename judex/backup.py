"""Local backup: bundle case JSONs + PDF peças into a single Windows-friendly ZIP.

The output is a regular ``.zip`` (ZIP64 when needed) so Windows Explorer
opens it natively — no tarball, no 7-Zip dependency.

Why per-entry compression: ``data/cases/*.json`` compresses ~4×, but
``data/cache/pdf/*.gz`` is already gzipped at write time (the four-file
quartet keyed on ``sha1(url)``), so deflating again costs CPU for ~0%
savings. We pick ``ZIP_DEFLATED`` for plain text/JSON and ``ZIP_STORED``
for anything already-compressed (``.gz``, ``.zst``) or already-binary
(``.pdf``, ``.duckdb``).

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

DEFAULT_CASES_DIR = Path("data/cases")
DEFAULT_PDF_CACHE_DIR = Path("data/cache/pdf")
DEFAULT_WAREHOUSE_PATH = Path("data/warehouse/judex.duckdb")

_STORED_SUFFIXES = frozenset({".gz", ".zst", ".pdf", ".duckdb", ".png", ".jpg", ".jpeg"})


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
    cases_dir: Path = DEFAULT_CASES_DIR,
    pdf_cache_dir: Path = DEFAULT_PDF_CACHE_DIR,
    warehouse_path: Path = DEFAULT_WAREHOUSE_PATH,
    progress_every: int = 5000,
) -> BackupResult:
    """Build a single ZIP containing case JSONs + (optionally) PDF peças + warehouse.

    Parameters
    ----------
    output_path
        Final ``.zip`` destination. Parent directories are created if missing.
    include_pecas
        Bundle ``data/cache/pdf/`` (the four-file quartet per URL).
    include_warehouse
        Bundle ``data/warehouse/judex.duckdb``. Off by default — the warehouse
        is regenerable in minutes from cases + cache via ``atualizar-warehouse``.
    classes
        Restrict the cases tree to listed STF classes (e.g. ``["HC"]``). When
        ``None``, all classes under ``cases_dir`` are included.
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
            sources.append((Path(cases_dir) / cls, f"data/cases/{cls}"))
    else:
        sources.append((Path(cases_dir), "data/cases"))
    if include_pecas:
        sources.append((Path(pdf_cache_dir), "data/cache/pdf"))

    entries = list(_iter_entries(sources))
    if include_warehouse and Path(warehouse_path).exists():
        wp = Path(warehouse_path)
        entries.append((wp, f"data/warehouse/{wp.name}", _compress_type_for(wp)))

    started = time.monotonic()
    manifest = {
        "schema": 1,
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
