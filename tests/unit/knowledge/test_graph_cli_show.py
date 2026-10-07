"""Testes da visualização do grafo pela CLI (v17-graph-cli, requisito "Visualização sem LLM").

Cada teste cita o ``#### Scenario`` (ou a tarefa) de ``openspec/changes/v17-graph-cli`` que cobre. Sem rede, banco ou
LLM: o grafo é em memória e qualquer chamada a provedor falha o teste.
"""

from __future__ import annotations

import json

import pytest

from src import config
from src.knowledge.graph_views import ReadOnlyGraph, load_project_view, render_view, sanitize_text
from src.knowledge.provenance import Actor
from tests.support.graph_cli_world import ESC, OTHER_PID, PID, World

pytestmark = pytest.mark.unit


@pytest.fixture
def world() -> World:
    return World()


@pytest.fixture(autouse=True)
def _no_llm(monkeypatch):
    """Tarefa 3.1: qualquer caminho que tente obter provedor ou roteador de LLM falha o teste."""

    def boom(*_a, **_k):
        raise AssertionError("graph show/node não pode chamar LLM")

    monkeypatch.setattr("src.model_router.ModelRouter.get_provider", boom)
    monkeypatch.setattr("src.llm.session.build_session_routing", boom)
    monkeypatch.setattr("src.llm.factory.create_provider", boom, raising=False)


def test_visualizar_o_projeto(world):
    """Scenario: Visualizar o projeto (nós, relações, veredito e leitura; nenhum LLM)."""
    code, out, _ = world.run(["show"])
    assert code == 0
    assert "Hipotese (1)" in out and "Descoberta (2)" in out and "Abordagem" in out
    assert world.ids["hipotese"] in out
    assert "+0,36 funciona (moderada)" in out  # veredito e leitura no nó que os tem
    assert "SOBRE" in out  # relações em árvore
    assert "segredo do outro projeto" not in out  # nada de outro projeto


def test_graph_show_nao_chama_llm(world, monkeypatch):
    """Tarefa 3.1: ``graph show`` e ``graph node`` não chamam nenhum provedor (o dublê falha se chamado)."""
    code_show, _, _ = world.run(["show", "--format", "mermaid"])
    code_node, _, _ = world.run(["node", world.ids["hipotese"]])
    assert code_show == 0 and code_node == 0  # o autouse ``_no_llm`` levantaria se houvesse chamada


def test_filtros_e_formatos(world):
    """Scenario: Filtros e formatos (``--label Descoberta --status ativa --format json``)."""
    code, out, _ = world.run(["show", "--label", "Descoberta", "--status", "ativa", "--format", "json"])
    assert code == 0
    data = json.loads(out)
    assert [n["id"] for n in data["nodes"]] == [world.ids["descoberta"]]
    assert all(n["label"] == "Descoberta" for n in data["nodes"])
    assert all(n["properties"]["status"] == "ativa" for n in data["nodes"])
    assert all(n["properties"]["projeto_id"] == PID for n in data["nodes"])


@pytest.mark.parametrize("fmt", ["text", "table", "json", "mermaid"])
def test_quatro_formatos_para_um_subgrafo(world, fmt):
    """Tarefa 3.2: os quatro formatos para um subgrafo de exemplo; ``json`` é válido."""
    code, out, _ = world.run(["show", "--label", "Hipotese", "--label", "Abordagem", "--format", fmt])
    assert code == 0 and out.strip()
    if fmt == "json":
        data = json.loads(out)
        assert {"nodes", "edges"} <= set(data) and len(data["nodes"]) == 2
    elif fmt == "mermaid":
        assert out.startswith("graph LR") and "-->" not in out.replace("-->|", "")  # arestas rotuladas
    elif fmt == "table":
        assert "Hipotese (1)" in out and "id" in out.splitlines()[1]
    else:
        assert "Abordagem (1)" in out


