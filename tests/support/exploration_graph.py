"""Construtores de grafo em memória para a exploração rastreável (v18.7-graph-exploration-relations, design §5.1).

Montam, sobre ``HypothesisWorld`` e ``CuratorGraph`` (sem duplicá-los), os nós e arestas que a exploração da V18.7
grava: ``Problema`` por tipo de objetivo, ``Hipotese`` de qualquer origem, ``Experimento`` com ``papel``, ``Resultado`` e
a referência do problema. Cada escrita usa o ``Actor`` que o caminho real usaria, para exercitar a validação do grafo.
Nada aqui usa rede, LLM ou banco. As mudanças seguintes da V18.7 reutilizam e estendem este módulo.
"""

from __future__ import annotations

from typing import Any

from src.knowledge.exploration_reads import structured_key
from src.knowledge.graph_store import Node
from tests.support.hypothesis_world import AGENTE, ORQ, PESQUISADOR, HypothesisWorld

FIXADA_EM = "2026-10-20T12:00:00+00:00"
_TIPOS_OBJETIVO = ("limiar", "discriminacao", "cobertura")


def problema(world: HypothesisWorld, tipo: str | None = "limiar", **campos: Any) -> Node:
    """``Problema`` confirmado do mundo, com ``criterio_sucesso`` do ``tipo`` pedido.

    ``tipo=None`` deixa o critério antigo, sem ``tipo`` (todos os ``Problema`` anteriores à V18.7). Até
    ``v18.7-exploration-limits`` o schema não confere a estrutura por tipo: o construtor só grava o mapa.
    """
    if tipo is not None and tipo not in _TIPOS_OBJETIVO:
        raise ValueError(f"tipo de objetivo desconhecido: {tipo!r}")
    criterio = {k: v for k, v in dict(world.problem.properties["criterio_sucesso"]).items() if k != "tipo"}
    if tipo is not None:
        criterio["tipo"] = tipo
    if tipo in ("discriminacao", "cobertura"):
        criterio.pop("alvo", None)
        criterio.pop("delta_min", None)
    if tipo == "discriminacao":
        criterio.setdefault("hipoteses_concorrentes", [{"hipotese_id": "h-a", "predicao": "A"}, {"hipotese_id": "h-b", "predicao": "B"}])
    criterio.update(campos)
    world.store.update_node(world.problem.id, {"criterio_sucesso": criterio}, actor=PESQUISADOR)
    node = world.store.get_node(world.problem.id)
    assert node is not None
    return node


def referencia_fixada(
    valor: float | None = 0.62, origem: str = "referencia_medida", metrica_id: str = "met-1", **extra: Any
) -> dict[str, Any]:
    """Mapa ``referencia_fixada`` válido (``resultado_id`` só com ``referencia_medida``)."""
    mapa: dict[str, Any] = {"valor": valor, "origem_referencia": origem, "metrica_id": metrica_id, "fixada_em": FIXADA_EM}
    if origem == "referencia_medida":
        mapa["resultado_id"] = "res-1"
    mapa.update(extra)
    return mapa


def hipotese(
    world: HypothesisWorld,
    *,
    origem: str = "researcher",
    status: str = "proposta",
    abandonada_por: str | None = None,
    motivo_abandono: str | None = None,
    chave: str | None = None,
    referencia: dict[str, Any] | None = None,
    enunciado: str = "H",
    actor: Any = None,
) -> str:
    """``Hipotese`` do problema do mundo.

    Origem ``sistema`` preenche ``chave_estruturada`` (por ``structured_key``) e ``referencia_fixada`` válida; o ``Actor``
    padrão segue a origem (pesquisador, orquestrador para ``sistema``, agente nas demais). Com ``status="abandonada"``,
    a hipótese nasce ``proposta`` e é abandonada em seguida pelo ``Actor`` do caminho real (pesquisador para
    ``abandonada_por="pesquisador"``, orquestrador nos demais).
    """
    by = actor or {"pesquisador": PESQUISADOR, "sistema": ORQ}.get(origem, AGENTE)
    props = world.base(enunciado=enunciado, justificativa="J", status="proposta", origem=origem)
    if origem == "sistema":
        abordagem = world.graph.abordagem(nome=f"abordagem-{enunciado}")
        metrica = world.graph.metrica
        props["chave_estruturada"] = chave or structured_key(world.problem.id, abordagem, str(metrica))
        props["referencia_fixada"] = referencia or referencia_fixada(metrica_id=str(metrica))
    if by.kind == "agente":
        props.update(justificativa_criacao="teste", nos_consultados=[])
    hid = world.store.create_node("Hipotese", props, actor=by)
    world.store.create_edge(hid, "SOBRE", world.problem.id, {}, actor=ORQ)
    if status != "proposta":
        changes: dict[str, Any] = {"status": status}
        if abandonada_por is not None:
            changes["abandonada_por"] = abandonada_por
        if motivo_abandono is not None:
            changes["motivo_abandono"] = motivo_abandono
        closer = PESQUISADOR if abandonada_por == "pesquisador" else ORQ
        world.store.update_node(hid, changes, actor=closer)
    return hid


def experimento(
    world: HypothesisWorld,
    *,
    papel: str | None = None,
    testa: str | None = None,
    prepara: tuple[str, ...] = (),
    subtarefa: str = "sub-1",
) -> str:
    """``Experimento`` com ``papel`` opcional (ausente = nó antigo), ``TESTA`` e ``PREPARA`` (``origem="derivado"``)."""
    props = world.base(subtarefa_id=subtarefa, status="sucesso", caminho_artefatos="/x", no_execucao="A")
    if papel is not None:
        props["papel"] = papel
    eid = world.store.create_node("Experimento", props, actor=ORQ)
    if testa is not None:
        world.store.create_edge(eid, "TESTA", testa, {}, actor=ORQ)
    for alvo in prepara:
        world.store.create_edge(eid, "PREPARA", alvo, {"origem": "derivado"}, actor=ORQ)
    return eid


def resultado(
    world: HypothesisWorld, experimento_id: str, valor: float = 0.8, *, metrica: str | None = None, validado: bool = True
) -> str:
    """``Resultado`` da métrica do problema (``PRODUZIU`` e ``MEDE``)."""
    props = world.base(
        nome_original="r2", valor=valor, caminho_metrics="/m", baseline=0.7,
        status_validacao="validado" if validado else "nao_validado",
    )
    rid = world.store.create_node("Resultado", props, actor=ORQ)
    world.store.create_edge(experimento_id, "PRODUZIU", rid, {}, actor=ORQ)
    world.store.create_edge(rid, "MEDE", metrica or world.graph.metrica, {}, actor=ORQ)
    return rid


def referencia(world: HypothesisWorld, valor: float = 0.62, *, metrica: str | None = None) -> tuple[str, str]:
    """``Experimento`` ``papel = "referencia"`` e ``Resultado`` ligado ao ``Problema`` por ``REFERENCIA_DE``.

    Returns:
        ``(experimento_id, resultado_id)``.
    """
    eid = experimento(world, papel="referencia", subtarefa="sub-ref")
    rid = resultado(world, eid, valor, metrica=metrica)
    world.store.create_edge(rid, "REFERENCIA_DE", world.problem.id, {"origem": "afirmado"}, actor=ORQ)
    return eid, rid
