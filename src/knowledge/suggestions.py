"""Sugestões do Curator ao Researcher: ``suggest_paths`` e ``curator_suggestions.jsonl`` (v18-hypothesis-loop, §6).

Após consolidar, o Curator indica novos caminhos ao Researcher. As fontes são **fechadas** e a seleção é
**determinística** (nenhum LLM decide o que sugerir; não consome orçamento de tokens):

1. oportunidade com ``status="aprovada"`` — **nunca** ``documentada`` (só o pesquisador decide sobre oportunidades);
2. ``caminho_sem_conclusao`` ativo com ``proximo_passo_sugerido``;
3. alternativas a hipóteses ``refutada``, a partir de uma ``licao_de_caminho`` sobre elas;
4. abordagens com veredito positivo (``FUNCIONOU_PARA``) em problemas similares (``related_experience``) que o
   projeto ainda não propôs.

Cada sugestão é ``{id, texto, fundamento_ids, tipo}``. O texto vem de nós escritos por agentes: é **dado não
confiável**, saneado aqui e entregue ao Researcher dentro de ``<dado_nao_confiavel>``. O arquivo da sessão é
append-only; as respostas do Researcher entram como eventos ``resposta`` (a sugestão pendente é a sem resposta).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from src import config
from src.knowledge import opportunities
from src.knowledge.graph_store import GraphStore, Node
from src.knowledge.graph_views import sanitize_text
from src.knowledge.hypotheses import PendingSuggestion
from src.knowledge.normalization import normalize_domain_term
from src.knowledge.projects import get_active_problem
from src.logger import get_logger

logger = get_logger(__name__)

FILENAME = "curator_suggestions.jsonl"
TIPO_OPORTUNIDADE = "oportunidade_aprovada"
TIPO_CAMINHO = "caminho_sem_conclusao"
TIPO_LICAO = "licao_de_caminho"
TIPO_VARIACAO = "abordagem_em_problema_similar"
SUGGESTION_TYPES = (TIPO_OPORTUNIDADE, TIPO_CAMINHO, TIPO_LICAO, TIPO_VARIACAO)
_MAX_TEXT = 300
_MAX_FILE_BYTES = 1024 * 1024
_MAX_SCAN = 500


class SuggestionError(RuntimeError):
    """Falha ao sugerir caminhos (diferente de "sem sugestões": a lista vazia é um resultado válido)."""


@dataclass(frozen=True)
class Suggestion:
    """Sugestão do Curator (texto saneado)."""

    id: str
    texto: str
    fundamento_ids: tuple[str, ...]
    tipo: str

    def to_pending(self) -> PendingSuggestion:
        """Forma usada para validar as respostas do Researcher."""
        return PendingSuggestion(self.id, self.texto, self.fundamento_ids, self.tipo)


def suggestion_id(tipo: str, fundamento_ids: list[str] | tuple[str, ...]) -> str:
    """ID determinístico (a mesma sugestão tem o mesmo ID entre ciclos)."""
    raw = f"{tipo}|{'|'.join(sorted(fundamento_ids))}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


class SuggestionStore:
    """``outputs/<sessão>/curator_suggestions.jsonl``: sugestões e respostas (append-only, leitura tolerante)."""

    def __init__(self, session_dir: Path) -> None:
        self._path = Path(session_dir) / FILENAME

    def _events(self) -> list[dict[str, Any]]:
        try:
            if not self._path.is_file():
                return []
            size = self._path.stat().st_size
            if size > _MAX_FILE_BYTES:
                logger.warning(
                    "Arquivo de sugestões acima do limite: ignorado (sugestões e respostas indisponíveis)",
                    extra={"extra": {"bytes": size, "limite": _MAX_FILE_BYTES, "arquivo": self._path.name}},
                )
                return []
            lines = self._path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError as exc:
            logger.warning("Sugestões ilegíveis", extra={"extra": {"erro": type(exc).__name__}})
            return []
        events: list[dict[str, Any]] = []
        for line in lines:
            try:
                item = json.loads(line)
            except ValueError:
                continue
            if isinstance(item, dict):
                events.append(item)
        return events

    def _append(self, events: list[dict[str, Any]]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as fh:
            for event in events:
                fh.write(json.dumps(event, ensure_ascii=False) + "\n")

    def known_ids(self) -> set[str]:
        """IDs de todas as sugestões já feitas nesta sessão (pendentes ou respondidas)."""
        return {str(e["id"]) for e in self._events() if e.get("evento") == "sugestao" and "id" in e}

    def answered(self) -> dict[str, str]:
        """``id`` -> ``aceita``/``recusada`` das sugestões já respondidas."""
        return {
            str(e["id"]): str(e.get("decisao"))
            for e in self._events()
            if e.get("evento") == "resposta" and "id" in e
        }

    def pending(self) -> list[Suggestion]:
        """Sugestões ainda sem resposta do Researcher."""
        answered = self.answered()
        out: list[Suggestion] = []
        for event in self._events():
            if event.get("evento") != "sugestao" or str(event.get("id")) in answered:
                continue
            fundamentos = event.get("fundamento_ids")
            out.append(
                Suggestion(
                    id=str(event.get("id")),
                    texto=sanitize_text(event.get("texto", ""), _MAX_TEXT),
                    fundamento_ids=tuple(str(f) for f in fundamentos) if isinstance(fundamentos, list) else (),
                    tipo=str(event.get("tipo", "")),
                )
            )
        return out

    def add(self, suggestions: list[Suggestion]) -> list[Suggestion]:
        """Acrescenta as sugestões novas (as já conhecidas são ignoradas) e devolve as gravadas."""
        known = self.known_ids()
        fresh = [s for s in suggestions if s.id not in known]
        self._append([{"evento": "sugestao", **asdict(s), "fundamento_ids": list(s.fundamento_ids)} for s in fresh])
        return fresh

    def record_answers(self, answers: dict[str, str]) -> None:
        """Registra as respostas (``aceita``/``recusada``) já gravadas no grafo."""
        if answers:
            self._append([{"evento": "resposta", "id": sid, "decisao": dec} for sid, dec in answers.items()])


def _clean(value: Any) -> str:
    return sanitize_text(value, _MAX_TEXT) if value is not None else ""


def _hypotheses_by_text(store: GraphStore, project_id: str) -> tuple[set[str], set[str]]:
    """(enunciados normalizados de todas as hipóteses do projeto, IDs das abordagens que elas propõem)."""
    texts: set[str] = set()
    approaches: set[str] = set()
    for node in store.find_nodes("Hipotese", {"projeto_id": project_id}, limit=_MAX_SCAN):
        texts.add(normalize_domain_term(str(node.properties.get("enunciado", ""))))
        sub = store.neighbors(node.id, ["PROPOE"], direction="out", depth=1)
        approaches.update(e.dst_id for e in sub.edges if e.src_id == node.id and e.rel_type == "PROPOE")
    return texts, approaches


def _refuted_scope(store: GraphStore, discovery: Node) -> bool:
    sub = store.neighbors(discovery.id, ["SOBRE"], direction="out", depth=1)
    by_id = {n.id: n for n in sub.nodes}
    return any(
        e.src_id == discovery.id and e.rel_type == "SOBRE" and by_id.get(e.dst_id) is not None
        and by_id[e.dst_id].label == "Hipotese" and by_id[e.dst_id].properties.get("status") == "refutada"
        for e in sub.edges
    )


def _variation_candidates(
    store: GraphStore, project_id: str, index: Any | None, proposed_approaches: set[str]
) -> list[Suggestion]:
    problem = get_active_problem(store, project_id)
    if index is None or problem is None:
        return []
    try:
        items = index.related_experience(problem.id, 20, restrict_to_visible=True)
    except Exception as exc:  # noqa: BLE001 - sem índice a fonte é omitida
        logger.info("Experiência relacionada indisponível", extra={"extra": {"erro": type(exc).__name__}})
        return []
    out: list[Suggestion] = []
    for item in items:
        node = item.node
        if item.kind != "funcionou" or node.label != "Abordagem" or node.id in proposed_approaches:
            continue
        sub = store.neighbors(node.id, ["FUNCIONOU_PARA"], direction="out", depth=1)
        for edge in sub.edges:
            if edge.src_id != node.id or edge.dst_id != item.origem_problema_id:
                continue
            if edge.properties.get("status") == "contestada":
                continue
            discovery_id = edge.properties.get("descoberta_id")
            discovery = store.get_node(discovery_id) if isinstance(discovery_id, str) else None
            verdict = discovery.properties.get("veredito") if discovery is not None else None
            visible = discovery is not None and (
                discovery.properties.get("projeto_id") == project_id
                or discovery.properties.get("visibilidade") == "compartilhavel"
            )
            if not visible or not isinstance(verdict, (int, float)) or isinstance(verdict, bool) or verdict <= 0:
                continue
            texto = f"Testar a abordagem '{_clean(node.properties.get('nome'))}', que funcionou em problema similar."
            out.append(Suggestion(suggestion_id(TIPO_VARIACAO, [discovery.id]), texto, (discovery.id,), TIPO_VARIACAO))
            break
    return out


def build_candidates(store: GraphStore, project_id: str, index: Any | None = None) -> list[Suggestion]:
    """Candidatas das fontes permitidas, em ordem de prioridade (oportunidades aprovadas primeiro).

    Nunca inclui oportunidade que não esteja ``aprovada`` e nunca repete o que o projeto já tem como hipótese.
    """
    texts, proposed = _hypotheses_by_text(store, project_id)
    out: list[Suggestion] = []
    for opp in sorted(
        store.find_nodes("Oportunidade", {"projeto_id": project_id, "status": opportunities.STATUS_APROVADA},
                         limit=_MAX_SCAN),
        key=lambda n: n.id,
    ):
        out.append(Suggestion(suggestion_id(TIPO_OPORTUNIDADE, [opp.id]), _clean(opp.properties.get("enunciado")),
                              (opp.id,), TIPO_OPORTUNIDADE))
    for disc in sorted(
        store.find_nodes("Descoberta", {"projeto_id": project_id, "tipo": "caminho_sem_conclusao", "status": "ativa"},
                         limit=_MAX_SCAN),
        key=lambda n: n.id,
    ):
        step = _clean(disc.properties.get("proximo_passo_sugerido"))
        if step:
            out.append(Suggestion(suggestion_id(TIPO_CAMINHO, [disc.id]), step, (disc.id,), TIPO_CAMINHO))
    for disc in sorted(
        store.find_nodes("Descoberta", {"projeto_id": project_id, "tipo": "licao_de_caminho", "status": "ativa"},
                         limit=_MAX_SCAN),
        key=lambda n: n.id,
    ):
        lesson = _clean(disc.properties.get("enunciado"))
        if lesson and _refuted_scope(store, disc):
            out.append(
                Suggestion(suggestion_id(TIPO_LICAO, [disc.id]), f"Alternativa à hipótese refutada: {lesson}",
                           (disc.id,), TIPO_LICAO)
            )
    out.extend(_variation_candidates(store, project_id, index, proposed))
    return [s for s in out if s.texto and normalize_domain_term(s.texto) not in texts]


def suggest_paths(
    store: GraphStore,
    project_id: str,
    session_dir: Path,
    *,
    index: Any | None = None,
    max_suggestions: int | None = None,
) -> list[Suggestion]:
    """Gera até ``max_suggestions`` sugestões novas e as grava em ``curator_suggestions.jsonl``.

    Args:
        store: Grafo.
        project_id: Projeto da sessão.
        session_dir: ``outputs/<sessão>/``.
        index: Índice semântico (fonte "abordagens em problemas similares"); opcional.
        max_suggestions: Máximo por ciclo (padrão: ``CURATOR_MAX_SUGGESTIONS``).

    Returns:
        As sugestões **novas** gravadas neste ciclo (as pendentes antigas continuam pendentes até a resposta).
    """
    limit = config.CURATOR_MAX_SUGGESTIONS if max_suggestions is None else max_suggestions
    if limit <= 0:
        return []
    sugestoes = SuggestionStore(session_dir)
    known = sugestoes.known_ids()
    fresh = [c for c in build_candidates(store, project_id, index) if c.id not in known]
    return sugestoes.add(fresh[:limit])
