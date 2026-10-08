"""Resolução e renderização de ``res``, ``src`` e ``calc`` (spec numeric-provenance)."""

from __future__ import annotations

import hashlib
import json

import pytest

from src.knowledge.graph_store import InMemoryGraphStore
from src.numeric_refs.render import display_value, format_number, render_text
from src.numeric_refs.sources import record_search_sources

from .helpers import fake_exec_id, make_resolver, new_ledger, record_run

pytestmark = pytest.mark.unit


@pytest.fixture
def world(tmp_path):
    outputs = tmp_path / "outputs"
    ledger = new_ledger(outputs)
    return outputs, ledger


def _render(text, resolver):
    return render_text(text, resolver)


def test_res_com_unidade_e_apendice(world):
    """Scenario: Resolução com unidade."""
    outputs, ledger = world
    exec_id = record_run(ledger, outputs, metrics={"rmse": 0.4498}, unidades={"rmse": "mm"})
    result = _render(f"O erro é {{{{res:{exec_id}/rmse}}}}.", make_resolver(outputs, ledger))
    assert result.texto == "O erro é 0,4498 mm [R1]."
    (code,) = result.codigos
    assert code.codigo == "R1" and code.valor_exato == 0.4498 and code.unidade == "mm"
    assert code.detalhe["exec_id"] == exec_id and code.detalhe["subtarefa"] == "treinar"
    assert code.detalhe["arquivo"] == "s1/treinar/metrics.json" and len(code.detalhe["sha256"]) == 64
    assert result.spans == [(len("O erro é "), len("O erro é 0,4498 mm [R1]"))]


def test_mesma_referencia_reaproveita_o_codigo(world):
    outputs, ledger = world
    e = record_run(ledger, outputs)
    r = _render(f"{{{{res:{e}/rmse}}}} e de novo {{{{res:{e}/rmse}}}}", make_resolver(outputs, ledger))
    assert r.texto.count("[R1]") == 2 and len(r.codigos) == 1 and r.codigos[0].ocorrencias == 2


def test_artefato_alterado_apos_a_execucao(world):
    """Scenario: Artefato alterado após a execução."""
    outputs, ledger = world
    e = record_run(ledger, outputs, tamper_after=True)
    raw = f"{{{{res:{e}/rmse}}}}"
    r = _render(f"valor {raw}", make_resolver(outputs, ledger))
    assert r.texto == f"valor `{raw}` [não verificado]"
    assert r.nao_resolvidos[0]["motivo"] == "artefato_alterado" and not r.codigos


def test_execucao_orfa(world):
    """Scenario: Execução órfã."""
    outputs, ledger = world
    e = record_run(ledger, outputs, finish=False)
    r = _render(f"{{{{res:{e}/rmse}}}}", make_resolver(outputs, ledger))
    assert r.nao_resolvidos[0]["motivo"] == "execucao_sem_termino" and "[não verificado]" in r.texto


@pytest.mark.parametrize(
    "build, motivo",
    [
        (lambda led, out: fake_exec_id(), "execucao_desconhecida"),
        (lambda led, out: record_run(led, out, status="falha_execucao"), "execucao_falhou"),
    ],
)
def test_motivos_de_execucao(world, build, motivo):
    outputs, ledger = world
    e = build(ledger, outputs)
    r = _render(f"{{{{res:{e}/rmse}}}}", make_resolver(outputs, ledger))
    assert r.nao_resolvidos[0]["motivo"] == motivo


def test_metrica_ausente_e_booleano_nao_e_numero(world):
    outputs, ledger = world
    e = record_run(ledger, outputs, metrics={"ok": True, "n": 3})
    resolver = make_resolver(outputs, ledger)
    assert _render(f"{{{{res:{e}/f1}}}}", resolver).nao_resolvidos[0]["motivo"] == "metrica_ausente"
    assert _render(f"{{{{res:{e}/ok}}}}", resolver).nao_resolvidos[0]["motivo"] == "metrica_ausente"
    assert _render(f"{{{{res:{e}/n}}}}", resolver).texto == "3 [R1]"


def test_param_vem_do_params_json(world):
    outputs, ledger = world
    e = record_run(ledger, outputs, parameters={"k": 3, "lr": 0.01})
    r = _render(f"k={{{{res:{e}/param.k}}}} lr={{{{res:{e}/param.lr}}}}", make_resolver(outputs, ledger))
    assert r.texto == "k=3 [R1] lr=0,01 [R2]"


