"""Ciclos de correção, leitor de métricas, armazenamento e checkpoint (spec: ciclos; contagens; pendentes)."""

import json

import pytest

from src.claims.metrics import ClaimVerificationReader
from src.claims.model import STATUSES, Afirmacao, Conclusao
from src.claims.revision import RevisionItem, apply_revisions, parse_revisions, revision_targets
from src.claims.service import ClaimService
from src.claims.store import ClaimStore, ClaimStoreError
from src.continuity import Checkpoint, CheckpointError
from tests.unit.claims.helpers import FakeVerifier, code, evidence_for, make_store

pytestmark = pytest.mark.unit

SECTIONS = ("Resultados",)
SOURCE = "## Resultados\n\nA é melhor que B por {{res:x}}.\n\nSegunda conclusão qualitativa do relatório.\n"


def _service(tmp_path, **kw):
    kw.setdefault("sense_of", lambda n: "maior_melhor")
    return ClaimService(store=make_store(tmp_path), verifier=kw.pop("verifier", FakeVerifier()), **kw)


@pytest.mark.asyncio
async def test_correcao_aprovada_registra_ciclo_e_preserva_antigas(tmp_path):
    codes = {"R1": code("R1", 0.81, "acuracia"), "R2": code("R2", 0.84, "acuracia")}
    svc = _service(tmp_path)
    ruim = Conclusao("rel:resultados:1", "relatorio", "A (0,81 [R1]) é melhor que B (0,84 [R2]).", "summarizer")
    first = await svc.verify_conclusion(ruim, codes, evidence_for())
    assert first[0].status_afirmacao == "refutada_deterministica"
    # o Summarizer reescreve; o texto novo é verificado
    svc.store.conclusoes[ruim.conclusao_id]["ciclos"] = 1
    boa = Conclusao("rel:resultados:1", "relatorio", "B (0,84 [R2]) é melhor que A (0,81 [R1]).", "summarizer")
    second = await svc.verify_conclusion(boa, codes, evidence_for())
    assert second[0].status_afirmacao == "suportada"
    entry = svc.store.conclusoes["rel:resultados:1"]
    assert entry["ciclos"] == 1 and entry["aprovada"] is True
    old = svc.store.get(first[0].afirmacao_id)
    assert old.substituida_por == second[0].afirmacao_id and old.status_afirmacao == "refutada_deterministica"


@pytest.mark.asyncio
async def test_contestada_nao_entra_em_ciclo(tmp_path):
    fake = FakeVerifier(lambda f, i: [{"texto": "x", "frase": 1, "status": "refutada", "evidencias": ["ev1"]}])
    svc = _service(tmp_path, verifier=fake)
    await svc.verify_conclusion(
        Conclusao("rel:resultados:1", "relatorio", "A é melhor que B por causa de C.", "summarizer"), {},
        evidence_for("res:e/a"),
    )
    assert svc.store.active()[0].status_afirmacao == "contestada"
    assert revision_targets(svc.store, SOURCE, SECTIONS) == []


@pytest.mark.asyncio
async def test_alvos_sao_refutada_deterministica_e_parcial(tmp_path):
    codes = {"R1": code("R1", 1.0, "acuracia"), "R2": code("R2", 2.0, "acuracia")}
    fake = FakeVerifier(lambda f, i: [
        {"texto": "x", "frase": 1, "status": "parcial", "evidencias": ["ev1"], "parte_nao_suportada": "p"}
    ])
    svc = _service(tmp_path, verifier=fake)
    await svc.verify_conclusion(
        Conclusao("rel:resultados:1", "relatorio", "A (1 [R1]) é melhor que B (2 [R2]).", "summarizer"),
        codes, evidence_for("res:e/a"),
    )
    await svc.verify_conclusion(
        Conclusao("rel:resultados:2", "relatorio", "Segunda conclusão qualitativa do relatório.", "summarizer"),
        codes, evidence_for("res:e/a"),
    )
    targets = revision_targets(svc.store, SOURCE, SECTIONS)
    assert [t.conclusao_id for t in targets] == ["rel:resultados:1", "rel:resultados:2"]
    assert targets[0].problemas[0]["status"] == "refutada_deterministica"
    assert targets[0].problemas[0]["valores_registrados"]["R1"]["valor"] == 1.0


