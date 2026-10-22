"""Testes do ``KnowledgeService`` (ADR 026: registros de resultado, regra de réplicas, atalhos e promoção).

Grafo em memória, sem rede, sem LLM. Cada teste cita o ``#### Scenario`` ou a tarefa de ``tasks.md`` que cobre.
"""

from __future__ import annotations

import pytest

from src.knowledge.graph_store import InMemoryGraphStore
from src.knowledge.service import KnowledgeService, KnowledgeServiceError
from tests.support.curator_graph import ORQ, CuratorGraph

pytestmark = pytest.mark.unit


@pytest.fixture
def world():
    store = InMemoryGraphStore()
    graph = CuratorGraph(store).setup_project()
    service = KnowledgeService(store)
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


def _records(store, abordagem=None):
    nodes = store.find_nodes("RegistroResultado", {})
    if abordagem is None:
        return nodes
    linked = {e.src_id for e in _edges(store, "REGISTRA", dst=abordagem)}
    return [n for n in nodes if n.id in linked]


def test_recalculo_conta_as_replicas_da_hipotese_e_liga_os_resultados(world):
    """Duas sementes acima do alvo e uma abaixo: contagens na hipótese e SUSTENTA/REFUTA sem peso."""
    store, graph, service = world
    hip, abordagem = graph.hipotese(), graph.abordagem()
    _, r1 = graph.tentativa(hip, abordagem, valor=0.80, seed=1)
    _, r2 = graph.tentativa(hip, abordagem, valor=0.82, seed=2)
    _, r3 = graph.tentativa(hip, abordagem, valor=0.60, seed=3)

    facts = service.recompute_hypothesis(hip)

    node = store.get_node(hip)
    assert (facts.n_atingiu_alvo, facts.n_abaixo_alvo) == (2, 1)
    assert node.properties["n_tentativas"] == 3
    assert node.properties["n_atingiu_alvo"] == 2 and node.properties["n_abaixo_alvo"] == 1
    assert "veredito" not in node.properties and "suporte" not in node.properties
    assert {e.src_id for e in _edges(store, "SUSTENTA", dst=hip)} == {r1, r2}
    assert {e.src_id for e in _edges(store, "REFUTA", dst=hip)} == {r3}
    for edge in _edges(store, "SUSTENTA", dst=hip) + _edges(store, "REFUTA", dst=hip):
        assert "peso" not in edge.properties and edge.properties["origem"] == "derivado"


def test_recalculo_nao_duplica_arestas(world):
    store, graph, service = world
    hip, abordagem = graph.hipotese(), graph.abordagem()
    _, res = graph.tentativa(hip, abordagem, valor=0.80)
    service.recompute_hypothesis(hip)
    service.recompute_hypothesis(hip)
    assert len(_edges(store, "SUSTENTA", src=res)) == 1


def test_evidencia_que_deixa_de_contar_e_contestada(world):
    """Resultado que o Validator deixa de verificar não é mais tentativa válida: a aresta fica contestada."""
    store, graph, service = world
    hip, abordagem = graph.hipotese(), graph.abordagem()
    _, res = graph.tentativa(hip, abordagem, valor=0.80)
    service.recompute_hypothesis(hip)
    assert _edges(store, "SUSTENTA", src=res)[0].properties["status"] == "confirmada"

    store.update_node(res, {"status_validacao": "nao_validado"}, actor=ORQ)
    facts = service.recompute_hypothesis(hip)

    assert facts.n_tentativas_validas == 0
    assert _edges(store, "SUSTENTA", src=res)[0].properties["status"] == "contestada"


def test_experimento_em_falha_com_valor_medido_e_tentativa_valida(world):
    """Falha por critério não atendido, mas com Resultado medido e verificado, conta abaixo do alvo."""
    store, graph, service = world
    hip, abordagem = graph.hipotese(), graph.abordagem()
    exp, _ = graph.tentativa(hip, abordagem, valor=0.40, seed=1)
    store.update_node(exp, {"status": "falha", "causa_falha": "ambigua", "assinatura_falha": "criterio_nao_atendido"},
                      actor=ORQ)
    sem_valor, _ = graph.tentativa(hip, abordagem, valor=None, seed=2)
    store.update_node(sem_valor, {"status": "falha", "causa_falha": "ambigua", "assinatura_falha": "sem_metricas"},
                      actor=ORQ)

    facts = service.recompute_hypothesis(hip)

    assert facts.n_tentativas_validas == 1 and facts.n_abaixo_alvo == 1