def test_unidade_vem_do_grafo_quando_o_arquivo_nao_a_informa(world):
    outputs, ledger = world
    graph = InMemoryGraphStore()
    graph.create_node(
        "Metrica",
        {"nome": "rmse", "sentido": "menor_melhor", "unidade": "mm", "status": "aprovado", "projeto_id": "proj",
         "sessao_id": "s1"},
        actor=_orq(),
    )
    e = record_run(ledger, outputs)
    r = _render(f"{{{{res:{e}/rmse}}}}", make_resolver(outputs, ledger, graph=graph))
    assert r.texto == "0,4498 mm [R1]"


def _orq():
    from src.knowledge.provenance import Actor

    return Actor(kind="orquestrador")


def test_literal_no_codigo_e_marcado(world):
    outputs, ledger = world
    e = record_run(ledger, outputs)
    resolver = make_resolver(outputs, ledger, literal_metrics={(e, "rmse")})
    r = _render(f"{{{{res:{e}/rmse}}}}", resolver)
    assert r.texto == "0,4498 [R1] [literal no código]" and r.codigos[0].literal


# --- calc ----------------------------------------------------------------------------------------------------------

def test_calc_divergencia_com_codigos_no_apendice(world):
    """Scenario: Divergência percentual (ponta a ponta)."""
    outputs, ledger = world
    e = record_run(ledger, outputs, metrics={"rmse": 0.45}, unidades={"rmse": "mm"})
    graph, insumo = _graph_with_insumo(outputs, "Artigo: RMSE de 0,42 mm no conjunto de teste.")
    expr = f'round(pct((res:{e}/rmse - src:{insumo}#"RMSE de 0,42 mm") / src:{insumo}#"RMSE de 0,42 mm"), 1)'
    r = _render(f"Diverge {{{{calc:{expr}}}}}.", make_resolver(outputs, ledger, graph=graph, session_ids=["s1"]))
    assert r.texto == "Diverge 7,1 % [C1]."
    (code,) = r.codigos
    assert code.tipo == "calc" and code.detalhe["constantes"] == [1.0]
    assert [o["origem"] for o in code.detalhe["operandos"]] == ["res", "src", "src"]


def test_calc_com_no_proibido_e_sem_referencia(world):
    """Scenarios: Nó não permitido e Literal disfarçado de cálculo."""
    outputs, ledger = world
    resolver = make_resolver(outputs, ledger)
    r1 = _render("{{calc:__import__('os')}}", resolver)
    r2 = _render("{{calc:0.95}}", resolver)
    assert r1.nao_resolvidos[0]["motivo"] in ("no_nao_permitido", "calculo_sem_referencia", "sintaxe_invalida")
    assert r2.nao_resolvidos[0]["motivo"] == "calculo_sem_referencia" and "[não verificado]" in r2.texto


def test_calc_propaga_operando_nao_verificado(world):
    outputs, ledger = world
    e = record_run(ledger, outputs, tamper_after=True)
    r = _render(f"{{{{calc:res:{e}/rmse * 2}}}}", make_resolver(outputs, ledger))
    assert r.nao_resolvidos[0]["motivo"] == "artefato_alterado"


# --- src -----------------------------------------------------------------------------------------------------------

def _graph_with_insumo(outputs, text, name="artigo.txt", session="s1"):
    snapshot = outputs / session / "input_snapshot"
    snapshot.mkdir(parents=True, exist_ok=True)
    path = snapshot / name
    path.write_text(text, encoding="utf-8")
    graph = InMemoryGraphStore()
    node = graph.create_node(
        "Insumo",
        {"tipo": "artigo", "titulo": "Artigo de referência", "hash_conteudo": hashlib.sha256(text.encode()).hexdigest(),
         "caminho": name, "projeto_id": "proj", "sessao_id": session},
        actor=_orq(),
    )
    return graph, node


def test_src_de_insumo_com_unidade_e_titulo(world):
    """Scenario: Trecho de insumo encontrado."""
    outputs, ledger = world
    graph, insumo = _graph_with_insumo(outputs, "O modelo atinge RMSE de 0,42 mm no teste.")
    resolver = make_resolver(outputs, ledger, graph=graph, session_ids=["s1"])
    r = _render(f"{{{{src:{insumo}#RMSE de 0,42 mm}}}}", resolver)
    assert r.texto == "0,42 mm [S1]" and r.codigos[0].detalhe["titulo"] == "Artigo de referência"


