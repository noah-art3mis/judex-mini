"""Lock in the v3 per-process JSON shape: bare dict, overwrite-on-save.

Per-process ``judex-mini_<CLASSE>_<N>.json`` files are single-record
by construction (one file per (classe, processo)). Writing a list,
or appending on re-save, was the v2 shape — now retired.
"""

from __future__ import annotations

import json
from pathlib import Path

from judex.data.export import _save_to_json


def _minimal_item(processo: int) -> dict:
    return {
        "schema_version": 3,
        "classe": "HC",
        "processo_id": processo,
        "andamentos": [],
    }


def test_save_writes_bare_dict_not_list(tmp_path: Path):
    out = tmp_path / "judex-mini_HC_1"
    _save_to_json(_minimal_item(1), str(out))  # type: ignore[arg-type]

    raw = json.loads((tmp_path / "judex-mini_HC_1.json").read_text())
    assert isinstance(raw, dict)
    assert raw["processo_id"] == 1


def test_save_overwrites_instead_of_appending(tmp_path: Path):
    out = tmp_path / "judex-mini_HC_1"
    _save_to_json(_minimal_item(1), str(out))  # type: ignore[arg-type]
    # Re-save with a different payload; the file must contain the
    # newer record only — no list-append semantics.
    _save_to_json(_minimal_item(2), str(out))  # type: ignore[arg-type]

    raw = json.loads((tmp_path / "judex-mini_HC_1.json").read_text())
    assert isinstance(raw, dict)
    assert raw["processo_id"] == 2
