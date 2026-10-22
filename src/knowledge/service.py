"""``KnowledgeService``: cálculos determinísticos do conhecimento (v17-curator-agent, design §2).

Tudo o que pode ser calculado é calculado **sem LLM**; o Curator só interpreta. Este serviço:

- coleta as tentativas de uma hipótese no grafo e conta as que atingem ou não o alvo (``src.knowledge.result_records``,
  única fonte do cálculo), gravando ``n_tentativas``, ``n_atingiu_alvo`` e ``n_abaixo_alvo`` na ``Hipotese`` e as
  arestas ``Resultado-SUSTENTA|REFUTA->Hipotese``;
- mantém o ``RegistroResultado`` de cada (problema, abordagem, configuração) e os atalhos derivados
  ``Abordagem-FUNCIONOU_PARA|FALHOU_PARA->Problema`` (ADR 026);
- detecta e aplica a promoção de uma configuração a ``Abordagem(tipo="configuracao")``.

Toda escrita passa pela porta única (``GraphStore``) com ``Actor(kind="orquestrador")``. Tudo o que vem do
grafo (inclusive texto escrito por agentes) é dado: nada aqui vira consulta, só propriedades tipadas.
"""

from __future__ import annotations

import functools
import hashlib
import math
from dataclasses import dataclass, field
from typing import Any

from src import config
from src.knowledge.errors import GraphStoreError
from src.knowledge.graph_store import Edge, GraphStore, Node
from src.knowledge.ingestion import hash_params
from src.knowledge.projects import get_active_problem
from src.knowledge.provenance import Actor
from src.knowledge.result_records import (
    QUALIFICADORES_VALIDOS,
    Attempt,
    Criterion,
    RecordFacts,
    classify_attempt,
    compute_record,
    holds_fails,
    holds_works,
    improvement,
    is_valid,
)
from src.logger import get_logger

logger = get_logger(__name__)

ACTOR_SERVICE = Actor(kind="orquestrador")
_MAX_ATTEMPTS = 2000
_MAX_RECORD_REFS = 100  # experimentos citados por registro
_MAX_RECORD_RESULTS = 5  # resultados ligados (BASEADA_EM) por registro: os melhores
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
    """O registro ou a contagem não pôde ser calculado (critério ou tentativas ausentes); mensagem acionável."""


