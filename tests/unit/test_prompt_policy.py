"""Teste de política de prompts (Roadmap V16 — openspec v16-research-assistant-prompts).

Percorre os templates de instrução e as instruções renderizadas de todos os
agentes para garantir que:

1. Os templates não contêm o valor literal "GeminiClaw" — o nome do produto
   só pode chegar aos prompts via `config.APP_NAME` (ADR 011).
2. As instruções renderizadas não citam mais "ADR 001" nem "Google ADK" —
   o sistema deixou de ser um harness baseado no ADK do Google (ADR 010, ADR 011).
3. As instruções renderizadas não orientam `subprocess` nem `pip install` —
   nenhum código roda no host, apenas via sandbox (ADR 014).
4. A instrução do Researcher proíbe busca bibliográfica autônoma.
"""

import importlib

import pytest

from src import config
from src.prompts import render_instruction

AGENT_MODULE_NAMES = [
    "agents.base.agent",
    "agents.developer.agent",
    "agents.researcher.agent",
    "agents.summarizer.agent",
    "agents.reviewer.agent",
]

FORBIDDEN_LITERAL_SUBSTRINGS = ("ADR 001", "Google ADK", "subprocess", "pip install")


def _agent_modules():
    """Importa e retorna todos os módulos de agente sob teste."""
    return [importlib.import_module(name) for name in AGENT_MODULE_NAMES]


@pytest.mark.unit
class TestPromptTemplatesDoNotHardcodeProductName:
    """Os templates de instrução não devem repetir o nome do produto literalmente."""

    def test_instruction_templates_have_no_literal_product_name(self) -> None:
        for module in _agent_modules():
            template = getattr(module, "_INSTRUCTION_TEMPLATE", None)
            assert template is not None, f"{module.__name__} não define _INSTRUCTION_TEMPLATE"
            assert "GeminiClaw" not in template, (
                f"{module.__name__}._INSTRUCTION_TEMPLATE contém o valor literal 'GeminiClaw'; "
                "use o marcador {app_name}."
            )

    def test_all_agent_modules_define_a_non_empty_description(self) -> None:
        for module in _agent_modules():
            description = getattr(module, "AGENT_DESCRIPTION", "")
            assert isinstance(description, str) and description.strip()


@pytest.mark.unit
class TestPromptPolicyOnRenderedInstructions:
    """As instruções renderizadas (com o APP_NAME padrão) não citam arquitetura obsoleta."""

    def test_no_forbidden_substrings_in_rendered_instructions(self) -> None:
        for module in _agent_modules():
            instruction = getattr(module, "AGENT_INSTRUCTION", None)
            assert instruction, f"{module.__name__} não define AGENT_INSTRUCTION"
            for forbidden in FORBIDDEN_LITERAL_SUBSTRINGS:
                assert forbidden not in instruction, (
                    f"{module.__name__}.AGENT_INSTRUCTION ainda contém '{forbidden}'"
                )

    def test_developer_instruction_states_sandbox_only_execution(self) -> None:
        from agents.developer.agent import AGENT_INSTRUCTION as DEVELOPER_INSTRUCTION

        instr_lower = DEVELOPER_INSTRUCTION.lower()
        assert "python_interpreter" in DEVELOPER_INSTRUCTION
        assert "sandbox" in instr_lower
        assert "packages" in instr_lower
        # Não pode mais afirmar que o próprio Developer roda em um container
        # dedicado (ADR 014) — código gerado roda no sandbox, não o agente.
        assert "executando em um container docker isolado" not in instr_lower


@pytest.mark.unit
class TestResearcherKeepsBibliographicSearchBan:
    """O Researcher continua proibido de fazer busca bibliográfica autônoma."""

    def test_researcher_forbids_autonomous_bibliographic_search(self) -> None:
        from agents.researcher.agent import AGENT_INSTRUCTION as RESEARCHER_INSTRUCTION

        instr_lower = RESEARCHER_INSTRUCTION.lower()
        assert "busca bibliográfica" in instr_lower
        assert "nunca" in instr_lower

    def test_researcher_allows_hypothesis_formulation_with_rationale(self) -> None:
        from agents.researcher.agent import AGENT_INSTRUCTION as RESEARCHER_INSTRUCTION

        instr_lower = RESEARCHER_INSTRUCTION.lower()
        assert "hipótese" in instr_lower
        assert "scientific_rationale" in RESEARCHER_INSTRUCTION

    def test_researcher_cites_adr_010_not_adr_001(self) -> None:
        from agents.researcher.agent import AGENT_INSTRUCTION as RESEARCHER_INSTRUCTION

        assert "ADR 010" in RESEARCHER_INSTRUCTION
        assert "ADR 001" not in RESEARCHER_INSTRUCTION


@pytest.mark.unit
class TestProductNameIsConfigurable:
    """Trocar `config.APP_NAME` deve refletir em todas as instruções renderizadas."""

    def test_renaming_app_name_propagates_to_every_instruction(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(config, "APP_NAME", "NovoNome")

        for module in _agent_modules():
            template = getattr(module, "_INSTRUCTION_TEMPLATE", None)
            if template is None:
                continue
            rendered = render_instruction(template)
            assert "NovoNome" in rendered or "{app_name}" not in template
            assert "GeminiClaw" not in rendered
