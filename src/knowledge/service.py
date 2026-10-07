"""``KnowledgeService``: cálculos determinísticos do conhecimento (v17-curator-agent, design §2).

Tudo o que pode ser calculado é calculado **sem LLM**; o Curator só interpreta. Este serviço:

- coleta as tentativas de uma hipótese no grafo e recalcula o veredito (``src.knowledge.verdict``, única
  fonte do cálculo), gravando ``suporte``, ``certeza``, ``veredito`` e ``n_tentativas`` na ``Hipotese`` e as
  arestas ``Resultado-SUSTENTA|REFUTA->Hipotese`` com ``peso = w``;
- recalcula as ``Descoberta``s ligadas (inclusive as condicionais, por ``filtro_condicoes``) e mantém os atalhos
  ``Abordagem-FUNCIONOU_PARA|FALHOU_PARA->Problema``;
- detecta e aplica a promoção de uma configuração a ``Abordagem(tipo="configuracao")``.

Toda escrita passa pela porta única (``GraphStore``) com ``Actor(kind="orquestrador")``. Tudo o que vem do
grafo (inclusive texto escrito por agentes) é dado: nada aqui vira consulta, só propriedades tipadas.
"""

from __future__ import annotations

import functools
import math
from dataclasses import dataclass, field
from typing import Any

from src import config
from src.knowledge.errors import GraphStoreError
from src.knowledge.graph_store import Edge, GraphStore, Node
from src.knowledge.ingestion import hash_params
from src.knowledge.projects import get_active_problem
from src.knowledge.provenance import Actor
from src.knowledge.verdict import Attempt, Criterion, VerdictParams, VerdictResult, compute_verdict
from src.logger import get_logger

logger = get_logger(__name__)

ACTOR_SERVICE = Actor(kind="orquestrador")
DISCOVERY_VERDICT_TYPES = ("funciona", "nao_funciona", "condicional")
_MAX_ATTEMPTS = 2000
_MAX_PROJECTS_SCANNED = 200
_PAGE = 200
_MAX_CONFIG_KEYS_IN_NAME = 3
_MAX_NAME_CHARS = 200
_NO_CONFIG = "sem_config"
# Relações de fatos (ingestão): seguras para memoizar durante uma operação.
_CACHEABLE_RELS = frozenset({"TESTA", "APLICOU", "PRODUZIU", "MEDE", "SOBRE", "FUNDIDA_EM", "EXECUTADO_EM"})


def _operation(fn: Any) -> Any:
    """Marca uma operação pública: o memo de leituras vale do início ao fim da operação mais externa."""

    @functools.wraps(fn)
    def wrapper(self: "KnowledgeService", *args: Any, **kwargs: Any) -> Any:
        if self._depth == 0:
            self._begin()
        self._depth += 1
        try:
            return fn(self, *args, **kwargs)
        finally:
            self._depth -= 1

    return wrapper


class KnowledgeServiceError(GraphStoreError):
    """O veredito não pôde ser calculado (critério ou tentativas ausentes); mensagem acionável."""


@dataclass(frozen=True)
class CollectedAttempt:
    """Uma tentativa lida do grafo, com os nós de onde veio.

    Attributes:
        attempt: A ``Attempt`` do módulo de veredito.
        experimento_id: ``Experimento`` de origem.
        resultado_id: ``Resultado`` do critério (``None`` em tentativas que falharam).
        abordagem_id: ``Abordagem`` aplicada, já resolvida por ``FUNDIDA_EM`` (``None`` se não houver).
        config: Configuração normalizada aplicada.
        projeto_id: Projeto do experimento.
        sessao_real: O experimento está ligado (``EXECUTADO_EM``) a uma ``Sessao`` do próprio projeto.
        compartilhavel: Experimento e resultado são ``compartilhavel`` (podem contar para outro projeto).
    """

    attempt: Attempt
    experimento_id: str
    resultado_id: str | None
    abordagem_id: str | None
    config: dict[str, Any]
    projeto_id: str
    sessao_real: bool = False
    compartilhavel: bool = False


@dataclass(frozen=True)
class PromotionCandidate:
    """Configuração elegível à promoção (≥ N positivos validados em ≥ M projetos).

    Attributes:
        abordagem_id: Abordagem base (canônica).
        config_hash: Hash da configuração normalizada.
        config: Configuração normalizada.
        positivos: Número de resultados positivos validados.
        projetos: Projetos distintos que os produziram.
        resultado_ids: Resultados positivos que sustentam a promoção.
    """

    abordagem_id: str
    config_hash: str
    config: dict[str, Any]
    positivos: int
    projetos: tuple[str, ...]
    resultado_ids: tuple[str, ...]


