"""Filtros de egresso (v18.5-egress-gate, spec data-egress; design §3 e §4)."""

import pytest

from src.egress import filters
from src.egress.filters import FilterContext, filter_execution_output, mask_numbers, rounded_range

pytestmark = pytest.mark.unit


INTEGRAL = "outputs/s/t/step_01.stdout.txt"


def _ctx(k: int = 10, max_chars: int = 4000, min_rows: int = 3, identifiers=(), integral=INTEGRAL):
    return FilterContext(
        k=k,
        output_max_chars=max_chars,
        table_min_rows=min_rows,
        known_identifiers=frozenset(identifiers),
        integral_path=integral,
    )


# --- Requisito: tracebacks com marcadores tipados ------------------------------------------------------------

def test_valor_com_virgula_decimal():
    """Cenário "Valor com vírgula decimal"."""
    stderr = (
        "Traceback (most recent call last):\n"
        '  File "/work/step_01.py", line 7, in <module>\n'
        "    float(x)\n"
        "ValueError: could not convert string to float: '12,5'"
    )
    ctx = _ctx()
    out = filter_execution_output(stderr, ctx)
    assert "ValueError: could not convert string to float: <str len=4 padrão=dd,d>" in out
    assert '  File "/work/step_01.py", line 7, in <module>' in out
    assert "12,5" not in out
    assert ctx.interventions[filters.IV_TRACEBACK] >= 1


def test_nome_de_coluna():
    """Cenário "Nome de coluna": literal idêntico a identificador conhecido é mantido."""
    stderr = "Traceback (most recent call last):\n  File \"a.py\", line 2, in <module>\nKeyError: 'temperatura'"
    out = filter_execution_output(stderr, _ctx(identifiers=["temperatura"]))
    assert "KeyError: 'temperatura'" in out
    desconhecido = filter_execution_output(stderr, _ctx())
    assert "'temperatura'" not in desconhecido and "<str len=11 padrão=aaaaaaaaaaa>" in desconhecido


def test_numeros_da_mensagem_de_excecao_viram_marcador():
    out = filter_execution_output("IndexError: index 25 is out of bounds for axis 0 with size 3", _ctx())
    assert "index <num padrão=dd> is out of bounds for axis <num padrão=d> with size <num padrão=d>" in out


def test_string_longa_na_excecao_sem_padrao():
    out = filter_execution_output("ValueError: bad value '" + "x" * 40 + "'", _ctx())
    assert "<str len=40>" in out


# --- Requisito: despejos tabulares retidos ------------------------------------------------------------------

def test_print_df():
    """Cenário "print(df)": rodapé `[120 rows x 4 columns]`."""
    stdout = (
        "          a      b  c\n"
        "0     1.2    3.4  x\n"
        "1     2.2    3.5  y\n"
        "...   ...    ... ..\n"
        "119   9.9    1.1  z\n"
        "\n"
        "[120 rows x 4 columns]"
    )
    out = filter_execution_output(stdout, _ctx())
    assert "[saída tabular retida: 120 linhas × 4 colunas;" in out
    assert "integral em outputs/s/t/step_01.stdout.txt]" in out
    assert "1.2" not in out and "9.9" not in out


def test_repr_de_dataframe_pequeno_sem_rodape_tambem_e_retido():
    out = filter_execution_output("     a    b\n0  1.0  2.0\n1  3.0  4.0", _ctx())
    assert out.startswith("[saída tabular retida: 2 linhas × 2 colunas; colunas: a, b;")


def test_series_repr_retido_e_dtypes_passam():
    assert "retida" in filter_execution_output("0    1.5\n1    2.5\nName: x, dtype: float64", _ctx())
    dtypes = "a    float64\nb      int64\ndtype: object"
    assert filter_execution_output(dtypes, _ctx()) == dtypes  # esquema, não dado


def test_blocos_delimitados_com_min_rows_ou_mais_linhas():
    despejo = "1.0 2.0 3.0\n4.0 5.0 6.0\n7.0 8.0 9.0"
    assert "[saída tabular retida: 3 linhas × 3 colunas;" in filter_execution_output(despejo, _ctx(min_rows=3))
    # Abaixo do mínimo configurado o bloco genérico não é retido.
    assert filter_execution_output(despejo, _ctx(min_rows=4)) == despejo


def test_csv_com_virgula_e_retido():
    out = filter_execution_output("1.5,2.5,3.5\n4.5,5.5,6.5\n7.5,8.5,9.5\n", _ctx())
    assert "[saída tabular retida: 3 linhas × 3 colunas;" in out


def test_lista_numerica_longa_e_retida_e_curta_passa():
    longa = filter_execution_output("[1.2, 3.4, 5.6, 7.8, 9.0]", _ctx())
    assert "[saída tabular retida: 5 linhas × 1 colunas;" in longa
    assert filter_execution_output("[0.5, 0.3]", _ctx()) == "[0.5, 0.3]"


def test_ndarray_aninhado_e_retido():
    out = filter_execution_output("array([[1., 2.],\n       [3., 4.],\n       [5., 6.]])", _ctx())
    assert "[saída tabular retida: 3 linhas × 2 colunas;" in out


# --- Requisito: estatísticas pela regra de k ---------------------------------------------------------------

def test_maximo_nunca_exato():
    """Cenário "Máximo nunca exato"."""
    assert filter_execution_output("max: 12.537", _ctx()) == "max: [10, 20)"


