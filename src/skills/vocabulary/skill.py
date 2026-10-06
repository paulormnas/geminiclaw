"""Ferramenta ``buscar_dominio``: consulta os domínios do vocabulário controlado (v17-domain-search §6).

Somente leitura: não escreve no grafo, em arquivo nem em rede (o embedding é local). A entrada do
agente é tratada como dado: vira um vetor de consulta e filtros tipados do Qdrant, nunca texto de
Cypher ou SQL. A telemetria (``domain_search``) não registra o texto da consulta, que pode conter
conteúdo de pesquisa (ADR 019 §3).

A ferramenta é oferecida apenas aos papéis em ``DOMAIN_SEARCH_ROLES``; por isso **não** é
registrada no ``registry`` global de skills (que alimenta todos os papéis).
"""

from __future__ import annotations

from typing import Any, Callable

from src.knowledge.domain_search import MAX_RESULTS, DomainHit, DomainSearch
from src.knowledge.semantic_index import DOMAIN_LEVELS
from src.logger import get_logger
from src.skills.base import BaseSkill, SkillResult

logger = get_logger(__name__)

# Papéis que recebem a ferramenta (o ``developer`` não escreve no grafo e fica de fora).
DOMAIN_SEARCH_ROLES: tuple[str, ...] = ("researcher", "curator")

_MAX_RESPONSE_CHARS = 2000
_MAX_ENTRY_CHARS = 300
_MAX_INPUT_CHARS = 1000  # teto de segurança antes de qualquer processamento (a busca trunca em 300)
_LEVEL_NAMES = {
    "grande_area": "grande área",
    "area": "área",
    "subarea": "subárea",
    "especialidade": "especialidade",
}
_DESCRIPTION = (
    "Busca, no vocabulário controlado de domínios (Tabela de Áreas do Conhecimento do CNPq), os "
    "termos mais próximos de um texto livre e devolve até 10 candidatos com o caminho completo "
    "(grande área > área > subárea > especialidade), nível, score e id. Use antes de ligar um "
    "Problema ou Projeto a um domínio (NO_DOMINIO). Somente leitura. 'sem_correspondencia: true' "
    "indica que nenhum termo é próximo o bastante."
)


def _one_line(text: str) -> str:
    """Colapsa quebras de linha e espaços (mantém a saída estável, uma entrada por linha)."""
    return " ".join(str(text).split())


def format_hits(hits: list[DomainHit]) -> str:
    """Formata os candidatos: ``<caminho>  (<nível>, score <valor>, id=<id>)``, uma linha cada.

    Cada entrada tem no máximo 300 caracteres e a resposta no máximo 2 000 (entradas inteiras:
    nada é cortado no meio de uma linha).
    """
    if not hits:
        return "sem_correspondencia: true"
    lines: list[str] = []
    for rank, hit in enumerate(hits[:MAX_RESULTS], start=1):
        nivel = _LEVEL_NAMES.get(hit.nivel, hit.nivel)
        extra = ", candidato" if hit.status == "candidato" else ""
        tail = f"  ({nivel}{extra}, score {hit.score:.2f}".replace(".", ",") + f", id={hit.node_id})"
        path = _one_line(" > ".join(hit.caminho) or hit.termo)
        prefix = f"{rank}. "
        room = _MAX_ENTRY_CHARS - len(prefix) - len(tail)
        if len(path) > room:
            path = path[: max(room - 1, 0)] + "…"
        line = prefix + path + tail
        if len("\n".join([*lines, line])) > _MAX_RESPONSE_CHARS:
            break
        lines.append(line)
    return "\n".join(lines)


def _as_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip().lower() in ("true", "false"):
        return value.strip().lower() == "true"
    return None


