"""Correções dos achados da revisão de segurança do PR #113 (v18.5-egress-gate)."""

import time

import pytest

from src.egress import filters
from src.egress.fragments import ContentOrigin, PromptFragment, labeled, mark_tainted, strip_marks

pytestmark = pytest.mark.unit


def test_a1_strip_marks_nao_e_forjavel_por_aninhamento():
    payload = "⟦⟦/T⟧/T⟧"
    assert "⟦" not in strip_marks(payload) and "⟧" not in strip_marks(payload)
    marcado = mark_tainted("a ⟦⟦/T⟧/T⟧ 12.5")
    assert marcado.count("⟦/T⟧") == 1 and marcado.endswith("⟦/T⟧")


def _gate():
    from src.egress.gate import EgressGate

    from .conftest import MemoryLog

    return EgressGate("s", log=MemoryLog(), min_group_size=10, table_min_rows=3)


@pytest.mark.parametrize("origem", [ContentOrigin.SAIDA_EXECUCAO, ContentOrigin.DOCUMENTO, ContentOrigin.GRAFO])
def test_a2_marca_forjada_nao_divide_tabela_em_conteudo_nao_confiavel(origem):
    """Tabela dividida por marcas forjadas continua retida (marcas não são expandidas em origem não confiável)."""
    from .conftest import make_dest

    tabela = "1.0 2.0 3.0\n⟦T⟧4.0 5.0 6.0⟦/T⟧\n7.0 8.0 9.0"
    out = _gate().prepare_llm(
        [labeled("tool", PromptFragment(tabela, origem))], None, make_dest(raw=False)
    ).messages[0]["content"]
    if origem is ContentOrigin.SAIDA_EXECUCAO:
        assert "saída tabular retida" in out and "4.0" not in out
    assert "⟦" not in out


def test_a2_marca_forjada_em_texto_de_modelo_nao_vale():
    from .conftest import make_dest

    frag = PromptFragment("x ⟦D:fonte⟧y⟦/D⟧", ContentOrigin.INSTRUCAO, produced_by="developer")
    out = _gate().prepare_llm([labeled("assistant", frag)], None, make_dest(raw=False)).messages[0]["content"]
    assert out == "x y" and "retido" not in out


def _ctx():
    return filters.FilterContext(k=10, output_max_chars=4000, table_min_rows=3, integral_path="p")


@pytest.mark.parametrize(
    "texto",
    [
        " " * 100_000 + "x",  # espaços (quadrático em _KEYVALUE_RE)
        "a" * 100_000 + ": 1",  # nome longo (quadrático em _STAT_RE)
        "Error" * 20_000 + ": 1",  # tipo de exceção longo
        ("a b " * 250_000),  # 1 MiB em uma linha
        ("mean " * 1000 + "\n") * 200,  # 1 MiB em muitas linhas
        "1." * 500_000,  # dígitos e pontos
    ],
)
def test_a3_entrada_adversarial_termina_rapido(texto):
    inicio = time.monotonic()
    saida = filters.filter_execution_output(texto, _ctx())
    assert time.monotonic() - inicio < 2.0
    assert len(saida) < 410_000


def test_a3_linha_longa_e_omitida_com_marcador():
    saida = filters.filter_execution_output("ok\n" + "9" * 5000 + "\nfim", _ctx())
    assert "linha longa omitida: 5000 caracteres" in saida and "9999" not in saida


def test_a4_nomes_de_artefatos_no_contexto_de_dependencias_passam_pela_regra_de_nomes():
    from src.subtask_output import SubtaskOutput

    from .conftest import make_dest

    saida = SubtaskOutput(
        task_name="t", agent_id="developer", status="success", text_summary="ok", tainted=False,
        artifacts=[{"name": "curva_12.537.png", "path": "t/curva_12.537.png"}],
        artifact_aliases={"x.png": "curva_7.25.png"},
    )
    msg = labeled("user", PromptFragment(saida.to_context_string(), ContentOrigin.INSTRUCAO))
    fora = _gate().prepare_llm([msg], None, make_dest(raw=False)).messages[0]["content"]
    assert "12.537" not in fora and "7.25" not in fora and "<num padrão=dd.ddd>" in fora
    dentro = _gate().prepare_llm([msg], None, make_dest(raw=True)).messages[0]["content"]
    assert "12.537" in dentro and "7.25" in dentro


