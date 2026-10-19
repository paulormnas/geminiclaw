"""Gerador determinístico de dados sintéticos de classificação binária (design §2.1).

Só biblioteca padrão: ``random.Random`` com semente textual, ``math`` e ``csv``. Mesmo regime e mesma semente dão o
mesmo ``dados.csv`` byte a byte **na mesma versão do Python e da plataforma** (o manifesto da rodada registra as duas).

O rótulo dos regimes P, T e F vem de ``s = Σ a_k · t_k(x)`` com seis termos de força decrescente em ``(t0 linear, t1
interação, t2 quadrático, t3 interação, t4 não polinomial, t5 interação)`` e ``y = 1`` com probabilidade ``Φ(s)`` (ruído
logístico-normal de desvio 1, que as forças já incorporam). Os ``a_k`` foram calibrados no oráculo (400 000 linhas,
semente 12345) para que o preditor de Bayes e os preditores dos ``k`` primeiros termos tenham as acurácias de
:mod:`scripts.verdict_lab.controlled.regimes`.
"""

from __future__ import annotations

import csv
import hashlib
import math
import random
from collections.abc import Iterator, Sequence
from pathlib import Path

N_ATRIBUTOS = 8
COLUNAS = tuple(f"x{i}" for i in range(1, N_ATRIBUTOS + 1)) + ("y",)
MOTIVO_COMPARTILHAVEL = "dado sintético gerado para calibração"

# Normalizações para variância 1 (``x² − 1`` tem variância 2; ``sin(2x)`` tem 0,5·(1 − e⁻⁸)).
_SQRT2 = math.sqrt(2.0)
_SIN_STD = math.sqrt(0.5 * (1.0 - math.exp(-8.0)))

# Forças ``a_0 … a_5`` por família de rótulo (design §2.1), calibradas no oráculo.
COEFICIENTES: dict[str, tuple[float, ...]] = {
    "P": (2.9329, 6.0232, 4.5518, 3.7661, 2.1565, 1.8275),
    "T": (1.2116, 2.1370, 1.6971, 1.4326, 0.8522, 0.9963),
}


def termos(x: Sequence[float]) -> tuple[float, ...]:
    """Os seis termos ``t_0 … t_5`` (variância 1) de uma linha ``x`` de oito atributos."""
    return (
        0.6 * x[6] + 0.8 * x[7],
        x[0] * x[1],
        (x[2] * x[2] - 1.0) / _SQRT2,
        x[3] * x[4],
        math.sin(2.0 * x[5]) / _SIN_STD,
        x[6] * x[7],
    )


def phi(z: float) -> float:
    """Função de distribuição da normal padrão."""
    return 0.5 * (1.0 + math.erf(z / _SQRT2))


def _soma(coef: Sequence[float], t: Sequence[float], k: int) -> float:
    return sum(coef[j] * t[j] for j in range(k + 1))


def semente_de(familia: str, semente: int) -> random.Random:
    """Gerador de números aleatórios da família e da semente (texto: independe de ``PYTHONHASHSEED``)."""
    return random.Random(f"verdict-lab-controlled:{familia}:{semente}")


def linhas(familia: str, n: int, semente: int) -> Iterator[tuple[tuple[float, ...], int]]:
    """``n`` linhas ``(atributos, rótulo)`` da família ``P``/``T`` (com sinal) ou ``N`` (ruído puro)."""
    if familia not in ("P", "T", "N"):
        raise ValueError(f"Família de rótulo desconhecida: {familia!r} (esperado P, T ou N).")
    rng = semente_de(familia, semente)
    coef = COEFICIENTES.get(familia)
    for _ in range(n):
        x = tuple(rng.gauss(0.0, 1.0) for _ in range(N_ATRIBUTOS))
        if coef is None:
            y = 1 if rng.random() < 0.5 else 0
        else:
            y = 1 if rng.random() < phi(_soma(coef, termos(x), len(coef) - 1)) else 0
        yield x, y


def escrever_csv(destino: Path, familia: str, n: int, semente: int) -> str:
    """Grava ``destino`` (``dados.csv``) e devolve o ``sha256``. Cabeçalho ``x1 … x8,y``; ``\\n`` como fim de linha."""
    destino.parent.mkdir(parents=True, exist_ok=True)
    with destino.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(COLUNAS)
        for x, y in linhas(familia, n, semente):
            writer.writerow([f"{v:.6f}" for v in x] + [y])
    return sha256_arquivo(destino)


def sha256_arquivo(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for bloco in iter(lambda: handle.read(1 << 20), b""):
            digest.update(bloco)
    return digest.hexdigest()


def escrever_manifesto(destino: Path, caminho_dado: str = "dados.csv") -> None:
    """Grava ``dados.yaml`` marcando o dado como ``compartilhavel`` (o Developer precisa enxergá-lo)."""
    destino.write_text(
        "versao: 1\n"
        "arquivos:\n"
        f"  - caminho: {caminho_dado}\n"
        "    marcacao: compartilhavel\n"
        f"    motivo: {MOTIVO_COMPARTILHAVEL}\n",
        encoding="utf-8",
    )


def sementes_das_repeticoes(semente_base: int, repeticoes: int) -> list[int]:
    """Semente do dado de cada repetição a partir de uma semente única (combinações recebem as mesmas)."""
    if repeticoes < 0:
        raise ValueError("repeticoes deve ser >= 0.")
    rng = random.Random(f"verdict-lab-controlled-sementes:{semente_base}")
    return [rng.randrange(1, 2**31) for _ in range(repeticoes)]


def oraculo(familia: str, *, n: int = 200_000, semente: int = 12345) -> dict[str, object]:
    """Acurácias do oráculo, por esperança sobre ``n`` linhas (sem sortear o rótulo; baixa variância).

    Returns:
        ``{"teto": acurácia do preditor de Bayes, "patamares": [p_0 … p_5]}`` em que ``p_k`` é a acurácia do preditor
        ``sinal(Σ_{j≤k} a_j t_j)``; para ``N``, ``teto`` 0,5 e ``patamares`` vazio.
    """
    if familia == "N":
        return {"teto": 0.5, "patamares": []}
    coef = COEFICIENTES.get(familia)
    if coef is None:
        raise ValueError(f"Família de rótulo desconhecida: {familia!r}.")
    rng = semente_de(f"oraculo-{familia}", semente)
    k_max = len(coef)
    somas = [0.0] * k_max
    for _ in range(n):
        x = [rng.gauss(0.0, 1.0) for _ in range(N_ATRIBUTOS)]
        t = termos(x)
        prob = phi(_soma(coef, t, k_max - 1))
        acumulado = 0.0
        for k in range(k_max):
            acumulado += coef[k] * t[k]
            somas[k] += prob if acumulado > 0 else 1.0 - prob
    patamares = [s / n for s in somas]
    return {"teto": patamares[-1], "patamares": patamares}
