"""Regimes sintéticos P, T, N e F: valores, ``Problema``, tarefa neutra e verdade (design §2 e §3).

Valores aprovados pelo pesquisador em 2026-10-19 (``design.md`` §2.3). Depois do piloto só mudam com registro no
relatório. O ``verdade.json`` guarda a resposta correta e **nunca** vai para ``input_context/``, para as saídas da
sessão nem para o ambiente do subprocesso (:func:`preparar_entrada` recusa um diretório de verdade dentro do de
entrada).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from scripts.verdict_lab.controlled import generator
from src.knowledge.problem import ProblemDraft

METRICA = "acurácia"
DELTA_MIN = 0.01
BASELINE = "classificador que prediz a classe majoritária"
POLITICA_OBJETIVO = "continuar"
ASSINATURA_FALHA_F = "MemoryError"

RESPOSTA_FUNCIONA = "funciona"
RESPOSTA_NUNCA_FUNCIONA = "nunca_funciona"


class RegimeError(ValueError):
    """Regime desconhecido ou diretórios de entrada e verdade incompatíveis."""


@dataclass(frozen=True)
class Regime:
    """Um regime sintético.

    Attributes:
        nome: ``P``, ``T``, ``N`` ou ``F``.
        familia: Família do rótulo no gerador (``P``, ``T`` ou ``N``).
        descricao: Frase curta para o relatório.
        teto: Acurácia do preditor de Bayes.
        alvo: Alvo do ``Problema``.
        patamares: Acurácia de quem descobre os ``k`` primeiros termos (``p_0 … p_5``); vazio em N.
        n_linhas: Linhas do ``dados.csv``.
        resposta: ``funciona`` (o alvo é alcançável) ou ``nunca_funciona``.
        abordagem_plantada: ``True`` quando o regime planta uma abordagem que falha (F).
    """

    nome: str
    familia: str
    descricao: str
    teto: float
    alvo: float
    patamares: tuple[float, ...]
    n_linhas: int
    resposta: str
    abordagem_plantada: bool = False


REGIMES: dict[str, Regime] = {
    "P": Regime(
        "P", "P", "efeito plantado: o alvo é alcançável por variações com evolução",
        teto=0.96, alvo=0.93, patamares=(0.62, 0.74, 0.82, 0.88, 0.93, 0.96), n_linhas=2000,
        resposta=RESPOSTA_FUNCIONA,
    ),
    "T": Regime(
        "T", "T", "teto abaixo do alvo: há sinal e evolução, mas o alvo não é alcançável",
        teto=0.90, alvo=0.93, patamares=(0.62, 0.72, 0.79, 0.84, 0.87, 0.90), n_linhas=2000,
        resposta=RESPOSTA_NUNCA_FUNCIONA,
    ),
    "N": Regime(
        "N", "N", "ruído puro: só alcança o alvo por acaso",
        teto=0.50, alvo=0.55, patamares=(), n_linhas=2000, resposta=RESPOSTA_NUNCA_FUNCIONA,
    ),
    "F": Regime(
        "F", "P", "como P, com volume que quebra a abordagem de núcleo denso no sandbox",
        teto=0.96, alvo=0.93, patamares=(0.62, 0.74, 0.82, 0.88, 0.93, 0.96), n_linhas=12000,
        resposta=RESPOSTA_FUNCIONA, abordagem_plantada=True,
    ),
}


def regime(nome: str) -> Regime:
    try:
        return REGIMES[nome]
    except KeyError:
        raise RegimeError(f"Regime desconhecido: {nome!r} (esperado um de {', '.join(REGIMES)}).") from None


def problem_draft(nome: str) -> ProblemDraft:
    """``Problema`` do regime: texto neutro, sem citar técnica, termo do rótulo nem o valor do alvo."""
    r = regime(nome)
    return ProblemDraft(
        titulo="Classificação binária em dados tabulares sintéticos",
        resumo=(
            "Conjunto tabular com oito atributos numéricos e um rótulo binário. O objetivo é montar um procedimento "
            "reprodutível de classificação, comparar abordagens e recomendar uma com justificativa. Um avanço seria "
            "uma acurácia de teste superior à do classificador que prediz a classe majoritária, com avaliação "
            "comparável entre as abordagens."
        ),
        classe="classificacao",
        caracteristicas_dados={"tamanho": f"{r.n_linhas} amostras", "modalidade": "tabular", "classes": "2"},
        dominios=("Aprendizado de Máquina",),
        metrica=METRICA,
        alvo=r.alvo,
        delta_min=DELTA_MIN,
        baseline_descricao=BASELINE,
        tipo="limiar",
        ao_atingir_objetivo=POLITICA_OBJETIVO,
    )


def tarefa(nome: str) -> str:
    """Texto neutro da tarefa (igual em todos os regimes, exceto o tamanho do dado)."""
    r = regime(nome)
    return (
        "Construa e avalie modelos de classificação para o conjunto de dados em input_context/dados.csv "
        f"({r.n_linhas} linhas, atributos x1 a x8 e rótulo y) e recomende o melhor, com justificativa. "
        "Salve os artefatos em disco."
    )


def verdade(nome: str, semente: int, sha256: str) -> dict[str, object]:
    """Conteúdo do ``verdade.json`` (design §3)."""
    r = regime(nome)
    return {
        "versao": 1,
        "regime": r.nome,
        "descricao": r.descricao,
        "semente": semente,
        "n_linhas": r.n_linhas,
        "teto": r.teto,
        "alvo": r.alvo,
        "delta_min": DELTA_MIN,
        "patamares": list(r.patamares),
        "sha256_dados": sha256,
        "resposta_correta": r.resposta,
        "abordagem_plantada": (
            {"descricao": "abordagem de núcleo denso (matriz n×n)", "assinatura_falha": ASSINATURA_FALHA_F}
            if r.abordagem_plantada
            else None
        ),
    }


def _dentro(filho: Path, pai: Path) -> bool:
    filho, pai = filho.resolve(), pai.resolve()
    return filho == pai or pai in filho.parents


def preparar_entrada(nome: str, semente: int, input_dir: Path, verdade_dir: Path) -> dict[str, object]:
    """Grava ``dados.csv`` e ``dados.yaml`` em ``input_dir`` e ``verdade.json`` em ``verdade_dir``.

    Raises:
        RegimeError: Regime desconhecido, ou ``verdade_dir`` igual a ``input_dir`` ou dentro dele (e vice-versa).
    """
    r = regime(nome)
    if _dentro(verdade_dir, input_dir) or _dentro(input_dir, verdade_dir):
        raise RegimeError(
            f"O diretório da verdade ({verdade_dir}) não pode conter nem estar dentro do de entrada ({input_dir}): "
            "os agentes enxergariam a resposta."
        )
    sha = generator.escrever_csv(input_dir / "dados.csv", r.familia, r.n_linhas, semente)
    generator.escrever_manifesto(input_dir / "dados.yaml")
    conteudo = verdade(nome, semente, sha)
    verdade_dir.mkdir(parents=True, exist_ok=True)
    (verdade_dir / "verdade.json").write_text(
        json.dumps(conteudo, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return conteudo
