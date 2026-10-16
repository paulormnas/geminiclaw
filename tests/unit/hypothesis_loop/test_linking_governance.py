"""``v18.7-hypothesis-linking``: retiradas só por decisão humana ou integridade, fila, retorno ao Researcher, eventos."""

from __future__ import annotations

import json
import re
from unittest.mock import patch

import pytest

from src.knowledge.hypothesis_cycle import ApprovalDecision
from src.orchestration.exploration_feedback import LinkageFeedback
from tests.support import exploration_graph as eg
from tests.support.hypothesis_world import AGENTE, ORQ
from tests.support.linking_world import LinkingCycle, sub

RF = {"nome": "random forest", "tipo": "algoritmo"}
REMOVED_CODES = {"sem_hipotese", "hipotese_id_inexistente", "hipotese_sem_enunciado", "hipotese_ja_concluida_ou_abandonada"}

pytestmark = pytest.mark.unit


def _fine_plan() -> list[dict]:
    """Plano em passos finos da bateria V18.6 (nomes genéricos)."""
    return [
        sub("eda", task_type="eda", criteria=None, approach={"nome": "análise exploratória", "tipo": "algoritmo"}),
        sub("preprocessar_dados", criteria=("proporção de nulos <= 0",)),
        sub("baseline_majoritario", task_type="validation", papel="referencia", criteria=None,
            depends_on=["preprocessar_dados"]),
        sub("treinar_knn", hypothesis_ref="h1", criteria=("acurácia no teste >= 0.9",), depends_on=["preprocessar_dados"]),
        sub("treinar_rf", approach=RF, depends_on=["preprocessar_dados"]),
    ]


def _h(ref: str, text: str | None = None) -> dict:
    return {"ref": ref, "enunciado": text or f"A hipótese {ref} difere bastante das demais", "justificativa": "J",
            "origem": "researcher"}


def _block(c: LinkingCycle) -> list[dict]:
    text = c.session.prompt_block()
    match = re.search(r'<dado_nao_confiavel origem="ligacoes_e_retiradas_do_ciclo_anterior">\n(.*?)\n</dado_nao_confiavel>',
                      text, re.S)
    assert match, text
    return json.loads(match.group(1))


def test_plano_em_passos_finos_executa(tmp_path):
    """Scenario: Plano em passos finos executa."""
    c = LinkingCycle(tmp_path, mode="auto")
    outcome = c.run(_fine_plan(), [_h("h1")])
    assert outcome.dropped == {}
    assert {t.task_name for t in outcome.tasks} == {"eda", "preprocessar_dados", "baseline_majoritario",
                                                    "treinar_knn", "treinar_rf"}
    assert c.events_of("hypothesis_cycle")[-1]["retiradas_por_motivo"] == {}


def test_contagens_do_ciclo(tmp_path):
    """Scenario: Contagens do ciclo (``papeis``, ``testes_por_origem``, hipóteses do sistema, sem texto de enunciado)."""
    c = LinkingCycle(tmp_path, mode="auto")
    c.run(_fine_plan(), [_h("h1", "ENUNCIADO-SECRETO-DA-PESQUISA")])
    event = c.events_of("hypothesis_cycle")[-1]
    assert event["papeis"] == {"teste": 2, "preparacao": 2, "referencia": 1}
    assert event["testes_por_origem"]["researcher"] == 1 and event["testes_por_origem"]["sistema"] == 1
    assert event["hipoteses_sistema_criadas"] == 1 and event["hipoteses_sistema_reutilizadas"] == 0
    assert event["ligacoes_prepara"] == 3  # eda -> Problema (1); preprocessar_dados -> h1 e hs (2)
    assert set(event["papel_fonte"]) == {"declarado", "hypothesis_ref", "task_type", "sinal_de_teste",
                                         "estrutura_dag", "residual"}
    assert "ENUNCIADO-SECRETO" not in repr(c.events)


