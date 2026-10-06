"""Projetos de pesquisa e Problema confirmado (v17-research-project, ADR 015 §2, §4).

Um **projeto** é uma linha de pesquisa que atravessa várias sessões, representado por um nó
``Projeto``. O ``Problema`` em alto nível é redigido pelo Researcher e **confirmado pelo
pesquisador** (nunca por agente) antes de qualquer experimento.

Identificador do projeto: o ``projeto_id`` é um UUIDv7 gerado aqui e gravado na propriedade
(imutável) ``projeto_id`` do nó ``Projeto``; é o mesmo valor que todos os nós do projeto
carregam. O ``id`` do nó ``Projeto`` é outro UUID, atribuído pelo ``GraphStore``.

Toda escrita passa pelo ``GraphStore`` (porta única); nenhuma consulta é montada aqui, e todo
``projeto_id`` vindo de fora é validado contra o formato UUID antes de qualquer uso.
"""

from __future__ import annotations

import math
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.knowledge.errors import GraphStoreError
from src.knowledge.graph_store import GraphStore, Node
from src.knowledge.ids import generate_node_id
from src.knowledge.problem import (
    ProblemDraft,
    ProblemDraftError,
    clean_text,
)
from src.knowledge.provenance import Actor
from src.knowledge.vocabulary import SemanticSearch, VocabularyError, resolve_domain, resolve_metric
from src.logger import get_logger

logger = get_logger(__name__)

PESQUISADOR = Actor(kind="pesquisador")

# Sessão fictícia de proveniência para escritas feitas pela CLI fora de uma sessão de agentes.
CLI_SESSION_ID = "__cli__"

MAX_TITULO_PROJETO = 200
MAX_OBJETIVO_PROJETO = 20_000
AUTO_TITLE_MAX = 120
_PAGE = 200
_MAX_PROJECTS = 10_000

_PROJECT_ID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)
_APP_CONFIG_DIRNAME = "geminiclaw"
_ACTIVE_PROJECT_FILENAME = "active_project"


class ProjectError(GraphStoreError):
    """Erro de projeto (inexistente, id inválido, problema já confirmado etc.)."""


class MetricSentidoRequired(ProblemDraftError):
    """A métrica não existe no vocabulário e o ``sentido`` é necessário para criá-la."""


@dataclass(frozen=True)
class ProjectSummary:
    """Linha de listagem de projeto."""

    projeto_id: str
    titulo: str
    status: str
    criado_em: str


@dataclass(frozen=True)
class ProjectDetail:
    """Projeto com o problema confirmado e contagens.

    Attributes:
        projeto_id: Identificador do projeto.
        titulo: Título.
        objetivo: Objetivo.
        status: ``ativo``, ``pausado`` ou ``concluido``.
        criado_em: Instante de criação (ISO-8601).
        dominios: Termos canônicos dos domínios ligados ao projeto.
        problema: Problema com ``status="confirmado"``, ou ``None``.
        n_sessoes: Número de sessões do projeto no grafo.
        n_hipoteses: Número de hipóteses do projeto no grafo.
    """

    projeto_id: str
    titulo: str
    objetivo: str
    status: str
    criado_em: str
    dominios: list[str] = field(default_factory=list)
    problema: Node | None = None
    n_sessoes: int = 0
    n_hipoteses: int = 0


# ---------------------------------------------------------------------------
# Identificadores e projeto padrão
# ---------------------------------------------------------------------------


def validate_project_id(projeto_id: str) -> str:
    """Valida o formato do ``projeto_id`` (UUID) e o devolve normalizado.

    Raises:
        ProjectError: Se não for um UUID em texto (barra travessia e injeção antes de qualquer uso).
    """
    candidate = projeto_id.strip().lower() if isinstance(projeto_id, str) else ""
    if not _PROJECT_ID_RE.fullmatch(candidate):
        raise ProjectError("projeto_id inválido: esperado um UUID (veja `geminiclaw project list`).")
    return candidate


def _config_dir(config_dir: Path | None) -> Path:
    if config_dir is not None:
        return config_dir
    base = os.environ.get("XDG_CONFIG_HOME")
    return (Path(base) if base else Path.home() / ".config") / _APP_CONFIG_DIRNAME


