"""Correções da revisão de segurança do PR #107 (v17-graph-cli): cada ataque do revisor vira um teste.

Os testes falhavam antes das correções e passam depois. Sem rede, banco ou LLM pago.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src import config
from src.human_gate import HumanGate
from src.knowledge import schema, validation
from src.knowledge.change_proposals import (
    ApplyError,
    HumanConfirmation,
    ProposalError,
    apply_plan,
    issue_confirmation,
    parse_ops,
    plan_changes,
    render_plan,
)
from src.knowledge.graph_store import Edge
from src.knowledge.provenance import Actor
from tests.support.graph_cli_world import PID, Scripted, World, propose

pytestmark = pytest.mark.unit
REPO = Path(__file__).resolve().parents[3]
REQ = "pedido"


@pytest.fixture(autouse=True)
def _setup(monkeypatch):
    monkeypatch.setattr(config, "CURATOR_ENABLED", True)
    monkeypatch.setattr("src.llm.metering.get_telemetry", lambda: MagicMock())


@pytest.fixture
def world() -> World:
    return World()


def plan_of(world: World, ops: list[dict]):
    return plan_changes(world.store, parse_ops(ops), project_id=PID)


def confirm(plan):
    return issue_confirmation(plan, "aplicar", tty=True)


# --------------------------------------------------------------------------- 1. mostrado == aplicado


def test_valor_longo_e_mostrado_por_inteiro_e_gravado_igual(world):
    """BLOQUEANTE 1: a cauda de um valor longo aparece na tela (antes era cortada em 80 e gravada inteira)."""
    tail = "CAUDA-TROCADA-CONCLUSAO"
    text = "Árvores funcionam em todo dataset. " * 5 + tail
    ops = [{"op": "update_node", "id": world.ids["descoberta"], "changes": {"enunciado": text}}]
    plan = plan_of(world, ops)
    shown = render_plan(plan, "x")
    assert tail in shown and json.dumps(text, ensure_ascii=False) in shown
    apply_plan(world.store, plan, request=REQ, confirmation=confirm(plan))
    assert world.store.get_node(world.ids["descoberta"]).properties["enunciado"] == text


def test_invariante_gravado_igual_exibido_para_todas_as_operacoes(world):
    """Invariante: todo valor efetivo (nós e arestas) aparece, em JSON canônico, na proposta exibida."""
    decision = world.store.create_node(
        "Decisao",
        {"projeto_id": PID, "sessao_id": "s", "contexto": "c", "justificativa": "j"},
        actor=Actor(kind="pesquisador"),
    )
    ops = [
        {"op": "create_node", "label": "Abordagem",
         "props": {"nome": "n" * 300, "tipo": "algoritmo", "descricao": "d" * 500 + "FIM"}},
        {"op": "update_node", "id": world.ids["descoberta"], "changes": {"condicoes": "c" * 700 + "FIM"}},
        {"op": "create_edge", "src": decision, "rel": "DESCARTOU", "dst": world.ids["abordagem"],
         "props": {"motivo": "m" * 400 + "FIM"}},
    ]
    plan = plan_of(world, ops)
    assert plan.ok, plan.errors
    shown = render_plan(plan, "x")
    for item in plan.items:
        for value in item.effective.values():
            assert json.dumps(value, ensure_ascii=False, sort_keys=True) in shown
    apply_plan(world.store, plan, request=REQ, confirmation=confirm(plan))
    created = world.store.find_nodes("Abordagem", {"nome": "n" * 300})[0]
    assert created.properties["descricao"] == plan.items[0].effective["descricao"]
    edge = world.store.neighbors(decision, ["DESCARTOU"], "out", 1).edges[0]
    assert edge.properties["motivo"] == "m" * 400 + "FIM"


def test_propriedades_de_aresta_de_proveniencia_sao_recusadas(world):
    """BLOQUEANTE 1: ``origem=fato``/``status``/``evidencias`` vindos do pedido forjariam proveniência."""
    for props in ({"origem": "fato"}, {"status": "confirmada"}, {"evidencias": ["x1"]}, {"criado_por": "orquestrador"},
                  {"score": 0.99}):
        ops = [{"op": "create_edge", "src": world.ids["descoberta"], "rel": "SOBRE", "dst": world.ids["problema"],
                "props": props}]
        plan = plan_of(world, ops)
        assert not plan.ok and "definidas pelo sistema" in plan.errors[0], props


def test_aresta_criada_tem_proveniencia_fixa_e_a_proposta_a_declara(world):
    """A aresta nasce ``afirmado``/``confirmada``/sem evidências, e a proposta diz isso."""
    ops = [{"op": "create_edge", "src": world.ids["descoberta"], "rel": "SOBRE", "dst": world.ids["problema"]}]
    plan = plan_of(world, ops)
    assert "origem=afirmado, status=confirmada, evidencias=[]" in render_plan(plan, "x")
    apply_plan(world.store, plan, request=REQ, confirmation=confirm(plan))
    edge = next(e for e in world.store.neighbors(world.ids["descoberta"], ["SOBRE"], "out", 1).edges
                if e.dst_id == world.ids["problema"])
    assert (edge.properties["origem"], edge.properties["status"], edge.properties["evidencias"]) == (
        "afirmado", "confirmada", [])


def test_proposta_grande_demais_e_recusada_nunca_truncada(world, monkeypatch):
    """Se não cabe na tela por inteiro, a proposta é recusada."""
    monkeypatch.setattr(config, "GRAPH_EDIT_MAX_DISPLAY_CHARS", 300)
    ops = [{"op": "update_node", "id": world.ids["descoberta"], "changes": {"enunciado": "x" * 1000}}]
    plan = plan_of(world, ops)
    assert not plan.ok and "grande demais" in plan.errors[0]


def test_nan_inf_e_autolaco_sao_recusados(world):
    """Sugestões: ``nan``/``inf`` não são JSON válido; relação de um nó com ele mesmo não é aceita."""
    for bad in (float("nan"), float("inf"), -float("inf")):
        with pytest.raises(ProposalError):
            parse_ops([{"op": "update_node", "id": "x", "changes": {"valor": bad}}])
    plan = plan_of(world, [{"op": "create_edge", "src": world.ids["abordagem"], "rel": "VARIANTE_DE",
                            "dst": world.ids["abordagem"]}])
    assert not plan.ok and "auto-laço" in plan.errors[0]


# --------------------------------------------------------------------------- 2. regras de rótulo nas arestas


def _edges_with_blocked_or_fact_src(world: World):
    blocked = set(validation.FACT_LABELS) | {"Problema", "Projeto", "Dominio", "Metrica"}
    seen = set()
    for edge in world.store._edges:  # noqa: SLF001 - inventário do grafo de teste
        src = world.store.get_node(edge.src_id)
        if src.label in blocked and (src.label, edge.rel_type) not in seen:
            seen.add((src.label, edge.rel_type))
            yield src.label, edge


def test_set_edge_status_recusa_origem_bloqueada_ou_fato_por_tipo_de_aresta(world):
    """IMPORTANTE 2: Projeto-INVESTIGA->Problema, Experimento-TESTA->Hipotese etc. não são contestadas."""
    checked = set()
    for label, edge in _edges_with_blocked_or_fact_src(world):
        op = {"op": "set_edge_status", "src": edge.src_id, "rel": edge.rel_type, "dst": edge.dst_id,
              "status": "contestada"}
        plan = plan_of(world, [op])
        assert not plan.ok, (label, edge.rel_type)
        checked.add((label, edge.rel_type))
    assert {("Projeto", "INVESTIGA"), ("Experimento", "TESTA"), ("Experimento", "PRODUZIU"),
            ("Resultado", "MEDE")} <= checked


def test_create_edge_recusa_origem_bloqueada_ou_fato_por_tipo_de_relacao(world):
    """IMPORTANTE 2: para toda relação do schema cuja origem é bloqueada/fato, ``create_edge`` é recusado."""
    nodes = {}
    for key in ("projeto", "problema", "metrica", "compartilhado", "hipotese", "abordagem", "descoberta",
                "oportunidade"):
        nodes[world.ids[key]] = world.store.get_node(world.ids[key])
    for res in world.store.find_nodes("Resultado", {"projeto_id": PID}, limit=1):
        nodes[res.id] = res
    for exp in world.store.find_nodes("Experimento", {"projeto_id": PID}, limit=1):
        nodes[exp.id] = exp
    blocked = set(validation.FACT_LABELS) | {"Problema", "Projeto", "Dominio", "Metrica"}
    attempted = 0
    for relation in schema.RELATION_SCHEMAS:
        for src in (n for n in nodes.values() if n.label in relation.src_labels and n.label in blocked):
            for dst in (n for n in nodes.values() if n.label in relation.dst_labels and n.id != src.id):
                if src.properties.get("projeto_id") != PID:
                    continue
                attempted += 1
                plan = plan_of(world, [{"op": "create_edge", "src": src.id, "rel": relation.rel_type,
                                        "dst": dst.id}])
                assert not plan.ok, (src.label, relation.rel_type, dst.label)
    assert attempted >= 3


def test_relacao_derivada_pode_ser_contestada_mas_nao_criada(world):
    """Decisão documentada: contestar relação derivada (ex.: FUNCIONOU_PARA) é permitido; criá-la à mão, não."""
    plan = plan_of(world, [{"op": "create_edge", "src": world.ids["abordagem"], "rel": "SEMELHANTE_A",
                            "dst": world.ids["abordagem"]}])
    assert not plan.ok


# --------------------------------------------------------------------------- 3. token de confirmação humana


def test_apply_plan_exige_confirmacao_humana_valida(world):
    """IMPORTANTE 3: sem token, com token inválido ou de outra proposta, nada é escrito."""
    op = {"op": "update_node", "id": world.ids["descoberta"], "changes": {"status": "contestada"}}
    plan = plan_of(world, [op])
    with pytest.raises(PermissionError):
        apply_plan(world.store, plan, request=REQ, confirmation=None)  # type: ignore[arg-type]
    for typed, tty in (("APLICAR", True), (" aplicar", True), ("aplicar", False), ("", True), ("sim", True)):
        with pytest.raises(PermissionError):
            HumanConfirmation(plan.fingerprint(), typed, tty)
    other = plan_of(world, [{**op, "changes": {"status": "substituida"}}])
    with pytest.raises(ProposalError, match="difere"):
        apply_plan(world.store, other, request=REQ, confirmation=confirm(plan))
    assert world.store.get_node(world.ids["descoberta"]).properties["status"] == "ativa"


def test_plano_adulterado_depois_da_exibicao_nao_aplica(world):
    """Invariante: alterar o que será gravado depois de confirmar muda a impressão digital e aborta."""
    plan = plan_of(world, [{"op": "update_node", "id": world.ids["descoberta"],
                            "changes": {"enunciado": "texto visto"}}])
    confirmation = confirm(plan)
    plan.items[0].effective["enunciado"] = "texto NÃO visto"
    with pytest.raises(ProposalError, match="difere"):
        apply_plan(world.store, plan, request=REQ, confirmation=confirmation)
    assert world.store.get_node(world.ids["descoberta"]).properties["enunciado"] != "texto NÃO visto"


def test_guarda_estatica_apply_plan_so_na_cli():
    """IMPORTANTE 3: ``apply_plan`` e a confirmação só em ``cli_graph``; importadores restritos."""
    forbidden = re.compile(r"\b(apply_plan|issue_confirmation|HumanConfirmation|_ACTOR)\b")
    allowed_users = {"src/knowledge/change_proposals.py", "src/cli_graph.py"}
    allowed_importers = allowed_users | {"agents/curator/edit.py"}
    offenders, importers = [], []
    for base in ("src", "agents"):
        for path in (REPO / base).rglob("*.py"):
            rel = str(path.relative_to(REPO))
            text = path.read_text(encoding="utf-8")
            if forbidden.search(text) and rel not in allowed_users:
                offenders.append(rel)
            if re.search(r"change_proposals", text) and rel not in allowed_importers:
                importers.append(rel)
    assert not offenders, offenders
    assert not importers, importers
    edit = (REPO / "agents/curator/edit.py").read_text(encoding="utf-8")
    assert not re.search(r"import[^\n]*\b(apply_plan|issue_confirmation|HumanConfirmation)\b", edit)
    for base in ("agents", "src/skills"):
        for path in (REPO / base).rglob("*.py"):
            assert not re.search(r"\bapply_plan\b|\bissue_confirmation\b", path.read_text(encoding="utf-8")), path


# --------------------------------------------------------------------------- 5. confirmação exata


@pytest.mark.parametrize("answer", ["APLICAR", "Aplicar", " aplicar", "aplicar ", "aplicar\t", "aplica"])
def test_somente_a_palavra_exata_aplica(world, answer):
    """IMPORTANTE 5: nem maiúsculas nem espaços; nada é alterado."""
    op = {"op": "update_node", "id": world.ids["descoberta"], "changes": {"status": "contestada"}}
    code, out, _ = world.run(["edit", REQ], inputs=[answer], provider=Scripted(propose([op])))
    assert code == 1 and world.store.get_node(world.ids["descoberta"]).properties["status"] == "ativa"


def test_palavra_exata_aplica(world):
    op = {"op": "update_node", "id": world.ids["descoberta"], "changes": {"status": "contestada"}}
    code, _, _ = world.run(["edit", REQ], inputs=["aplicar"], provider=Scripted(propose([op])))
    assert code == 0


# --------------------------------------------------------------------------- 6. Mermaid


@pytest.mark.parametrize(
    "evil",
    ["#lt;img src=x onerror=alert(1)#gt;", "#quot;]; click n0 call evil()", "%%{init: {'theme':'x'}}%%",
     "x\nclick n0 href \"http://e\"", "a --> b", "n0[\"y\"]"],
)
def test_mermaid_nao_deixa_entidade_nem_diretiva_passar(world, evil):
    """IMPORTANTE 6: ``#`` é escapado (sem contrabando de entidade) e nenhuma diretiva/linha extra surge."""
    world.store.update_node(world.ids["abordagem"], {"nome": evil}, actor=Actor(kind="pesquisador"))
    _, out, _ = world.run(["show", "--label", "Abordagem", "--format", "mermaid"])
    node_line = next(line for line in out.splitlines() if line.strip().startswith("n0"))
    sanitized = " ".join(evil.split())
    assert node_line.count("#35;") == sanitized.count("#")  # todo '#' literal virou entidade própria
    assert "{" not in out and "%%{" not in out
    for line in out.splitlines():
        assert re.match(r"^(graph LR|\s+n\d+(\[\".*\"\]| -->\|.*\| n\d+)|\s+%% .*)$", line), line
    assert "<" not in out and ">" not in out.replace("-->", "")