@dataclass
class RecomputeReport:
    """O que um recálculo pós-subtarefa fez (contagens, sem texto de pesquisa)."""

    hipoteses: int = 0
    descobertas: int = 0
    promovidas: list[str] = field(default_factory=list)
    ignoradas: int = 0


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _matches_filter(collected: CollectedAttempt, filtro: dict[str, Any] | None) -> bool:
    """Aplica ``filtro_condicoes`` (``dataset_ids`` e ``no_execucao``): vazio/ausente = todas as tentativas."""
    if not filtro:
        return True
    datasets = filtro.get("dataset_ids")
    if datasets and not (set(collected.attempt.dataset_ids) & {str(d) for d in datasets}):
        return False
    nodes = filtro.get("no_execucao")
    if nodes and collected.attempt.node_id not in {str(n) for n in nodes}:
        return False
    return True


class KnowledgeService:
    """Recalcula vereditos, mantém arestas derivadas e promove configurações (sem LLM)."""

    def __init__(
        self, store: GraphStore, params: VerdictParams | None = None, *, actor: Actor = ACTOR_SERVICE
    ) -> None:
        """Inicializa o serviço.

        Args:
            store: Porta única do grafo (de produção, o store indexado).
            params: Parâmetros do veredito (padrão: ``VerdictParams.from_config()``).
            actor: Autor das escritas (orquestrador).
        """
        self._store = store
        self._params = params or VerdictParams.from_config()
        self._actor = actor
        # Memo de leituras estruturais, válido dentro de uma operação pública (limpo a cada entrada): evita o N+1.
        self._nbcache: dict[tuple[str, str, str], Any] = {}
        self._verdict_cache: dict[str, tuple[VerdictResult, list[CollectedAttempt], Node]] = {}
        self._project_cache: dict[str, bool] = {}
        self._depth = 0

    # ------------------------------------------------------------------ leitura

    def _begin(self) -> None:
        """Início de uma operação pública: descarta os memos (o grafo pode ter mudado desde a última)."""
        self._nbcache.clear()
        self._verdict_cache.clear()
        self._project_cache.clear()


    def _sub(self, node_id: str, rel: str, direction: str) -> Any:
        """``neighbors`` de uma relação **estrutural** (fatos), memoizado; relações derivadas nunca são memoizadas."""
        if rel not in _CACHEABLE_RELS:
            return self._store.neighbors(node_id, [rel], direction=direction, depth=1)
        key = (node_id, rel, direction)
        if key not in self._nbcache:
            self._nbcache[key] = self._store.neighbors(node_id, [rel], direction=direction, depth=1)
        return self._nbcache[key]

    def _out(self, node_id: str, rel: str) -> list[Node]:
        sub = self._sub(node_id, rel, "out")
        by_id = {n.id: n for n in sub.nodes}
        return [by_id[e.dst_id] for e in sub.edges if e.src_id == node_id and e.rel_type == rel and e.dst_id in by_id]

    def _in(self, node_id: str, rel: str) -> list[Node]:
        sub = self._sub(node_id, rel, "in")
        by_id = {n.id: n for n in sub.nodes}
        return [by_id[e.src_id] for e in sub.edges if e.dst_id == node_id and e.rel_type == rel and e.src_id in by_id]

    def _out_edges(self, node_id: str, rel: str) -> list[Edge]:
        sub = self._sub(node_id, rel, "out")
        return [e for e in sub.edges if e.src_id == node_id and e.rel_type == rel]

    def canonical_approach(self, abordagem_id: str) -> str:
        """Segue ``FUNDIDA_EM`` até a abordagem canônica (com proteção contra ciclos)."""
        current, seen = abordagem_id, {abordagem_id}
        while True:
            edges = self._out_edges(current, "FUNDIDA_EM")
            targets = [e.dst_id for e in edges if e.properties.get("status") != "contestada"]
            if not targets or targets[0] in seen:
                return current
            current = targets[0]
            seen.add(current)

    def merged_approaches(self, canonica_id: str) -> set[str]:
        """Abordagens que resolvem para ``canonica_id`` (ela mesma e as fundidas nela, transitivamente)."""
        found = {canonica_id}
        frontier = [canonica_id]
        while frontier:
            nxt: list[str] = []
            for current in frontier:
                for other in self._in(current, "FUNDIDA_EM"):
                    if other.id not in found:
                        found.add(other.id)
                        nxt.append(other.id)
            frontier = nxt
        return found

    def problem_for(self, hipotese: Node) -> Node | None:
        """``Problema`` da hipótese (``SOBRE``) ou, sem ele, o ``Problema`` confirmado do projeto."""
        for node in self._out(hipotese.id, "SOBRE"):
            if node.label == "Problema":
                return node
        projeto = hipotese.properties.get("projeto_id")
        return get_active_problem(self._store, str(projeto)) if projeto else None

    def criterion_for(self, problema: Node) -> tuple[Criterion, Node]:
        """``Criterion`` do ``Problema`` (sentido da ``Metrica`` + ``delta_min``/``alvo``) e a ``Metrica``.

        Raises:
            KnowledgeServiceError: Problema sem ``criterio_sucesso`` com métrica resolvida.
        """
        criterio = problema.properties.get("criterio_sucesso")
        if not isinstance(criterio, dict):
            raise KnowledgeServiceError(f"Problema '{problema.id}' sem criterio_sucesso: veredito indisponível.")
        metric: Node | None = None
        if criterio.get("metrica_id"):
            metric = self._store.get_node(str(criterio["metrica_id"]))
        if metric is None and criterio.get("metrica"):
            found = self._store.find_nodes("Metrica", {"nome": str(criterio["metrica"])}, limit=1)
            metric = found[0] if found else None
        if metric is None or metric.properties.get("sentido") not in ("maior_melhor", "menor_melhor"):
            raise KnowledgeServiceError(f"Problema '{problema.id}' sem métrica canônica: veredito indisponível.")
        delta, alvo = criterio.get("delta_min"), criterio.get("alvo")
        return (
            Criterion(
                sentido=metric.properties["sentido"],
                delta_min=float(delta) if _is_number(delta) else None,
                alvo=float(alvo) if _is_number(alvo) else None,
            ),
            metric,
        )

    def _config_of(self, exp: Node) -> tuple[dict[str, Any], str, str | None]:
        """``(config normalizada, hash, abordagem canônica)`` do experimento (aresta ``APLICOU``)."""
        for edge in self._out_edges(exp.id, "APLICOU"):
            cfg = edge.properties.get("config")
            cfg = cfg if isinstance(cfg, dict) else {}
            digest = hash_params(cfg) if cfg else (edge.properties.get("hash_params") or _NO_CONFIG)
            return cfg, str(digest), self.canonical_approach(edge.dst_id)
        return {}, str(exp.properties.get("hash_params") or _NO_CONFIG), None

    def _real_session(self, exp: Node, projeto: str) -> bool:
        """Projeto existente no grafo e experimento ligado a uma ``Sessao`` dele (dado do grafo, não do agente)."""
        if not projeto:
            return False
        if projeto not in self._project_cache:
            self._project_cache[projeto] = bool(self._store.find_nodes("Projeto", {"projeto_id": projeto}, limit=1))
        if not self._project_cache[projeto]:
            return False
        sessoes = self._out(exp.id, "EXECUTADO_EM")
        return any(n.label == "Sessao" and n.properties.get("projeto_id") == projeto for n in sessoes)

    def _attempt_from(self, exp: Node, metric: Node) -> CollectedAttempt | None:
        props = exp.properties
        cfg, config_hash, abordagem = self._config_of(exp)
        dataset_ids = tuple(str(d) for d in (props.get("dataset_ids") or []))
        base = {
            "timestamp": str(props.get("criado_em") or ""),
            "node_id": str(props.get("no_execucao") or ""),
            "session_id": str(props.get("sessao_id") or ""),
            "seed": props.get("seed") if isinstance(props.get("seed"), int) else None,
            "dataset_ids": dataset_ids,
            "config_hash": config_hash,
        }
        projeto = str(props.get("projeto_id") or "")
        sessao_real = self._real_session(exp, projeto)
        if props.get("status") == "falha":
            cause = props.get("causa_falha")
            cause = cause if cause in ("infraestrutura", "abordagem", "ambigua") else "ambigua"
            signature = props.get("assinatura_falha") or ("sem_assinatura" if cause == "abordagem" else None)
            attempt = Attempt(
                attempt_id=exp.id, outcome_kind="falha", failure_cause=cause, failure_signature=signature, **base
            )
            return CollectedAttempt(attempt, exp.id, None, abordagem, cfg, projeto, sessao_real, False)
        for result in self._out(exp.id, "PRODUZIU"):
            if result.label != "Resultado":
                continue
            if not any(m.id == metric.id for m in self._out(result.id, "MEDE")):
                continue
            value = result.properties.get("valor")
            if not _is_number(value):
                continue
            baseline = result.properties.get("baseline")
            attempt = Attempt(
                attempt_id=result.id,
                outcome_kind="resultado",
                value=float(value),
                baseline=float(baseline) if _is_number(baseline) else None,
                validation=result.properties.get("status_validacao", "nao_validado"),
                contract_complete=props.get("seed") is not None and props.get("hash_params") is not None,
                **base,
            )
            shared = (
                props.get("visibilidade") == "compartilhavel"
                and result.properties.get("visibilidade") == "compartilhavel"
            )
            return CollectedAttempt(attempt, exp.id, result.id, abordagem, cfg, projeto, sessao_real, shared)
        return None  # experimento sem resultado da métrica do critério: não é tentativa desta hipótese

    def collect_attempts(self, hipotese: Node, metric: Node) -> list[CollectedAttempt]:
        """Tentativas da hipótese: ``Experimento-TESTA->Hipotese`` + o ``Resultado`` da métrica do critério."""
        collected: list[CollectedAttempt] = []
        for exp in self._in(hipotese.id, "TESTA")[:_MAX_ATTEMPTS]:
            if exp.label != "Experimento":
                continue
            item = self._attempt_from(exp, metric)
            if item is not None:
                collected.append(item)
        return collected

    def _hypothesis_node(self, hipotese_id: str) -> Node:
        node = self._store.get_node(hipotese_id)
        if node is None or node.label != "Hipotese":
            raise KnowledgeServiceError(f"Hipótese '{hipotese_id}' não encontrada.")
        return node

    # --------------------------------------------------------------- hipóteses

    @_operation
    def verdict_for_hypothesis(
        self, hipotese_id: str, filtro: dict[str, Any] | None = None
    ) -> tuple[VerdictResult, list[CollectedAttempt], Node]:
        """Calcula (sem gravar) o veredito da hipótese, opcionalmente só sobre as tentativas do ``filtro``.

        Returns:
            ``(resultado, tentativas usadas, Metrica do critério)``.

        Raises:
            KnowledgeServiceError: Hipótese, problema ou métrica ausentes.
        """
        if filtro is None and hipotese_id in self._verdict_cache:
            return self._verdict_cache[hipotese_id]
        hipotese = self._hypothesis_node(hipotese_id)
        problema = self.problem_for(hipotese)
        if problema is None:
            raise KnowledgeServiceError(f"Hipótese '{hipotese_id}' sem Problema: veredito indisponível.")
        criterion, metric = self.criterion_for(problema)
        collected = [c for c in self.collect_attempts(hipotese, metric) if _matches_filter(c, filtro)]
        out = (compute_verdict([c.attempt for c in collected], criterion, self._params), collected, metric)
        if filtro is None:
            self._verdict_cache[hipotese_id] = out
        return out

    @_operation
    def recompute_hypothesis(self, hipotese_id: str) -> VerdictResult:
        """Recalcula e grava o veredito da hipótese e as arestas ``SUSTENTA``/``REFUTA``.

        Grava ``suporte``, ``certeza``, ``veredito`` e ``n_tentativas`` (só se mudaram) e, por evidência com
        ``Resultado``, ``Resultado-SUSTENTA|REFUTA->Hipotese`` com ``peso = w`` (atualiza o ``peso``; a
        evidência que deixa de contar, ou que muda de lado, recebe ``status="contestada"``).

        Raises:
            KnowledgeServiceError: Veredito indisponível (ver ``verdict_for_hypothesis``).
        """
        result, collected, _ = self.verdict_for_hypothesis(hipotese_id)
        hipotese = self._hypothesis_node(hipotese_id)
        values = {
            "suporte": round(result.suporte, 6),
            "certeza": round(result.certeza, 6),
            "veredito": round(result.veredito, 6),
            "n_tentativas": result.n_tentativas,
        }
        if any(hipotese.properties.get(k) != v for k, v in values.items()):
            self._store.update_node(hipotese_id, values, actor=self._actor)
        self._sync_evidence_edges(hipotese_id, result, collected)
        return result

    def _sync_evidence_edges(self, hipotese_id: str, result: VerdictResult, collected: list[CollectedAttempt]) -> None:
        by_attempt = {c.attempt.attempt_id: c for c in collected}
        existing: dict[tuple[str, str], Edge] = {}
        for rel in ("SUSTENTA", "REFUTA"):
            for edge in self._store.neighbors(hipotese_id, [rel], direction="in", depth=1).edges:
                if edge.dst_id == hipotese_id and edge.rel_type == rel:
                    existing[(edge.src_id, rel)] = edge
        wanted: dict[tuple[str, str], float] = {}
        for detail in result.detalhes:
            item = by_attempt.get(detail.attempt_id)
            if item is None or item.resultado_id is None or detail.w <= 0:
                continue
            rel = "SUSTENTA" if detail.classificacao == "positiva" else "REFUTA"
            wanted[(item.resultado_id, rel)] = round(detail.w, 6)
        for (resultado_id, rel), peso in wanted.items():
            edge = existing.get((resultado_id, rel))
            if edge is None:
                self._store.create_edge(
                    resultado_id, rel, hipotese_id,
                    {"peso": peso, "origem": "derivado", "evidencias": [resultado_id]}, actor=self._actor,
                )
                continue
            changes_needed = edge.properties.get("peso") != peso
            if changes_needed:
                self._store.update_edge(resultado_id, rel, hipotese_id, {"peso": peso}, actor=self._actor)
            if edge.properties.get("status") == "contestada":
                self._store.set_edge_status(resultado_id, rel, hipotese_id, "confirmada", actor=self._actor)
        for (resultado_id, rel), edge in existing.items():
            if (resultado_id, rel) not in wanted and edge.properties.get("status") != "contestada":
                self._store.set_edge_status(resultado_id, rel, hipotese_id, "contestada", actor=self._actor)

    # ------------------------------------------------------------- descobertas

    @_operation
    def verdict_for_scope(
        self, sobre: list[Node], filtro: dict[str, Any] | None = None
    ) -> tuple[VerdictResult, list[CollectedAttempt], Node, Node | None, Node | None] | None:
        """Veredito sobre o escopo de uma descoberta: uma ``Hipotese``, ou ``Abordagem`` + ``Problema``.

        Returns:
            ``(resultado, tentativas, Metrica, abordagem, problema)`` ou ``None`` se o escopo não permite
            calcular (ex.: só ``Abordagem``, sem ``Hipotese`` nem ``Problema``).

        Raises:
            KnowledgeServiceError: Escopo calculável, mas sem critério/métrica.
        """
        hipoteses = [n for n in sobre if n.label == "Hipotese"]
        abordagem = next((n for n in sobre if n.label == "Abordagem"), None)
        problema = next((n for n in sobre if n.label == "Problema"), None)
        if hipoteses:
            collected: list[CollectedAttempt] = []
            metric: Node | None = None
            for hip in hipoteses:
                prob = self.problem_for(hip)
                if prob is None:
                    raise KnowledgeServiceError(f"Hipótese '{hip.id}' sem Problema: veredito indisponível.")
                criterion, metric = self.criterion_for(prob)
                problema = problema or prob
                collected.extend(self.collect_attempts(hip, metric))
            assert metric is not None
            collected = [c for c in collected if _matches_filter(c, filtro)]
            verdict = compute_verdict([c.attempt for c in collected], criterion, self._params)
            return verdict, collected, metric, abordagem, problema
        if abordagem is not None and problema is not None:
            criterion, metric = self.criterion_for(problema)
            canonical = self.canonical_approach(abordagem.id)
            family = self.merged_approaches(canonical)
            collected = []
            seen: set[str] = set()
            for member in family:
                for exp in self._in(member, "APLICOU"):
                    if exp.label != "Experimento" or exp.id in seen:
                        continue
                    seen.add(exp.id)
                    if not self._experiment_targets(exp, problema):
                        continue
                    item = self._attempt_from(exp, metric)
                    if item is not None and _matches_filter(item, filtro):
                        collected.append(item)
            verdict = compute_verdict([c.attempt for c in collected], criterion, self._params)
            return verdict, collected, metric, abordagem, problema
        return None

    @_operation
    def evidence_in_scope(self, evidence: Node, sobre: list[Node]) -> bool:
        """A evidência (``Resultado``, ``Experimento`` ou ``Decisao``) está ligada ao escopo (``sobre``) da descoberta.

        ``Resultado``/``Experimento``: o experimento testa uma das hipóteses do escopo, aplica a abordagem do
        escopo (ou de uma fundida nela) ou testa hipótese sobre o ``Problema`` do escopo. ``Decisao``: ``ESCOLHEU`` ou
        ``DESCARTOU`` algum nó do escopo.
        """
        scope_ids = {n.id for n in sobre}
        if evidence.label == "Decisao":
            for rel in ("ESCOLHEU", "DESCARTOU"):
                sub = self._store.neighbors(evidence.id, [rel], direction="out", depth=1)
                if any(e.src_id == evidence.id and e.dst_id in scope_ids for e in sub.edges):
                    return True
            return False
        exp = evidence
        if evidence.label == "Resultado":
            owners = [n for n in self._in(evidence.id, "PRODUZIU") if n.label == "Experimento"]
            if not owners:
                return False
            exp = owners[0]
        hip_ids = {h.id for h in self._out(exp.id, "TESTA") if h.label == "Hipotese"}
        if hip_ids & scope_ids:
            return True
        family: set[str] = set()
        for node in sobre:
            if node.label == "Abordagem":
                family |= self.merged_approaches(self.canonical_approach(node.id))
        if family and any(a.id in family for a in self._out(exp.id, "APLICOU")):
            return True
        for node in sobre:
            if node.label == "Problema" and self._experiment_targets(exp, node):
                return True
        return False

    def _experiment_targets(self, exp: Node, problema: Node) -> bool:
        """O experimento testa uma hipótese sobre este ``Problema`` (``SOBRE`` ou o confirmado do projeto)."""
        for hip in self._out(exp.id, "TESTA"):
            prob = self.problem_for(hip)
            if prob is not None and prob.id == problema.id:
                return True
        return False

    @_operation
    def recompute_discovery(self, descoberta_id: str) -> VerdictResult:
        """Recalcula ``veredito``, ``confianca`` e ``n_evidencias`` da descoberta e mantém os atalhos.

        Só descobertas ``funciona``/``nao_funciona``/``condicional`` têm veredito; respeita ``filtro_condicoes``.

        Raises:
            KnowledgeServiceError: Descoberta inexistente, de outro tipo ou sem escopo calculável.
        """
        node = self._store.get_node(descoberta_id)
        if node is None or node.label != "Descoberta":
            raise KnowledgeServiceError(f"Descoberta '{descoberta_id}' não encontrada.")
        if node.properties.get("tipo") not in DISCOVERY_VERDICT_TYPES:
            raise KnowledgeServiceError("Só descobertas funciona/nao_funciona/condicional têm veredito calculado.")
        sobre = [n for n in self._out(descoberta_id, "SOBRE")]
        filtro = node.properties.get("filtro_condicoes")
        scope = self.verdict_for_scope(sobre, filtro if isinstance(filtro, dict) else None)
        if scope is None:
            raise KnowledgeServiceError(f"Descoberta '{descoberta_id}' sem Hipótese ou Abordagem+Problema em SOBRE.")
        result, collected, metric, abordagem, problema = scope
        # n_evidencias conta as evidências (BASEADA_EM) ligadas à descoberta; o recálculo nunca a diminui.
        linked = len(self._out(descoberta_id, "BASEADA_EM"))
        values = {
            "veredito": round(result.veredito, 6),
            "confianca": round(result.confianca, 6),
            "n_evidencias": max(int(node.properties.get("n_evidencias") or 0), linked),
        }
        if any(node.properties.get(k) != v for k, v in values.items()):
            self._store.update_node(descoberta_id, values, actor=self._actor)
        if abordagem is not None and problema is not None:
            self._sync_shortcut(node, result, collected, metric, abordagem, problema)
        return result

    def _sync_shortcut(
        self,
        descoberta: Node,
        result: VerdictResult,
        collected: list[CollectedAttempt],
        metric: Node,
        abordagem: Node,
        problema: Node,
    ) -> None:
        """Mantém ``FUNCIONOU_PARA``/``FALHOU_PARA`` da descoberta (ou os contesta se o veredito caiu)."""
        tipo = descoberta.properties.get("tipo")
        if tipo not in ("funciona", "nao_funciona"):
            return
        rel = "FUNCIONOU_PARA" if tipo == "funciona" else "FALHOU_PARA"
        other = "FALHOU_PARA" if tipo == "funciona" else "FUNCIONOU_PARA"
        floor = config.KNOWLEDGE_SHORTCUT_MIN_VERDICT
        holds = (result.veredito >= floor) if tipo == "funciona" else (result.veredito <= -floor)
        edges = [e for e in self._out_edges(abordagem.id, rel) if e.dst_id == problema.id]
        mine = [e for e in edges if e.properties.get("descoberta_id") == descoberta.id]
        foreign = [e for e in edges if e.properties.get("descoberta_id") not in (None, descoberta.id)]
        if not holds:
            for edge in mine:
                if edge.properties.get("status") != "contestada":
                    self._store.set_edge_status(abordagem.id, rel, problema.id, "contestada", actor=self._actor)
            return
        if foreign and not mine:
            logger.warning(
                "Atalho já mantido por outra descoberta; não duplicado",
                extra={"extra": {"rel": rel, "abordagem_id": abordagem.id, "problema_id": problema.id}},
            )
            return
        positives = [c for c in collected if c.resultado_id is not None]
        evidence_ids = [c.resultado_id for c in positives][:50]
        if tipo == "funciona":
            best = self._best_attempt(positives, metric)
            if best is None:
                return
            props: dict[str, Any] = {
                "metrica": str(metric.properties.get("nome")),
                "melhor_valor": best.attempt.value,
                "config": best.config,
                "n_exp": len(collected),
                "descoberta_id": descoberta.id,
            }
        else:
            props = {
                "motivo": (
                    f"veredito {result.veredito:+.2f} ({result.leitura}) sobre {result.n_tentativas} tentativa(s)"
                ),
                "n_exp": len(collected),
                "descoberta_id": descoberta.id,
            }
        if mine:
            self._store.update_edge(abordagem.id, rel, problema.id, props, actor=self._actor)
            if mine[0].properties.get("status") == "contestada":
                self._store.set_edge_status(abordagem.id, rel, problema.id, "confirmada", actor=self._actor)
        else:
            self._store.create_edge(
                abordagem.id, rel, problema.id,
                {**props, "origem": "derivado", "evidencias": evidence_ids}, actor=self._actor,
            )
        # O atalho oposto, se existir para esta descoberta, deixa de valer.
        for edge in self._out_edges(abordagem.id, other):
            if edge.dst_id == problema.id and edge.properties.get("descoberta_id") == descoberta.id:
                if edge.properties.get("status") != "contestada":
                    self._store.set_edge_status(abordagem.id, other, problema.id, "contestada", actor=self._actor)

    @staticmethod
    def _best_attempt(items: list[CollectedAttempt], metric: Node) -> CollectedAttempt | None:
        validated = [c for c in items if c.attempt.value is not None and c.attempt.validation == "validado"]
        pool = validated or [c for c in items if c.attempt.value is not None]
        if not pool:
            return None
        pick = max if metric.properties.get("sentido") == "maior_melhor" else min
        return pick(pool, key=lambda c: c.attempt.value)  # type: ignore[arg-type,return-value]

    @_operation
    def recompute_approach(self, abordagem_id: str) -> int:
        """Recalcula as descobertas ligadas à abordagem canônica e às fundidas nela (após uma fusão).

        Returns:
            Quantas descobertas foram recalculadas.
        """
        recomputed = 0
        for member in self.merged_approaches(self.canonical_approach(abordagem_id)):
            for disc in self._in(member, "SOBRE"):
                if disc.label != "Descoberta" or disc.properties.get("tipo") not in DISCOVERY_VERDICT_TYPES:
                    continue
                try:
                    self.recompute_discovery(disc.id)
                    recomputed += 1
                except GraphStoreError as exc:
                    logger.info("Descoberta não recalculada", extra={"extra": {"motivo": type(exc).__name__}})
        return recomputed

    # ---------------------------------------------------------------- promoção

    @_operation
    def promotion_candidates(
        self, projeto_id: str, *, abordagem_ids: set[str] | None = None
    ) -> list[PromotionCandidate]:
        """Configurações elegíveis: mesma ``config`` (hash) numa ``Abordagem``, ≥ N positivos validados em ≥ M projetos.

        Positivo = tentativa classificada ``positiva`` pelo veredito da sua hipótese **e** com ``Resultado``
        ``validado``. Abordagens fundidas contam na canônica. Idempotência: configurações já promovidas (uma
        ``Abordagem(tipo="configuracao")`` com o mesmo hash ligada por ``VARIANTE_DE``) não voltam a ser candidatas.

        Escopo e privacidade (revisão do PR #106): a promoção pertence ao ``projeto_id`` da sessão e só considera
        abordagens base **desse** projeto. Contam apenas tentativas de projetos **reais** (``Projeto`` no grafo e
        experimento ligado por ``EXECUTADO_EM`` a uma ``Sessao`` do próprio projeto); tentativas de **outro** projeto só
        contam se o experimento e o resultado forem ``compartilhavel``. Nada de outro projeto entra na configuração,
        no nome ou nas evidências além do que for compartilhável.

        Args:
            projeto_id: Projeto da sessão (onde a promoção é gravada).
            abordagem_ids: Se informado, só estas abordagens base (canônicas).
        """
        groups: dict[tuple[str, str], list[CollectedAttempt]] = {}
        seen_exp: set[str] = set()
        for hip in self._hypotheses_to_scan(projeto_id, abordagem_ids):
            try:
                result, collected, _ = self.verdict_for_hypothesis(hip.id)
            except KnowledgeServiceError:
                continue
            positive_ids = {d.attempt_id for d in result.detalhes if d.classificacao == "positiva"}
            for item in collected:
                if (
                    item.attempt.attempt_id not in positive_ids
                    or item.attempt.validation != "validado"
                    or item.abordagem_id is None
                    or not item.config
                    or item.experimento_id in seen_exp
                    or not item.sessao_real
                    or (item.projeto_id != projeto_id and not item.compartilhavel)
                ):
                    continue
                seen_exp.add(item.experimento_id)
                groups.setdefault((item.abordagem_id, item.attempt.config_hash), []).append(item)
        candidates: list[PromotionCandidate] = []
        for (abordagem_id, digest), items in groups.items():
            if abordagem_ids is not None and abordagem_id not in abordagem_ids:
                continue
            base = self._store.get_node(abordagem_id)
            if (
                base is None
                or base.properties.get("tipo") == "configuracao"
                or base.properties.get("projeto_id") != projeto_id
            ):
                continue
            own = [i for i in items if i.projeto_id == projeto_id]
            if not own:
                continue
            projetos = tuple(sorted({i.projeto_id for i in items if i.projeto_id}))
            if len(items) < config.PROMOTION_MIN_POSITIVES or len(projetos) < config.PROMOTION_MIN_PROJECTS:
                continue
            if self._already_promoted(abordagem_id, digest):
                continue
            candidates.append(
                PromotionCandidate(
                    abordagem_id=abordagem_id,
                    config_hash=digest,
                    config=own[0].config,
                    positivos=len(items),
                    projetos=projetos,
                    resultado_ids=tuple(i.resultado_id for i in items if i.resultado_id),
                )
            )
        return candidates

    def _hypotheses_to_scan(self, projeto_id: str | None, abordagem_ids: set[str] | None) -> list[Node]:
        """Hipóteses cujas tentativas podem formar candidatas (só as das abordagens pedidas, se informadas)."""
        found: dict[str, Node] = {}
        if abordagem_ids is not None:
            for canonical in abordagem_ids:
                for member in self.merged_approaches(canonical):
                    for exp in self._in(member, "APLICOU"):
                        for hip in self._out(exp.id, "TESTA"):
                            if hip.label == "Hipotese":
                                found[hip.id] = hip
            return list(found.values())[:_MAX_ATTEMPTS]
        for projeto in self._projects(projeto_id):
            for hip in self._store.project_subgraph(projeto, labels=["Hipotese"]).nodes:
                found[hip.id] = hip
        return list(found.values())[:_MAX_ATTEMPTS]

    def _projects(self, projeto_id: str | None) -> list[str]:
        """Projetos a examinar: o informado mais os demais (a promoção é entre projetos)."""
        ids: list[str] = []
        after: str | None = None
        while len(ids) < _MAX_PROJECTS_SCANNED:
            page = self._store.list_nodes("Projeto", after_id=after, limit=_PAGE)
            if not page:
                break
            ids.extend(str(n.properties["projeto_id"]) for n in page if n.properties.get("projeto_id"))
            after = page[-1].id
        if projeto_id and projeto_id not in ids:
            ids.append(projeto_id)
        return ids[:_MAX_PROJECTS_SCANNED]

    def _already_promoted(self, abordagem_id: str, digest: str) -> bool:
        for variant in self._in(abordagem_id, "VARIANTE_DE"):
            cfg = variant.properties.get("config_normalizada")
            if (
                variant.properties.get("tipo") == "configuracao"
                and isinstance(cfg, dict)
                and cfg.get("hash") == digest
            ):
                return True
        return False

    @staticmethod
    def _config_label(cfg: dict[str, Any]) -> str:
        scalars = [(k, v) for k, v in sorted(cfg.items()) if isinstance(v, (str, int, float, bool))]
        return ", ".join(f"{k}={v}" for k, v in scalars[:_MAX_CONFIG_KEYS_IN_NAME])

    @_operation
    def promote_configuration(self, candidate: PromotionCandidate, projeto_id: str) -> str:
        """Cria ``Abordagem(tipo="configuracao")`` + ``VARIANTE_DE`` a base; idempotente por (base, hash).

        O nome é ``"<base> [<até 3 pares chave=valor escalares, em ordem alfabética>]"``. As evidências ficam na
        aresta ``VARIANTE_DE`` (``evidencias``) e na descrição.

        A nova abordagem é gravada **no projeto da sessão** (``projeto_id``), que deve ser o da abordagem base.

        Returns:
            O ``id`` da nova abordagem (ou da já existente, se a configuração já foi promovida).

        Raises:
            KnowledgeServiceError: Abordagem base inexistente ou de outro projeto.
        """
        base = self._store.get_node(candidate.abordagem_id)
        if base is None or base.label != "Abordagem":
            raise KnowledgeServiceError(f"Abordagem base '{candidate.abordagem_id}' não encontrada.")
        if base.properties.get("projeto_id") != projeto_id:
            raise KnowledgeServiceError("A promoção só grava no projeto da sessão e sobre abordagem dele.")
        for variant in self._in(base.id, "VARIANTE_DE"):
            cfg = variant.properties.get("config_normalizada")
            if (
                variant.properties.get("tipo") == "configuracao"
                and isinstance(cfg, dict)
                and cfg.get("hash") == candidate.config_hash
            ):
                return variant.id
        label = self._config_label(candidate.config)
        nome = f"{base.properties.get('nome', 'abordagem')} [{label}]"[:_MAX_NAME_CHARS]
        descricao = (
            f"Configuração promovida automaticamente: {candidate.positivos} resultado(s) positivo(s) validado(s) "
            f"em {len(candidate.projetos)} projeto(s) (critério: ≥ {config.PROMOTION_MIN_POSITIVES} em "
            f"≥ {config.PROMOTION_MIN_PROJECTS}). Evidências na aresta VARIANTE_DE."
        )
        new_id = self._store.create_node(
            "Abordagem",
            {
                "nome": nome,
                "tipo": "configuracao",
                "descricao": descricao,
                "config_normalizada": {"hash": candidate.config_hash, "config": candidate.config},
                "projeto_id": projeto_id,
                "sessao_id": base.properties.get("sessao_id", "knowledge-service"),
            },
            actor=self._actor,
        )
        self._store.create_edge(
            new_id, "VARIANTE_DE", base.id,
            {"origem": "derivado", "evidencias": list(candidate.resultado_ids)[:100]}, actor=self._actor,
        )
        return new_id

    # ------------------------------------------------------- pós-subtarefa (loop)

    @_operation
    def after_subtask(self, projeto_id: str, subtarefa_id: str) -> RecomputeReport:
        """Recálculo determinístico após uma subtarefa ingerida (task 2.5).

        Recalcula as hipóteses testadas pelo experimento, as descobertas ligadas a elas ou à abordagem aplicada
        e aplica as promoções de configuração da abordagem. Falhas de cálculo viram contagem em ``ignoradas``
        (a sessão nunca para por isso).
        """
        report = RecomputeReport()
        experiments = self._store.find_nodes(
            "Experimento", {"projeto_id": projeto_id, "subtarefa_id": subtarefa_id}, limit=1
        )
        if not experiments:
            return report
        exp = experiments[0]
        hipoteses = [n for n in self._out(exp.id, "TESTA") if n.label == "Hipotese"]
        _, _, abordagem_id = self._config_of(exp)
        discoveries: dict[str, Node] = {}
        for hip in hipoteses:
            try:
                self.recompute_hypothesis(hip.id)
                report.hipoteses += 1
            except GraphStoreError as exc:
                report.ignoradas += 1
                logger.info("Veredito da hipótese indisponível", extra={"extra": {"motivo": type(exc).__name__}})
            for disc in self._in(hip.id, "SOBRE"):
                if disc.label == "Descoberta":
                    discoveries[disc.id] = disc
        if abordagem_id is not None:
            for member in self.merged_approaches(abordagem_id):
                for disc in self._in(member, "SOBRE"):
                    if disc.label == "Descoberta":
                        discoveries[disc.id] = disc
        for disc in discoveries.values():
            if disc.properties.get("tipo") not in DISCOVERY_VERDICT_TYPES:
                continue
            try:
                self.recompute_discovery(disc.id)
                report.descobertas += 1
            except GraphStoreError:
                report.ignoradas += 1
        if abordagem_id is not None:
            try:
                for candidate in self.promotion_candidates(projeto_id, abordagem_ids={abordagem_id}):
                    report.promovidas.append(self.promote_configuration(candidate, projeto_id))
            except GraphStoreError as exc:
                report.ignoradas += 1
                logger.warning("Promoção de configuração falhou", extra={"extra": {"motivo": type(exc).__name__}})
        return report