def test_resultado_de_treino_nao_e_tentativa(world):
    store, graph, service = world
    hip, abordagem = graph.hipotese(), graph.abordagem()
    _, res = graph.tentativa(hip, abordagem, valor=0.99)
    store.update_node(res, {"qualificador": "treino"}, actor=ORQ)

    assert service.recompute_hypothesis(hip).n_tentativas_validas == 0


def test_registro_guarda_os_fatos_por_configuracao_com_delta_base_e_delta_pai(world):
    """Um registro por (problema, abordagem, configuração); ``delta_pai`` é sobre a configuração anterior."""
    store, graph, service = world
    problema = store.get_node(graph.problema)
    hip, abordagem = graph.hipotese(), graph.abordagem()
    graph.tentativa(hip, abordagem, valor=0.80, baseline=0.70, seed=1, config={"modelo": "gb", "p": 1})
    graph.tentativa(hip, abordagem, valor=0.78, baseline=0.70, seed=2, config={"modelo": "gb", "p": 1})
    graph.tentativa(hip, abordagem, valor=0.90, baseline=0.70, seed=1, config={"modelo": "gb", "p": 2})

    ids = service.recompute_records(abordagem, problema)

    assert len(ids) == 2 and len(_records(store, abordagem)) == 2
    primeiro, segundo = (store.get_node(i) for i in ids)
    assert primeiro.properties["melhor_valor"] == pytest.approx(0.80)
    assert primeiro.properties["n_tentativas_validas"] == 2 and primeiro.properties["n_replicas_independentes"] == 2
    assert primeiro.properties["n_atingiu_alvo"] == 2 and primeiro.properties["atingiu_alvo"] is True
    assert primeiro.properties["delta_base"] == pytest.approx(0.10) and "delta_pai" not in primeiro.properties
    assert segundo.properties["melhor_valor"] == pytest.approx(0.90)
    assert segundo.properties["delta_pai"] == pytest.approx(0.10)
    assert segundo.properties["qualificacao"] == "pendente" and segundo.properties["criado_por"] == "orquestrador"
    assert {e.dst_id for e in _edges(store, "SOBRE", src=primeiro.id)} == {graph.problema}
    assert _edges(store, "BASEADA_EM", src=primeiro.id)

    service.recompute_records(abordagem, problema)  # idempotente
    assert len(_records(store, abordagem)) == 2 and len(_edges(store, "REGISTRA", dst=abordagem)) == 2


def test_atalho_funcionou_para_vem_do_registro_e_e_contestado_quando_a_regra_deixa_de_valer(world):
    """Duas réplicas acima do alvo mantêm FUNCIONOU_PARA com registro_id; uma delas deixar de valer contesta."""
    store, graph, service = world
    problema = store.get_node(graph.problema)
    hip, abordagem = graph.hipotese(), graph.abordagem()
    graph.tentativa(hip, abordagem, valor=0.80, seed=1)
    _, segunda = graph.tentativa(hip, abordagem, valor=0.82, seed=2)

    (registro_id,) = service.recompute_records(abordagem, problema)

    atalho = _edges(store, "FUNCIONOU_PARA", src=abordagem, dst=graph.problema)
    assert len(atalho) == 1 and atalho[0].properties["registro_id"] == registro_id
    assert atalho[0].properties["melhor_valor"] == pytest.approx(0.82) and atalho[0].properties["n_exp"] == 2
    assert atalho[0].properties["status"] == "confirmada"
    assert not _edges(store, "FALHOU_PARA", src=abordagem)

    store.update_node(segunda, {"status_validacao": "nao_validado"}, actor=ORQ)
    service.recompute_records(abordagem, problema)

    assert _edges(store, "FUNCIONOU_PARA", src=abordagem, dst=graph.problema)[0].properties["status"] == "contestada"


def test_atalho_falhou_para_exige_duas_replicas_abaixo_do_alvo_e_nenhuma_acima(world):
    store, graph, service = world
    problema = store.get_node(graph.problema)
    hip, abordagem = graph.hipotese(), graph.abordagem()
    graph.tentativa(hip, abordagem, valor=0.60, seed=1)
    service.recompute_records(abordagem, problema)
    assert not _edges(store, "FALHOU_PARA", src=abordagem)

    graph.tentativa(hip, abordagem, valor=0.62, seed=2)
    service.recompute_records(abordagem, problema)
    falhou = _edges(store, "FALHOU_PARA", src=abordagem, dst=graph.problema)
    assert len(falhou) == 1 and falhou[0].properties["n_exp"] == 2 and "registro_id" in falhou[0].properties

    graph.tentativa(hip, abordagem, valor=0.90, seed=3)  # uma réplica acima do alvo reabre a abordagem
    service.recompute_records(abordagem, problema)
    assert _edges(store, "FALHOU_PARA", src=abordagem, dst=graph.problema)[0].properties["status"] == "contestada"


