"""Roadmap V3 - Testes unitários — Etapa V1: Instruções especializadas para pesquisa.

Valida que cada AGENT_INSTRUCTION contém as palavras-chave obrigatórias
definidas no roadmap v3, Etapa V1.
"""

import pytest

from agents.base.agent import AGENT_INSTRUCTION as BASE_INSTRUCTION
from agents.researcher.agent import AGENT_INSTRUCTION as RESEARCHER_INSTRUCTION


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