@dataclass(frozen=True)
class CollectedAttempt:
    """Uma tentativa lida do grafo, com os nós de onde veio.

    Attributes:
        attempt: A ``Attempt`` do módulo de registros.
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
    registros: int = 0
    promovidas: list[str] = field(default_factory=list)
    ignoradas: int = 0


def _rank(facts: RecordFacts, metric: Node) -> float:
    """Chave de ordenação do melhor registro (maior é melhor), respeitando o sentido da métrica."""
    value = facts.melhor_valor if facts.melhor_valor is not None else 0.0
    return value if metric.properties.get("sentido") == "maior_melhor" else -value


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
    """Mantém registros de resultado e arestas derivadas e promove configurações (sem LLM)."""

    def __init__(self, store: GraphStore, *, actor: Actor = ACTOR_SERVICE) -> None:
        """Inicializa o serviço.

        Args:
            store: Porta única do grafo (de produção, o store indexado).
            actor: Autor das escritas (orquestrador).
        """
        self._store = store
        self._actor = actor
        # Memo de leituras estruturais, válido dentro de uma operação pública (limpo a cada entrada): evita o N+1.
        self._nbcache: dict[tuple[str, str, str], Any] = {}
        self._project_cache: dict[str, bool] = {}
        self._depth = 0

    # ------------------------------------------------------------------ leitura

    def _begin(self) -> None:
        """Início de uma operação pública: descarta os memos (o grafo pode ter mudado desde a última)."""
        self._nbcache.clear()
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

    def _in_active(self, node_id: str, rel: str) -> list[Node]:
        """Nós com aresta ``rel`` ativa até ``node_id`` (arestas ``contestada``, p.ex. fusão revertida, não contam)."""
        sub = self._sub(node_id, rel, "in")
        by_id = {n.id: n for n in sub.nodes}
        return [
            by_id[e.src_id]
            for e in sub.edges
            if e.dst_id == node_id and e.rel_type == rel and e.src_id in by_id
            and e.properties.get("status") != "contestada"
        ]

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
                for other in self._in_active(current, "FUNDIDA_EM"):
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
            raise KnowledgeServiceError(f"Problema '{problema.id}' sem criterio_sucesso: critério indisponível.")
        metric: Node | None = None
        if criterio.get("metrica_id"):
            metric = self._store.get_node(str(criterio["metrica_id"]))
        if metric is None and criterio.get("metrica"):
            found = self._store.find_nodes("Metrica", {"nome": str(criterio["metrica"])}, limit=1)
            metric = found[0] if found else None
        if metric is None or metric.properties.get("sentido") not in ("maior_melhor", "menor_melhor"):
            raise KnowledgeServiceError(f"Problema '{problema.id}' sem métrica canônica: critério indisponível.")
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

    def _results_of(self, exp: Node, metric: Node) -> list[Node]:
        """``Resultado``s do experimento que medem a métrica do critério, só de teste ou validação cruzada."""
        found: list[Node] = []
        for result in self._out(exp.id, "PRODUZIU"):
            if result.label != "Resultado" or not _is_number(result.properties.get("valor")):
                continue
            if not any(m.id == metric.id for m in self._out(result.id, "MEDE")):
                continue
            qualifier = result.properties.get("qualificador")
            if qualifier is not None and qualifier not in QUALIFICADORES_VALIDOS:
                continue
            found.append(result)
        return found

    def _attempt_from(self, exp: Node, metric: Node) -> CollectedAttempt | None:
        """Tentativa do experimento: válida quando mede a métrica do critério, qualquer que seja o ``status``.

        Um experimento em ``falha`` com ``criterio_nao_atendido`` ou ``divergente_documentado`` que tem valor medido é
        uma tentativa válida (ADR 026 §3). Sem valor, só a ``falha`` é tentativa (``falha`` do registro de falhas).
        """
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
        results = self._results_of(exp, metric)
        if results:
            pick = max if metric.properties.get("sentido") == "maior_melhor" else min
            verified = [r for r in results if r.properties.get("status_validacao") != "nao_validado"]
            result = pick(verified or results, key=lambda r: float(r.properties["valor"]))
            baseline = result.properties.get("baseline")
            attempt = Attempt(
                attempt_id=result.id,
                outcome_kind="resultado",
                value=float(result.properties["valor"]),
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
        if props.get("status") == "falha":
            cause = props.get("causa_falha")
            cause = cause if cause in ("infraestrutura", "abordagem", "ambigua") else "ambigua"
            signature = props.get("assinatura_falha") or ("sem_assinatura" if cause == "abordagem" else None)
            attempt = Attempt(
                attempt_id=exp.id, outcome_kind="falha", failure_cause=cause, failure_signature=signature, **base
            )
            return CollectedAttempt(attempt, exp.id, None, abordagem, cfg, projeto, sessao_real, False)
        return None  # experimento sem resultado da métrica do critério: não é tentativa

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

    def _reference_value(self, problema: Node, metric: Node) -> float | None:
        """Melhor valor medido nos experimentos de referência (``REFERENCIA_DE``) do problema, ou ``None``."""
        values = [
            float(r.properties["valor"])
            for r in self._in(problema.id, "REFERENCIA_DE")
            if r.label == "Resultado"
            and _is_number(r.properties.get("valor"))
            and any(m.id == metric.id for m in self._out(r.id, "MEDE"))
        ]
        if not values:
            return None
        return max(values) if metric.properties.get("sentido") == "maior_melhor" else min(values)

    @_operation
    def hypothesis_facts(self, hipotese_id: str) -> tuple[RecordFacts, list[CollectedAttempt], Node, Criterion]:
        """Conta (sem gravar) as tentativas da hipótese que atingem ou não o alvo do critério.

        Returns:
            ``(fatos, tentativas, Metrica do critério, critério)``.

        Raises:
            KnowledgeServiceError: Hipótese, problema ou métrica ausentes.
        """
        hipotese = self._hypothesis_node(hipotese_id)
        problema = self.problem_for(hipotese)
        if problema is None:
            raise KnowledgeServiceError(f"Hipótese '{hipotese_id}' sem Problema: critério indisponível.")
        criterion, metric = self.criterion_for(problema)
        collected = self.collect_attempts(hipotese, metric)
        facts = compute_record(
            [c.attempt for c in collected], criterion, reference_value=self._reference_value(problema, metric)
        )
        return facts, collected, metric, criterion

    @_operation
    def recompute_hypothesis(self, hipotese_id: str) -> RecordFacts:
        """Recalcula e grava as contagens da hipótese e as arestas ``SUSTENTA``/``REFUTA``.

        Grava ``n_tentativas`` (todas as tentativas, inclusive falhas e resultados não verificados),
        ``n_atingiu_alvo`` e ``n_abaixo_alvo`` (só se mudaram) e, por tentativa com
        ``Resultado``, ``Resultado-SUSTENTA|REFUTA->Hipotese`` (a que deixa de contar, ou muda de lado, fica
        ``contestada``).

        Raises:
            KnowledgeServiceError: Critério indisponível (ver ``hypothesis_facts``).
        """
        facts, collected, metric, criterion = self.hypothesis_facts(hipotese_id)
        hipotese = self._hypothesis_node(hipotese_id)
        values = {
            "n_tentativas": len(collected),
            "n_atingiu_alvo": facts.n_atingiu_alvo,
            "n_abaixo_alvo": facts.n_abaixo_alvo,
        }
        if any(hipotese.properties.get(k) != v for k, v in values.items()):
            self._store.update_node(hipotese_id, values, actor=self._actor)
        problema = self.problem_for(hipotese)
        reference = self._reference_value(problema, metric) if problema is not None else None
        self._sync_evidence_edges(hipotese_id, criterion, collected, reference)
        return facts

    def _sync_evidence_edges(
        self, hipotese_id: str, criterion: Criterion, collected: list[CollectedAttempt], reference: float | None
    ) -> None:
        existing: dict[tuple[str, str], Edge] = {}
        for rel in ("SUSTENTA", "REFUTA"):
            for edge in self._store.neighbors(hipotese_id, [rel], direction="in", depth=1).edges:
                if edge.dst_id == hipotese_id and edge.rel_type == rel:
                    existing[(edge.src_id, rel)] = edge
        wanted: set[tuple[str, str]] = set()
        for item in collected:
            if item.resultado_id is None:
                continue
            kind = classify_attempt(item.attempt, criterion, reference)
            if kind == "invalida":
                continue
            wanted.add((item.resultado_id, "SUSTENTA" if kind == "atingiu" else "REFUTA"))
        for resultado_id, rel in wanted:
            edge = existing.get((resultado_id, rel))
            if edge is None:
                self._store.create_edge(
                    resultado_id, rel, hipotese_id,
                    {"origem": "derivado", "evidencias": [resultado_id]}, actor=self._actor,
                )
            elif edge.properties.get("status") == "contestada":
                self._store.set_edge_status(resultado_id, rel, hipotese_id, "confirmada", actor=self._actor)
        for (resultado_id, rel), edge in existing.items():
            if (resultado_id, rel) not in wanted and edge.properties.get("status") != "contestada":
                self._store.set_edge_status(resultado_id, rel, hipotese_id, "contestada", actor=self._actor)

    # ------------------------------------------------------- registros de resultado

    @_operation
    def scope_facts(
        self, sobre: list[Node], filtro: dict[str, Any] | None = None
    ) -> tuple[RecordFacts, list[CollectedAttempt], Node, Node | None, Node | None] | None:
        """Fatos medidos sobre o escopo de uma descoberta: uma ``Hipotese``, ou ``Abordagem`` + ``Problema``.

        Returns:
            ``(fatos, tentativas, Metrica, abordagem, problema)`` ou ``None`` se o escopo não permite calcular (ex.:
            só ``Abordagem``, sem ``Hipotese`` nem ``Problema``).

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
                    raise KnowledgeServiceError(f"Hipótese '{hip.id}' sem Problema: critério indisponível.")
                criterion, metric = self.criterion_for(prob)
                problema = problema or prob
                collected.extend(self.collect_attempts(hip, metric))
            assert metric is not None
        elif abordagem is not None and problema is not None:
            criterion, metric = self.criterion_for(problema)
            collected = self._family_attempts(abordagem.id, problema, metric)
        else:
            return None
        collected = [c for c in collected if _matches_filter(c, filtro)]
        facts = compute_record(
            [c.attempt for c in collected], criterion,
            reference_value=self._reference_value(problema, metric) if problema is not None else None,
        )
        return facts, collected, metric, abordagem, problema

    def _family_attempts(self, abordagem_id: str, problema: Node, metric: Node) -> list[CollectedAttempt]:
        """Tentativas válidas da abordagem canônica (e das fundidas nela) que testam hipóteses sobre o problema."""
        collected: list[CollectedAttempt] = []
        seen: set[str] = set()
        for member in self.merged_approaches(self.canonical_approach(abordagem_id)):
            for exp in self._in(member, "APLICOU"):
                if exp.label != "Experimento" or exp.id in seen:
                    continue
                seen.add(exp.id)
                if not self._experiment_targets(exp, problema):
                    continue
                item = self._attempt_from(exp, metric)
                if item is not None and is_valid(item.attempt):
                    collected.append(item)
        return collected

    @_operation
    def records_in_scope(self, sobre: list[Node]) -> list[Node]:
        """``RegistroResultado``s do escopo: da abordagem (e fundidas) no problema, ou das hipóteses indicadas."""
        pairs: set[tuple[str, str]] = set()
        abordagem = next((n for n in sobre if n.label == "Abordagem"), None)
        problema = next((n for n in sobre if n.label == "Problema"), None)
        if abordagem is not None and problema is not None:
            pairs.add((self.canonical_approach(abordagem.id), problema.id))
        for hip in (n for n in sobre if n.label == "Hipotese"):
            prob = self.problem_for(hip)
            if prob is None:
                continue
            for exp in self._in(hip.id, "TESTA"):
                _, _, canonical = self._config_of(exp)
                if canonical is not None:
                    pairs.add((canonical, prob.id))
        found: dict[str, Node] = {}
        for canonical, problema_id in pairs:
            for member in self.merged_approaches(canonical):
                for record in self._in(member, "REGISTRA"):
                    if record.label == "RegistroResultado" and any(
                        p.id == problema_id for p in self._out(record.id, "SOBRE")
                    ):
                        found[record.id] = record
        return list(found.values())

    @_operation
    def recompute_records(self, abordagem_id: str, problema: Node) -> list[str]:
        """Recalcula os registros da abordagem canônica no problema (um por configuração) e os atalhos derivados.

        Returns:
            Os ids dos registros, na ordem da primeira tentativa de cada configuração.

        Raises:
            KnowledgeServiceError: Problema sem critério ou métrica canônica.
        """
        canonical = self.canonical_approach(abordagem_id)
        abordagem = self._store.get_node(canonical)
        if abordagem is None or abordagem.label != "Abordagem":
            raise KnowledgeServiceError(f"Abordagem '{abordagem_id}' não encontrada.")
        criterion, metric = self.criterion_for(problema)
        reference = self._reference_value(problema, metric)
        groups: dict[str, list[CollectedAttempt]] = {}
        for item in self._family_attempts(canonical, problema, metric):
            groups.setdefault(item.attempt.config_hash, []).append(item)
        ordered = sorted(groups.items(), key=lambda kv: min(c.attempt.timestamp for c in kv[1]))
        computed: list[tuple[str, RecordFacts, list[CollectedAttempt]]] = []
        earlier: float | None = None
        for digest, items in ordered:
            facts = compute_record(
                [c.attempt for c in items], criterion, parent_best=earlier, reference_value=reference
            )
            record_id = self._upsert_record(problema, abordagem, digest, items, facts, metric)
            computed.append((record_id, facts, items))
            if facts.melhor_valor is not None:
                better = facts.melhor_valor
                if earlier is None or improvement(better, earlier, criterion.sentido) > 0:
                    earlier = better
        self._sync_shortcuts(abordagem, problema, metric, computed)
        return [record_id for record_id, _, _ in computed]

    def _upsert_record(
        self, problema: Node, abordagem: Node, digest: str, items: list[CollectedAttempt], facts: RecordFacts,
        metric: Node,
    ) -> str:
        chave = hashlib.sha256(f"{problema.id}|{abordagem.id}|{digest}".encode()).hexdigest()[:32]
        valid = [c for c in items if is_valid(c.attempt)]
        shared = bool(valid) and all(c.compartilhavel for c in valid)
        condicoes = {
            "config_hash": digest,
            "config": valid[0].config if valid else {},
            "dataset_ids": sorted({d for c in valid for d in c.attempt.dataset_ids}),
            "no_execucao": sorted({c.attempt.node_id for c in valid if c.attempt.node_id}),
        }
        values: dict[str, Any] = {
            "metrica": str(metric.properties.get("nome")),
            "melhor_valor": None if facts.melhor_valor is None else round(facts.melhor_valor, 9),
            "delta_base": None if facts.delta_base is None else round(facts.delta_base, 9),
            "delta_pai": None if facts.delta_pai is None else round(facts.delta_pai, 9),
            "n_tentativas_validas": facts.n_tentativas_validas,
            "n_replicas_independentes": facts.n_replicas_independentes,
            "n_atingiu_alvo": facts.n_atingiu_alvo,
            "n_abaixo_alvo": facts.n_abaixo_alvo,
            "atingiu_alvo": facts.atingiu_alvo,
            "condicoes": condicoes,
            "experimentos": sorted({c.experimento_id for c in valid})[:_MAX_RECORD_REFS],
            "visibilidade": "compartilhavel" if shared else "privado",
        }
        values = {k: v for k, v in values.items() if v is not None}
        found = self._store.find_nodes("RegistroResultado", {"chave": chave}, limit=1)
        if found:
            record = found[0]
            changed = {k: v for k, v in values.items() if record.properties.get(k) != v}
            if changed:
                self._store.update_node(record.id, changed, actor=self._actor)
            record_id = record.id
        else:
            record_id = self._store.create_node(
                "RegistroResultado",
                {
                    **values,
                    "chave": chave,
                    "qualificacao": "pendente",
                    "projeto_id": str(problema.properties.get("projeto_id") or ""),
                    "sessao_id": "knowledge-service",
                },
                actor=self._actor,
            )
            self._store.create_edge(record_id, "REGISTRA", abordagem.id, {"origem": "derivado"}, actor=self._actor)
            self._store.create_edge(record_id, "SOBRE", problema.id, {"origem": "derivado"}, actor=self._actor)
        linked = {n.id for n in self._store.neighbors(record_id, ["BASEADA_EM"], direction="out", depth=1).nodes}
        for result_id in facts.resultado_ids[:_MAX_RECORD_RESULTS]:
            if result_id not in linked:
                self._store.create_edge(
                    record_id, "BASEADA_EM", result_id, {"origem": "derivado", "evidencias": [result_id]},
                    actor=self._actor,
                )
        return record_id

    def _sync_shortcuts(
        self, abordagem: Node, problema: Node, metric: Node,
        computed: list[tuple[str, RecordFacts, list[CollectedAttempt]]],
    ) -> None:
        """Mantém ``FUNCIONOU_PARA``/``FALHOU_PARA`` derivados dos registros (ou os contesta quando deixam de valer)."""
        works = [c for c in computed if holds_works(c[1], min_replicas=config.HYPOTHESIS_MIN_REPLICAS)]
        fails = (
            not any(f.n_atingiu_alvo for _, f, _ in computed)
            and any(holds_fails(f, min_refutations=config.HYPOTHESIS_MIN_REFUTATIONS) for _, f, _ in computed)
        )
        if works:
            record_id, facts, items = max(works, key=lambda c: _rank(c[1], metric))
            cfg = next((c.config for c in items if c.config), {})
            self._set_shortcut(
                abordagem, problema, "FUNCIONOU_PARA",
                {
                    "metrica": str(metric.properties.get("nome")),
                    "melhor_valor": facts.melhor_valor,
                    "config": cfg,
                    "n_exp": facts.n_tentativas_validas,
                    "registro_id": record_id,
                },
                [r for r in facts.resultado_ids][:50],
            )
        else:
            self._contest_shortcut(abordagem, problema, "FUNCIONOU_PARA")
        if fails and not works:
            record_id, facts, _ = max(computed, key=lambda c: c[1].n_abaixo_alvo)
            self._set_shortcut(
                abordagem, problema, "FALHOU_PARA",
                {
                    "motivo": (
                        f"{facts.n_abaixo_alvo} réplica(s) independente(s) abaixo do alvo "
                        f"({metric.properties.get('nome')}); nenhuma o atinge"
                    ),
                    "n_exp": facts.n_tentativas_validas,
                    "registro_id": record_id,
                },
                list(facts.resultado_ids)[:50],
            )
        else:
            self._contest_shortcut(abordagem, problema, "FALHOU_PARA")

    def _set_shortcut(
        self, abordagem: Node, problema: Node, rel: str, props: dict[str, Any], evidencias: list[str]
    ) -> None:
        edges = [e for e in self._out_edges(abordagem.id, rel) if e.dst_id == problema.id]
        if edges:
            self._store.update_edge(abordagem.id, rel, problema.id, props, actor=self._actor)
            if edges[0].properties.get("status") == "contestada":
                self._store.set_edge_status(abordagem.id, rel, problema.id, "confirmada", actor=self._actor)
        else:
            self._store.create_edge(
                abordagem.id, rel, problema.id, {**props, "origem": "derivado", "evidencias": evidencias},
                actor=self._actor,
            )

    def _contest_shortcut(self, abordagem: Node, problema: Node, rel: str) -> None:
        for edge in self._out_edges(abordagem.id, rel):
            if edge.dst_id == problema.id and edge.properties.get("status") != "contestada":
                self._store.set_edge_status(abordagem.id, rel, problema.id, "contestada", actor=self._actor)

    @_operation
    def recompute_approach(self, abordagem_id: str) -> int:
        """Recalcula os registros da abordagem canônica (e das fundidas) em todos os problemas em que foi aplicada.

        Returns:
            Quantos registros foram recalculados.
        """
        canonical = self.canonical_approach(abordagem_id)
        problems: dict[str, Node] = {}
        for member in self.merged_approaches(canonical):
            for exp in self._in(member, "APLICOU"):
                for hip in self._out(exp.id, "TESTA"):
                    prob = self.problem_for(hip) if hip.label == "Hipotese" else None
                    if prob is not None:
                        problems[prob.id] = prob
        total = 0
        for prob in problems.values():
            try:
                total += len(self.recompute_records(canonical, prob))
            except GraphStoreError as exc:
                logger.info("Registros não recalculados", extra={"extra": {"motivo": type(exc).__name__}})
        return total

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
        if evidence.label == "RegistroResultado":
            return self._record_in_scope(evidence, sobre, scope_ids)
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

    def _record_in_scope(self, record: Node, sobre: list[Node], scope_ids: set[str]) -> bool:
        """O ``RegistroResultado`` é do problema ou da abordagem do escopo, ou de experimento que o escopo cobre."""
        if any(n.id in scope_ids for n in self._out(record.id, "SOBRE")):
            return True
        family: set[str] = set()
        for node in sobre:
            if node.label == "Abordagem":
                family |= self.merged_approaches(self.canonical_approach(node.id))
        if any(n.id in family for n in self._out(record.id, "REGISTRA")):
            return True
        for exp_id in list(record.properties.get("experimentos") or [])[:20]:
            exp = self._store.get_node(str(exp_id))
            if exp is not None and exp.label == "Experimento" and self.evidence_in_scope(exp, sobre):
                return True
        return False

    def _experiment_targets(self, exp: Node, problema: Node) -> bool:
        """O experimento testa uma hipótese sobre este ``Problema`` (``SOBRE`` ou o confirmado do projeto)."""
        for hip in self._out(exp.id, "TESTA"):
            prob = self.problem_for(hip)
            if prob is not None and prob.id == problema.id:
                return True
        return False

    # ---------------------------------------------------------------- promoção

    @_operation
    def promotion_candidates(
        self, projeto_id: str, *, abordagem_ids: set[str] | None = None
    ) -> list[PromotionCandidate]:
        """Configurações elegíveis: mesma ``config`` (hash) numa ``Abordagem``, ≥ N positivos validados em ≥ M projetos.

        Positivo = tentativa que atinge o alvo do critério da sua hipótese **e** com ``Resultado``
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
                facts, collected, metric, criterion = self.hypothesis_facts(hip.id)
            except KnowledgeServiceError:
                continue
            problema = self.problem_for(hip)
            reference = self._reference_value(problema, metric) if problema is not None else None
            positive_ids = {
                c.attempt.attempt_id
                for c in collected
                if classify_attempt(c.attempt, criterion, reference) == "atingiu"
            }
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

        Recalcula as hipóteses testadas pelo experimento e os registros de resultado da abordagem aplicada nos
        problemas dessas hipóteses (com os atalhos derivados), e aplica as promoções de configuração da abordagem.
        Falhas de cálculo viram contagem em ``ignoradas`` (a sessão nunca para por isso).
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
        problems: dict[str, Node] = {}
        for hip in hipoteses:
            try:
                self.recompute_hypothesis(hip.id)
                report.hipoteses += 1
            except GraphStoreError as exc:
                report.ignoradas += 1
                logger.info("Contagem da hipótese indisponível", extra={"extra": {"motivo": type(exc).__name__}})
            problem = self.problem_for(hip)
            if problem is not None:
                problems[problem.id] = problem
        if abordagem_id is not None:
            for problem in problems.values():
                try:
                    report.registros += len(self.recompute_records(abordagem_id, problem))
                except GraphStoreError as exc:
                    report.ignoradas += 1
                    logger.info("Registro indisponível", extra={"extra": {"motivo": type(exc).__name__}})
        if abordagem_id is not None:
            try:
                for candidate in self.promotion_candidates(projeto_id, abordagem_ids={abordagem_id}):
                    report.promovidas.append(self.promote_configuration(candidate, projeto_id))
            except GraphStoreError as exc:
                report.ignoradas += 1
                logger.warning("Promoção de configuração falhou", extra={"extra": {"motivo": type(exc).__name__}})
        return report