def test_dominio_e_depth(world):
    """Filtro por domínio (``NO_DOMINIO``, só Projeto/Problema pelo schema) e expansão por ``--depth``."""
    world.store.create_edge(world.ids["problema"], "NO_DOMINIO", world.ids["compartilhado"], {},
                            actor=Actor(kind="pesquisador"))
    _, out, _ = world.run(["show", "--dominio", "Aprendizado de Máquina", "--format", "json"])
    assert [n["id"] for n in json.loads(out)["nodes"]] == [world.ids["problema"]]
    _, out, _ = world.run(["show", "--dominio", "aprendizado de máquina", "--depth", "1", "--format", "json"])
    ids = {n["id"] for n in json.loads(out)["nodes"]}
    assert {world.ids["problema"], world.ids["hipotese"], world.ids["projeto"]} <= ids
    assert world.ids["descoberta"] not in ids and world.ids["outro_projeto_no"] not in ids


def test_detalhe_do_no(world):
    """Scenario: Detalhe do nó (propriedades, relações, histórico e fatores q, m, d, b, w por tentativa)."""
    code, out, _ = world.run(["node", world.ids["hipotese"]])
    assert code == 0
    assert "enunciado: Árvores de decisão melhoram o R2" in out
    assert "TESTA" in out and "Relações" in out
    assert "Histórico de alterações (1)" in out and "orquestrador" in out
    assert "Veredito por tentativa" in out
    assert out.count("q=") == 2 and "w=" in out and "m=" in out and "d=" in out and "b=" in out


def test_detalhe_no_json(world):
    """``graph node --format json`` traz o detalhamento do veredito estruturado."""
    _, out, _ = world.run(["node", world.ids["hipotese"], "--format", "json"])
    data = json.loads(out)
    assert len(data["verdict_breakdown"]["tentativas"]) == 2
    assert set(data["verdict_breakdown"]["tentativas"][0]) >= {"q", "m", "d", "b", "w"}


def test_grafo_grande(world, monkeypatch):
    """Scenario: Grafo grande (trunca com aviso e sugestão de filtros; ``--offset`` pagina)."""
    monkeypatch.setattr(config, "GRAPH_SHOW_MAX_NODES", 3)
    code, out, _ = world.run(["show"])
    assert code == 0
    assert "AVISO: saída truncada" in out and "--label" in out and "--offset 3" in out
    _, out2, _ = world.run(["show", "--offset", "3", "--format", "json"])
    assert 0 < len(json.loads(out2)["nodes"]) <= 3
    _, js, _ = world.run(["show", "--format", "json"])
    data = json.loads(js)
    assert data["truncated"] is True and len(data["nodes"]) == 3 and data["total_nodes"] > 3


def test_no_de_outro_projeto_nao_aparece_nem_se_revela(world):
    """Restrição ao projeto ativo/visibilidade: nó privado de outro projeto é "não encontrado" (sem revelar)."""
    code, out, _ = world.run(["node", world.ids["outro_projeto_no"]])
    assert code == 1 and "Nó não encontrado no projeto" in out
    code, out2, _ = world.run(["node", "inexistente-123"])
    assert out2 == out  # mesma resposta: não revela a existência
    code, out3, _ = world.run(["node", world.ids["compartilhado"]])
    assert code == 0 and "aprendizado de máquina" in out3  # compartilhável é visível


def test_sem_projeto_orienta_o_pesquisador(world, tmp_path):
    """Sem projeto ativo nem ``--project``, erro orientando ``--project``."""
    code, out, _ = world.run(["show"], with_project=False, config_dir=tmp_path)
    assert code == 1 and "--project" in out


def test_projeto_inexistente(world):
    """Projeto inexistente é erro explícito (nunca saída vazia silenciosa)."""
    code, out, _ = world.run(["show", "--project", OTHER_PID.replace("2", "3")], with_project=False)
    assert code == 1 and "não encontrado" in out


