import hashlib
import json

import pytest

from scripts.memory_eval.families import FamilyError, build_family, prepare

pytestmark = pytest.mark.unit


def _hashes(root, family):
    out = {}
    for m in family.membros:
        for kind, name in (("entrada", "dados.csv"), ("verdade", "verdade.json")):
            path = root / kind / m.nome / name
            out[(m.nome, name)] = hashlib.sha256(path.read_bytes()).hexdigest()
    return out


def test_familia_reproduzivel_com_a_mesma_semente(tmp_path):
    family = build_family("fam", "relacionada", 3, 7)
    prepare(family, tmp_path / "a")
    prepare(build_family("fam", "relacionada", 3, 7), tmp_path / "b")
    assert _hashes(tmp_path / "a", family) == _hashes(tmp_path / "b", family)


def test_relacionada_compartilha_o_regime_e_controle_nao(tmp_path):
    rel = build_family("r", "relacionada", 3, 1)
    ctl = build_family("c", "controle", 3, 1)
    assert {m.regime for m in rel.membros} == {"P"}
    assert {m.regime for m in ctl.membros} == {"P", "T", "N"}
    assert len({m.semente for m in rel.membros}) == 3


def test_verdade_traz_a_familia_e_fica_fora_da_entrada(tmp_path):
    family = build_family("fam", "controle", 2, 3)
    prepare(family, tmp_path)
    verdade = json.loads((tmp_path / "verdade" / family.membros[0].nome / "verdade.json").read_text())
    assert verdade["familia"] == "fam" and verdade["tipo_familia"] == "controle"
    assert not list((tmp_path / "entrada").rglob("verdade.json"))


def test_ruido_muda_os_rotulos(tmp_path):
    family = build_family("fam", "relacionada", 4, 5)
    prepare(family, tmp_path)
    assert {m.ruido for m in family.membros} >= {0.0, 0.02}


def test_familia_com_menos_de_dois_membros_e_recusada():
    with pytest.raises(FamilyError):
        build_family("fam", "relacionada", 1, 1)