def test_escopo_condicional_so_conta_as_tentativas_do_dataset(world):
    """``filtro_condicoes`` restringe as tentativas do escopo: ds1 atinge o alvo, ds2 fica abaixo."""
    store, graph, service = world
    hip, abordagem = graph.hipotese(), graph.abordagem()
    graph.tentativa(hip, abordagem, valor=0.80, seed=1, datasets=["ds1"])
    graph.tentativa(hip, abordagem, valor=0.82, seed=2, datasets=["ds1"])
    graph.tentativa(hip, abordagem, valor=0.60, seed=1, datasets=["ds2"])
    graph.tentativa(hip, abordagem, valor=0.62, seed=2, datasets=["ds2"])
    sobre = [store.get_node(hip)]

    ds1 = service.scope_facts(sobre, {"dataset_ids": ["ds1"]})[0]
    ds2 = service.scope_facts(sobre, {"dataset_ids": ["ds2"]})[0]

    assert (ds1.n_atingiu_alvo, ds1.n_abaixo_alvo) == (2, 0)
    assert (ds2.n_atingiu_alvo, ds2.n_abaixo_alvo) == (0, 2)


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

    assert service.promotion_candidates("proj1") == []
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
    g2.tentativa(hip2, abordagem, valor=0.81, no="C", config=cfg, projeto_id="proj2", visibilidade="compartilhavel")

    candidates = service.promotion_candidates("proj1")

    assert len(candidates) == 1
    assert candidates[0].positivos == 3
    assert candidates[0].projetos == ("proj1", "proj2")
    new_id = service.promote_configuration(candidates[0], "proj1")
    node = store.get_node(new_id)
    assert node.properties["tipo"] == "configuracao"
    assert node.properties["nome"].startswith("GradientBoosting [")
    assert "modelo=gb" in node.properties["nome"]
    variante = _edges(store, "VARIANTE_DE", src=new_id, dst=abordagem)
    assert len(variante) == 1 and len(variante[0].properties["evidencias"]) == 3

    assert service.promotion_candidates("proj1") == []
    assert service.promote_configuration(candidates[0], "proj1") == new_id
    assert len(store.find_nodes("Abordagem", {"tipo": "configuracao"})) == 1


def test_fusao_inclui_as_tentativas_da_fundida_nos_registros_da_canonica(world):
    """Fusão: o registro da canônica passa a incluir as tentativas da fundida (e nada é apagado)."""
    store, graph, service = world
    problema = store.get_node(graph.problema)
    hip = graph.hipotese()
    canonica = graph.abordagem("ResNet-18")
    duplicada = graph.abordagem("resnet18")
    graph.tentativa(hip, canonica, valor=0.80, no="A")
    graph.tentativa(hip, duplicada, valor=0.80, no="B", seed=2)
    graph.tentativa(hip, duplicada, valor=0.80, no="C", seed=3)
    (antes,) = service.recompute_records(canonica, problema)
    assert store.get_node(antes).properties["n_tentativas_validas"] == 1

    store.update_node(duplicada, {"status": "fundida"}, actor=ORQ)
    store.create_edge(duplicada, "FUNDIDA_EM", canonica, {}, actor=ORQ)
    assert service.recompute_approach(canonica) == 1

    (depois,) = _records(store, canonica)
    assert depois.properties["n_tentativas_validas"] == 3
    assert store.get_node(duplicada) is not None and store.get_node(canonica) is not None


def test_sem_criterio_a_contagem_e_indisponivel_com_erro_acionavel(world):
    """Fail-fast: hipótese de projeto sem Problema confirmado não tem contagem inventada."""
    store = InMemoryGraphStore()
    graph = CuratorGraph(store, "11111111-1111-4111-8111-111111111111")
    graph.projeto = store.create_node("Projeto", graph.base(titulo="P", objetivo="O", status="ativo"), actor=ORQ)
    hip = graph.hipotese(com_problema=False)

    with pytest.raises(KnowledgeServiceError):
        KnowledgeService(store).recompute_hypothesis(hip)


