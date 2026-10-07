"""Testes do ``KnowledgeService`` (v17-curator-agent, spec ``curator``: veredito sem LLM e promoção).

Grafo em memória, sem rede, sem LLM. Cada teste cita o ``#### Scenario`` ou a tarefa de ``tasks.md`` que cobre.
"""

from __future__ import annotations

import pytest

from src.knowledge.graph_store import InMemoryGraphStore
from src.knowledge.service import KnowledgeService, KnowledgeServiceError
from src.knowledge.verdict import VerdictParams
from tests.support.curator_graph import ORQ, CuratorGraph

pytestmark = pytest.mark.unit


@pytest.fixture
def world():
    store = InMemoryGraphStore()
    graph = CuratorGraph(store).setup_project()
    service = KnowledgeService(store, VerdictParams())
    return store, graph, service


def _edges(store, rel, dst=None, src=None):
    return [
        e
        for e in store._edges  # noqa: SLF001 - inspeção direta do grafo em memória
        if e.rel_type == rel and (dst is None or e.dst_id == dst) and (src is None or e.src_id == src)
    ]


def _descoberta(store, graph, tipo, *, sobre, filtro=None, **extra):
    props = {
        **graph.base(),
        "tipo": tipo,
        "enunciado": "e",
        "n_evidencias": 1,
        "status": "ativa",
        "justificativa_criacao": "j",
        "nos_consultados": [],
        **extra,
    }
    if filtro is not None:
        props["filtro_condicoes"] = filtro
    did = store.create_node("Descoberta", props, actor=ORQ.__class__(kind="agente", role="curator"))
    for target in sobre:
        store.create_edge(did, "SOBRE", target, {}, actor=ORQ)
    return did


def test_recalculo_reproduz_os_testes_ouro_do_veredito(world):
    """Tarefa 6.5 — o recálculo a partir de nós reproduz o exemplo do ADR 015 §9.6 (pesos e veredito +0,17)."""
    store, graph, service = world
    hip, abordagem = graph.hipotese(), graph.abordagem()
    results = graph.adr_e1_e6(hip, abordagem)

    result = service.recompute_hypothesis(hip)

    pesos = {d.attempt_id: d.w for d in result.detalhes}
    assert pesos[results["E1"]] == pytest.approx(1.000, abs=0.005)
    assert pesos[results["E2"]] == pytest.approx(0.160, abs=0.005)
    assert pesos[results["E3"]] == pytest.approx(0.315, abs=0.005)
    assert pesos[results["E4"]] == pytest.approx(0.600, abs=0.005)
    assert pesos[results["E5"]] == pytest.approx(0.800, abs=0.005)
    assert pesos[results["E6"]] == pytest.approx(0.150, abs=0.005)
    assert result.veredito == pytest.approx(0.171, abs=0.005)
    assert result.leitura == "funciona_fraca"


def test_recalculo_apos_resultado_atualiza_hipotese_e_arestas_com_peso(world):
    """Scenario: Recálculo após resultado — Hipotese atualizada e SUSTENTA/REFUTA com peso igual ao w."""
    store, graph, service = world
    hip, abordagem = graph.hipotese(), graph.abordagem()
    results = graph.adr_e1_e6(hip, abordagem)

    result = service.recompute_hypothesis(hip)

    node = store.get_node(hip)
    assert node.properties["veredito"] == pytest.approx(result.veredito, abs=1e-5)
    assert node.properties["suporte"] == pytest.approx(result.suporte, abs=1e-5)
    assert node.properties["certeza"] == pytest.approx(result.certeza, abs=1e-5)
    assert node.properties["n_tentativas"] == 6
    sustenta = {e.src_id: e for e in _edges(store, "SUSTENTA", dst=hip)}
    refuta = {e.src_id: e for e in _edges(store, "REFUTA", dst=hip)}
    assert set(sustenta) == {results[k] for k in ("E1", "E2", "E3", "E4", "E6")}
    assert set(refuta) == {results["E5"]}
    pesos = {d.attempt_id: d.w for d in result.detalhes}
    for rid, edge in {**sustenta, **refuta}.items():
        assert edge.properties["peso"] == pytest.approx(pesos[rid], abs=1e-5)
        assert edge.properties["origem"] == "derivado"