# --------------------------------------------------------------------------- 7. reversão


def test_falha_de_reversao_e_reportada_e_auditada(world, monkeypatch):
    """IMPORTANTE 7: se desfazer também falha, o relatório diz (não é engolido) e a auditoria registra."""
    first = {"op": "update_node", "id": world.ids["descoberta"], "changes": {"status": "contestada"}}
    second = {"op": "update_node", "id": world.ids["descoberta2"], "changes": {"status": "ativa"}}
    plan = plan_of(world, [first, second])
    original = world.store.update_node
    calls = {"n": 0}

    def flaky(node_id, changes, *, actor):
        calls["n"] += 1
        if calls["n"] >= 2:
            raise RuntimeError("falha simulada")  # 2ª escrita e a reversão da 1ª
        return original(node_id, changes, actor=actor)

    monkeypatch.setattr(world.store, "update_node", flaky)
    with pytest.raises(ApplyError) as info:
        apply_plan(world.store, plan, request=REQ, confirmation=confirm(plan))
    monkeypatch.undo()
    assert info.value.rolled_back == 0 and info.value.rollback_failures
    assert "FALHOU" in str(info.value)
    trail = [e for e in world.store.audit_log if e["changes"].get("evento") == "reversao"]
    assert trail and trail[0]["changes"]["falhas_de_reversao"]