def test_retorno_do_ciclo_ao_researcher(tmp_path):
    """Scenario: Retorno do ciclo."""
    c = LinkingCycle(tmp_path, mode="auto")
    c.run(_fine_plan(), [_h("h1")])
    (hs,) = c.system_hypotheses()
    items = _block(c)
    texts = " ".join(i["texto"] for i in items)
    assert "preprocessar_dados" in texts and "preparação de" in texts and "treinar_rf" in texts and hs.id in texts
    baseline = next(i for i in items if i["subtarefa"] == "baseline_majoritario")
    assert "referência do Problema" in baseline["texto"]
    assert all(set(i) >= {"subtarefa", "papel", "acao", "motivo", "hipoteses"} for i in items)


def test_baseline_nao_declarado_sugere_declarar_a_referencia(tmp_path):
    """Scenario: Baseline não declarado."""
    c = LinkingCycle(tmp_path)
    c.run([sub("baseline_dummy", criteria=("accuracy >= 0.3",))])
    (item,) = [i for i in _block(c) if i["subtarefa"] == "baseline_dummy" and i["acao"] == "baseline_provavel"]
    assert "papel: referencia" in item["texto"]


def test_limite_de_itens_do_retorno(tmp_path):
    """Scenario: Limite de itens (as retiradas ficam entre os itens que cabem)."""
    c = LinkingCycle(tmp_path)
    fb = LinkageFeedback()
    for i in range(5):
        fb.prepares(f"prep_{i}", [])
    fb.withdrawn("a", "teste", "hipotese_rejeitada_pelo_pesquisador")
    fb.withdrawn("b", "teste", "depende_de_subtarefa_retirada")
    with patch("src.config.LINKAGE_FEEDBACK_MAX_ITEMS", 3):
        c.session._feedback = fb.items()
    items = _block(c)
    assert len(items) == 3 and {i["acao"] for i in items[:2]} == {"retirada"}


def test_papel_invalido_e_registrado_sem_reprovar(tmp_path):
    """Scenario: Plano sem papel não é reprovado (a subtarefa segue como se não tivesse o campo)."""
    c = LinkingCycle(tmp_path)
    outcome = c.run([sub("a"), sub("b", papel="exploratoria")])
    assert outcome.dropped == {} and c.tasks["b"].papel_decidido == "teste"
    assert any(i["acao"] == "formato" and i["subtarefa"] == "b" and "papel" in i["texto"] for i in c.session.linkage_feedback())


def test_rejeicao_parcial_nao_derruba_a_preparacao_compartilhada(tmp_path):
    """Scenario: Rejeição parcial não derruba a preparação compartilhada."""
    reject_h1 = lambda items: {  # noqa: E731
        i.id: ApprovalDecision("rejeitar", motivo="não") if "h1" in i.enunciado else ApprovalDecision("aprovar")
        for i in items
    }
    c = LinkingCycle(tmp_path, mode="assisted", approver=reject_h1)
    outcome = c.run(
        [sub("preprocessar_dados", criteria=("proporção de nulos <= 0",)),
         sub("treinar_h1", hypothesis_ref="h1", depends_on=["preprocessar_dados"]),
         sub("treinar_h2", hypothesis_ref="h2", depends_on=["preprocessar_dados"])],
        [_h("h1", "A hipótese h1 é de um tipo"), _h("h2", "Outra ideia h2 totalmente diversa")],
    )
    assert outcome.dropped == {"treinar_h1": "hipotese_rejeitada_pelo_pesquisador"}
    assert {t.task_name for t in outcome.tasks} == {"preprocessar_dados", "treinar_h2"}


def test_preparacao_que_so_servia_a_hipotese_rejeitada(tmp_path):
    """Scenario: Preparação que só servia a hipótese rejeitada."""
    c = LinkingCycle(tmp_path, mode="assisted", approver=lambda items: {
        i.id: ApprovalDecision("rejeitar", motivo="não") for i in items})
    outcome = c.run(
        [sub("limpar_textos", criteria=("proporção de nulos <= 0",)),
         sub("treinar_h1", hypothesis_ref="h1", depends_on=["limpar_textos"])],
        [_h("h1")],
    )
    assert outcome.dropped == {"limpar_textos": "hipotese_rejeitada_pelo_pesquisador",
                               "treinar_h1": "hipotese_rejeitada_pelo_pesquisador"}


