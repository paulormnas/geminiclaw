"""Corpus de saídas reais de execução com o resultado esperado do filtro (tarefa 7.4, v18.5-egress-gate).

Cada caso traz a saída como o interpretador a produz (tracebacks do pandas e do scikit-learn, `print(df)`,
`describe()`, `info()`, logs de treino, relatórios de classificação) e o que o modelo sem dados brutos deve (e não deve)
receber. Os limites heurísticos conhecidos (ADR 019 §3) estão marcados.
"""

import pytest

from src.egress import filters
from src.egress.filters import FilterContext, filter_execution_output

pytestmark = pytest.mark.unit

PATH = "outputs/s/t/step_02.stdout.txt"
IDENTIFICADORES = frozenset({"temperatura", "umidade", "medicoes.csv"})


def _filtrar(texto: str, k: int = 10) -> tuple[str, FilterContext]:
    ctx = FilterContext(k=k, output_max_chars=4000, table_min_rows=3, known_identifiers=IDENTIFICADORES,
                        integral_path=PATH)
    return filter_execution_output(texto, ctx), ctx


TRACEBACK_PANDAS_KEYERROR = """\
Traceback (most recent call last):
  File "/work/step_02.py", line 5, in <module>
    serie = df['pressao_atm']
  File "/usr/lib/python3.11/site-packages/pandas/core/frame.py", line 3893, in __getitem__
    indexer = self.columns.get_loc(key)
  File "/usr/lib/python3.11/site-packages/pandas/core/indexes/base.py", line 3798, in get_loc
    raise KeyError(key) from err
KeyError: 'pressao_atm'
"""

TRACEBACK_VALUEERROR_VIRGULA = """\
Traceback (most recent call last):
  File "/work/step_02.py", line 9, in <module>
    df['temperatura'] = df['temperatura'].astype(float)
ValueError: could not convert string to float: '23,7'
"""

TRACEBACK_INDEXERROR = "IndexError: index 7 is out of bounds for axis 0 with size 5\n"

PRINT_DF = """\
   temperatura  umidade  lote
0         23.7     41.2     1
1         24.1     40.8     1
2         23.9     41.0     2
3         24.4     39.9     2
4         24.0     40.5     3
"""

PRINT_DF_TRUNCADO = """\
     temperatura  umidade  lote
0           23.7     41.2     1
1           24.1     40.8     1
..           ...      ...   ...
998         24.2     40.1    50
999         23.8     41.5    50

[1000 rows x 3 columns]
"""

DESCRIBE = """\
       temperatura     umidade
count   1000.000000  1000.000000
mean      24.012345    40.501234
std        0.502112     0.800456
min       22.100000    37.900000
25%       23.700000    40.000000
50%       24.000000    40.500000
75%       24.300000    41.000000
max       25.900000    43.100000
"""

INFO = """\
<class 'pandas.core.frame.DataFrame'>
RangeIndex: 1000 entries, 0 to 999
Data columns (total 3 columns):
 #   Column       Non-Null Count  Dtype
---  ------       --------------  -----
 0   temperatura  1000 non-null   float64
 1   umidade      1000 non-null   float64
 2   lote         1000 non-null   int64
dtypes: float64(2), int64(1)
memory usage: 23.6 KB
"""

LOG_TREINO = "\n".join(
    f"Epoch {i}/300 - loss: {1 / (i + 1):.4f} - val_loss: {1.1 / (i + 1):.4f} - lr: 0.001" for i in range(1, 301)
)

CLASSIFICATION_REPORT = """\
              precision    recall  f1-score   support

           0       0.91      0.89      0.90       120
           1       0.88      0.90      0.89       110
           2       0.93      0.92      0.92       130

    accuracy                           0.91       360
"""

SHAPE_E_DTYPES = "(1000, 3)\ntemperatura    float64\numidade        float64\nlote            int64\ndtype: object\n"

ESTATISTICAS_COM_N = "n=250\nmedia: 24.01\ndesvio = 0.5\nmin: 22.1\nmax: 25.9\nmediana: 24.0\n"
ESTATISTICAS_N_PEQUENO = "n=4\nmedia: 24.01\ndesvio = 0.5\nmax: 25.9\n"


def test_keyerror_do_pandas_mantem_arquivo_linha_e_coluna_conhecida_ou_marca_a_desconhecida():
    saida, ctx = _filtrar(TRACEBACK_PANDAS_KEYERROR)
    assert 'File "/work/step_02.py", line 5, in <module>' in saida
    assert "KeyError: <str len=11 padrão=aaaaaaa_aaa>" in saida  # 'pressao_atm' não é identificador conhecido
    assert ctx.interventions[filters.IV_TRACEBACK] >= 1


