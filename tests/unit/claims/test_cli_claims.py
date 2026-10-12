"""``geminiclaw claims list|resolve`` (spec: revisão humana das contestadas)."""

import json

import pytest

from src.claims.model import Afirmacao
from src.claims.store import ClaimStore
from src.cli_claims import handle_claims_command

pytestmark = pytest.mark.unit


@pytest.fixture
def outputs(tmp_path):
    store = ClaimStore(tmp_path / "s1", "s1")
    disputed = Afirmacao("id-contestada", "A1", "rel:resultados:1", "o ganho vem de X", (0, 5), "modelo", "contestada")
    ok = Afirmacao("id-ok", "A2", "rel:resultados:1", "outra", (0, 5), "modelo", "suportada")
    desc = Afirmacao("id-desc", "A3", "desc:n1", "descoberta contestada", (0, 5), "modelo", "contestada")
    for claim in (disputed, ok, desc):
        store.add(claim)
    store.save()
    return tmp_path


def load(outputs, claim_id):
    return ClaimStore.load(outputs / "s1", "s1").get(claim_id)


def test_list_filtra_por_status_e_e_somente_leitura(outputs, capsys):
    before = (outputs / "s1" / "afirmacoes.json").read_text(encoding="utf-8")
    assert handle_claims_command(["list", "--status", "contestada", "--json"], outputs) == 0
    rows = json.loads(capsys.readouterr().out)
    assert {r["afirmacao_id"] for r in rows} == {"id-contestada", "id-desc"}
    assert (outputs / "s1" / "afirmacoes.json").read_text(encoding="utf-8") == before


def test_descartada_vira_suportada_com_ator_pesquisador(outputs, capsys):
    code = handle_claims_command(
        ["resolve", "id-contestada", "--decisao", "descartada", "--motivo", "a evidência sustenta"], outputs
    )
    assert code == 0
    claim = load(outputs, "id-contestada")
    assert claim.status_afirmacao == "suportada"
    assert [h["status"] for h in claim.historico] == ["contestada", "suportada"]  # o anterior permanece
    assert claim.historico[-1]["ator"] == "pesquisador"
    assert claim.revisao_pesquisador["decisao"] == "descartada"


def test_mantida_em_relatorio_so_registra_a_revisao(outputs):
    assert handle_claims_command(
        ["resolve", "id-contestada", "--decisao", "mantida", "--motivo", "concordo"], outputs
    ) == 0
    claim = load(outputs, "id-contestada")
    assert claim.status_afirmacao == "contestada"
    assert claim.revisao_pesquisador["decisao"] == "mantida"
    assert claim.historico[-1]["ator"] == "pesquisador" and claim.historico[-1]["revisao"] == "mantida"


def test_mantida_em_descoberta_sinaliza_o_curator(outputs):
    from src.knowledge.curator_flags import FlagStore

    assert handle_claims_command(
        ["resolve", "id-desc", "--decisao", "mantida", "--motivo", "concordo"], outputs
    ) == 0
    assert load(outputs, "id-desc").status_afirmacao == "contestada"
    pendentes = FlagStore(outputs / "s1").pending()
    assert len(pendentes) == 1 and pendentes[0].tipo == "falha_relevante"
    assert pendentes[0].refs == ("n1",)


def test_so_contestadas_sao_revisadas(outputs, capsys):
    assert handle_claims_command(["resolve", "id-ok", "--decisao", "mantida", "--motivo", "x"], outputs) == 1
    assert "contestadas" in capsys.readouterr().err


def test_afirmacao_inexistente(outputs):
    assert handle_claims_command(["resolve", "nada", "--decisao", "mantida", "--motivo", "x"], outputs) == 1


def test_motivo_e_obrigatorio(outputs):
    assert handle_claims_command(["resolve", "id-contestada", "--decisao", "mantida"], outputs) == 2
    assert handle_claims_command(
        ["resolve", "id-contestada", "--decisao", "mantida", "--motivo", "  "], outputs
    ) == 2


def test_evidencia_do_grafo_nunca_e_tocada(outputs):
    # o comando não importa o grafo quando a afirmação não tem nó (arquivo da sessão é a única fonte)
    import src.cli_claims as cli

    assert "SUSTENTA" not in open(cli.__file__, encoding="utf-8").read()