class DomainSearchSkill(BaseSkill):
    """Skill somente leitura de busca de domínios."""

    name = "buscar_dominio"
    description = _DESCRIPTION
    parameters_schema = {
        "type": "object",
        "properties": {
            "texto": {
                "type": "string",
                "description": "Termo ou descrição do domínio (2 a 300 caracteres), em português ou inglês.",
            },
            "contexto": {
                "type": "string",
                "description": "Contexto opcional, por exemplo o título do problema (até 300 caracteres).",
            },
            "dentro_de": {
                "type": "string",
                "description": "Código CNPq ou ID de um domínio; restringe a busca à sua subárvore.",
            },
            "nivel_maximo": {
                "type": "string",
                "enum": list(DOMAIN_LEVELS),
                "description": "Nível mais específico aceito nos resultados.",
            },
            "incluir_candidatos": {
                "type": "boolean",
                "description": "Inclui termos candidatos ainda não aprovados (padrão: falso).",
            },
        },
        "required": ["texto"],
    }

    def __init__(self, search_factory: Callable[[], DomainSearch] | None = None) -> None:
        """Inicializa a skill.

        Args:
            search_factory: Cria a ``DomainSearch`` sob demanda (padrão: ``open_domain_search``).
                Preguiçosa para não abrir conexões ao montar o agente.
        """
        self._factory = search_factory
        self._search: DomainSearch | None = None

    def _get_search(self) -> DomainSearch:
        if self._search is None:
            if self._factory is not None:
                self._search = self._factory()
            else:
                from src.knowledge.domain_search import open_domain_search

                self._search = open_domain_search()
        return self._search

    async def run(
        self,
        texto: Any = None,
        contexto: Any = None,
        dentro_de: Any = None,
        nivel_maximo: Any = None,
        incluir_candidatos: Any = False,
        **_ignored: Any,
    ) -> SkillResult:
        """Busca domínios. Ver ``parameters_schema``; parâmetros desconhecidos são ignorados."""
        for label, value in (("texto", texto), ("contexto", contexto), ("dentro_de", dentro_de)):
            if value is not None and not isinstance(value, str):
                return SkillResult(success=False, output="", error=f"`{label}` deve ser texto.")
            if isinstance(value, str) and len(value) > _MAX_INPUT_CHARS and label != "texto":
                return SkillResult(success=False, output="", error=f"`{label}` longo demais.")
        if nivel_maximo is not None and nivel_maximo not in DOMAIN_LEVELS:
            return SkillResult(
                success=False, output="", error=f"`nivel_maximo` inválido; use um de {list(DOMAIN_LEVELS)}."
            )
        include = _as_bool(incluir_candidatos)
        if include is None:
            return SkillResult(success=False, output="", error="`incluir_candidatos` deve ser verdadeiro ou falso.")
        # Texto muito longo é só aparado (a busca trunca em DOMAIN_SEARCH_MAX_QUERY_CHARS).
        query = texto[:_MAX_INPUT_CHARS] if isinstance(texto, str) else None
        try:
            hits = self._get_search().search(
                query or "",
                context=contexto,
                within=dentro_de,
                max_level=nivel_maximo,
                include_candidates=include,
            )
        except ValueError as exc:
            return SkillResult(success=False, output="", error=str(exc))
        except Exception as exc:  # noqa: BLE001 - grafo/índice indisponível vira erro explícito, sem vazar detalhes
            logger.warning(
                "buscar_dominio indisponível",
                extra={"event": "domain_search_unavailable", "error_type": type(exc).__name__},
            )
            return SkillResult(
                success=False,
                output="",
                error="Busca de domínio indisponível: verifique o grafo de conhecimento e o índice semântico.",
            )

        best = hits[0] if hits else None
        # Telemetria: nunca inclui o texto da consulta nem o contexto (podem ter conteúdo de pesquisa).
        logger.info(
            "Busca de domínio",
            extra={
                "event": "domain_search",
                "resultados": len(hits),
                "melhor_score": round(best.score, 4) if best else None,
                "nivel_do_melhor": best.nivel if best else None,
                "candidatos_incluidos": include,
            },
        )
        return SkillResult(
            success=True,
            output=format_hits(hits),
            metadata={"resultados": len(hits), "sem_correspondencia": not hits},
        )


def domain_search_tools(role: str, search_factory: Callable[[], DomainSearch] | None = None) -> list[Callable]:
    """Ferramentas de busca de domínio de um papel (vazia para papéis fora de ``DOMAIN_SEARCH_ROLES``).

    Args:
        role: Papel do agente (``researcher``, ``curator``, ...).
        search_factory: ``DomainSearch`` injetável (testes).

    Returns:
        Lista com a ferramenta ``buscar_dominio`` no formato de ferramenta dos agentes.
    """
    if role not in DOMAIN_SEARCH_ROLES:
        return []
    from src.skills import SkillRegistry

    local = SkillRegistry()  # registro próprio: a ferramenta não entra no registry global
    local.register(DomainSearchSkill(search_factory))
    return local.as_tools()