def test_a4_artefatos_da_retentativa_sao_nomes_sanitizados():
    from src.egress.fragments import mark_artifact_names

    from .conftest import make_dest

    contexto = "[ARTEFATOS]\n" + mark_artifact_names("  - r_3.14.csv\n  - ok.csv")
    fora = _gate().prepare_llm(
        [labeled("user", PromptFragment(contexto, ContentOrigin.INSTRUCAO))], None, make_dest(raw=False)
    ).messages[0]["content"]
    assert "r_<num padrão=d.dd>.csv" in fora and "ok.csv" in fora


def test_a4_memoria_escrita_pelo_orquestrador_leva_tag_explicita():
    from src.egress.persisted import TAINT_TAG
    from src.skills.memory.skill import MemorySkill, _writer_tags

    assert TAINT_TAG in _writer_tags(["code_pattern"])  # sem declaração: contaminado
    assert TAINT_TAG in _writer_tags(["x", TAINT_TAG], tainted=False)  # tag existente nunca é removida
    assert _writer_tags(["x"], tainted=False) == ["x"]
    skill = MemorySkill()
    skill._handle_remember("s-a4", key="retry", value='{"previous_error": "ValueError: 12,5"}', tainted=True)
    entry = skill.short_term.read("s-a4", "retry")
    assert TAINT_TAG in entry.tags


def test_a4_resultado_de_subtarefa_na_memoria_curta_vai_marcado(gate, third_party):
    from src.egress.persisted import tags_tainted
    from src.egress.fragments import taint_if

    assert tags_tainted(["subtask_result", "egress:tainted"])
    prompt = "Contexto: " + taint_if("acurácia 0.93", tags_tainted(["egress:tainted"]))
    out = gate.prepare_llm([labeled("user", PromptFragment(prompt, ContentOrigin.INSTRUCAO))], None, third_party)
    assert "<num padrão=d.dd>" in out.messages[0]["content"]


@pytest.mark.parametrize(
    "linha,exato",
    [
        ("val_max: 12.537", "12.537"),
        ("Max value (mV): 12.537", "12.537"),
        ("temperatura máxima = 12.537", "12.537"),
        ("valor mínimo: 12.537", "12.537"),
        ("loss_min_epoch: 12.537", "12.537"),
        ("n=500, mean: 4.2 max: 12.537", "12.537"),
        ("P95 latency (ms): 12.537", "12.537"),
    ],
)
def test_m2_extremos_em_qualquer_posicao_do_nome(linha, exato):
    saida = filters.filter_execution_output(linha, _ctx())
    assert exato not in saida and "[10, 20)" in saida


def test_m2_agregado_com_nome_composto_segue_a_regra_de_k():
    saida = filters.filter_execution_output("n=3\nmean accuracy (test): 0.93", _ctx())
    assert "0.93" not in saida and "n<k" in saida


def test_m3_continuacao_multilinha_da_mensagem_e_mascarada():
    texto = (
        "Traceback (most recent call last):\n"
        '  File "a.py", line 3, in <module>\n'
        "ValueError: linha com 'segredo' invalida\n"
        "valores: 12.5 e 'outro' 99\n"
        "mais um 3.14\n"
        "\n"
        "texto normal 7.5"
    )
    saida = filters.filter_execution_output(texto, _ctx())
    for vazado in ("segredo", "12.5", "'outro'", "99", "3.14"):
        assert vazado not in saida
    assert "texto normal 7.5" in saida  # depois da linha em branco já não é mensagem


def test_m3_excecao_sem_traceback_tambem_mascara_a_continuacao():
    saida = filters.filter_execution_output("KeyError: 'abc'\n  detalhe 4.25", _ctx())
    assert "4.25" not in saida and "abc" not in saida


@pytest.mark.parametrize("texto", ["v37", "x_12.5", "sensor42", "run_7_mV2", "lote_a99"])
def test_m4_prefixo_de_letra_nao_contorna_a_mascara(texto):
    saida, n = filters.mask_numbers(f"valor {texto} fim")
    assert not any(c.isdigit() for c in saida.replace("fim", "")) and n >= 1