def test_parse_e_aplicacao_das_revisoes():
    items = [RevisionItem("rel:resultados:1", "A é melhor que B por {{res:x}}.", [])]
    raw = json.dumps({"conclusoes": [
        {"conclusao_id": "rel:resultados:1", "texto": "B supera A segundo {{res:x}}."},
        {"conclusao_id": "rel:resultados:9", "texto": "ignorada"},
    ]})
    revisions = parse_revisions(raw, items)
    assert list(revisions) == ["rel:resultados:1"]
    revised = apply_revisions(SOURCE, revisions, SECTIONS)
    assert "B supera A segundo {{res:x}}." in revised and "Segunda conclusão qualitativa" in revised


@pytest.mark.parametrize("texto", ["# Título\ntexto", "texto [A1 · parcial]", "<!-- x -->", "p1\n\np2", ""])
def test_revisao_com_formato_invalido_e_descartada(texto):
    items = [RevisionItem("c", "t", [])]
    assert parse_revisions(json.dumps({"conclusoes": [{"conclusao_id": "c", "texto": texto}]}), items) == {}


# --- métricas, armazenamento, checkpoint ------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_leitor_de_metricas(tmp_path):
    svc = _service(tmp_path)
    codes = {"R1": code("R1", 1.0, "acuracia"), "R2": code("R2", 2.0, "acuracia")}
    await svc.verify_conclusion(
        Conclusao("rel:resultados:1", "relatorio", "A (1 [R1]) é melhor que B (2 [R2]).", "summarizer"),
        codes, evidence_for(),
    )
    svc.store.save()
    data = ClaimVerificationReader(tmp_path).read("s1")
    assert set(data["afirmacoes_por_status"]) == set(STATUSES)
    assert data["afirmacoes_por_status"]["refutada_deterministica"] == 1
    assert data["ciclos_correcao_conclusoes"] == [{"conclusao_id": "rel:resultados:1", "ciclos": 0, "aprovada": False}]


def test_leitor_sem_arquivo(tmp_path):
    with pytest.raises(FileNotFoundError):
        ClaimVerificationReader(tmp_path).read("nada")


def test_store_grava_e_recarrega_sem_perder_historico(tmp_path):
    store = make_store(tmp_path)
    claim = Afirmacao("id1", "A1", "c", "t", (0, 1), "modelo", "contestada")
    store.add(claim)
    store.change_status(claim, "suportada", "pesquisador", motivo="m")
    store.save()
    again = ClaimStore.load(tmp_path / "s1", "s1")
    assert [h["status"] for h in again.get("id1").historico] == ["contestada", "suportada"]
    assert not (tmp_path / "s1" / "afirmacoes.json.tmp").exists()


def test_store_ilegivel_falha_explicito(tmp_path):
    (tmp_path / "s1").mkdir()
    (tmp_path / "s1" / "afirmacoes.json").write_text("{", encoding="utf-8")
    with pytest.raises(ClaimStoreError):
        ClaimStore.load(tmp_path / "s1", "s1")


def test_modelo_valida_invariantes():
    with pytest.raises(ValueError):
        Afirmacao("i", "A1", "c", "t", (0, 1), "modelo", "parcial")
    with pytest.raises(ValueError):
        Afirmacao("i", "A1", "c", "t", (0, 1), "modelo", "pendente")
    with pytest.raises(ValueError):
        Afirmacao("i", "A1", "c", "t", (0, 1), "modelo", "inventado")


def test_checkpoint_guarda_afirmacoes_pendentes():
    cp = Checkpoint(session_id="s1")
    cp.afirmacoes_pendentes = [{"afirmacao_id": "n1", "session_id": "s1", "conclusao_id": "rel:resultados:1"}]
    data = cp.to_dict()
    assert Checkpoint.from_dict(data, expected_session_id="s1").afirmacoes_pendentes == cp.afirmacoes_pendentes


def test_checkpoint_antigo_sem_a_chave_continua_valido():
    data = Checkpoint(session_id="s1").to_dict()
    data.pop("afirmacoes_pendentes")
    assert Checkpoint.from_dict(data, expected_session_id="s1").afirmacoes_pendentes == []


def test_checkpoint_rejeita_pendente_malformado():
    data = Checkpoint(session_id="s1").to_dict()
    data["afirmacoes_pendentes"] = [{"afirmacao_id": "../x", "session_id": "s1", "conclusao_id": "c"}]
    with pytest.raises(CheckpointError):
        Checkpoint.from_dict(data, expected_session_id="s1")