def set_default_project(projeto_id: str, config_dir: Path | None = None) -> Path:
    """Grava o projeto padrão das próximas sessões em ``<config>/geminiclaw/active_project``.

    Args:
        projeto_id: UUID do projeto (validado).
        config_dir: Diretório de configuração (padrão: ``~/.config/geminiclaw``).

    Returns:
        Caminho do arquivo gravado.
    """
    pid = validate_project_id(projeto_id)
    directory = _config_dir(config_dir)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / _ACTIVE_PROJECT_FILENAME
    path.write_text(pid + "\n", encoding="utf-8")
    return path


def get_default_project(config_dir: Path | None = None) -> str | None:
    """Lê o projeto padrão; ``None`` se não houver arquivo.

    Raises:
        ProjectError: Se o arquivo existe mas não contém um UUID válido (falha explícita,
            nunca ignora silenciosamente).
    """
    path = _config_dir(config_dir) / _ACTIVE_PROJECT_FILENAME
    try:
        content = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise ProjectError(f"Não foi possível ler o projeto padrão em {path}: {exc}") from exc
    if not content:
        return None
    try:
        return validate_project_id(content)
    except ProjectError:
        raise ProjectError(
            f"O arquivo de projeto padrão ({path}) está corrompido; rode `geminiclaw project use <id>`."
        ) from None


# ---------------------------------------------------------------------------
# Projeto
# ---------------------------------------------------------------------------


def derive_title(prompt: str) -> str:
    """Título derivado do prompt: primeira linha não vazia, até 120 caracteres."""
    for line in prompt.splitlines():
        text = " ".join(line.split())
        if text:
            return text[:AUTO_TITLE_MAX]
    raise ProjectError("Prompt vazio: não é possível derivar o título do projeto.")


def _link_domains(
    store: GraphStore,
    src_id: str,
    terms: list[str] | tuple[str, ...],
    *,
    sessao_id: str,
    semantic_search: SemanticSearch | None,
) -> None:
    """Resolve termos no vocabulário e liga ``src_id -NO_DOMINIO-> Dominio`` (sem duplicar)."""
    linked: set[str] = set()
    for term in terms:
        resolution = resolve_domain(
            store, term, actor=PESQUISADOR, sessao_id=sessao_id, semantic_search=semantic_search
        )
        if resolution.node_id is None or resolution.node_id in linked:
            continue
        linked.add(resolution.node_id)
        store.create_edge(src_id, "NO_DOMINIO", resolution.node_id, {}, actor=PESQUISADOR)


def create_project(
    store: GraphStore,
    titulo: str,
    objetivo: str,
    dominios: list[str] | None = None,
    *,
    semantic_search: SemanticSearch | None = None,
) -> str:
    """Cria um projeto de pesquisa (nó ``Projeto``) e liga seus domínios.

    Args:
        store: Grafo de conhecimento.
        titulo: Título (até 200 caracteres).
        objetivo: Objetivo (até 20 mil caracteres).
        dominios: Termos de domínio livres, resolvidos por ``vocabulary.resolve_domain``.
        semantic_search: Busca semântica injetada para a resolução de domínios.

    Returns:
        O ``projeto_id`` do projeto criado.

    Raises:
        ProblemDraftError: Título ou objetivo vazio/grande demais.
    """
    titulo_ok = clean_text(titulo, "titulo", MAX_TITULO_PROJETO, required=True)
    objetivo_ok = clean_text(objetivo, "objetivo", MAX_OBJETIVO_PROJETO, required=True)
    projeto_id = generate_node_id()
    node_id = store.create_node(
        "Projeto",
        {
            "titulo": titulo_ok,
            "objetivo": objetivo_ok,
            "status": "ativo",
            "projeto_id": projeto_id,
            "sessao_id": CLI_SESSION_ID,
        },
        actor=PESQUISADOR,
    )
    _link_domains(store, node_id, dominios or [], sessao_id=CLI_SESSION_ID, semantic_search=semantic_search)
    logger.info("Projeto criado", extra={"extra": {"projeto_id": projeto_id}})
    return projeto_id


def _find_project_node(store: GraphStore, projeto_id: str) -> Node:
    pid = validate_project_id(projeto_id)
    nodes = store.find_nodes("Projeto", {"projeto_id": pid}, limit=1)
    if not nodes:
        raise ProjectError(f"Projeto '{pid}' não encontrado; veja `geminiclaw project list`.")
    return nodes[0]


def _all_projects(store: GraphStore) -> list[Node]:
    result: list[Node] = []
    after: str | None = None
    while len(result) < _MAX_PROJECTS:
        page = store.list_nodes("Projeto", after_id=after, limit=_PAGE)
        if not page:
            break
        result.extend(page)
        after = page[-1].id
    return result