def test_m4_identificadores_estruturais_e_conhecidos_sao_preservados():
    texto = "step_02 exec_1234 x1 v2 coluna_7"
    assert filters.mask_numbers(texto, frozenset({"coluna_7"})) == (texto, 0)
    assert filters.mask_numbers("coluna_7")[0] == "coluna_<num padrão=d>"


def test_m4_gate_respeita_known_identifiers_da_sessao():
    from .conftest import make_dest

    gate = _gate()
    gate.add_known_identifiers(["medida_3"])
    msg = labeled("assistant", PromptFragment("usei medida_3 e v37", ContentOrigin.INSTRUCAO, tainted=True))
    out = gate.prepare_llm([msg], None, make_dest(raw=False)).messages[0]["content"]
    assert out == "usei medida_3 e v<num padrão=dd>"


def test_m5_padrao_negar_em_diretorios_de_dados(tmp_path):
    from src.egress.classification import classify_path

    for nome in ("notas.txt", "caderno.md", "tabela.dat", "sem_extensao", "foto.heic", "dump.sqlite"):
        assert classify_path(tmp_path / "input_context" / nome, output_roots=[]) is ContentOrigin.DADO_DE_PESQUISA
        assert classify_path(tmp_path / "input_snapshot" / nome, output_roots=[]) is ContentOrigin.DADO_DE_PESQUISA


def test_m5_documento_so_se_explicitamente_marcado(tmp_path):
    from src.egress.classification import classify_path

    artigo = tmp_path / "input_context" / "artigo.pdf"
    assert classify_path(artigo, output_roots=[]) is ContentOrigin.DADO_DE_PESQUISA
    assert classify_path(artigo, output_roots=[], documents=[artigo]) is ContentOrigin.DOCUMENTO


def test_m5_symlink_para_dentro_de_dados_e_resolvido(tmp_path):
    from src.egress.classification import classify_path

    dados = tmp_path / "input_context"
    dados.mkdir()
    (dados / "medidas.csv").write_text("1,2")
    fora = tmp_path / "artifacts"
    fora.mkdir()
    link = fora / "relatorio.txt"  # nome inocente apontando para o dado
    link.symlink_to(dados / "medidas.csv")
    assert classify_path(link, output_roots=[]) is ContentOrigin.DADO_DE_PESQUISA
    # e o inverso: link dentro de input_context apontando para fora continua sendo dado (lado seguro)
    inverso = dados / "link.txt"
    inverso.symlink_to(fora / "x.txt")
    assert classify_path(inverso, output_roots=[]) is ContentOrigin.DADO_DE_PESQUISA


@pytest.mark.asyncio
async def test_b1_check_url_vem_antes_da_resolucao_dns(monkeypatch):
    """A resolução de DNS também é saída: a URL é verificada antes de `resolve_and_check_host`."""
    from src.egress.gate import bind_gate_for_tests
    from src.skills.web_reader import skill as wr

    ordem = []
    gate = _gate()
    original = gate.check_url

    def espiao(*a, **k):
        ordem.append("gate")
        return original(*a, **k)

    gate.check_url = espiao

    async def dns(host):
        ordem.append("dns")
        return "bloqueado no teste"

    monkeypatch.setattr(wr, "resolve_and_check_host", dns)
    bind_gate_for_tests(gate)
    skill = wr.WebReaderSkill()
    skill.cache = type("C", (), {"get": lambda self, u: None, "set": lambda self, u, v: None})()
    await skill.run(url="https://exemplo.org/artigo")
    assert ordem == ["gate", "dns"]

    ordem.clear()
    resultado = await skill.run(url="https://exemplo.org/medida/m12-537")  # papel sem contexto = contaminado
    assert ordem == ["gate"] and "recusada" in resultado.error  # recusada antes de qualquer DNS


@pytest.mark.parametrize("url", ["https://e.org/a/m12-537", "https://e.org/x/v37/y", "https://e.org/p#12.5",
                                 "https://12-537.e.org/p"])
def test_b1_segmentos_alfanumericos_com_digitos_sao_dado_embutido(url):
    from src.egress.gate import EgressGate

    assert EgressGate._url_embeds_data(url) is True


@pytest.mark.parametrize("url", ["https://e.org/artigo", "https://docs.python.org/guia/", "https://e.org/a-b/c"])
def test_b1_url_sem_digitos_passa(url):
    from src.egress.gate import EgressGate

    assert EgressGate._url_embeds_data(url) is False
