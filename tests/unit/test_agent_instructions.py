"""Roadmap V3 - Testes unitários — Etapa V1: Instruções especializadas para pesquisa.

Valida que cada AGENT_INSTRUCTION contém as palavras-chave obrigatórias
definidas no roadmap v3, Etapa V1.
"""

import pytest

from agents.planner.agent import AGENT_INSTRUCTION as PLANNER_INSTRUCTION
from agents.validator.agent import AGENT_INSTRUCTION as VALIDATOR_INSTRUCTION
from agents.researcher.agent import AGENT_INSTRUCTION as RESEARCHER_INSTRUCTION
from agents.base.agent import AGENT_INSTRUCTION as BASE_INSTRUCTION


# ---------------------------------------------------------------------------
# Planner
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPlannerInstruction:
    """Valida a instrução do agente Planner."""

    def test_planner_has_research_persona(self) -> None:
        """Planner deve ter persona de pesquisa acadêmica."""
        assert "pesquisa acadêmica" in PLANNER_INSTRUCTION.lower() or "planejador de pesquisa" in PLANNER_INSTRUCTION.lower()

    def test_planner_decomposition_flow(self) -> None:
        """Planner deve mencionar o fluxo levantamento → análise → síntese → relatório."""
        instr_lower = PLANNER_INSTRUCTION.lower()
        assert "levantamento" in instr_lower
        assert "síntese" in instr_lower or "sintese" in instr_lower
        assert "relatório" in instr_lower or "relatorio" in instr_lower

    def test_planner_has_depends_on_field(self) -> None:
        """Planner deve mencionar o campo depends_on no formato JSON."""
        assert "depends_on" in PLANNER_INSTRUCTION

    def test_planner_has_expected_artifacts_field(self) -> None:
        """Planner deve mencionar o campo expected_artifacts."""
        assert "expected_artifacts" in PLANNER_INSTRUCTION

    def test_planner_has_task_name_field(self) -> None:
        """Planner deve mencionar o campo task_name."""
        assert "task_name" in PLANNER_INSTRUCTION

    def test_planner_has_subtask_limit(self) -> None:
        """Planner deve mencionar o limite de 5 subtarefas para o Pi 5."""
        assert "5" in PLANNER_INSTRUCTION
        instr_lower = PLANNER_INSTRUCTION.lower()
        assert "subtarefa" in instr_lower or "subtask" in instr_lower

    def test_planner_mentions_pi5_constraint(self) -> None:
        """Planner deve mencionar o Raspberry Pi 5 como motivação do limite."""
        assert "Raspberry Pi 5" in PLANNER_INSTRUCTION or "pi 5" in PLANNER_INSTRUCTION.lower()

    def test_planner_has_task_fusion_rule(self) -> None:
        """Planner deve mencionar a regra de fusão de tarefas com dependência de I/O."""
        instr_lower = PLANNER_INSTRUCTION.lower()
        assert "fusão" in instr_lower or "fusao" in instr_lower or "fundir" in instr_lower

    def test_planner_output_is_json_only(self) -> None:
        """Planner deve instruir saída exclusivamente em JSON."""
        instr_lower = PLANNER_INSTRUCTION.lower()
        assert "json" in instr_lower

    def test_planner_mentions_write_artifact(self) -> None:
        """Planner deve referenciar write_artifact para persistência."""
        assert "write_artifact" in PLANNER_INSTRUCTION

    def test_planner_mentions_researcher_agent(self) -> None:
        """Planner deve listar o agente researcher como disponível."""
        assert "researcher" in PLANNER_INSTRUCTION

    def test_planner_mentions_base_agent(self) -> None:
        """Planner deve listar o agente base como disponível."""
        assert "base" in PLANNER_INSTRUCTION


# ---------------------------------------------------------------------------
# Validator
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestValidatorInstruction:
    """Valida a instrução do agente Validator."""

    def test_validator_has_explicit_checklist(self) -> None:
        """Validator deve ter checklist explícito de validação."""
        instr_lower = VALIDATOR_INSTRUCTION.lower()
        assert "checklist" in instr_lower or "critério" in instr_lower or "criterio" in instr_lower

    def test_validator_checks_dependencies(self) -> None:
        """Validator deve verificar o campo depends_on."""
        assert "depends_on" in VALIDATOR_INSTRUCTION

    def test_validator_checks_pi5_viability(self) -> None:
        """Validator deve verificar viabilidade no Raspberry Pi 5."""
        assert "Pi 5" in VALIDATOR_INSTRUCTION or "pi 5" in VALIDATOR_INSTRUCTION.lower()

    def test_validator_rejects_plans_over_7_subtasks(self) -> None:
        """Validator deve rejeitar planos com mais de 7 subtarefas."""
        assert "7" in VALIDATOR_INSTRUCTION
        instr_lower = VALIDATOR_INSTRUCTION.lower()
        assert "subtarefa" in instr_lower or "subtask" in instr_lower

    def test_validator_requires_search_skills_for_research(self) -> None:
        """Validator deve verificar que subtarefas de pesquisa usam quick_search ou deep_search."""
        assert "quick_search" in VALIDATOR_INSTRUCTION
        assert "deep_search" in VALIDATOR_INSTRUCTION

    def test_validator_has_corrected_plan_field(self) -> None:
        """Validator deve incluir campo corrected_plan quando revision_needed."""
        assert "corrected_plan" in VALIDATOR_INSTRUCTION

    def test_validator_response_has_status_field(self) -> None:
        """Formato de resposta do Validator deve incluir campo status."""
        assert '"status"' in VALIDATOR_INSTRUCTION or "'status'" in VALIDATOR_INSTRUCTION or "status" in VALIDATOR_INSTRUCTION

    def test_validator_response_has_reason_field(self) -> None:
        """Formato de resposta do Validator deve incluir campo reason."""
        assert "reason" in VALIDATOR_INSTRUCTION

    def test_validator_checks_write_artifact_usage(self) -> None:
        """Validator deve verificar que subtarefas especificam write_artifact."""
        assert "write_artifact" in VALIDATOR_INSTRUCTION


