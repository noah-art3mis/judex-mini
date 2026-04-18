import json
from pathlib import Path

from scripts.run_sweep import _write_item_json


def test_writes_list_wrapped_json(tmp_path: Path) -> None:
    items_dir = tmp_path / "items"
    item = {"classe": "HC", "processo_id": 12345, "partes": []}

    _write_item_json(items_dir, "HC", 12345, item)

    path = items_dir / "judex-mini_HC_12345-12345.json"
    assert path.exists()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(data, list) and len(data) == 1
    assert data[0]["classe"] == "HC"
    assert data[0]["processo_id"] == 12345


def test_overwrites_existing(tmp_path: Path) -> None:
    items_dir = tmp_path / "items"

    _write_item_json(items_dir, "HC", 1, {"first": True})
    _write_item_json(items_dir, "HC", 1, {"second": True})

    data = json.loads(
        (items_dir / "judex-mini_HC_1-1.json").read_text(encoding="utf-8")
    )
    assert data[0] == {"second": True}


def test_creates_nested_dir(tmp_path: Path) -> None:
    nested = tmp_path / "a" / "b" / "c"
    _write_item_json(nested, "HC", 42, {"ok": True})
    assert (nested / "judex-mini_HC_42-42.json").exists()


def test_no_tmp_leftover(tmp_path: Path) -> None:
    items_dir = tmp_path / "items"
    _write_item_json(items_dir, "HC", 7, {"x": 1})
    leftovers = list(items_dir.glob("*.tmp"))
    assert leftovers == []
