"""Regressão do benchmark V18.6: o GPT-6.1 Sol devolve `issues` como objetos; o restante do pipeline junta texto."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.agents.validator.agent import ValidatorAgent, issue_text
from src.llm.base import LLMResponse

pytestmark = pytest.mark.unit


def test_issue_text_de_objeto_e_de_texto() -> None:
    assert issue_text({"criterio": "c", "problema": "p"}) == "criterio: c; problema: p"
    assert issue_text("já é texto") == "já é texto"


@pytest.mark.asyncio
async def test_problemas_do_plano_em_objeto_viram_texto() -> None:
    reply = '{"status": "revision_needed", "reason": "r", "issues": [{"criterio": "c", "problema": "p"}, "outro"]}'
    provider = MagicMock()
    provider.model_name = "m"
    provider.generate = AsyncMock(return_value=LLMResponse(text=reply))
    steps = [{"agent_id": "developer", "task_name": "t", "prompt": "p", "validation_criteria": ["acuracia >= 0.8"]}]
    with patch("src.agents.validator.agent.record_llm_call"):
        result = await ValidatorAgent(provider=provider).validate_plan(steps, "t")
    assert all(isinstance(i, str) for i in result.issues)
    assert "; ".join(result.issues)  # o orquestrador junta os problemas