def test_recalculo_atualiza_o_peso_sem_duplicar_arestas(world):
    """Scenario: Recálculo após resultado — um novo resultado muda o ``b`` e o ``peso`` é atualizado in place."""
    store, graph, service = world
    hip, abordagem = graph.hipotese(), graph.abordagem()
    _, r1 = graph.tentativa(hip, abordagem, valor=0.80, config={"modelo": "gb", "p": 1})
    service.recompute_hypothesis(hip)
    edge = _edges(store, "SUSTENTA", src=r1)[0]
    antes = edge.properties["peso"]
    assert antes == pytest.approx(1.0)  # uma só configuração: sem penalidade de busca (b = 1)

    graph.tentativa(hip, abordagem, valor=0.79, no="B", config={"modelo": "gb", "p": 2})  # 2ª config
    service.recompute_hypothesis(hip)

    assert len(_edges(store, "SUSTENTA", src=r1)) == 1
    assert _edges(store, "SUSTENTA", src=r1)[0].properties["peso"] < antes  # b < 1 com 2 configs sem réplica


def test_evidencia_que_deixa_de_contar_e_contestada(world):
    """Scenario: Recálculo após resultado — evidência que deixa de contar recebe status contestada."""
    store, graph, service = world
    hip, abordagem = graph.hipotese(), graph.abordagem()
    _, res = graph.tentativa(hip, abordagem, valor=0.80)
    service.recompute_hypothesis(hip)
    assert _edges(store, "SUSTENTA", src=res)[0].properties["status"] == "confirmada"

    # O resultado deixa de ser validado (por exemplo, o Validator reavaliou): não é mais evidência.
    store.update_node(res, {"status_validacao": "nao_validado"}, actor=ORQ)
    service.recompute_hypothesis(hip)

    assert _edges(store, "SUSTENTA", src=res)[0].properties["status"] == "contestada"


def test_atalho_funcionou_para_e_contestado_quando_o_veredito_cai(world):
    """Scenario: Atalho contestado — veredito 0,2 mantém FUNCIONOU_PARA; ao cair para 0,05 a aresta é contestada."""
    store, graph, service = world
    hip, abordagem = graph.hipotese(), graph.abordagem()
    # 5 sementes positivas na mesma sessão: veredito ~ +0,22 (tabela de referência do ADR 015 §9.7).
    for seed in range(1, 6):
        graph.tentativa(hip, abordagem, valor=0.80, seed=seed)
    descoberta = _descoberta(store, graph, "funciona", sobre=[abordagem, graph.problema, hip])
    result = service.recompute_discovery(descoberta)
    assert 0.1 <= result.veredito < 0.3
    atalho = _edges(store, "FUNCIONOU_PARA", src=abordagem, dst=graph.problema)
    assert len(atalho) == 1
    assert atalho[0].properties["descoberta_id"] == descoberta
    assert atalho[0].properties["melhor_valor"] == pytest.approx(0.80)
    assert atalho[0].properties["n_exp"] == 5
    assert atalho[0].properties["status"] == "confirmada"

    # Duas evidências negativas independentes (nós diferentes) levam o veredito para a faixa insuficiente.
    for i, no in enumerate(("B", "C")):
        graph.tentativa(hip, abordagem, valor=0.70, no=no, seed=10 + i, datasets=[f"d{i}"])
    result = service.recompute_discovery(descoberta)

    assert abs(result.veredito) < 0.1
    atalho = _edges(store, "FUNCIONOU_PARA", src=abordagem, dst=graph.problema)
    assert len(atalho) == 1
    assert atalho[0].properties["status"] == "contestada"


def test_descoberta_condicional_so_conta_as_tentativas_do_dataset(world):
    """Scenario: Descoberta condicional — filtro_condicoes dataset d1 dá +0,28 e dataset d2 dá -0,08 (ADR 015)."""
    store, graph, service = world
    hip, abordagem = graph.hipotese(), graph.abordagem()
    graph.adr_e1_e6(hip, abordagem)
    d1 = _descoberta(store, graph, "condicional", sobre=[hip], filtro={"dataset_ids": ["ds1"]}, condicoes="ds1")
    d2 = _descoberta(store, graph, "condicional", sobre=[hip], filtro={"dataset_ids": ["ds2"]}, condicoes="ds2")

    r1 = service.recompute_discovery(d1)
    r2 = service.recompute_discovery(d2)

    assert r1.veredito == pytest.approx(0.28, abs=0.005)
    assert r2.veredito == pytest.approx(-0.08, abs=0.005)
    assert store.get_node(d1).properties["veredito"] == pytest.approx(0.28, abs=0.005)
    assert store.get_node(d2).properties["confianca"] == pytest.approx(0.08, abs=0.005)


def _two_projects(store):
    """Dois projetos com o mesmo Problema/Metrica; a Abordagem base fica no projeto 1 (a fusão a compartilha)."""
    g1 = CuratorGraph(store, "proj1").setup_project()
    g2 = CuratorGraph(store, "proj2").setup_project()
    return g1, g2


