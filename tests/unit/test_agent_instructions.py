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

    def test_planner_context_decomposition(self) -> None:
        """Planner deve mencionar decomposição baseada em contexto."""
        instr_lower = PLANNER_INSTRUCTION.lower()
        assert "contexto" in instr_lower
        assert "metodológico" in instr_lower or "metodologico" in instr_lower

    def test_planner_has_depends_on_field(self) -> None:
        """Planner deve mencionar o campo depends_on no formato JSON."""
        assert "depends_on" in PLANNER_INSTRUCTION

    def test_planner_has_validation_criteria_field(self) -> None:
        """Planner deve mencionar o campo validation_criteria."""
        assert "validation_criteria" in PLANNER_INSTRUCTION

    def test_planner_has_subtask_limit(self) -> None:
        """Planner deve mencionar o limite de 7 subtarefas para o Pi 5."""
        assert "7" in PLANNER_INSTRUCTION
        instr_lower = PLANNER_INSTRUCTION.lower()
        assert "subtarefa" in instr_lower or "subtask" in instr_lower

    def test_planner_mentions_multi_instance(self) -> None:
        """Planner deve mencionar instanciar múltiplos agentes."""
        instr_lower = PLANNER_INSTRUCTION.lower()
        assert "múltiplos" in instr_lower or "multiplos" in instr_lower
        assert "agentes" in instr_lower

    def test_planner_output_is_json_only(self) -> None:
        """Planner deve instruir saída exclusivamente em JSON."""
        instr_lower = PLANNER_INSTRUCTION.lower()
        assert "json" in instr_lower

    def test_planner_mentions_preferred_model(self) -> None:
        """Planner deve mencionar preferred_model."""
        assert "preferred_model" in PLANNER_INSTRUCTION


# ---------------------------------------------------------------------------
# Validator
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestValidatorInstruction:
    """Valida a instrução do agente Validator."""

    def test_validator_validates_methodology(self) -> None:
        """Validator deve validar a metodologia."""
        instr_lower = VALIDATOR_INSTRUCTION.lower()
        assert "metodologia" in instr_lower

    def test_validator_checks_validation_criteria(self) -> None:
        """Validator deve verificar presence de validation_criteria."""
        assert "validation_criteria" in VALIDATOR_INSTRUCTION

    def test_validator_rejects_plans_over_7_subtasks(self) -> None:
        """Validator deve rejeitar planos com mais de 7 subtarefas."""
        assert "7" in VALIDATOR_INSTRUCTION

    def test_validator_checks_local_consultation(self) -> None:
        """Validator deve verificar se houve consulta local."""
        instr_lower = VALIDATOR_INSTRUCTION.lower()
        assert "local" in instr_lower or "bases locais" in instr_lower


# ---------------------------------------------------------------------------
# Researcher
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestResearcherInstruction:
    """Valida a instrução do agente Researcher."""

    def test_researcher_defines_methodology(self) -> None:
        """Researcher deve definir metodologia."""
        instr_lower = RESEARCHER_INSTRUCTION.lower()
        assert "metodologia" in instr_lower

    def test_researcher_requires_local_consultation(self) -> None:
        """Researcher deve consultar bases locais primeiro."""
        instr_lower = RESEARCHER_INSTRUCTION.lower()
        assert "local" in instr_lower or "bases locais" in instr_lower

    def test_researcher_has_boolean_operators(self) -> None:
        """Researcher deve usar operadores booleanos."""
        assert "AND" in RESEARCHER_INSTRUCTION or "OR" in RESEARCHER_INSTRUCTION

    def test_researcher_classifies_sources(self) -> None:
        """Researcher deve classificar fontes (primária, etc)."""
        instr_lower = RESEARCHER_INSTRUCTION.lower()
        assert "primária" in instr_lower or "primaria" in instr_lower


# ---------------------------------------------------------------------------
# Summarizer
# ---------------------------------------------------------------------------

from agents.summarizer.agent import AGENT_INSTRUCTION as SUMMARIZER_INSTRUCTION

@pytest.mark.unit
class TestSummarizerInstruction:
    """Valida a instrução do agente Summarizer."""

    def test_summarizer_has_traceability(self) -> None:
        """Summarizer deve ter rastreabilidade obrigatória."""
        instr_lower = SUMMARIZER_INSTRUCTION.lower()
        assert "rastreabilidade" in instr_lower

    def test_summarizer_has_references_with_url(self) -> None:
        """Summarizer deve ter referências com URL."""
        assert "URL" in SUMMARIZER_INSTRUCTION

    def test_summarizer_has_critical_analysis(self) -> None:
        """Summarizer deve ter análise crítica."""
        instr_lower = SUMMARIZER_INSTRUCTION.lower()
        assert "crítica" in instr_lower or "critica" in instr_lower

    def test_summarizer_has_confidence_level(self) -> None:
        """Summarizer deve ter nível de confiança."""
        instr_lower = SUMMARIZER_INSTRUCTION.lower()
        assert "confiança" in instr_lower or "confianca" in instr_lower


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
        """Base deve exigir execução do código gerado."""
        assert "python_interpreter" in BASE_INSTRUCTION

    def test_base_requires_write_artifact(self) -> None:
        """Base deve exigir write_artifact."""
        assert "write_artifact" in BASE_INSTRUCTION