def test_reversao_restaura_os_valores_anteriores_da_oportunidade(world, monkeypatch):
    """IMPORTANTE 7: a reversão devolve status e campos de decisão ao valor anterior (None = sem valor)."""
    before = dict(world.store.get_node(world.ids["oportunidade"]).properties)
    ops = [
        {"op": "update_node", "id": world.ids["oportunidade"], "changes": {"status": "rejeitada"}, "motivo": "m"},
        {"op": "update_node", "id": world.ids["descoberta"], "changes": {"status": "contestada"}},
    ]
    plan = plan_of(world, ops)
    original = world.store.update_node
    calls = {"n": 0}

    def flaky(node_id, changes, *, actor):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("falha simulada")
        return original(node_id, changes, actor=actor)

    monkeypatch.setattr(world.store, "update_node", flaky)
    with pytest.raises(ApplyError) as info:
        apply_plan(world.store, plan, request=REQ, confirmation=confirm(plan))
    monkeypatch.undo()
    assert info.value.rolled_back == 1 and not info.value.rollback_failures
    after = world.store.get_node(world.ids["oportunidade"]).properties
    for key in ("status", "decidido_por", "decidido_em", "motivo_decisao", "enunciado"):
        assert after.get(key) == before.get(key), key  # None e ausente são equivalentes


