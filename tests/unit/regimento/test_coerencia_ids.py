"""Ids do regimento.yaml iguais aos do código (v18.7-agent-system-prompts, ADR 022 §5; completado na seção 8)."""

import pytest

from src.agents.regimento import carregar_regimento
from src.agents.subtask_contract import INTEGRITY_RULES
from src.config import SessionMode
from src.knowledge import objective as objective_module
from src.knowledge import schema
from src.orchestration import exploration_linking
from src.orchestration.exploration import ExplorationStop
from src.research_consult import DECISOES_RESERVADAS

pytestmark = pytest.mark.unit


def _ids(chave):
    return {item["id"] for item in carregar_regimento().estrutura[chave]}


def test_motivos_de_parada_iguais_ao_schema_e_cobrem_a_exploracao():
    assert _ids("motivos_parada") == set(schema.NODE_SCHEMAS["Sessao"].properties["motivo_parada"].enum)
    assert {m.value for m in ExplorationStop} <= _ids("motivos_parada")


def test_motivos_de_retirada_iguais_as_constantes_do_codigo():
    constantes = {
        valor for nome, valor in vars(exploration_linking).items()
        if nome.startswith("DROP_") and isinstance(valor, str)
    }
    assert _ids("motivos_retirada") == constantes


def test_papeis_tipos_e_desfechos():
    est = carregar_regimento().estrutura
    assert _ids("papeis_experimento") == set(schema.PAPEIS_EXPERIMENTO)
    assert _ids("tipos_objetivo") == set(schema.TIPOS_OBJETIVO)
    desfechos = {d["id"] for t in est["tipos_objetivo"] for d in t.get("desfechos", [])}
    assert desfechos == {
        objective_module.DESFECHO_UMA_COMPATIVEL, objective_module.DESFECHO_TODAS_CONTRARIADAS,
        objective_module.DESFECHO_VARIAS_COMPATIVEIS, objective_module.DESFECHO_AGUARDA_FISICO,
    }
    regras = {r["regra"] for r in est["ordem_decisao_papel"]}
    assert len(regras) == 6


def test_integridade_decisoes_e_modos():
    est = carregar_regimento().estrutura
    assert _ids("regras_integridade") == {r.id for r in INTEGRITY_RULES}
    assert set(est["decisoes_reservadas"]) == set(DECISOES_RESERVADAS)
    assert {"ativar_adendo_regimento", "aprovar_hipotese", "decidir_objetivo_atingido",
            "responder_pergunta_agente", "decidir_continuidade"} <= set(est["decisoes_reservadas"])
    assert _ids("modos") == {m.value for m in SessionMode}


def test_regras_de_seguranca_da_lista_nominal_existem_com_destino():
    por_id = {r["id"]: r for r in carregar_regimento().estrutura["regras_seguranca"]}
    for nominal in ("dado_observado_nao_confiavel", "decisoes_reservadas", "egresso_agregados", "confinamento_sandbox",
                    "caminho_inputs"):
        assert por_id[nominal]["destino"] and por_id[nominal]["texto"]
