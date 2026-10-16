"""Códigos de saída, apelido e estados (v18.7-background-sessions, tarefas 1.3 e 2.2)."""

from __future__ import annotations

import pytest

from src.knowledge import schema
from src.session.alias import is_alias, next_alias, slugify
from src.session.continuity import RESUME_CONFIRM, RESUME_OK, Checkpoint, evaluate_resumability
from src.session.exit_codes import (
    EXIT_AWAITING_RESEARCHER,
    EXIT_ERROR,
    EXIT_INTERRUPTED,
    EXIT_LIMIT,
    EXIT_RESEARCH_STOP,
    exit_code_for,
)
from src.session.states import FINISHED_STATUSES, UNFINISHED_STATUSES

pytestmark = pytest.mark.unit

MOTIVOS = schema.NODE_SCHEMAS["Sessao"].properties["motivo_parada"].enum


def test_todo_motivo_de_parada_tem_classe():
    """Scenario: todo valor de ``Sessao.motivo_parada`` tem classe (um motivo novo sem classe falha aqui)."""
    for motivo in MOTIVOS:
        if motivo == "erro":
            assert exit_code_for(motivo) == EXIT_ERROR
            continue
        assert exit_code_for(motivo) != EXIT_ERROR, f"motivo sem classe de saída: {motivo}"


@pytest.mark.parametrize(
    ("motivo", "codigo"),
    [
        ("solucao_encontrada", EXIT_RESEARCH_STOP),
        ("sem_caminhos_promissores", EXIT_RESEARCH_STOP),
        ("hipoteses_nao_testadas", EXIT_RESEARCH_STOP),
        ("limite_tokens", EXIT_LIMIT),
        ("limite_cota_provedor", EXIT_LIMIT),
        ("versao_modelo", EXIT_LIMIT),
        ("planos_rejeitados", EXIT_LIMIT),
        ("aguarda_pesquisador", EXIT_AWAITING_RESEARCHER),
        ("suspensa_sem_pesquisador", EXIT_AWAITING_RESEARCHER),
        ("interrompida_pesquisador", EXIT_INTERRUPTED),
        ("interrompida", EXIT_INTERRUPTED),
        ("encerrada_pesquisador", EXIT_INTERRUPTED),
        ("erro", EXIT_ERROR),
    ],
)
def test_codigo_por_motivo(motivo, codigo):
    assert exit_code_for(motivo) == codigo


def test_motivo_desconhecido_ou_ausente_falha_fechado():
    assert exit_code_for("motivo_que_nao_existe") == EXIT_ERROR
    assert exit_code_for(None) == EXIT_ERROR


def test_apelido_menor_numero_livre_no_projeto():
    assert next_alias("Câncer de Mama!", []) == "cancerdemama-01"
    assert next_alias("Câncer de Mama!", ["cancerdemama-01", "cancerdemama-03", None]) == "cancerdemama-02"
    assert next_alias("projeto-muito-comprido-mesmo", []) == "projetomuito-01"


def test_apelido_sem_projeto():
    assert slugify(None) == "sessao" and slugify("!!!") == "sessao"
    assert next_alias(None, ["sessao-01"]) == "sessao-02"
    assert is_alias("sessao-02") and not is_alias("Sessao 2")


def test_estados_terminados_e_por_terminar_nao_se_misturam():
    assert not set(FINISHED_STATUSES) & set(UNFINISHED_STATUSES)
    assert "active" not in FINISHED_STATUSES + UNFINISHED_STATUSES


@pytest.mark.parametrize("motivo", ["aguarda_pesquisador", "suspensa_sem_pesquisador"])
def test_estados_retomaveis_sem_confirmacao(motivo):
    """Scenario: ``aguarda_pesquisador`` e ``suspensa_sem_pesquisador`` retomam sem perguntar."""
    cp = Checkpoint(session_id="s", motivo_parada=motivo)
    assert evaluate_resumability("closed", cp).decision == RESUME_OK
    assert evaluate_resumability(motivo, cp).decision == RESUME_OK


def test_encerrada_pelo_pesquisador_pede_confirmacao():
    cp = Checkpoint(session_id="s", motivo_parada="encerrada_pesquisador")
    assert evaluate_resumability("closed", cp).decision == RESUME_CONFIRM
