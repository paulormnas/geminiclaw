"""Testes do rascunho do Problema pelo Researcher (v17-research-project). Sem LLM real nem rede."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from agents.researcher.agent import DRAFT_PROBLEM_INSTRUCTION, DRAFT_PROBLEM_MAX_REPAIRS, draft_problem
from src.knowledge.problem import ProblemDraftError

VALID = {
    "titulo": "Previsão do rendimento",
    "resumo": "Contexto, lacuna, objetivo e avanço esperado.",
    "classe": "regressao",
    "caracteristicas_dados": {"tamanho": "~2 mil"},
    "dominios": ["Química Orgânica"],
    "criterio_sucesso": {"metrica": "R2", "alvo": 0.8, "delta_min": 0.05, "baseline_descricao": "linear"},
}
PROJETO = SimpleNamespace(titulo="P", objetivo="O")


def fake_llm(*responses: str):
    calls: list[tuple[str, str]] = []
    queue = list(responses)

    async def _call(prompt: str, instruction: str) -> str:
        calls.append((prompt, instruction))
        return queue.pop(0)

    _call.calls = calls  # type: ignore[attr-defined]
    return _call


@pytest.mark.unit
@pytest.mark.asyncio
class TestDraftProblem:
    async def test_json_valido(self) -> None:
        draft = await draft_problem("p", None, PROJETO, llm_call=fake_llm(json.dumps(VALID)))
        assert draft.titulo == "Previsão do rendimento" and draft.delta_min == 0.05

    async def test_json_invalido_e_reparado(self) -> None:
        """Rascunho com JSON inválido é reparado (a mensagem de erro volta ao modelo)."""
        llm = fake_llm("isto não é json", "```json\n" + json.dumps(VALID) + "\n```")
        draft = await draft_problem("p", None, PROJETO, llm_call=llm)
        assert draft.resumo.startswith("Contexto")
        assert len(llm.calls) == 2
        assert "inválida" in llm.calls[1][0]

    async def test_json_invalido_falha_com_mensagem_clara(self) -> None:
        """Esgotados os reparos, falha com mensagem acionável."""
        llm = fake_llm(*["{}"] * (DRAFT_PROBLEM_MAX_REPAIRS + 1))
        with pytest.raises(ProblemDraftError, match="tentativas"):
            await draft_problem("p", None, PROJETO, llm_call=llm)
        assert len(llm.calls) == DRAFT_PROBLEM_MAX_REPAIRS + 1

    async def test_comentario_e_contexto_no_prompt(self) -> None:
        ctx = SimpleNamespace(to_prompt_context=lambda: "CONTEXTO-X")
        llm = fake_llm(json.dumps(VALID))
        await draft_problem("p", ctx, PROJETO, "foque em ruído", llm_call=llm)
        text = llm.calls[0][0]
        assert "CONTEXTO-X" in text and "foque em ruído" in text

    async def test_saida_acima_do_limite_e_recusada(self) -> None:
        big = {**VALID, "resumo": "x" * 5000}
        llm = fake_llm(*[json.dumps(big)] * (DRAFT_PROBLEM_MAX_REPAIRS + 1))
        with pytest.raises(ProblemDraftError):
            await draft_problem("p", None, PROJETO, llm_call=llm)


@pytest.mark.unit
class TestInstrucaoDoRascunho:
    def test_instrucao_pede_alto_nivel_sem_abordagem(self) -> None:
        """Scenario: Instrução do rascunho — resumo de artigo sem resultados, sem mencionar a abordagem."""
        text = DRAFT_PROBLEM_INSTRUCTION.lower()
        assert "resumo de um artigo" in text and "sem resultados" in text
        assert "independente de técnica" in text
        assert "não cite" in text and "abordagem" in text
        assert "{app_name}" not in DRAFT_PROBLEM_INSTRUCTION
