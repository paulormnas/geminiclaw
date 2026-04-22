"""Roadmap V3 - Testes unitários — Etapa V3: Triage local sem container.

Valida:
- Prompts curtos são classificados como SIMPLE com alta confiança
- Palavras-chave de pesquisa/complexidade disparam COMPLEX
- Múltiplos verbos de ação disparam COMPLEX
- Histórico de decisões influencia a classificação
- Confiança está sempre no intervalo [0, 1]
- AutonomousLoop usa TriageClassifier no modo heuristic/hybrid/llm
- Modo heuristic nunca chama _llm_triage_direct
"""

import os
import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from src.triage import TriageClassifier


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_classifier(**kwargs) -> TriageClassifier:
    """Cria um TriageClassifier com os parâmetros fornecidos."""
    return TriageClassifier(**kwargs)


# ---------------------------------------------------------------------------
# Heurística 1 — comprimento do prompt
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestTriageByLength:
    """Roadmap V3 - Etapa V3: Testes de classificação por comprimento do prompt."""

    def test_very_short_prompt_is_simple(self) -> None:
        """Prompt com poucos tokens deve ser SIMPLE com confiança ≥ 0.8."""
        clf = _make_classifier()
        decision, confidence = clf.classify("Olá, tudo bem?")
        assert decision == "SIMPLE"
        assert confidence >= 0.8  # < 20 tokens: 0.90; 20-49 tokens: 0.85


    def test_one_word_prompt_is_simple(self) -> None:
        """Prompt de uma palavra é SIMPLE."""
        clf = _make_classifier()
        decision, _ = clf.classify("Python")
        assert decision == "SIMPLE"

    def test_short_question_is_simple(self) -> None:
        """Pergunta curta sem keywords de complexidade é SIMPLE."""
        clf = _make_classifier()
        decision, _ = clf.classify("Qual a capital do Brasil?")
        assert decision == "SIMPLE"


# ---------------------------------------------------------------------------
# Heurística 2 — palavras-chave de pesquisa
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestTriageByKeywords:
    """Roadmap V3 - Etapa V3: Testes de classificação por palavras-chave."""

    def test_single_research_keyword_is_complex(self) -> None:
        """Um único keyword de pesquisa em prompt longo deve ser COMPLEX."""
        clf = _make_classifier()
        # Prompt com mais de 50 tokens e uma keyword
        prompt = "Por favor, analise os dados do arquivo iris.csv e me diga o que você encontrou nele. " * 3
        decision, confidence = clf.classify(prompt)
        assert decision == "COMPLEX"
        assert confidence > 0.0

    def test_multiple_research_keywords_high_confidence(self) -> None:
        """Múltiplas keywords devem gerar COMPLEX com confiança mais alta."""
        clf = _make_classifier()
        prompt = (
            "Pesquise o estado da arte em machine learning, compare os principais algoritmos "
            "de classificação, analise o dataset Iris e gere um relatório com visualizações."
        )
        decision, confidence = clf.classify(prompt)
        assert decision == "COMPLEX"
        assert confidence >= 0.75

    def test_pipeline_keyword_is_complex(self) -> None:
        """A palavra 'pipeline' deve disparar COMPLEX."""
        clf = _make_classifier()
        prompt = "Construa um pipeline de processamento de dados para o projeto de análise de textos."
        decision, _ = clf.classify(prompt)
        assert decision == "COMPLEX"

    def test_dataset_keyword_is_complex(self) -> None:
        """A palavra 'dataset' em prompt longo deve disparar COMPLEX."""
        clf = _make_classifier()
        prompt = (
            "Eu tenho um dataset com informações sobre clientes e preciso fazer uma análise "
            "exploratória para encontrar padrões e tendências no comportamento de compra."
        )
        decision, _ = clf.classify(prompt)
        assert decision == "COMPLEX"


# ---------------------------------------------------------------------------
# Heurística 3 — múltiplos verbos de ação
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestTriageByActionVerbs:
    """Roadmap V3 - Etapa V3: Testes de classificação por verbos de ação."""

    def test_two_action_verbs_is_complex(self) -> None:
        """Dois verbos de ação fortes devem produzir COMPLEX."""
        clf = _make_classifier()
        prompt = (
            "Por favor, pesquise os melhores frameworks de Python para criação de APIs REST "
            "e analise os prós e contras de cada um em termos de performance e escalabilidade."
        )
        decision, _ = clf.classify(prompt)
        assert decision == "COMPLEX"


# ---------------------------------------------------------------------------
# Heurística 5 — histórico de decisões
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestTriageByHistory:
    """Roadmap V3 - Etapa V3: Testes de classificação influenciada pelo histórico."""

    def test_repeated_complex_history_biases_to_complex(self) -> None:
        """Após 3 COMPLEX consecutivos, prompt ambíguo deve ser COMPLEX."""
        clf = _make_classifier(history_size=3, confidence_threshold=0.7)

        # Injeta 3 COMPLEX no histórico
        clf._history = ["COMPLEX", "COMPLEX", "COMPLEX"]

        # Prompt ambíguo: sem keywords de complexidade, sem verbos de ação,
        # mas longo o suficiente para não ser barrado pela regra de comprimento
        prompt = (
            "Fale sobre a evolução dos computadores ao longo das décadas "
            "e quais foram as principais mudanças tecnológicas que aconteceram. " * 2
        )
        decision, confidence = clf.classify(prompt)
        assert decision == "COMPLEX"
        assert confidence == 0.65  # confiança da heurística de histórico


    def test_reset_history_clears_decisions(self) -> None:
        """reset_history deve limpar o histórico de decisões."""
        clf = _make_classifier()
        clf._history = ["COMPLEX", "COMPLEX", "COMPLEX"]
        clf.reset_history()
        assert clf._history == []


