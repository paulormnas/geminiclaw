"""Sintaxe das referências, avaliador ``calc`` e validação de nomes (spec numeric-provenance)."""

from __future__ import annotations

import inspect
import json

import pytest

from src.numeric_refs import calc as calc_module
from src.numeric_refs.calc import CalcError, Quantity, evaluate, parse_expression
from src.numeric_refs.syntax import CalcExpr, ResTarget, SrcTarget, find_malformed, find_references
from src.numeric_refs.units import unit_from_text

pytestmark = pytest.mark.unit

E1 = "exec_12345678-1234-4123-8123-123456789abc"
E2 = "exec_87654321-4321-4abc-8abc-cba987654321"


# --- sintaxe -------------------------------------------------------------------------------------------------------

def test_referencias_validas():
    """Scenario: Referências válidas."""
    text = (
        f"A {{{{res:{E1}/rmse}}}}, B {{{{calc:res:{E1}/a / res:{E2}/b}}}} e "
        "C {{src:https://exemplo.org/p#RMSE de 0,42 mm}}."
    )
    refs = find_references(text)
    assert [r.kind for r in refs] == ["res", "calc", "src"]
    assert refs[0].payload == ResTarget(E1, "rmse")
    assert isinstance(refs[1].payload, CalcExpr) and refs[1].payload.expressao == f"res:{E1}/a / res:{E2}/b"
    assert refs[2].payload == SrcTarget("https://exemplo.org/p", "RMSE de 0,42 mm") and refs[2].payload.is_url
    assert text[refs[0].span[0] : refs[0].span[1]] == refs[0].raw
    assert find_malformed(text) == []


def test_referencia_malformada_tem_posicao():
    """Scenario: Referência malformada."""
    text = "texto {{res:exec_123/rmse}} fim"
    (issue,) = find_malformed(text)
    assert issue.posicao == text.index("{{res:") and "exec_123" in issue.trecho
    assert find_references(text) == []


def test_nao_fechada_e_forma_incompleta():
    assert find_malformed("{{calc:1 + res:x") and find_malformed("{{src:semtrecho}}")
    assert find_malformed("{{outro:x}}") == []


def test_parametro_e_nome_com_ponto():
    (ref,) = find_references(f"{{{{res:{E1}/param.learning-rate}}}}")
    assert ref.payload.is_param and ref.payload.nome == "param.learning-rate"


def test_chave_de_identidade_ignora_espacos_do_calc():
    a, b = find_references("{{calc:1  +  res:%s/a}} {{calc:1 + res:%s/a}}" % (E1, E1))
    assert a.key == b.key


def test_nome_de_metrica_invalido_na_gravacao(tmp_path):
    """Scenario: Nome de métrica inválido na gravação."""
    from src.skills.code.scientific_helpers import save_experiment_artifacts

    with pytest.raises(ValueError, match=r"\[A-Za-z_\]\[A-Za-z0-9_\.-\]\*") as info:
        save_experiment_artifacts("t", {}, {"acurácia final": 0.9}, output_dir=str(tmp_path))
    assert "acurácia final" in str(info.value) and not (tmp_path / "metrics.json").exists()


def test_unidades_sao_gravadas_e_validadas(tmp_path):
    from src.skills.code.scientific_helpers import save_experiment_artifacts

    save_experiment_artifacts("t", {}, {"rmse": 0.4498}, output_dir=str(tmp_path), unidades={"rmse": "mm"})
    assert json.loads((tmp_path / "metrics.json").read_text())["unidades"] == {"rmse": "mm"}
    with pytest.raises(ValueError, match="unidades"):
        save_experiment_artifacts("t", {}, {"rmse": 0.4}, output_dir=str(tmp_path), unidades={"outra": "mm"})


# --- calc ----------------------------------------------------------------------------------------------------------

def _eval(expression: str, **values: Quantity):
    parsed = parse_expression(expression)
    return evaluate(parsed, {f"_o{i}": v for i, v in enumerate(values.values())})


def test_divergencia_percentual():
    """Scenario: Divergência percentual — 0,45 mm contra 0,42 mm dá 7,1 %."""
    expr = f'round(pct((res:{E1}/rmse - src:ins#"RMSE de 0,42 mm") / src:ins#"RMSE de 0,42 mm"), 1)'
    parsed = parse_expression(expr)
    assert [o.kind for o in parsed.operandos] == ["res", "src", "src"]
    mm = unit_from_text("mm")
    result = evaluate(parsed, {"_o0": Quantity(0.45, mm), "_o1": Quantity(0.42, mm), "_o2": Quantity(0.42, mm)})
    assert result.valor == pytest.approx(7.1) and result.unidade == "%" and result.decimais == 1


