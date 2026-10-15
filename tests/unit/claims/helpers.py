"""Apoio dos testes de verificação de afirmações: verificador simulado e construtores de valores."""

from __future__ import annotations

from typing import Any, Callable

from src.claims.deterministic import CodeValue
from src.claims.store import ClaimStore
from src.claims.verifier import ClaimBatchResult, ClaimVerifierError, EvidenceItem


class FakeVerifier:
    """Verificador simulado: devolve ``responder(frases, itens)`` e conta as chamadas (nenhum LLM real)."""

    def __init__(self, responder: Callable[[list[str], list[EvidenceItem]], Any] | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self._responder = responder or (lambda frases, itens: [])

    async def verify_claims(
        self, conclusao_id: str, conclusao_autor: str, frases: list[str], itens: list[EvidenceItem]
    ) -> ClaimBatchResult:
        self.calls.append({"conclusao_id": conclusao_id, "autor": conclusao_autor, "frases": frases, "itens": itens})
        result = self._responder(frases, itens)
        if isinstance(result, Exception):
            raise result
        return ClaimBatchResult(afirmacoes=list(result))


def supported(texto: str, frase: int = 1, evidencias: list[str] | None = None) -> dict[str, Any]:
    return {"texto": texto, "frase": frase, "status": "suportada", "evidencias": evidencias or ["ev1"],
            "justificativa": "ok"}


def code(codigo: str, valor: float, metrica: str | None = None, unidade: str | None = None) -> CodeValue:
    return CodeValue(codigo, valor, unidade, metrica)


def evidence_for(*refs: str) -> Callable[[Any, list], list[EvidenceItem]]:
    """Construtor de pacote com um item global por ``ref``."""
    from src.utils.egress_fragments import ContentOrigin

    def build(_conclusao: Any, _sentences: list) -> list[EvidenceItem]:
        return [
            EvidenceItem(f"ev{n}", ref, f"item {n}", f"conteúdo de {ref}", ContentOrigin.SAIDA_EXECUCAO)
            for n, ref in enumerate(refs, start=1)
        ]

    return build


def make_store(tmp_path, session_id: str = "s1") -> ClaimStore:
    return ClaimStore(tmp_path / session_id, session_id)


__all__ = ["ClaimVerifierError", "FakeVerifier", "code", "evidence_for", "make_store", "supported"]