# ---------------------------------------------------------------------------
# Researcher
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestResearcherInstruction:
    """Valida a instrução do agente Researcher."""

    def test_researcher_has_bibliographic_persona(self) -> None:
        """Researcher deve ter persona de pesquisador bibliográfico."""
        instr_lower = RESEARCHER_INSTRUCTION.lower()
        assert "bibliográfi" in instr_lower or "bibliografi" in instr_lower

    def test_researcher_requires_url_citations(self) -> None:
        """Researcher deve exigir citação de fontes com URL."""
        instr_lower = RESEARCHER_INSTRUCTION.lower()
        assert "url" in instr_lower
        assert "fonte" in instr_lower or "fontes" in instr_lower

    def test_researcher_requires_write_artifact(self) -> None:
        """Researcher deve usar write_artifact para salvar relatório."""
        assert "write_artifact" in RESEARCHER_INSTRUCTION

    def test_researcher_has_search_strategy(self) -> None:
        """Researcher deve descrever estratégia de pesquisa em etapas."""
        instr_lower = RESEARCHER_INSTRUCTION.lower()
        assert "query" in instr_lower or "busca" in instr_lower
        assert "síntese" in instr_lower or "sintese" in instr_lower or "sintetize" in instr_lower

    def test_researcher_mentions_quick_search(self) -> None:
        """Researcher deve mencionar quick_search para busca web."""
        assert "quick_search" in RESEARCHER_INSTRUCTION

    def test_researcher_mentions_deep_search(self) -> None:
        """Researcher deve mencionar deep_search para pesquisa profunda."""
        assert "deep_search" in RESEARCHER_INSTRUCTION

    def test_researcher_requires_markdown_report(self) -> None:
        """Researcher deve instruir produção de relatório em Markdown."""
        instr_lower = RESEARCHER_INSTRUCTION.lower()
        assert "markdown" in instr_lower or "relatório" in instr_lower or "relatorio" in instr_lower

    def test_researcher_mentions_memory_recall(self) -> None:
        """Researcher deve mencionar uso da ferramenta memory para recall."""
        assert "memory" in RESEARCHER_INSTRUCTION or "memória" in RESEARCHER_INSTRUCTION.lower()

    def test_researcher_requires_portuguese(self) -> None:
        """Researcher deve instruir respostas em português brasileiro."""
        instr_lower = RESEARCHER_INSTRUCTION.lower()
        assert "português" in instr_lower or "portugues" in instr_lower


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBaseInstruction:
    """Valida a instrução do agente Base."""

    def test_base_has_data_analysis_persona(self) -> None:
        """Base deve ter persona de análise de dados e geração de código."""
        instr_lower = BASE_INSTRUCTION.lower()
        assert "análise de dados" in instr_lower or "analise de dados" in instr_lower

    def test_base_requires_code_execution(self) -> None:
        """Base deve exigir execução do código gerado, nunca apenas exibi-lo."""
        instr_lower = BASE_INSTRUCTION.lower()
        assert "python_interpreter" in instr_lower or "python_interpreter" in BASE_INSTRUCTION

    def test_base_execute_never_display_rule(self) -> None:
        """Base deve ter regra explícita: executar, nunca apenas exibir."""
        instr_lower = BASE_INSTRUCTION.lower()
        # Deve mencionar que nunca basta exibir o código
        assert "nunca" in instr_lower or "never" in instr_lower or "sem executar" in instr_lower or "sem execut" in instr_lower

    def test_base_requires_write_artifact(self) -> None:
        """Base deve exigir write_artifact para todos os outputs."""
        assert "write_artifact" in BASE_INSTRUCTION

    def test_base_mentions_outputs_directory(self) -> None:
        """Base deve mencionar o diretório /outputs/."""
        assert "/outputs/" in BASE_INSTRUCTION

    def test_base_mentions_memory_tool(self) -> None:
        """Base deve mencionar uso da ferramenta memory."""
        assert "memory" in BASE_INSTRUCTION or "memória" in BASE_INSTRUCTION.lower()

    def test_base_requires_portuguese(self) -> None:
        """Base deve instruir respostas em português brasileiro."""
        instr_lower = BASE_INSTRUCTION.lower()
        assert "português" in instr_lower or "portugues" in instr_lower