def test_faixas_arredondadas():
    assert rounded_range("12.537") == "[10, 20)"
    assert rounded_range("0.0347") == "[0.03, 0.04)"
    assert rounded_range("-5.2") == "[-6, -5)"
    assert rounded_range("0") == "0"
    assert rounded_range("45%") == "[40%, 50%)"


def test_extremos_em_faixa_em_qualquer_n():
    out = filter_execution_output("n=5000\nmin: 1.5\nmediana = 7.25\nq3: 8.1\np95: 9.9", _ctx())
    assert "min: [1, 2)" in out and "mediana = [7, 8)" in out and "q3: [8, 9)" in out and "p95: [9, 10)" in out


def test_media_abaixo_de_k():
    """Cenário "Média abaixo de k": k > 3, `n=3` e `mean: 4.2` no mesmo bloco."""
    out = filter_execution_output("n=3\nmean: 4.2", _ctx(k=5))
    assert "mean: <estatística retida: n<k>" in out
    assert "4.2" not in out


def test_media_com_n_suficiente_passa():
    assert filter_execution_output("n=50, mean: 4.2, std: 0.3", _ctx(k=10)) == "n=50, mean: 4.2, std: 0.3"


def test_describe():
    """Cenário "describe()": count, mean e std como estão; min, quartis e max como faixas."""
    stdout = (
        "          x      y\n"
        "count  120.0  120.0\n"
        "mean     5.1    2.0\n"
        "std      0.3    0.1\n"
        "min      1.2    0.5\n"
        "25%      3.4    1.0\n"
        "50%      5.0    2.0\n"
        "75%      6.1    3.0\n"
        "max     12.5    4.9"
    )
    ctx = _ctx(k=10)
    out = filter_execution_output(stdout, ctx)
    assert "x: count=120.0, mean=5.1, std=0.3, min=[1, 2), 25%=[3, 4), 50%=[5, 6), 75%=[6, 7), max=[10, 20)" in out
    assert "y: count=120.0, mean=2.0, std=0.1, min=[0.5, 0.6)" in out
    assert "12.5" not in out
    assert ctx.interventions[filters.IV_EXTREMO] == 10


def test_describe_com_count_abaixo_de_k_retem_media_e_desvio():
    stdout = (
        "          x\ncount   4.0\nmean    5.1\nstd     0.3\nmin     1.2\n"
        "25%     3.4\n50%     5.0\n75%     6.1\nmax    12.5"
    )
    out = filter_execution_output(stdout, _ctx(k=10))
    assert "mean=<estatística retida: n<k>" in out and "std=<estatística retida: n<k>" in out


def test_tamanho_de_grupo_nao_reconhecido():
    """Cenário "Tamanho de grupo não reconhecido": a linha passa e a intervenção é registrada."""
    ctx = _ctx()
    assert filter_execution_output("mean: 4.2", ctx) == "mean: 4.2"
    assert ctx.interventions[filters.IV_SEM_N] == 1


# --- Requisito: elisão de saídas longas --------------------------------------------------------------------

def test_log_de_treino():
    """Cenário "Log de treino": início, fim e marcador; total ≤ limite + marcador."""
    linhas = [f"Epoch {i}/500 - loss: 0.{i:04d} - val_loss: 0.9" for i in range(500)]
    ctx = _ctx(max_chars=4000)
    out = filter_execution_output("\n".join(linhas), ctx)
    assert out.startswith(linhas[0]) and out.endswith(linhas[-1])
    marcador = [ln for ln in out.split("\n") if ln.startswith("[... ")]
    assert len(marcador) == 1
    assert "linhas /" in marcador[0]
    assert f"caracteres omitidos; integral em {INTEGRAL} ...]" in marcador[0]
    assert len(out) <= 4000 + len(marcador[0]) + 1
    assert ctx.interventions[filters.IV_ELISAO] == 1


def test_linha_unica_gigante_tambem_e_elidida():
    out = filter_execution_output("x" * 10000, _ctx(max_chars=1000))
    assert "caracteres omitidos" in out and len(out) < 1300


# --- Números literais e artefatos --------------------------------------------------------------------------

def test_numeros_literais_viram_marcadores_tipados():
    out, count = mask_numbers("a média foi 12.4, acc=0.93, 45%, 1.5e-3 e 1,5")
    assert out == (
        "a média foi <num padrão=dd.d>, acc=<num padrão=d.dd>, <num padrão=dd%>, "
        "<num padrão=d.de-d> e <num padrão=d,d>"
    )
    assert count == 5


def test_identificadores_com_digitos_nao_sao_trocados():
    texto = "veja x1, step_02, exec_1234 e v2"
    assert mask_numbers(texto) == (texto, 0)


def test_referencias_sao_preservadas_textualmente():
    out, _ = mask_numbers("{{res:exec_1234/acc}} {{calc:a*2}} {{src:doc_9}} e 0.93")
    assert out == "{{res:exec_1234/acc}} {{calc:a*2}} {{src:doc_9}} e <num padrão=d.dd>"


def test_mascarar_duas_vezes_e_idempotente():
    primeiro, _ = mask_numbers("valor 12.5 e <str len=4 padrão=dd,d>")
    assert mask_numbers(primeiro) == (primeiro, 0)


def test_nome_de_artefato():
    assert filters.sanitize_artifact_name("resultados.csv") == "resultados.csv"
    assert filters.sanitize_artifact_name("curva_12.537.png") == "curva_<num padrão=dd.ddd>.png"