def test_apos_subtarefa_recalcula_hipotese_e_registros(world):
    """``after_subtask`` recalcula as hipóteses testadas pelo experimento e os registros da abordagem aplicada."""
    store, graph, service = world
    hip, abordagem = graph.hipotese(), graph.abordagem()
    exp, _ = graph.tentativa(hip, abordagem, valor=0.80)
    subtarefa = store.get_node(exp).properties["subtarefa_id"]

    report = service.after_subtask("proj1", subtarefa)

    assert report.hipoteses == 1 and report.registros == 1
    assert store.get_node(hip).properties["n_tentativas"] == 1
    assert len(_records(store, abordagem)) == 1


def test_registro_que_perdeu_as_tentativas_validas_e_zerado_e_nao_sustenta_mais_nada(world):
    """Uma réplica deixa de valer: o registro antigo não pode manter ``atingiu_alvo`` nem ``melhor_valor``."""
    store, graph, service = world
    problema = store.get_node(graph.problema)
    hip, abordagem = graph.hipotese(), graph.abordagem()
    _, r1 = graph.tentativa(hip, abordagem, valor=0.80, seed=1)
    _, r2 = graph.tentativa(hip, abordagem, valor=0.82, seed=2)
    (registro,) = service.recompute_records(abordagem, problema)
    assert store.get_node(registro).properties["atingiu_alvo"] is True

    for res in (r1, r2):
        store.update_node(res, {"status_validacao": "nao_validado"}, actor=ORQ)
    assert service.recompute_records(abordagem, problema) == []

    node = store.get_node(registro)
    assert node.properties["atingiu_alvo"] is False and node.properties["n_atingiu_alvo"] == 0
    assert node.properties["n_tentativas_validas"] == 0 and node.properties.get("melhor_valor") is None
    assert service.records_in_scope([store.get_node(abordagem), problema])  # o nó segue existindo (nada é apagado)


def test_atalho_decide_sobre_a_abordagem_inteira_e_atualiza_as_evidencias(world):
    """Duas configurações com um acerto cada: a abordagem tem duas réplicas independentes e o atalho existe."""
    store, graph, service = world
    problema = store.get_node(graph.problema)
    hip, abordagem = graph.hipotese(), graph.abordagem()
    _, r1 = graph.tentativa(hip, abordagem, valor=0.80, seed=42, config={"modelo": "gb", "p": 1})
    graph.tentativa(hip, abordagem, valor=0.82, seed=42, config={"modelo": "gb", "p": 2})
    ids = service.recompute_records(abordagem, problema)

    assert len(ids) == 2
    (atalho,) = _edges(store, "FUNCIONOU_PARA", src=abordagem, dst=graph.problema)
    assert atalho.properties["n_exp"] == 2 and atalho.properties["melhor_valor"] == pytest.approx(0.82)
    assert atalho.properties["registro_id"] in ids

    _, r3 = graph.tentativa(hip, abordagem, valor=0.90, seed=42, config={"modelo": "gb", "p": 3})
    service.recompute_records(abordagem, problema)
    (atalho,) = _edges(store, "FUNCIONOU_PARA", src=abordagem, dst=graph.problema)
    assert atalho.properties["melhor_valor"] == pytest.approx(0.90) and r3 in atalho.properties["evidencias"]
    assert store.get_node(atalho.properties["registro_id"]).properties["melhor_valor"] == pytest.approx(0.90)


def test_valor_de_teste_vale_mais_que_o_de_validacao_cruzada(world):
    """O experimento com cv=0,97 e teste=0,90 conta o valor de teste (o cv costuma ser otimista)."""
    store, graph, service = world
    hip, abordagem = graph.hipotese(), graph.abordagem()
    exp, cv = graph.tentativa(hip, abordagem, valor=0.97)
    store.update_node(cv, {"qualificador": "cv"}, actor=ORQ)
    teste = store.create_node(
        "Resultado",
        {**graph.base(), "nome_original": "r2", "valor": 0.90, "status_validacao": "validado", "caminho_metrics": "/m",
         "baseline": 0.7, "qualificador": "teste"},
        actor=ORQ,
    )
    store.create_edge(exp, "PRODUZIU", teste, {}, actor=ORQ)
    store.create_edge(teste, "MEDE", graph.metrica, {}, actor=ORQ)

    facts = service.recompute_hypothesis(hip)

    assert facts.melhor_valor == pytest.approx(0.90) and facts.resultado_ids == (teste,)
