"""Teste de integração — Etapa V2: subtarefa B recebe contexto de subtarefa A.

Valida o fluxo completo de compartilhamento de contexto dentro do
AutonomousLoop sem depender de containers Docker ou API real.
"""

import pytest
from unittest.mock import MagicMock, AsyncMock

from src.orchestrator import AgentTask, AgentResult, OrchestratorResult
from src.autonomous_loop import AutonomousLoop


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_agent_result(
    task_name: str,
    response_text: str,
    status: str = "success",
) -> AgentResult:
    """Cria um AgentResult simulando a resposta de um agente."""
    return AgentResult(
        agent_id="researcher",
        session_id=f"sess_{task_name}",
        status=status,
        response={"text": response_text},
        error=None,
    )


def _make_orchestrator_with_tasks(
    tasks: list[AgentTask],
    responses: list[AgentResult],
) -> tuple[AutonomousLoop, list[str]]:
    """
    Cria um AutonomousLoop mockado onde:
    - _run_planning_loop retorna `tasks`
    - _execute_agent retorna respostas em sequência

    Também captura os prompts enviados a cada agente.
    O passo _promote_findings é substituído por um no-op para isolar o teste.

    Returns:
        (loop, captured_prompts)
    """
    captured_prompts: list[str] = []
    call_idx = 0

    async def fake_execute_agent(task: AgentTask, master_session_id: str) -> AgentResult:
        nonlocal call_idx
        captured_prompts.append(task.prompt)
        result = responses[call_idx]
        call_idx += 1
        return result

    mock_orchestrator = MagicMock()
    mock_orchestrator._execute_agent = AsyncMock(side_effect=fake_execute_agent)
    mock_orchestrator._run_planning_loop = AsyncMock(return_value=tasks)
    mock_orchestrator.output_manager = MagicMock()
    mock_orchestrator.output_manager.list_artifacts = MagicMock(return_value=[])

    loop = AutonomousLoop(orchestrator=mock_orchestrator)
    # Substitui _promote_findings por no-op para isolar o teste
    loop._promote_findings = AsyncMock()  # type: ignore[method-assign]
    # Limpa ShortTermMemory para evitar contaminação entre testes
    loop._short_term_memory.clear("master_sess_integ")

    return loop, captured_prompts



