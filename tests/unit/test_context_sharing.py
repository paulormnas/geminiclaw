"""Roadmap v3 - Testes unitários — Etapa V2: Compartilhamento de contexto entre subtarefas.

Valida:
- AgentTask contém os novos campos task_name, depends_on, expected_artifacts
- _build_context_prefix lê da ShortTermMemory e formata corretamente
- Truncamento a _CONTEXT_MAX_CHARS é respeitado
- Tarefas sem depends_on recebem string vazia
- Validação de corrected_plan no orchestrator (parsing do Validator)
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from src.orchestrator import AgentTask, AgentResult, OrchestratorResult
from src.autonomous_loop import AutonomousLoop, _CONTEXT_MAX_CHARS
from src.skills.memory.short_term import ShortTermMemory


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_loop() -> AutonomousLoop:
    """Cria um AutonomousLoop com orquestrador mockado."""
    mock_orchestrator = MagicMock()
    return AutonomousLoop(orchestrator=mock_orchestrator)


# ---------------------------------------------------------------------------
# AgentTask — novos campos V2
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAgentTaskV2Fields:
    """Verifica que AgentTask possui os novos campos adicionados na V2."""

    def test_agent_task_has_task_name_field(self) -> None:
        """AgentTask deve aceitar task_name."""
        task = AgentTask(
            agent_id="researcher",
            image="geminiclaw-researcher",
            prompt="Pesquise X",
            task_name="levantamento_fontes",
        )
        assert task.task_name == "levantamento_fontes"

    def test_agent_task_task_name_defaults_to_empty_string(self) -> None:
        """task_name deve ter default de string vazia."""
        task = AgentTask(agent_id="base", image="img", prompt="p")
        assert task.task_name == ""

    def test_agent_task_has_depends_on_field(self) -> None:
        """AgentTask deve aceitar depends_on como lista de strings."""
        task = AgentTask(
            agent_id="base",
            image="img",
            prompt="Analise os dados",
            depends_on=["levantamento_fontes", "coleta_dados"],
        )
        assert task.depends_on == ["levantamento_fontes", "coleta_dados"]

    def test_agent_task_depends_on_defaults_to_empty_list(self) -> None:
        """depends_on deve ter default de lista vazia."""
        task = AgentTask(agent_id="base", image="img", prompt="p")
        assert task.depends_on == []

    def test_agent_task_has_expected_artifacts_field(self) -> None:
        """AgentTask deve aceitar expected_artifacts como lista de strings."""
        task = AgentTask(
            agent_id="researcher",
            image="img",
            prompt="p",
            expected_artifacts=["relatorio.md", "dados.csv"],
        )
        assert task.expected_artifacts == ["relatorio.md", "dados.csv"]

    def test_agent_task_expected_artifacts_defaults_to_empty_list(self) -> None:
        """expected_artifacts deve ter default de lista vazia."""
        task = AgentTask(agent_id="base", image="img", prompt="p")
        assert task.expected_artifacts == []

    def test_agent_task_full_v2_construction(self) -> None:
        """AgentTask deve aceitar todos os campos V2 juntos."""
        task = AgentTask(
            agent_id="base",
            image="geminiclaw-base",
            prompt="Analise iris.csv",
            task_name="analise_dados",
            depends_on=["levantamento_fontes"],
            expected_artifacts=["resultado.png", "stats.json"],
        )
        assert task.agent_id == "base"
        assert task.task_name == "analise_dados"
        assert task.depends_on == ["levantamento_fontes"]
        assert task.expected_artifacts == ["resultado.png", "stats.json"]


# ---------------------------------------------------------------------------
# _build_context_prefix — sem dependências
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBuildContextPrefixNoDeps:
    """Testa _build_context_prefix quando depends_on está vazio."""

    def test_returns_empty_string_when_no_deps(self) -> None:
        """Sem depends_on, deve retornar string vazia."""
        loop = _make_loop()
        result = loop._build_context_prefix("sess_1", [])
        assert result == ""

    def test_returns_empty_string_when_dep_not_in_memory(self) -> None:
        """Se a dependência não estiver na ShortTermMemory, retorna string vazia."""
        loop = _make_loop()
        # Garante memória limpa para a sessão
        loop._short_term_memory.clear("sess_dep_miss")
        result = loop._build_context_prefix("sess_dep_miss", ["tarefa_inexistente"])
        assert result == ""


# ---------------------------------------------------------------------------
# _build_context_prefix — com dependências na memória
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBuildContextPrefixWithDeps:
    """Testa _build_context_prefix quando há resultados na ShortTermMemory."""

    def _write(self, loop: AutonomousLoop, session_id: str, task_name: str, value: str) -> None:
        """Helper para escrever na ShortTermMemory do loop."""
        loop._short_term_memory.write(
            session_id=session_id,
            key=f"result:{task_name}",
            value=value,
            source="researcher",
            tags=["subtask_result", task_name],
        )

    def test_returns_context_block_for_single_dep(self) -> None:
        """Com uma dependência na memória, deve retornar bloco de contexto."""
        loop = _make_loop()
        session = "sess_single_dep"
        loop._short_term_memory.clear(session)

        self._write(loop, session, "levantamento_fontes", "Resultado da pesquisa bibliográfica.")

        prefix = loop._build_context_prefix(session, ["levantamento_fontes"])

        assert prefix.startswith("Contexto das etapas anteriores:")
        assert "levantamento_fontes" in prefix
        assert "Resultado da pesquisa bibliográfica." in prefix

    def test_returns_context_for_multiple_deps(self) -> None:
        """Com múltiplas dependências, todas devem aparecer no bloco."""
        loop = _make_loop()
        session = "sess_multi_dep"
        loop._short_term_memory.clear(session)

        self._write(loop, session, "etapa_a", "Texto da etapa A.")
        self._write(loop, session, "etapa_b", "Texto da etapa B.")

        prefix = loop._build_context_prefix(session, ["etapa_a", "etapa_b"])

        assert "etapa_a" in prefix
        assert "Texto da etapa A." in prefix
        assert "etapa_b" in prefix
        assert "Texto da etapa B." in prefix

    def test_skips_missing_dep_includes_present_one(self) -> None:
        """Se uma dependência não existir, inclui apenas as presentes."""
        loop = _make_loop()
        session = "sess_partial_dep"
        loop._short_term_memory.clear(session)

        self._write(loop, session, "etapa_existente", "Dados da etapa existente.")

        prefix = loop._build_context_prefix(session, ["etapa_inexistente", "etapa_existente"])

        assert "etapa_existente" in prefix
        assert "etapa_inexistente" not in prefix

    def test_prefix_ends_with_double_newline(self) -> None:
        """O prefixo deve terminar com dois newlines para separar do prompt."""
        loop = _make_loop()
        session = "sess_ending"
        loop._short_term_memory.clear(session)

        self._write(loop, session, "t1", "valor")

        prefix = loop._build_context_prefix(session, ["t1"])
        assert prefix.endswith("\n\n")


# ---------------------------------------------------------------------------
# _build_context_prefix — truncamento
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBuildContextPrefixTruncation:
    """Testa o truncamento do contexto ao limite _CONTEXT_MAX_CHARS."""

    def test_context_truncated_when_exceeds_limit(self) -> None:
        """Contexto maior que _CONTEXT_MAX_CHARS deve ser truncado."""
        loop = _make_loop()
        session = "sess_truncate"
        loop._short_term_memory.clear(session)

        # Texto maior que o limite
        large_text = "X" * (_CONTEXT_MAX_CHARS + 5_000)
        loop._short_term_memory.write(
            session_id=session,
            key="result:big_task",
            value=large_text,
            source="researcher",
        )

        prefix = loop._build_context_prefix(session, ["big_task"])

        # O prefixo completo (cabeçalho + contexto + \n\n) deve ser menor que
        # _CONTEXT_MAX_CHARS + overhead razoável do template
        # O que importa: a parte de contexto nunca excede _CONTEXT_MAX_CHARS
        assert len(prefix) <= _CONTEXT_MAX_CHARS + 200  # 200 de overhead do template

    def test_context_not_truncated_when_within_limit(self) -> None:
        """Contexto menor que o limite não deve ser truncado."""
        loop = _make_loop()
        session = "sess_no_truncate"
        loop._short_term_memory.clear(session)

        text = "A" * 100
        loop._short_term_memory.write(
            session_id=session,
            key="result:small_task",
            value=text,
            source="researcher",
        )

        prefix = loop._build_context_prefix(session, ["small_task"])
        assert "A" * 100 in prefix


# ---------------------------------------------------------------------------
# ShortTermMemory — operações básicas (garantia de contrato V2)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestShortTermMemoryV2Contract:
    """Verifica o contrato de ShortTermMemory usado pela injeção de contexto V2."""

    def test_write_and_read_subtask_result(self) -> None:
        """Deve escrever e ler resultado de subtarefa pela chave result:<task_name>."""
        mem = ShortTermMemory()
        session = "sess_stm_v2"
        mem.clear(session)

        mem.write(
            session_id=session,
            key="result:pesquisa_iris",
            value="O dataset Iris tem 150 amostras.",
            source="researcher",
            tags=["subtask_result", "pesquisa_iris"],
        )

        entry = mem.read(session, "result:pesquisa_iris")
        assert entry is not None
        assert entry.value == "O dataset Iris tem 150 amostras."
        assert entry.source == "researcher"

    def test_clear_removes_session_results(self) -> None:
        """clear() deve remover todos os resultados da sessão."""
        mem = ShortTermMemory()
        session = "sess_stm_clear"

        mem.write(session_id=session, key="result:t1", value="val1", source="base")
        mem.clear(session)

        assert mem.read(session, "result:t1") is None
        assert mem.list_all(session) == []

    def test_read_returns_none_for_missing_key(self) -> None:
        """read() deve retornar None para chaves inexistentes."""
        mem = ShortTermMemory()
        result = mem.read("sess_inexistente", "result:tarefa_inexistente")
        assert result is None