def test_preparacao_ligada_so_ao_problema_nunca_e_retirada_por_hipotese(tmp_path):
    c = LinkingCycle(tmp_path, mode="assisted", approver=lambda items: {})
    outcome = c.run([sub("eda", task_type="eda", criteria=None),
                     sub("treinar_h1", hypothesis_ref="h1")], [_h("h1")])
    assert outcome.dropped == {"treinar_h1": "hipotese_aguarda_aprovacao"}
    assert "eda" in {t.task_name for t in outcome.tasks}


def test_teste_que_depende_de_teste_retirado(tmp_path):
    """Scenario: Teste que depende de teste retirado."""
    c = LinkingCycle(tmp_path, mode="assisted", approver=lambda items: {
        i.id: ApprovalDecision("rejeitar", motivo="não") if "h1" in i.enunciado else ApprovalDecision("aprovar")
        for i in items})
    outcome = c.run(
        [sub("treinar_h1", hypothesis_ref="h1"),
         sub("comparar", hypothesis_ref="h3", depends_on=["treinar_h1"])],
        [_h("h1", "A hipótese h1 é de um tipo"), _h("h3", "Outra ideia h3 totalmente diversa")],
    )
    assert outcome.dropped == {"treinar_h1": "hipotese_rejeitada_pelo_pesquisador",
                               "comparar": "depende_de_subtarefa_retirada"}


def test_motivos_removidos_nunca_aparecem(tmp_path):
    """Scenario: Motivos removidos (nos planos das cenas desta spec)."""
    seen: set[str] = set()
    c = LinkingCycle(tmp_path, mode="auto")
    seen |= set(c.run(_fine_plan(), [_h("h1")]).dropped.values())
    seen |= set(c.run([sub("x", hypothesis_ref="h9"), sub("y", papel="exploratoria", criteria=None)]).dropped.values())
    seen |= set(c.run([sub("z", hypothesis_ref="h1")], [{"ref": "h1", "enunciado": ""}]).dropped.values())
    assert not seen & REMOVED_CODES


def test_replicacao_de_hipotese_validada(tmp_path):
    """Scenario: Replicação de hipótese validada (continua ``validada`` até o fim do ciclo)."""
    c = LinkingCycle(tmp_path)
    h1 = c.w.hypothesis("H1", status="validada")
    outcome = c.run([sub("treinar_knn_seed2", hypothesis_ref=h1)])
    assert "treinar_knn_seed2" in {t.task_name for t in outcome.tasks} and c.status(h1) == "validada"


def test_hipotese_abandonada_pelo_pesquisador_retira_o_teste(tmp_path):
    """Scenario: Hipótese abandonada pelo pesquisador."""
    c = LinkingCycle(tmp_path)
    h5 = c.w.hypothesis("H5", status="abandonada", abandonada_por="pesquisador")
    outcome = c.run([sub("t", hypothesis_ref=h5)])
    assert outcome.dropped == {"t": "hipotese_hipotese_abandonada"}


def test_hipotese_abandonada_pelo_agente_volta_pela_governanca(tmp_path):
    """Scenario: Hipótese abandonada pelo agente (não grava ``abandonada_por = pesquisador``)."""
    c = LinkingCycle(tmp_path, mode="assisted", approver=lambda items: {})
    h6 = c.w.hypothesis("H6", status="abandonada", abandonada_por="agente")
    outcome = c.run([sub("t", hypothesis_ref=h6)])
    props = c.w.store.get_node(h6).properties
    assert props["status"] == "proposta" and props.get("abandonada_por") != "pesquisador"
    assert outcome.dropped == {"t": "hipotese_aguarda_aprovacao"}


