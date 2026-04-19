"""Behavioral tests for src/data/reshape.py — pure JSON v1/v2/v3 → v7.

Inputs are real on-disk corpus snapshots captured at
tests/fixtures/reshape/. We assert on the *transformations*, not on
full-dict equality, so ground-truth field values can drift without
breaking the harness.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from src.data.reshape import reshape_to_v7

FIXTURES = Path(__file__).parent.parent / "fixtures" / "reshape"


def _load(name: str) -> dict | list:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture
def v1_v2_input():
    return _load("v1_v2_input.json")


@pytest.fixture
def v3_input():
    return _load("v3_input.json")


@pytest.fixture
def v7_control():
    return _load("v7_control.json")


# ----- Container + meta -----------------------------------------------------

def test_unwraps_list_input(v1_v2_input):
    assert isinstance(v1_v2_input, list)
    out = reshape_to_v7(v1_v2_input)
    assert isinstance(out, dict)


def test_meta_slot_synthesised_for_v1_v2(v1_v2_input):
    out = reshape_to_v7(v1_v2_input)
    assert out["_meta"]["schema_version"] == 7
    assert out["_meta"]["status_http"] == 200
    assert isinstance(out["_meta"]["extraido"], str)
    # Top-level provenance keys must not coexist with the slot.
    assert "schema_version" not in out
    assert "status_http" not in out
    assert "extraido" not in out


def test_meta_slot_carries_v3_extraido(v3_input):
    inp_extraido = v3_input[0]["extraido"]
    out = reshape_to_v7(v3_input)
    assert out["_meta"]["schema_version"] == 7
    # Preserve the original scrape timestamp; don't fabricate a new one.
    assert out["_meta"]["extraido"] == inp_extraido
    assert out["_meta"]["status_http"] == 200


# ----- Date format: DD/MM/YYYY → ISO + drop *_iso companions ---------------

def test_data_protocolo_is_iso(v1_v2_input, v3_input):
    for inp in (v1_v2_input, v3_input):
        out = reshape_to_v7(inp)
        if out["data_protocolo"] is not None:
            assert _looks_iso_date(out["data_protocolo"]), out["data_protocolo"]
        assert "data_protocolo_iso" not in out


def test_andamento_data_is_iso_no_companion(v1_v2_input):
    out = reshape_to_v7(v1_v2_input)
    for a in out["andamentos"]:
        if a["data"] is not None:
            assert _looks_iso_date(a["data"]), a["data"]
        assert "data_iso" not in a


def test_peticao_data_is_iso_no_companion(v3_input):
    out = reshape_to_v7(v3_input)
    for p in out["peticoes"]:
        if p["data"] is not None:
            assert _looks_iso_date(p["data"]), p["data"]
        assert "data_iso" not in p
        assert "recebido_data_iso" not in p
        if p.get("recebido_data") is not None:
            # ISO datetime: 'YYYY-MM-DDTHH:MM:SS'
            assert "T" in p["recebido_data"], p["recebido_data"]


# ----- Andamento link unification (v4 → v5) --------------------------------

def test_andamento_link_descricao_folded_into_link(v1_v2_input):
    out = reshape_to_v7(v1_v2_input)
    for a in out["andamentos"]:
        assert "link_descricao" not in a
        link = a["link"]
        assert link is None or set(link.keys()) == {"tipo", "url", "text", "extractor"}


# ----- Index field unification ---------------------------------------------

def test_andamento_index_renamed(v1_v2_input):
    out = reshape_to_v7(v1_v2_input)
    for a in out["andamentos"]:
        assert "index_num" not in a
        assert "id" not in a
        assert isinstance(a["index"], int)


def test_recurso_data_to_tipo_id_to_index(v3_input):
    # v3 sample may or may not have recursos — the assertion only fires
    # when the list is non-empty. Still pinned by v1/v2 below.
    out = reshape_to_v7(v3_input)
    for r in out["recursos"]:
        assert "data" not in r
        assert "id" not in r
        assert isinstance(r["index"], int)
        # tipo can legitimately be None when source had no label
        assert "tipo" in r


# ----- sessao_virtual metadata ASCII snake_case ----------------------------

def test_sessao_metadata_keys_ascii(v3_input):
    out = reshape_to_v7(v3_input)
    for sv in out["sessao_virtual"]:
        md = sv.get("metadata") or {}
        # Forbidden legacy spellings.
        for bad in ("data_início", "data_prevista_fim", "relatora", "órgão_julgador"):
            assert bad not in md


# ----- Outcome promotion (str → OutcomeInfo) -------------------------------

def test_outcome_string_promoted_to_dict(v1_v2_input):
    inp_outcome = v1_v2_input[0].get("outcome")
    out = reshape_to_v7(v1_v2_input)
    if isinstance(inp_outcome, str):
        assert isinstance(out["outcome"], dict)
        assert out["outcome"]["verdict"] == inp_outcome
        assert out["outcome"]["source"] in ("sessao_virtual", "andamentos")
        assert isinstance(out["outcome"]["source_index"], int)
    elif inp_outcome is None:
        assert out["outcome"] is None


def test_outcome_dict_passthrough(v3_input):
    inp_outcome = v3_input[0].get("outcome")
    out = reshape_to_v7(v3_input)
    if isinstance(inp_outcome, dict):
        assert out["outcome"] == inp_outcome


# ----- primeiro_autor re-derivation ----------------------------------------
#
# `extract_primeiro_autor` is the source of truth. Its `AUTHOR_PARTY_TIPOS`
# prefix list evolves (e.g. PACTE was added so HCs surface the paciente
# instead of the impetrante). Shape-only migrations must pick up the
# current rule by re-deriving from the `partes` list, not by trusting
# whatever primeiro_autor was stamped into the file at scrape time.

def test_primeiro_autor_rederived_from_partes_overrides_stale_value():
    raw = {
        "schema_version": 3,
        "classe": "HC",
        "processo_id": 1,
        "partes": [
            {"index": 1, "tipo": "PACTE.(S)", "nome": "ALICE"},
            {"index": 2, "tipo": "IMPTE.(S)", "nome": "BOB"},
        ],
        "primeiro_autor": "BOB",  # stale — pre-PACTE rule surfaced IMPTE
        "andamentos": [], "peticoes": [], "recursos": [],
        "deslocamentos": [], "sessao_virtual": [], "pautas": [],
    }
    out = reshape_to_v7(raw)
    assert out["primeiro_autor"] == "ALICE"


def test_primeiro_autor_preserved_when_partes_yield_no_author():
    # No party type in AUTHOR_PARTY_TIPOS → derivation returns None;
    # reshape should keep whatever was already on the record rather
    # than stomp it with None.
    raw = {
        "schema_version": 3,
        "classe": "HC",
        "processo_id": 1,
        "partes": [
            {"index": 1, "tipo": "ADV.(A/S)", "nome": "LAWYER"},
        ],
        "primeiro_autor": "LEGACY",
        "andamentos": [], "peticoes": [], "recursos": [],
        "deslocamentos": [], "sessao_virtual": [], "pautas": [],
    }
    out = reshape_to_v7(raw)
    assert out["primeiro_autor"] == "LEGACY"


def test_primeiro_autor_absent_when_partes_empty_and_no_prior_value():
    raw = {
        "schema_version": 3,
        "classe": "HC",
        "processo_id": 1,
        "partes": [],
        "andamentos": [], "peticoes": [], "recursos": [],
        "deslocamentos": [], "sessao_virtual": [], "pautas": [],
    }
    out = reshape_to_v7(raw)
    assert out.get("primeiro_autor") is None


# ----- v7: publicacoes_dje seeded empty on migration -----------------------

def test_publicacoes_dje_seeded_empty_when_missing(v3_input):
    # v3 input has no publicacoes_dje (pre-v7); renormalizer seeds []
    # so downstream readers can assume the key exists.
    out = reshape_to_v7(v3_input)
    assert out["publicacoes_dje"] == []


def test_publicacoes_dje_preserved_when_already_populated():
    # When a record already carries publicacoes_dje (e.g. re-reshape of
    # a v7 record), the reshape must not clobber it with [].
    raw = {
        "_meta": {"schema_version": 7, "status_http": 200, "extraido": "2026-04-19T00:00:00"},
        "classe": "HC", "processo_id": 158802,
        "publicacoes_dje": [{"numero": 204, "decisoes": []}],
    }
    out = reshape_to_v7(raw)
    assert out["publicacoes_dje"] == [{"numero": 204, "decisoes": []}]


# ----- Idempotency + v7 control --------------------------------------------

def test_v7_control_is_unchanged(v7_control):
    expected = copy.deepcopy(v7_control)
    out = reshape_to_v7(v7_control)
    assert out == expected


def test_reshape_is_idempotent(v1_v2_input, v3_input):
    for inp in (v1_v2_input, v3_input):
        once = reshape_to_v7(copy.deepcopy(inp))
        twice = reshape_to_v7(copy.deepcopy(once))
        assert twice == once


# ----- helpers -------------------------------------------------------------

def _looks_iso_date(s: str) -> bool:
    if not isinstance(s, str) or len(s) < 10:
        return False
    return s[4] == "-" and s[7] == "-" and s[:4].isdigit()
