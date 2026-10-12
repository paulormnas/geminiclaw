"""Modelo das afirmações (v18.5-claim-verification, design §1-§2, ADR 019 §6).

``status_afirmacao`` é um atributo **novo e independente** de ``Resultado.status_validacao``, de ``Attempt.validation``
e de ``Descoberta.status``: nenhum desses campos muda de valor ou de enumeração por causa dele.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

StatusAfirmacao = Literal[
    "suportada", "parcial", "refutada_deterministica", "contestada", "nao_verificavel", "pendente"
]
STATUSES: tuple[str, ...] = (
    "suportada",
    "parcial",
    "refutada_deterministica",
    "contestada",
    "nao_verificavel",
    "pendente",
)

MotivoPendencia = Literal["orcamento_esgotado", "falha_verificador", "sem_modelo_verificador"]
MOTIVOS_PENDENCIA: tuple[str, ...] = ("orcamento_esgotado", "falha_verificador", "sem_modelo_verificador")

METODO_DETERMINISTICO = "deterministico"
METODO_MODELO = "modelo"

ORIGEM_RELATORIO = "relatorio"
ORIGEM_DESCOBERTA = "descoberta"

ATOR_ORQUESTRADOR = "orquestrador"
ATOR_PESQUISADOR = "pesquisador"

FILE_VERSION = 1


@dataclass
class Conclusao:
    """Unidade de texto conferida (design §1).

    Attributes:
        conclusao_id: ``rel:<secao>:<n>`` (relatório) ou ``desc:<descoberta_id>``.
        origem: ``relatorio`` ou ``descoberta``.
        texto: Texto canônico da conclusão (com os valores já resolvidos pelas referências numéricas).
        autor: Papel que escreveu a conclusão (``summarizer`` ou ``curator``).
        secao: Seção do relatório (só para ``relatorio``).
        inicio: Posição do texto no relatório renderizado (só para ``relatorio``; não é gravada).
        ciclos: Ciclos de correção usados (§8).
        aprovada: Nenhuma ``refutada_deterministica`` restante depois dos ciclos (``None`` até haver verificação).
    """

    conclusao_id: str
    origem: str
    texto: str
    autor: str
    secao: str | None = None
    inicio: int = 0
    ciclos: int = 0
    aprovada: bool | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "conclusao_id": self.conclusao_id,
            "origem": self.origem,
            "autor": self.autor,
            "secao": self.secao,
            "ciclos": self.ciclos,
            "aprovada": self.aprovada,
        }


@dataclass
class Afirmacao:
    """Proposição verificável isoladamente, com o trecho de origem na conclusão (design §2)."""

    afirmacao_id: str
    codigo: str
    conclusao_id: str
    texto: str
    span: tuple[int, int]
    metodo: str | None
    status_afirmacao: str
    parte_nao_suportada: str | None = None
    evidencias: list[str] = field(default_factory=list)
    valores_registrados: dict[str, Any] = field(default_factory=dict)
    justificativa: str = ""
    verificador: dict[str, Any] | None = None
    motivo_pendencia: str | None = None
    motivo_nao_verificavel: str | None = None
    historico: list[dict[str, Any]] = field(default_factory=list)
    substituida_por: str | None = None
    revisao_pesquisador: dict[str, Any] | None = None
    session_id: str | None = None
    no_grafo: str | None = None  # id do nó ``Afirmacao`` (só para afirmações de Descoberta)

    def __post_init__(self) -> None:
        if self.status_afirmacao not in STATUSES:
            raise ValueError(f"status_afirmacao inválido: {self.status_afirmacao!r}")
        if self.status_afirmacao == "parcial" and not (self.parte_nao_suportada or "").strip():
            raise ValueError("'parcial' exige parte_nao_suportada.")
        if self.status_afirmacao == "pendente" and self.motivo_pendencia not in MOTIVOS_PENDENCIA:
            raise ValueError("'pendente' exige motivo_pendencia válido.")
        self.span = (int(self.span[0]), int(self.span[1]))

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["span"] = list(self.span)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Afirmacao":
        known = {k: data[k] for k in cls.__dataclass_fields__ if k in data}
        known["span"] = tuple(known.get("span") or (0, 0))
        return cls(**known)

    @property
    def revisada(self) -> bool:
        return self.substituida_por is not None
