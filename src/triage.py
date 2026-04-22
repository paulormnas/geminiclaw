"""Roadmap V3 - Etapa V3: Classificador de triage local sem container.

Evita o overhead de spawnar um container Docker (~3-5s no Raspberry Pi 5)
apenas para decidir se uma tarefa é SIMPLE ou COMPLEX.

Suporta três modos via variável de ambiente TRIAGE_MODE:
- heuristic : apenas heurísticas locais (sem LLM, sem rede)
- llm       : chamada direta à API Gemini (sem container)
- hybrid    : heurísticas primeiro; fallback para LLM quando confiança < threshold
"""

import re
from typing import Literal

from src.logger import get_logger

logger = get_logger(__name__)

TriageDecision = Literal["SIMPLE", "COMPLEX"]

# ---------------------------------------------------------------------------
# Vocabulário de pesquisa / complexidade
# Roadmap V3 - Etapa V3: palavras-chave para decisão heurística
# ---------------------------------------------------------------------------

# Palavras-chave que indicam tarefa COMPLEX (pesquisa, análise, pipeline)
_COMPLEX_KEYWORDS: list[str] = [
    "pesquise", "pesquisa", "pesquisar",
    "compare", "compara", "comparar", "comparação",
    "analise", "análise", "analisa", "analisar",
    "pipeline", "workflow",
    "relatório", "relatorio", "report",
    "implemente", "implementa", "implementar",
    "desenvolva", "desenvolver",
    "treine", "treina", "treinar", "treinamento",
    "classifique", "classifica", "classificar", "classificação",
    "dataset", "conjunto de dados",
    "machine learning", "deep learning", "aprendizado",
    "revisão bibliográfica", "revisao bibliografica",
    "estado da arte", "survey", "levantamento",
    "indexe", "indexar", "indexação",
    "processe", "processar", "processamento",
    "transforme", "transformar",
    "visualize", "visualizar", "visualização",
    "busque profunda", "deep search",
    "múltiplas etapas", "multiplas etapas",
    "etapas", "subtarefas", "plano de execução",
]

# Verbos de ação fortes (cada ocorrência eleva complexidade)
_ACTION_VERBS: list[str] = [
    "pesquise", "analise", "compare", "implemente", "desenvolva",
    "treine", "classifique", "execute", "crie", "gere", "calcule",
    "processe", "transforme", "visualize", "indexe", "busque",
    "escreva", "produza", "construa", "avalie", "valide",
]


# ---------------------------------------------------------------------------
# TriageClassifier
# ---------------------------------------------------------------------------


class TriageClassifier:
    """Classifica prompts como SIMPLE ou COMPLEX usando heurísticas locais.

    Projetado para evitar o overhead de container no Raspberry Pi 5.
    Mantém um histórico das últimas decisões para identificar padrões
    de uso repetitivo e ajustar o limiar de complexidade.

    Args:
        history_size: Número de decisões recentes a considerar.
        confidence_threshold: Limiar abaixo do qual o modo 'hybrid'
            aciona o fallback LLM. Deve estar entre 0.0 e 1.0.
    """

    def __init__(
        self,
        history_size: int = 3,
        confidence_threshold: float = 0.7,
    ) -> None:
        self.history_size = history_size
        self.confidence_threshold = confidence_threshold
        self._history: list[TriageDecision] = []

    # ------------------------------------------------------------------
    # Métodos públicos
    # ------------------------------------------------------------------

    def classify(self, prompt: str) -> tuple[TriageDecision, float]:
        """Classifica o prompt e registra a decisão no histórico.

        Args:
            prompt: Texto enviado pelo usuário.

        Returns:
            Tupla (decisão, confiança) onde confiança está em [0, 1].
        """
        decision, confidence = self._classify_heuristic(prompt)

        logger.info(
            "Triage heurístico concluído",
            extra={
                "decision": decision,
                "confidence": round(confidence, 3),
                "prompt_tokens": self._count_tokens_approx(prompt),
            },
        )

        self._history.append(decision)
        return decision, confidence

    def reset_history(self) -> None:
        """Limpa o histórico de decisões."""
        self._history.clear()

    # ------------------------------------------------------------------
    # Heurísticas internas
    # ------------------------------------------------------------------

    @staticmethod
    def _count_tokens_approx(text: str) -> int:
        """Aproxima a contagem de tokens dividindo por 4 (padrão BPE médio)."""
        return max(1, len(text) // 4)

    def _classify_heuristic(self, prompt: str) -> tuple[TriageDecision, float]:
        """Aplica as heurísticas de classificação em ordem de prioridade.

        Heurísticas (em ordem de aplicação):
        1. Múltiplas palavras-chave de pesquisa/complexidade (≥ 2 → COMPLEX)
        2. Um único keyword de complexidade (→ COMPLEX, confiança moderada)
        3. Múltiplos verbos de ação (≥ 2 → COMPLEX)
        4. Prompt muito curto (< 20 tokens → SIMPLE, alta confiança)
        5. Histórico recente todo-COMPLEX (→ COMPLEX, confiança baixa)
        6. Prompt curto-médio (< 50 tokens, sem keywords/verbos → SIMPLE)
        7. Padrão: SIMPLE com confiança moderada

        Args:
            prompt: Texto do usuário.

        Returns:
            Tupla (decisão, confiança).
        """
        prompt_lower = prompt.lower().strip()
        token_count = self._count_tokens_approx(prompt)

        # Heurística 1 — múltiplas palavras-chave de complexidade (prioridade mais alta)
        keyword_hits = sum(1 for kw in _COMPLEX_KEYWORDS if kw in prompt_lower)
        if keyword_hits >= 2:
            confidence = min(0.75 + keyword_hits * 0.04, 0.99)
            return "COMPLEX", confidence

        # Heurística 2 — um único keyword de complexidade
        if keyword_hits == 1:
            return "COMPLEX", 0.72

        # Heurística 3 — múltiplos verbos de ação
        verb_hits = sum(1 for v in _ACTION_VERBS if v in prompt_lower)
        if verb_hits >= 2:
            return "COMPLEX", 0.82

        # Heurística 4 — prompt muito curto é simples (sem keywords nem verbos)
        if token_count < 20:
            return "SIMPLE", 0.90

        # Heurística 5 — histórico recente todo-COMPLEX (padrão de uso)
        if (
            len(self._history) >= self.history_size
            and all(d == "COMPLEX" for d in self._history[-self.history_size :])
        ):
            return "COMPLEX", 0.65

        # Heurística 6 — prompt curto sem keywords/verbos
        if token_count < 50:
            return "SIMPLE", 0.85

        # Padrão: SIMPLE com confiança moderada
        return "SIMPLE", 0.70