# --------------------------------------------------------------------------- 8. sugestões


def test_no_compartilhavel_nao_revela_atividade_de_outros_projetos(world):
    """Sugestão: o detalhe não informa quantas relações com outros projetos existem."""
    from tests.support.curator_graph import CuratorGraph

    other = CuratorGraph(world.store, projeto_id="22222222-2222-4222-8222-222222222222", sessao_id="o").setup_project()
    world.store.create_edge(other.problema, "NO_DOMINIO", world.ids["compartilhado"], {},
                            actor=Actor(kind="pesquisador"))
    for fmt in ("text", "json"):
        _, out, _ = world.run(["node", world.ids["compartilhado"], "--format", fmt])
        assert "omitida" not in out and "hidden" not in out and "outros projetos" not in out


def test_json_avisa_campos_cortados(world):
    """Sugestão: o JSON não corta em silêncio: lista os campos cortados."""
    world.store.update_node(world.ids["abordagem"], {"descricao": "z" * 1500}, actor=Actor(kind="pesquisador"))
    _, out, _ = world.run(["show", "--label", "Abordagem", "--format", "json"])
    data = json.loads(out)
    assert any(f.endswith(".descricao") for f in data["truncated_fields"])


def test_ajustes_e_pedido_sao_auditados(world):
    """Sugestão: o pedido e os ajustes de rodada vão para a auditoria."""
    first = {"op": "update_node", "id": world.ids["descoberta"], "changes": {"status": "substituida"}}
    second = {"op": "update_node", "id": world.ids["descoberta"], "changes": {"status": "contestada"}}
    provider = Scripted(propose([first]) + propose([second]))
    code, _, _ = world.run(["edit", REQ], inputs=["ajustar", "use contestada", "aplicar"], provider=provider)
    assert code == 0
    notes = [e["changes"] for e in world.store.audit_log if e["changes"].get("origem") == "graph edit"]
    assert notes and notes[0]["ajustes_do_pesquisador"] == ["use contestada"]