@pytest.mark.parametrize(
    "expression",
    [
        f"__import__('os').system('x') + res:{E1}/a",
        f"(res:{E1}/a).real",
        f"[1, 2][0] + res:{E1}/a",
        f"(lambda: 1)() + res:{E1}/a",
        f"[x for x in range(3)] and res:{E1}/a",
        f"res:{E1}/a if True else 1",
        f"res:{E1}/a % 2",
        f"res:{E1}/a // 2",
        f"open('x') + res:{E1}/a",
        f"'texto' + res:{E1}/a",
        f"True + res:{E1}/a",
    ],
)
def test_nos_nao_permitidos(expression):
    """Scenario: Nó não permitido."""
    parsed = None
    with pytest.raises(CalcError) as info:
        parsed = parse_expression(expression)
        evaluate(parsed, {"_o0": Quantity(1.0, None)})
    assert info.value.codigo in (calc_module.ERR_NODE, calc_module.ERR_SYNTAX)


def test_literal_disfarcado_de_calculo():
    """Scenario: Literal disfarçado de cálculo."""
    with pytest.raises(CalcError) as info:
        parse_expression("0.95")
    assert info.value.codigo == calc_module.ERR_NO_REF


def test_operando_malformado_e_identificador_reservado():
    with pytest.raises(CalcError):
        parse_expression("res:exec_1/a + 1")
    with pytest.raises(CalcError):
        parse_expression(f"_o0 + res:{E1}/a")


def test_unidades_incompativeis_e_divisao_por_zero():
    """Scenario: Unidades incompatíveis e divisão por zero."""
    expr = f"res:{E1}/a + res:{E2}/b"
    with pytest.raises(CalcError) as info:
        _eval(expr, a=Quantity(1.0, unit_from_text("mm")), b=Quantity(2.0, unit_from_text("s")))
    assert info.value.codigo == calc_module.ERR_UNITS
    with pytest.raises(CalcError) as info:
        _eval(f"res:{E1}/a / res:{E2}/b", a=Quantity(1.0, None), b=Quantity(0.0, None))
    assert info.value.codigo == calc_module.ERR_MATH


def test_algebra_de_unidades():
    mm, s = unit_from_text("mm"), unit_from_text("s")
    assert _eval(f"res:{E1}/a / res:{E2}/b", a=Quantity(6.0, mm), b=Quantity(2.0, s)).unidade == "mm/s"
    assert _eval(f"res:{E1}/a / res:{E2}/b", a=Quantity(6.0, mm), b=Quantity(2.0, mm)).unidade == ""
    assert _eval(f"res:{E1}/a * 2", a=Quantity(3.0, mm)).unidade == "mm"
    assert _eval(f"sqrt(res:{E1}/a * res:{E2}/b)", a=Quantity(4.0, mm), b=Quantity(9.0, mm)).unidade == "mm"
    assert _eval(f"res:{E1}/a + res:{E2}/b", a=Quantity(1.0, None), b=Quantity(2.0, None)).unidade is None


@pytest.mark.parametrize(
    "expression, values, expected",
    [
        ("abs(res:%s/a)", [-3.0], 3.0),
        ("min(res:%s/a, 2)", [5.0], 2.0),
        ("max(res:%s/a, 2)", [5.0], 5.0),
        ("media(res:%s/a, 4)", [2.0], 3.0),
        ("sqrt(res:%s/a)", [16.0], 4.0),
        ("res:%s/a ** 2", [3.0], 9.0),
        ("-res:%s/a + 1", [3.0], -2.0),
        ("round(res:%s/a, 2)", [2.345], 2.35),
        ("pct(res:%s/a)", [0.25], 25.0),
    ],
)
def test_funcoes_e_operadores(expression, values, expected):
    result = _eval(expression % E1, a=Quantity(values[0], {}))
    assert result.valor == pytest.approx(expected)


def test_limites_de_tamanho_nos_e_expoente():
    with pytest.raises(CalcError) as info:
        parse_expression("res:%s/a + " % E1 + " + ".join(["1"] * 200))
    assert info.value.codigo == calc_module.ERR_LIMIT
    with pytest.raises(CalcError) as info:
        _eval(f"res:{E1}/a ** 9", a=Quantity(2.0, {}))
    assert info.value.codigo == calc_module.ERR_LIMIT
    with pytest.raises(CalcError):
        _eval(f"res:{E1}/a ** res:{E2}/b", a=Quantity(2.0, {}), b=Quantity(2.0, {}))
    with pytest.raises(CalcError):
        _eval(f"sqrt(res:{E1}/a)", a=Quantity(-1.0, {}))
    with pytest.raises(CalcError) as info:
        parse_expression("abs(" * 20 + f"res:{E1}/a" + ")" * 20)
    assert info.value.codigo == calc_module.ERR_LIMIT


def test_round_exige_inteiro_constante():
    with pytest.raises(CalcError):
        _eval(f"round(res:{E1}/a, 11)", a=Quantity(1.2, {}))
    with pytest.raises(CalcError):
        _eval(f"round(res:{E1}/a, 1.5)", a=Quantity(1.2, {}))


def test_modulo_nao_usa_eval_nem_exec():
    """Tarefa 6.3: o avaliador não usa ``eval``, ``exec`` nem ``compile``."""
    import ast

    tree = ast.parse(inspect.getsource(calc_module))
    called = {n.func.id for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert not called & {"eval", "exec", "compile", "__import__"}
    imported = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    assert "numexpr" not in imported