# ---------------------------------------------------------------------------
# Teste principal: B recebe contexto de A
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
class TestContextInjectionIntegration:
    """Testes de integração do compartilhamento de contexto entre subtarefas."""

    async def test_task_b_receives_context_from_task_a(self) -> None:
        """Subtarefa B deve receber o resultado de A no prefixo do prompt."""
        tasks = [
            AgentTask(
                agent_id="researcher",
                image="geminiclaw-researcher",
                prompt="Pesquise sobre o dataset Iris.",
                task_name="pesquisa_iris",
                depends_on=[],
            ),
            AgentTask(
                agent_id="base",
                image="geminiclaw-base",
                prompt="Treine um modelo com os dados encontrados.",
                task_name="treino_modelo",
                depends_on=["pesquisa_iris"],
            ),
        ]

        responses = [
            _make_agent_result("pesquisa_iris", "O Iris tem 150 amostras com 4 features."),
            _make_agent_result("treino_modelo", "Modelo treinado com acurácia 95%."),
        ]

        loop, captured_prompts = _make_orchestrator_with_tasks(tasks, responses)

        result = await loop._run_complex_path("Pesquise e treine", "master_sess_integ")

        # Resultado consolidado
        assert result.total == 2
        assert result.succeeded == 2

        # Tarefa A: sem depends_on, prompt original inalterado
        assert captured_prompts[0] == "Pesquise sobre o dataset Iris."

        # Tarefa B: deve ter o prefixo de contexto
        prompt_b = captured_prompts[1]
        assert "Contexto das etapas anteriores:" in prompt_b
        assert "pesquisa_iris" in prompt_b
        assert "O Iris tem 150 amostras com 4 features." in prompt_b
        assert "Treine um modelo com os dados encontrados." in prompt_b

    async def test_task_without_depends_on_gets_no_prefix(self) -> None:
        """Subtarefa sem depends_on NÃO deve receber prefixo de contexto."""
        tasks = [
            AgentTask(
                agent_id="base",
                image="geminiclaw-base",
                prompt="Execute análise simples.",
                task_name="analise",
                depends_on=[],
            ),
        ]

        responses = [
            _make_agent_result("analise", "Análise concluída."),
        ]

        loop, captured_prompts = _make_orchestrator_with_tasks(tasks, responses)
        loop._short_term_memory.clear("master_sess_no_prefix")

        result = await loop._run_complex_path("Análise simples", "master_sess_no_prefix")

        assert result.succeeded == 1
        assert captured_prompts[0] == "Execute análise simples."
        assert "Contexto das etapas anteriores:" not in captured_prompts[0]

    async def test_chain_abc_context_propagation(self) -> None:
        """Cadeia A→B→C: C deve receber contexto de B (que vem de A)."""
        tasks = [
            AgentTask(
                agent_id="researcher",
                image="img",
                prompt="Passo A.",
                task_name="passo_a",
                depends_on=[],
            ),
            AgentTask(
                agent_id="base",
                image="img",
                prompt="Passo B.",
                task_name="passo_b",
                depends_on=["passo_a"],
            ),
            AgentTask(
                agent_id="base",
                image="img",
                prompt="Passo C.",
                task_name="passo_c",
                depends_on=["passo_b"],
            ),
        ]

        responses = [
            _make_agent_result("passo_a", "Resultado A."),
            _make_agent_result("passo_b", "Resultado B (usando A)."),
            _make_agent_result("passo_c", "Resultado C (usando B)."),
        ]

        loop, captured_prompts = _make_orchestrator_with_tasks(tasks, responses)
        loop._short_term_memory.clear("master_sess_chain")

        result = await loop._run_complex_path("Cadeia A→B→C", "master_sess_chain")

        assert result.succeeded == 3

        # Passo A: sem contexto
        assert "Contexto das etapas anteriores:" not in captured_prompts[0]

        # Passo B: contexto de A
        assert "passo_a" in captured_prompts[1]
        assert "Resultado A." in captured_prompts[1]

        # Passo C: contexto de B (não de A diretamente)
        assert "passo_b" in captured_prompts[2]
        assert "Resultado B" in captured_prompts[2]
        assert "passo_a" not in captured_prompts[2]  # C só depende de B

    async def test_failed_task_result_not_stored(self) -> None:
        """O resultado de uma subtarefa com falha NÃO deve ser armazenado na memória."""
        tasks = [
            AgentTask(
                agent_id="researcher",
                image="img",
                prompt="Tarefa que vai falhar.",
                task_name="tarefa_falha",
                depends_on=[],
            ),
            AgentTask(
                agent_id="base",
                image="img",
                prompt="Tarefa que depende da anterior.",
                task_name="tarefa_dependente",
                depends_on=["tarefa_falha"],
            ),
        ]

        responses = [
            AgentResult(
                agent_id="researcher",
                session_id="s1",
                status="error",
                response={},
                error="Erro simulado",
            ),
            _make_agent_result("tarefa_dependente", "Executei sem contexto."),
        ]

        loop, captured_prompts = _make_orchestrator_with_tasks(tasks, responses)
        loop._short_term_memory.clear("master_sess_fail")

        # max_retries=1 para acelerar o teste
        loop.max_retries = 1
        result = await loop._run_complex_path("Falha parcial", "master_sess_fail")

        # Tarefa dependente executa mas sem contexto (pois a anterior falhou)
        prompt_dep = captured_prompts[1]
        assert "Contexto das etapas anteriores:" not in prompt_dep

    async def test_short_term_memory_cleared_after_completion(self) -> None:
        """A ShortTermMemory deve ser limpa após a conclusão do _run_complex_path."""
        tasks = [
            AgentTask(
                agent_id="researcher",
                image="img",
                prompt="Tarefa única.",
                task_name="unica",
                depends_on=[],
            ),
        ]

        responses = [_make_agent_result("unica", "Resultado único.")]

        session = "master_sess_cleanup_v2"
        loop, _ = _make_orchestrator_with_tasks(tasks, responses)
        loop._short_term_memory.clear(session)

        await loop._run_complex_path("Tarefa", session)

        # Após conclusão, a memória da sessão deve estar limpa
        assert loop._short_term_memory.list_all(session) == []