def test_hipotese_abandonada_sem_a_propriedade_e_sem_nota_e_do_agente(tmp_path):
    """Leitura compatível: nó antigo sem ``abandonada_por`` e sem nota de rejeição não bloqueia."""
    c = LinkingCycle(tmp_path, mode="auto")
    antiga = c.w.hypothesis("Antiga", status="abandonada")
    outcome = c.run([sub("t", hypothesis_ref=antiga)])
    assert outcome.dropped == {} and c.status(antiga) == "em_teste"


def test_recusa_do_researcher_grava_abandono_pelo_agente(tmp_path):
    """Recusas e alternativas descartadas pelo Researcher gravam ``abandonada_por = agente``."""
    from src.knowledge.hypotheses import PendingSuggestion

    c = LinkingCycle(tmp_path)
    book = c.session.book
    book._pending = lambda: [PendingSuggestion("s1", "Testar uma ideia nova bem específica", (), "caminho")]  # noqa: SLF001
    from src.knowledge.hypotheses import PlanExtras, SuggestionReply

    report = book.record(PlanExtras(respostas=(SuggestionReply("s1", "recusada", "sem tempo"),), novo_formato=True))
    assert report.respostas_registradas == {"s1": "recusada"}
    abandoned = [n for n in c.w.store.find_nodes("Hipotese", {"projeto_id": c.w.pid}, limit=10)
                 if n.properties["status"] == "abandonada"]
    assert [n.properties["abandonada_por"] for n in abandoned] == ["agente"]


def test_derivada_de_aceita_hipotese_do_projeto_e_ref_anterior(tmp_path):
    """Scenarios: Refinamento e ID de outro projeto."""
    c = LinkingCycle(tmp_path)
    hs1 = eg.hipotese(c.w, origem="sistema", enunciado="HS1")
    foreign = c.w.store.create_node(
        "Hipotese",
        {"projeto_id": "outro", "sessao_id": "x", "enunciado": "alheia", "justificativa": "j", "status": "proposta",
         "origem": "researcher", "justificativa_criacao": "t", "nos_consultados": []},
        actor=AGENTE,
    )
    outcome = c.run(
        [sub("t", hypothesis_ref="h2")],
        [{**_h("h1", "A hipótese h1 vem do sistema"), "derivada_de": [hs1]},
         {**_h("h2", "Padronizar os atributos melhora o kNN"), "derivada_de": ["h1"]},
         {**_h("h3", "Uma terceira ideia totalmente distinta"), "derivada_de": [foreign]}],
    )
    ref = outcome.report.ref_map

    def derived(src: str) -> set[str]:
        graph = c.w.store.neighbors(src, ["DERIVADA_DE"], direction="out", depth=1)
        return {e.dst_id for e in graph.edges if e.src_id == src}

    assert derived(ref["h1"]) == {hs1} and derived(ref["h2"]) == {ref["h1"]} and derived(ref["h3"]) == set()


def test_hipoteses_do_sistema_visiveis_ao_curator_e_ao_researcher(tmp_path):
    """Scenario: Hipótese do sistema no contexto."""
    c = LinkingCycle(tmp_path)
    hs1 = eg.hipotese(c.w, origem="sistema", enunciado="HS1", status="em_teste")
    view = {i["id"]: i for i in c.session.cycle.open_hypotheses_view()}
    assert view[hs1]["origem"] == "sistema"
    assert "sistema" in c.session.prompt_block()


def test_o_proprio_ciclo_nao_funde_hipoteses_por_acao_do_curator(tmp_path):
    """O sistema nunca funde hipóteses: duas do sistema com abordagens diferentes seguem separadas após dois ciclos."""
    c = LinkingCycle(tmp_path)
    c.run([sub("a", approach=RF), sub("b", approach={"nome": "svm", "tipo": "algoritmo"})])
    c.run([sub("a", approach=RF), sub("b", approach={"nome": "svm", "tipo": "algoritmo"})])
    assert len(c.system_hypotheses()) == 2 and ORQ.kind == "orquestrador"