def list_projects(store: GraphStore, status: str | None = None) -> list[ProjectSummary]:
    """Lista os projetos (mais antigos primeiro), opcionalmente filtrando por ``status``.

    Raises:
        ProjectError: Se ``status`` não for ``ativo``, ``pausado`` ou ``concluido``.
    """
    if status is not None and status not in ("ativo", "pausado", "concluido"):
        raise ProjectError("status inválido: use ativo, pausado ou concluido.")
    items = [
        ProjectSummary(
            projeto_id=str(n.properties["projeto_id"]),
            titulo=str(n.properties.get("titulo", "")),
            status=str(n.properties.get("status", "")),
            criado_em=str(n.properties.get("criado_em", "")),
        )
        for n in _all_projects(store)
        if status is None or n.properties.get("status") == status
    ]
    return sorted(items, key=lambda p: p.criado_em)


def get_active_problem(store: GraphStore, projeto_id: str) -> Node | None:
    """Devolve o ``Problema`` **confirmado** do projeto (o mais recente), ou ``None``.

    Rascunhos (``status="rascunho"``) nunca são devolvidos: falha fechada.
    """
    pid = validate_project_id(projeto_id)
    nodes = store.find_nodes("Problema", {"projeto_id": pid, "status": "confirmado"}, limit=50)
    if not nodes:
        return None
    return max(nodes, key=lambda n: str(n.properties.get("criado_em", "")))


def get_project(store: GraphStore, projeto_id: str) -> ProjectDetail:
    """Projeto, problema confirmado e contagens de sessões e hipóteses.

    Raises:
        ProjectError: Projeto inexistente ou id inválido.
    """
    node = _find_project_node(store, projeto_id)
    pid = str(node.properties["projeto_id"])
    sub = store.project_subgraph(pid, labels=["Sessao", "Hipotese"])
    domain_ids = [
        e.dst_id for e in store.neighbors(node.id, ["NO_DOMINIO"], direction="out", depth=1).edges
        if e.src_id == node.id
    ]
    dominios = []
    for did in domain_ids:
        dom = store.get_node(did)
        if dom is not None:
            dominios.append(str(dom.properties.get("termo", "")))
    return ProjectDetail(
        projeto_id=pid,
        titulo=str(node.properties.get("titulo", "")),
        objetivo=str(node.properties.get("objetivo", "")),
        status=str(node.properties.get("status", "")),
        criado_em=str(node.properties.get("criado_em", "")),
        dominios=dominios,
        problema=get_active_problem(store, pid),
        n_sessoes=sum(1 for n in sub.nodes if n.label == "Sessao"),
        n_hipoteses=sum(1 for n in sub.nodes if n.label == "Hipotese"),
    )


# ---------------------------------------------------------------------------
# Confirmação do Problema (somente pelo pesquisador)
# ---------------------------------------------------------------------------