def test_filtros_invalidos(world):
    """Rótulo desconhecido, formato e profundidade inválidos são recusados."""
    assert world.run(["show", "--label", "Inexistente"])[0] == 1
    assert world.run(["show", "--depth", "9"])[0] == 1
    assert world.run(["show", "--offset", "-1"])[0] == 1
    assert world.run(["show", "--format", "xml"])[0] != 0


@pytest.mark.parametrize("fmt", ["text", "table", "json", "mermaid"])
def test_saida_sem_codigos_de_controle_do_terminal(world, fmt):
    """Segurança: ANSI/OSC/bidi vindos do conteúdo do grafo nunca chegam ao terminal."""
    evil = f"{ESC}[2J{ESC}]0;titulo\x07vermelho{ESC}[31m ‮texto⁦ \x9b31m fim\x00"
    world.store.update_node(world.ids["descoberta"], {"enunciado": evil}, actor=Actor(kind="pesquisador"))
    world.store.update_node(
        world.ids["abordagem"], {"descricao": evil}, actor=Actor(kind="pesquisador")
    )
    _, out, _ = world.run(["show", "--format", fmt])
    _, detail, _ = world.run(["node", world.ids["descoberta"]])
    _, detail_json, _ = world.run(["node", world.ids["descoberta"], "--format", "json"])
    for text in (out, detail, detail_json):
        assert ESC not in text and "\x07" not in text and "\x9b" not in text and "\x00" not in text
        assert "‮" not in text and "⁦" not in text
    assert "vermelho" in detail  # o texto legítimo permanece


def test_sanitize_text_limites():
    """``sanitize_text`` corta, colapsa espaços e troca quebras por espaço."""
    assert sanitize_text("a\n\tb\r\nc") == "a b c"
    assert sanitize_text("x" * 500, 10) == "x" * 9 + "…"
    assert sanitize_text(f"{ESC}[31mred{ESC}[0m") == "[31mred[0m"


def test_mermaid_neutraliza_texto_do_grafo(world):
    """Segurança: texto do grafo não escapa do rótulo Mermaid (aspas, colchetes, tags)."""
    world.store.update_node(world.ids["abordagem"], {"nome": 'x"] A-->B <script>[y]'}, actor=Actor(kind="pesquisador"))
    _, out, _ = world.run(["show", "--label", "Abordagem", "--format", "mermaid"])
    node_lines = [line for line in out.splitlines()[1:] if line.strip().startswith("n")]
    assert node_lines and all(line.count('"') == 2 and line.endswith('"]') for line in node_lines)
    assert "<script>" not in out and "A-->B" not in out
    assert "#quot;" in out and "#lt;" in out


def test_visao_somente_leitura_nao_expoe_escrita(world):
    """Sem acesso direto ao banco: a fachada de leitura não tem métodos de escrita nem consulta livre."""
    reader = ReadOnlyGraph(world.store)
    for name in ("create_node", "update_node", "create_edge", "set_edge_status", "update_edge", "read_query",
                 "record_audit_note"):
        assert not hasattr(reader, name)
    view = load_project_view(reader, PID)
    assert view.total_nodes == len(view.nodes) and not view.truncated
    assert "Nenhum nó" in render_view(load_project_view(reader, PID, status="inexistente"), "text")


def test_inventario_de_comandos():
    """Scenario: Inventário de comandos (nenhum executa consulta de escrita fornecida pelo usuário)."""
    from src.cli_graph import _build_parser

    parser = _build_parser()
    actions = parser._subparsers._group_actions[0].choices  # noqa: SLF001
    assert set(actions) == {"show", "node", "edit"}
    flags = {opt for p in actions.values() for a in p._actions for opt in a.option_strings}  # noqa: SLF001
    for forbidden in ("--query", "--cypher", "--sql", "--yes", "-y", "--force", "--no-confirm", "--run"):
        assert forbidden not in flags
    import inspect

    import src.cli_graph as module

    source = inspect.getsource(module)
    assert "read_query" not in source and "cypher" not in source.lower().replace("cypher/sql", "")