def test_promocao_com_tres_positivos_em_um_projeto_nao_promove(world):
    """Scenario: Critério não atingido — 3 positivos validados em um único projeto: nenhuma abordagem criada."""
    store, graph, service = world
    hip, abordagem = graph.hipotese(), graph.abordagem()
    for i, no in enumerate(("A", "B", "C")):
        graph.tentativa(hip, abordagem, valor=0.80, no=no, seed=i + 1, config={"modelo": "gb", "p": 1})

    assert service.promotion_candidates() == []
    assert not store.find_nodes("Abordagem", {"tipo": "configuracao"})


def test_promocao_com_tres_positivos_em_dois_projetos_promove_e_e_idempotente(world):
    """Scenario: Critério atingido — 3 positivos em 2 projetos criam Abordagem configuracao com VARIANTE_DE;
    reexecutar não duplica."""
    store, graph, service = world
    g2 = CuratorGraph(store, "proj2").setup_project()
    hip1, abordagem = graph.hipotese(), graph.abordagem()
    hip2 = g2.hipotese()
    cfg = {"modelo": "gb", "profundidade": 3, "taxa": 0.1}
    graph.tentativa(hip1, abordagem, valor=0.80, no="A", config=cfg)
    graph.tentativa(hip1, abordagem, valor=0.80, no="B", config=cfg)
    # O experimento do projeto 2 aplicou a mesma abordagem (canônica, por fusão) com a mesma configuração.
    g2.tentativa(hip2, abordagem, valor=0.81, no="C", config=cfg, projeto_id="proj2")

    candidates = service.promotion_candidates()

    assert len(candidates) == 1
    assert candidates[0].positivos == 3
    assert candidates[0].projetos == ("proj1", "proj2")
    new_id = service.promote_configuration(candidates[0])
    node = store.get_node(new_id)
    assert node.properties["tipo"] == "configuracao"
    assert node.properties["nome"].startswith("GradientBoosting [")
    assert "modelo=gb" in node.properties["nome"]
    variante = _edges(store, "VARIANTE_DE", src=new_id, dst=abordagem)
    assert len(variante) == 1 and len(variante[0].properties["evidencias"]) == 3

    assert service.promotion_candidates() == []
    assert service.promote_configuration(candidates[0]) == new_id
    assert len(store.find_nodes("Abordagem", {"tipo": "configuracao"})) == 1


def test_fusao_inclui_as_tentativas_da_fundida_no_veredito_da_canonica(world):
    """Scenario: Fusão — o veredito da canônica passa a incluir as tentativas da fundida (e nada é apagado)."""
    store, graph, service = world
    hip = graph.hipotese()
    canonica = graph.abordagem("ResNet-18")
    duplicada = graph.abordagem("resnet18")
    graph.tentativa(hip, canonica, valor=0.80, no="A")
    graph.tentativa(hip, duplicada, valor=0.80, no="B")
    graph.tentativa(hip, duplicada, valor=0.80, no="C", seed=2)
    descoberta = _descoberta(store, graph, "funciona", sobre=[canonica, graph.problema])
    antes = service.recompute_discovery(descoberta)
    assert antes.n_tentativas == 1

    store.update_node(duplicada, {"status": "fundida"}, actor=ORQ)
    store.create_edge(duplicada, "FUNDIDA_EM", canonica, {}, actor=ORQ)
    service.recompute_approach(canonica)

    depois = service.recompute_discovery(descoberta)
    assert depois.n_tentativas == 3
    assert store.get_node(duplicada) is not None and store.get_node(canonica) is not None


def test_sem_criterio_o_veredito_e_indisponivel_com_erro_acionavel(world):
    """Fail-fast: hipótese de projeto sem Problema confirmado não tem veredito inventado."""
    store = InMemoryGraphStore()
    graph = CuratorGraph(store, "11111111-1111-4111-8111-111111111111")
    graph.projeto = store.create_node("Projeto", graph.base(titulo="P", objetivo="O", status="ativo"), actor=ORQ)
    hip = graph.hipotese(com_problema=False)

    with pytest.raises(KnowledgeServiceError):
        KnowledgeService(store, VerdictParams()).recompute_hypothesis(hip)


def test_apos_subtarefa_recalcula_hipotese_descoberta_e_promocao(world):
    """Tarefa 2.5 — ``after_subtask`` recalcula as hipóteses testadas e as descobertas ligadas."""
    store, graph, service = world
    hip, abordagem = graph.hipotese(), graph.abordagem()
    exp, _ = graph.tentativa(hip, abordagem, valor=0.80)
    descoberta = _descoberta(store, graph, "funciona", sobre=[abordagem, graph.problema])
    subtarefa = store.get_node(exp).properties["subtarefa_id"]

    report = service.after_subtask("proj1", subtarefa)

    assert report.hipoteses == 1 and report.descobertas == 1
    assert store.get_node(hip).properties["n_tentativas"] == 1
    assert store.get_node(descoberta).properties["veredito"] is not None