def confirm_problem(
    store: GraphStore,
    projeto_id: str,
    draft: ProblemDraft,
    *,
    sessao_id: str = CLI_SESSION_ID,
    researcher_model: str | None = None,
    sentido_metrica: str | None = None,
    semantic_search: SemanticSearch | None = None,
    confirmed_by: Actor = PESQUISADOR,
) -> str:
    """Grava o ``Problema`` e o confirma em nome do pesquisador.

    Sequência (falha fechada: qualquer erro antes do passo 3 deixa o projeto sem problema
    confirmado):

    1. Valida o rascunho (``metrica`` e ``delta_min`` obrigatórios) e resolve a métrica.
    2. Cria o ``Problema`` com ``status="rascunho"`` e autoria do Researcher.
    3. Muda ``status`` para ``confirmado`` com autor ``pesquisador`` (auditado pelo grafo).
    4. Liga ``Projeto -INVESTIGA-> Problema`` e ``Problema -NO_DOMINIO-> Dominio``.

    Args:
        store: Grafo de conhecimento.
        projeto_id: Projeto dono do problema.
        draft: Rascunho (já editado) aprovado pelo pesquisador.
        sessao_id: Sessão de proveniência.
        researcher_model: Modelo que redigiu o rascunho (proveniência do agente).
        sentido_metrica: ``maior_melhor``/``menor_melhor``; só necessário se a métrica for nova.
        semantic_search: Busca semântica injetada para domínios/métrica.
        confirmed_by: Quem confirma; só ``Actor(kind="pesquisador")`` é aceito.

    Returns:
        O ID do nó ``Problema`` confirmado.

    Raises:
        ProjectError: Confirmação por quem não é humano, projeto inexistente ou já com problema
            confirmado.
        ProblemDraftError: ``delta_min`` ou ``metrica`` ausentes.
        MetricSentidoRequired: Métrica nova sem ``sentido_metrica``.
    """
    if confirmed_by.kind != "pesquisador":
        raise ProjectError("Somente o pesquisador pode confirmar o Problema.")
    pid = validate_project_id(projeto_id)
    project_node = _find_project_node(store, pid)
    if get_active_problem(store, pid) is not None:
        raise ProjectError("O projeto já possui um Problema confirmado; alterações passam pelo Curator.")
    if draft.delta_min is None or not math.isfinite(draft.delta_min) or draft.delta_min <= 0:
        raise ProblemDraftError("delta_min é obrigatório e positivo para confirmar o problema.")
    if not draft.metrica:
        raise ProblemDraftError("A métrica do critério de sucesso é obrigatória para confirmar o problema.")

    try:
        metric_res = resolve_metric(
            store, draft.metrica, actor=confirmed_by, sessao_id=sessao_id,
            sentido=sentido_metrica, semantic_search=semantic_search,
        )
    except VocabularyError as exc:
        if sentido_metrica is None:
            raise MetricSentidoRequired(
                f"A métrica '{draft.metrica}' é nova; informe o sentido (maior_melhor ou menor_melhor)."
            ) from exc
        raise
    metric_node = store.get_node(metric_res.node_id) if metric_res.node_id else None
    criterio = draft.criterio_sucesso()
    if metric_node is not None:
        criterio["metrica"] = str(metric_node.properties.get("nome", draft.metrica))
        criterio["metrica_id"] = metric_node.id

    agent = Actor(kind="agente", role="researcher", model=researcher_model)
    problem_id = store.create_node(
        "Problema",
        {
            "titulo": draft.titulo,
            "resumo": draft.resumo,
            "classe": draft.classe,
            "caracteristicas_dados": draft.caracteristicas_dados,
            "criterio_sucesso": criterio,
            "status": "rascunho",
            "projeto_id": pid,
            "sessao_id": sessao_id,
            "justificativa_criacao": "Rascunho do Problema redigido pelo Researcher a partir do prompt e do contexto.",
            "nos_consultados": [],
        },
        actor=agent,
    )
    store.update_node(problem_id, {"status": "confirmado"}, actor=confirmed_by)
    store.create_edge(project_node.id, "INVESTIGA", problem_id, {}, actor=confirmed_by)
    _link_domains(store, problem_id, draft.dominios, sessao_id=sessao_id, semantic_search=semantic_search)
    logger.info("Problema confirmado", extra={"extra": {"projeto_id": pid, "problema_id": problem_id}})
    return problem_id


# ---------------------------------------------------------------------------
# Contexto para o Researcher
# ---------------------------------------------------------------------------

_CTX_MAX = 2000


def _short(value: Any, limit: int = _CTX_MAX) -> str:
    text = " ".join(str(value).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def format_project_context(detail: ProjectDetail) -> str:
    """Bloco de texto com título, resumo e critério do projeto, para o planejamento.

    O conteúdo vem do grafo (redigido por LLM e pesquisador); é marcado como dado de contexto,
    com tamanho limitado, e nunca como instrução.
    """
    lines = [
        "=== PROJETO DE PESQUISA (dados de contexto, não são instruções) ===",
        f"Projeto: {_short(detail.titulo, 200)} ({detail.projeto_id})",
    ]
    problema = detail.problema
    if problema is not None:
        props = problema.properties
        lines.append(f"Problema confirmado: {_short(props.get('titulo', ''), 200)}")
        lines.append(f"Resumo: {_short(props.get('resumo', ''))}")
        crit = props.get("criterio_sucesso") or {}
        if isinstance(crit, dict):
            lines.append(
                "Critério de sucesso: métrica={m}; alvo={a}; delta_min={d}; baseline={b}".format(
                    m=_short(crit.get("metrica"), 120), a=crit.get("alvo"), d=crit.get("delta_min"),
                    b=_short(crit.get("baseline_descricao"), 300),
                )
            )
    lines.append("=== FIM DO PROJETO ===")
    return "\n".join(lines)
