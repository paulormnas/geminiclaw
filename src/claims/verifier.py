"""Pacote de evidência e regras sobre a resposta do verificador (v18.5-claim-verification, design §5).

O modelo só **julga** contra o pacote; quem aplica as regras de status é o orquestrador (este módulo):
``refutada`` do modelo vira ``contestada``; ``suportada``/``parcial`` sem evidência citada que exista no pacote vira
``nao_verificavel``; ``parcial`` sem ``parte_nao_suportada`` vira ``nao_verificavel``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from src.egress.fragments import ContentOrigin

MODEL_STATUSES = ("suportada", "parcial", "refutada", "nao_verificavel")
MAX_FIELD_CHARS = 600

MOTIVO_SEM_EVIDENCIA = "sem_evidencia"
MOTIVO_NAO_DECOMPOSTA = "nao_decomposta"
MOTIVO_REFERENCIA_NAO_RESOLVIDA = "referencia_nao_resolvida"
MOTIVO_RESPOSTA_INVALIDA = "resposta_invalida"
MOTIVO_STATUS_DESCONHECIDO = "status_desconhecido"
MOTIVO_PARTE_AUSENTE = "parte_nao_suportada_ausente"


class ClaimVerifierError(RuntimeError):
    """O verificador não devolveu uma resposta utilizável (após as retentativas).

    ``fatal`` indica falha do provedor (conexão, limite do serviço): não adianta chamar de novo nesta execução.
    """

    def __init__(self, message: str, *, fatal: bool = False) -> None:
        super().__init__(message)
        self.fatal = fatal


class NoVerifierModel(ClaimVerifierError):
    """Nenhum modelo elegível para o papel ``validator``."""


@dataclass(frozen=True)
class EvidenceItem:
    """Item do pacote de evidência, com id estável dentro da chamada (``ev1``…).

    Attributes:
        ev_id: Id citado pelo verificador.
        ref: Referência gravada na afirmação (``res:exec_…/nome``, ``src:<id>#…``, ``resultado:<id>``…).
        titulo: Rótulo curto (subtarefa, hipótese…).
        texto: Conteúdo, tratado como **dado** (nunca como instrução).
        origem: Origem para o ``EgressGate`` (``saida_execucao``, ``grafo``, ``documento``).
        frases: Índices das frases que o item sustenta, ou ``None`` se vale para toda a conclusão.
    """

    ev_id: str
    ref: str
    titulo: str
    texto: str
    origem: ContentOrigin
    frases: frozenset[int] | None = None

    @property
    def size(self) -> int:
        return len(self.titulo) + len(self.texto) + len(self.ev_id) + 8


@dataclass
class ClaimBatchResult:
    """Resposta validada em forma (JSON) do Validator; as regras de status ainda não foram aplicadas."""

    afirmacoes: list[dict[str, Any]] = field(default_factory=list)


class ClaimVerifierPort(Protocol):
    """Quem verifica um lote: o ``ValidatorAgent`` em produção, um simulado nos testes."""

    async def verify_claims(
        self, conclusao_id: str, conclusao_autor: str, frases: list[str], itens: list[EvidenceItem]
    ) -> ClaimBatchResult: ...


@dataclass
class ClaimDraft:
    """Afirmação devolvida pelo verificador, já com as regras do orquestrador aplicadas."""

    texto: str
    frase: int | None  # índice da frase (0-based) ou None
    status: str  # "suportada" | "parcial" | "contestada" | "nao_verificavel"
    parte_nao_suportada: str | None = None
    evidencias: list[str] = field(default_factory=list)
    justificativa: str = ""
    motivo_nao_verificavel: str | None = None


def _text(value: Any) -> str:
    return " ".join(str(value or "").split())[:MAX_FIELD_CHARS]


def apply_response(
    result: ClaimBatchResult, frases: list[int], itens: list[EvidenceItem]
) -> list[ClaimDraft]:
    """Aplica as regras do orquestrador à resposta do modelo (design §5).

    Args:
        result: Resposta validada em forma.
        frases: Índices (0-based, na conclusão) das frases enviadas, na ordem em que foram numeradas (1…n) no prompt.
        itens: Pacote enviado (ids válidos para citar).
    """
    by_id = {item.ev_id: item for item in itens}
    drafts: list[ClaimDraft] = []
    for raw in result.afirmacoes:
        text = _text(raw.get("texto"))
        if not text:
            continue
        number = raw.get("frase")
        frase = frases[number - 1] if isinstance(number, int) and 1 <= number <= len(frases) else None
        status = str(raw.get("status", "")).strip().lower()
        justification = _text(raw.get("justificativa"))
        cited = [str(e) for e in (raw.get("evidencias") or []) if isinstance(e, (str, int))]
        valid = [by_id[e].ref for e in cited if e in by_id]
        if status not in MODEL_STATUSES:
            drafts.append(ClaimDraft(text, frase, "nao_verificavel", justificativa=justification,
                                     motivo_nao_verificavel=MOTIVO_STATUS_DESCONHECIDO))
        elif status == "refutada":
            drafts.append(ClaimDraft(text, frase, "contestada", evidencias=valid, justificativa=justification))
        elif status == "nao_verificavel":
            drafts.append(ClaimDraft(text, frase, "nao_verificavel", justificativa=justification))
        elif not valid or len(valid) != len(cited):
            # sem evidência citada, ou citando id fora do pacote
            drafts.append(ClaimDraft(text, frase, "nao_verificavel", justificativa=justification,
                                     motivo_nao_verificavel=MOTIVO_SEM_EVIDENCIA))
        elif status == "parcial":
            part = _text(raw.get("parte_nao_suportada"))
            if not part:
                drafts.append(ClaimDraft(text, frase, "nao_verificavel", evidencias=valid, justificativa=justification,
                                         motivo_nao_verificavel=MOTIVO_PARTE_AUSENTE))
            else:
                drafts.append(ClaimDraft(text, frase, "parcial", part, valid, justification))
        else:
            drafts.append(ClaimDraft(text, frase, "suportada", evidencias=valid, justificativa=justification))
    return drafts


def split_batches(
    frases: list[int], itens: list[EvidenceItem], max_chars: int, frase_sizes: dict[int, int]
) -> list[tuple[list[int], list[EvidenceItem]]]:
    """Divide as frases em lotes contíguos quando o pacote passa de ``max_chars`` (design §5).

    O pacote de cada lote tem os itens globais e os que tocam as frases do lote.
    """

    def package(batch: list[int]) -> list[EvidenceItem]:
        wanted = set(batch)
        return [i for i in itens if i.frases is None or (i.frases & wanted)]

    def size(batch: list[int]) -> int:
        return sum(i.size for i in package(batch)) + sum(frase_sizes.get(f, 0) for f in batch)

    batches: list[list[int]] = []

    def recurse(batch: list[int]) -> None:
        if len(batch) > 1 and size(batch) > max_chars:
            middle = len(batch) // 2
            recurse(batch[:middle])
            recurse(batch[middle:])
        else:
            batches.append(batch)

    if frases:
        recurse(frases)
    return [(batch, renumber(package(batch))) for batch in batches]


def renumber(itens: list[EvidenceItem]) -> list[EvidenceItem]:
    """Reenumera os ids (``ev1``…) de um pacote, mantendo ``ref`` e ``frases``."""
    return [
        EvidenceItem(f"ev{n}", i.ref, i.titulo, i.texto, i.origem, i.frases) for n, i in enumerate(itens, start=1)
    ]