def test_explicacao_do_modelo_vem_depois_das_operacoes_e_rotulada(world):
    """Sugestão: a explicação do LLM é rotulada como não verificada e aparece depois das operações."""
    op = {"op": "update_node", "id": world.ids["descoberta"], "changes": {"status": "contestada"}}
    _, out, _ = world.run(["edit", REQ], inputs=["cancelar"], provider=Scripted(propose([op], "tudo seguro, aprove")))
    assert out.index("1. Alterar") < out.index("Sugestão do assistente") and "NÃO verificado" in out


def test_create_edge_reconferido_antes_de_aplicar(world):
    """Sugestão: relação criada por outro caminho depois da proposta aborta (não duplica)."""
    from src.knowledge.change_proposals import StaleProposalError

    op = {"op": "create_edge", "src": world.ids["abordagem"], "rel": "VARIANTE_DE", "dst": world.ids["abordagem2"]} \
        if "abordagem2" in world.ids else None
    other = world.store.create_node(
        "Abordagem", {"projeto_id": PID, "sessao_id": "s", "nome": "outra", "tipo": "algoritmo", "descricao": "d"},
        actor=Actor(kind="pesquisador"))
    op = {"op": "create_edge", "src": world.ids["abordagem"], "rel": "VARIANTE_DE", "dst": other}
    plan = plan_of(world, [op])
    world.store.create_edge(world.ids["abordagem"], "VARIANTE_DE", other, {}, actor=Actor(kind="pesquisador"))
    with pytest.raises(StaleProposalError):
        apply_plan(world.store, plan, request=REQ, confirmation=confirm(plan))