def test_valueerror_com_virgula_decimal_nao_vaza_o_valor():
    saida, _ = _filtrar(TRACEBACK_VALUEERROR_VIRGULA)
    assert "ValueError: could not convert string to float: <str len=4 padrão=dd,d>" in saida
    assert "23,7" not in saida
    assert "df['temperatura'] = df['temperatura'].astype(float)" in saida  # a linha de código ecoada é código


def test_indexerror_troca_os_numeros_da_mensagem():
    saida, _ = _filtrar(TRACEBACK_INDEXERROR)
    esperado = "IndexError: index <num padrão=d> is out of bounds for axis <num padrão=d> with size <num padrão=d>"
    assert saida.strip() == esperado


def test_print_df_pequeno_sem_rodape_e_retido():
    saida, ctx = _filtrar(PRINT_DF)
    assert "[saída tabular retida: 5 linhas × 3 colunas; colunas: temperatura, umidade, lote;" in saida
    assert "23.7" not in saida and "24.4" not in saida
    assert ctx.interventions[filters.IV_TABELA] == 1


def test_print_df_truncado_com_rodape_e_retido():
    saida, _ = _filtrar(PRINT_DF_TRUNCADO)
    assert "[saída tabular retida: 1000 linhas × 3 colunas;" in saida and "23.7" not in saida


def test_describe_vira_linhas_por_coluna_com_faixas():
    saida, ctx = _filtrar(DESCRIBE)
    assert "temperatura: count=1000.000000, mean=24.012345, std=0.502112, min=[20, 30)" in saida
    assert "umidade: count=1000.000000, mean=40.501234, std=0.800456, min=[30, 40)" in saida
    assert "max=[20, 30)" in saida and "25.900000" not in saida and "43.100000" not in saida
    assert ctx.interventions[filters.IV_EXTREMO] == 10


def test_info_do_dataframe_e_esquema_e_passa():
    saida, _ = _filtrar(INFO)
    assert saida == INFO.rstrip("\n") or saida == INFO  # contagens de linhas e tipos são esquema


def test_log_de_treino_e_elidido_preservando_inicio_e_fim():
    saida, ctx = _filtrar(LOG_TREINO)
    linhas = LOG_TREINO.split("\n")
    assert saida.startswith(linhas[0]) and saida.endswith(linhas[-1])
    assert "caracteres omitidos; integral em outputs/s/t/step_02.stdout.txt" in saida
    assert ctx.interventions[filters.IV_ELISAO] == 1


def test_classification_report_e_retido_limite_conhecido():
    """Limite heurístico declarado (design §14): métricas por classe lembram uma tabela e são retidas."""
    saida, _ = _filtrar(CLASSIFICATION_REPORT)
    assert "saída tabular retida" in saida


def test_shape_e_dtypes_passam():
    saida, _ = _filtrar(SHAPE_E_DTYPES)
    assert saida.strip() == SHAPE_E_DTYPES.strip()


def test_estatisticas_impressas_com_n_suficiente():
    saida, _ = _filtrar(ESTATISTICAS_COM_N)
    assert "media: 24.01" in saida and "desvio = 0.5" in saida
    assert "min: [20, 30)" in saida and "max: [20, 30)" in saida and "mediana: [20, 30)" in saida


def test_estatisticas_com_n_abaixo_de_k():
    saida, _ = _filtrar(ESTATISTICAS_N_PEQUENO)
    assert "media: <estatística retida: n<k>" in saida and "desvio = <estatística retida: n<k>" in saida
    assert "max: [20, 30)" in saida


def test_k_vem_da_configuracao_da_sessao():
    com_k_baixo, _ = _filtrar(ESTATISTICAS_N_PEQUENO, k=3)
    assert "media: 24.01" in com_k_baixo  # n=4 >= k=3


@pytest.mark.parametrize(
    "texto",
    [TRACEBACK_PANDAS_KEYERROR, TRACEBACK_VALUEERROR_VIRGULA, PRINT_DF, DESCRIBE, ESTATISTICAS_COM_N],
)
def test_o_filtro_e_idempotente(texto):
    """Refiltrar a própria saída não muda nada (a elisão por tamanho fica de fora: ela corta de novo)."""
    uma_vez, _ = _filtrar(texto)
    duas_vezes, _ = _filtrar(uma_vez)
    assert duas_vezes == uma_vez