def test_src_de_insumo_alterado_ou_desconhecido(world):
    outputs, ledger = world
    graph, insumo = _graph_with_insumo(outputs, "RMSE de 0,42 mm")
    (outputs / "s1" / "input_snapshot" / "artigo.txt").write_text("RMSE de 0,99 mm", encoding="utf-8")
    resolver = make_resolver(outputs, ledger, graph=graph, session_ids=["s1"])
    assert _render(f"{{{{src:{insumo}#RMSE de 0,42 mm}}}}", resolver).nao_resolvidos[0]["motivo"] == "insumo_alterado"
    assert _render("{{src:nao-existe#RMSE de 0,42 mm}}", resolver).nao_resolvidos[0]["motivo"] == "insumo_desconhecido"
    assert _render("{{src:x#y}}", make_resolver(outputs, ledger)).nao_resolvidos[0]["motivo"] == "insumo_desconhecido"


def test_src_trecho_ambiguo_ausente_e_sem_numero(world):
    """Scenario: Trecho ambíguo."""
    outputs, ledger = world
    graph, insumo = _graph_with_insumo(outputs, "RMSE de 0,42 mm e MAE de 0,3 mm. Sem número aqui.")
    resolver = make_resolver(outputs, ledger, graph=graph, session_ids=["s1"])
    def motivo(t: str) -> str:
        return _render(f"{{{{src:{insumo}#{t}}}}}", resolver).nao_resolvidos[0]["motivo"]

    assert motivo("RMSE de 0,42 mm e MAE de 0,3 mm") == "trecho_ambiguo"
    assert motivo("outro texto 5") == "trecho_nao_encontrado"
    assert motivo("Sem número aqui") == "trecho_sem_numero"


def test_src_de_url_exige_fonte_consultada(world):
    """Scenario: URL não consultada."""
    outputs, ledger = world
    resolver = make_resolver(outputs, ledger, session_ids=["s1"])
    miss = _render("{{src:https://exemplo.org/p#RMSE de 0,42 mm}}", resolver)
    assert miss.nao_resolvidos[0]["motivo"] == "fonte_nao_consultada"
    record_search_sources(outputs / "s1", "rmse", [
        {"url": "https://exemplo.org/p", "title": "Paper", "snippet": "Resultados: RMSE de 0,42 mm (n=10)"},
    ])
    hit = _render("{{src:https://exemplo.org/p#RMSE de 0,42 mm}}", make_resolver(outputs, ledger, session_ids=["s1"]))
    assert hit.texto == "0,42 mm [S1]" and hit.codigos[0].detalhe["titulo"] == "Paper"
    miss2 = _render("{{src:https://exemplo.org/p#RMSE de 9,9 mm}}", make_resolver(outputs, ledger, session_ids=["s1"]))
    assert miss2.nao_resolvidos[0]["motivo"] == "trecho_nao_encontrado"


def test_fontes_da_busca_sao_gravadas_em_jsonl(tmp_path):
    n = record_search_sources(tmp_path, "q", [
        {"url": "https://a.org", "title": "A", "snippet": "x 1"},
        {"url": "ftp://b", "title": "B"},
        {"title": "sem url"},
    ])
    lines = (tmp_path / "fontes_busca.jsonl").read_text(encoding="utf-8").splitlines()
    entry = json.loads(lines[0])
    assert n == 1 and entry["url"] == "https://a.org" and len(entry["sha256_trecho"]) == 64


# --- apresentação --------------------------------------------------------------------------------------------------

@pytest.mark.parametrize(
    "value, kwargs, expected",
    [
        (0.4498, {}, "0,4498"), (7.1, {"decimals": 1}, "7,1"), (7.0, {"decimals": 1}, "7,0"),
        (12345.678, {}, "12 345,7"), (1234567.0, {}, "1,23457 × 10⁶"), (0.00012, {}, "1,2 × 10⁻⁴"),
        (3.0, {"integer": True}, "3"), (95.0, {}, "95"), (-0.5, {}, "-0,5"), (0.0, {}, "0"),
        (1234.5, {}, "1234,5"),
    ],
)
def test_formato_pt_br(value, kwargs, expected):
    assert format_number(value, max_sig=6, **kwargs) == expected


def test_malformada_fica_em_codigo_com_marca(world):
    outputs, ledger = world
    r = _render("x {{res:exec_123/rmse}} y", make_resolver(outputs, ledger))
    assert r.texto == "x `{{res:exec_123/rmse}}` [não verificado] y"
    assert r.nao_resolvidos[0]["motivo"] == "sintaxe_invalida"


def test_display_value_com_unidade_percentual():
    from src.numeric_refs.resolver import ResolvedValue

    rv = ResolvedValue(7.1, "%", "calc", {}, True, decimais=1)
    assert display_value(rv) == "7,1 %"