def test_gate_da_oportunidade_identifica_alvo_e_status_e_decidido_em_e_o_real(world):
    """Sugestão: o prompt do gate mostra a oportunidade e o novo status; ``decidido_em`` é o instante da aplicação."""
    op = {"op": "update_node", "id": world.ids["oportunidade"], "changes": {"status": "aprovada"}, "motivo": "ok"}
    started = datetime.now(timezone.utc)
    code, out, prompts = world.run(["edit", REQ], inputs=["aplicar", "s"], provider=Scripted(propose([op])),
                                   gate=HumanGate())
    assert code == 0
    gate_prompt = next(p for p in prompts if "aprovar_oportunidade" in p)
    assert world.ids["oportunidade"] in gate_prompt and "aprovada" in gate_prompt
    decided = datetime.fromisoformat(world.store.get_node(world.ids["oportunidade"]).properties["decidido_em"])
    assert started <= decided <= datetime.now(timezone.utc)
    plan = plan_of(world, [op])
    assert "decidido_em" not in plan.items[0].effective  # não fixado no plano


def test_project_id_faz_parte_da_impressao_digital(world):
    """Mutar ``project_id`` depois de confirmar aborta (antes gravava em outro projeto)."""
    op = {"op": "create_node", "label": "Abordagem", "props": {"nome": "x", "tipo": "algoritmo", "descricao": "d"}}
    plan = plan_of(world, [op])
    confirmation = confirm(plan)
    plan.project_id = "22222222-2222-4222-8222-222222222222"
    with pytest.raises(ProposalError, match="difere"):
        apply_plan(world.store, plan, request=REQ, confirmation=confirmation)
    assert world.store.find_nodes("Abordagem", {"nome": "x"}) == []


def test_relacao_derivada_so_pode_ser_contestada(world):
    """``set_edge_status`` não reafirma (``confirmada``) relação derivada; contestar segue permitido."""
    world.store._edges.append(  # noqa: SLF001 - relação derivada gravada pelo cálculo (orquestrador)
        Edge(world.ids["abordagem"], "FUNCIONOU_PARA", world.ids["problema"], {"status": "contestada"})
    )
    base = {"op": "set_edge_status", "src": world.ids["abordagem"], "rel": "FUNCIONOU_PARA",
            "dst": world.ids["problema"]}
    assert not plan_of(world, [{**base, "status": "confirmada"}]).ok
    assert plan_of(world, [{**base, "status": "contestada"}]).ok