# ---------------------------------------------------------------------------
# Confiança — invariantes
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestTriageConfidence:
    """Roadmap V3 - Etapa V3: Invariantes de confiança."""

    @pytest.mark.parametrize("prompt", [
        "Ok",
        "Qual é 2 + 2?",
        "Pesquise e analise o dataset Iris, treine um modelo e gere um relatório completo.",
        "Compare frameworks de machine learning e implemente um pipeline de classificação.",
        "A" * 1000,
    ])
    def test_confidence_is_in_valid_range(self, prompt: str) -> None:
        """Confiança deve sempre estar no intervalo [0, 1]."""
        clf = _make_classifier()
        _, confidence = clf.classify(prompt)
        assert 0.0 <= confidence <= 1.0, f"Confiança fora do intervalo: {confidence}"

    def test_classify_updates_history(self) -> None:
        """classify() deve adicionar a decisão ao histórico."""
        clf = _make_classifier()
        assert len(clf._history) == 0
        clf.classify("Olá")
        assert len(clf._history) == 1
        clf.classify("Pesquise e analise e compare e treine o modelo.")
        assert len(clf._history) == 2


# ---------------------------------------------------------------------------
# Integração com AutonomousLoop — modo heuristic
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
class TestAutonomousLoopTriageMode:
    """Roadmap V3 - Etapa V3: AutonomousLoop usa TriageClassifier por modo."""

    async def test_heuristic_mode_never_calls_llm(self) -> None:
        """No modo heuristic, _llm_triage_direct nunca deve ser chamado."""
        from src.autonomous_loop import AutonomousLoop

        mock_orchestrator = MagicMock()
        loop = AutonomousLoop(orchestrator=mock_orchestrator)
        loop._llm_triage_direct = AsyncMock(return_value=True)  # type: ignore[method-assign]

        with patch.dict(os.environ, {"TRIAGE_MODE": "heuristic"}):
            await loop._is_complex_triage("Olá, tudo bem?", "sess")

        loop._llm_triage_direct.assert_not_called()

    async def test_heuristic_mode_short_prompt_is_simple(self) -> None:
        """No modo heuristic, prompt curto deve ser classificado como SIMPLE."""
        from src.autonomous_loop import AutonomousLoop

        mock_orchestrator = MagicMock()
        loop = AutonomousLoop(orchestrator=mock_orchestrator)

        with patch.dict(os.environ, {"TRIAGE_MODE": "heuristic"}):
            is_complex = await loop._is_complex_triage("Qual é 2+2?", "sess")

        assert is_complex is False

    async def test_heuristic_mode_research_prompt_is_complex(self) -> None:
        """No modo heuristic, prompt de pesquisa deve ser classificado como COMPLEX."""
        from src.autonomous_loop import AutonomousLoop

        mock_orchestrator = MagicMock()
        loop = AutonomousLoop(orchestrator=mock_orchestrator)

        prompt = (
            "Pesquise o estado da arte em machine learning, analise os principais algoritmos "
            "e compare o desempenho deles no dataset Iris com um relatório final."
        )
        with patch.dict(os.environ, {"TRIAGE_MODE": "heuristic"}):
            is_complex = await loop._is_complex_triage(prompt, "sess")

        assert is_complex is True

    async def test_hybrid_mode_high_confidence_no_llm_call(self) -> None:
        """No modo hybrid com alta confiança, LLM não deve ser chamado."""
        from src.autonomous_loop import AutonomousLoop

        mock_orchestrator = MagicMock()
        loop = AutonomousLoop(orchestrator=mock_orchestrator)
        loop._llm_triage_direct = AsyncMock(return_value=True)  # type: ignore[method-assign]

        # Prompt com alta confiança para COMPLEX
        prompt = (
            "Pesquise o estado da arte em machine learning, analise os principais algoritmos "
            "e compare o desempenho deles no dataset Iris com relatório."
        )
        with patch.dict(os.environ, {"TRIAGE_MODE": "hybrid", "TRIAGE_CONFIDENCE_THRESHOLD": "0.7"}):
            await loop._is_complex_triage(prompt, "sess")

        loop._llm_triage_direct.assert_not_called()

    async def test_llm_mode_always_calls_llm(self) -> None:
        """No modo llm, _llm_triage_direct deve sempre ser chamado."""
        from src.autonomous_loop import AutonomousLoop

        mock_orchestrator = MagicMock()
        loop = AutonomousLoop(orchestrator=mock_orchestrator)
        loop._llm_triage_direct = AsyncMock(return_value=False)  # type: ignore[method-assign]

        with patch.dict(os.environ, {"TRIAGE_MODE": "llm"}):
            is_complex = await loop._is_complex_triage("Qualquer prompt", "sess")

        loop._llm_triage_direct.assert_called_once()
        assert is_complex is False
