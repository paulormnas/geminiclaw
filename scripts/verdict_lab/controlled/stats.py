"""Intervalos de 95 % das taxas e resumos de distribuição (design §6.2), só com a biblioteca padrão."""

from __future__ import annotations

import math
from dataclasses import dataclass

Z95 = 1.959964
ALFA = 0.05


@dataclass(frozen=True)
class Taxa:
    """``k`` sucessos em ``n`` com o intervalo de 95 %.

    Attributes:
        k: Sucessos.
        n: Total.
        valor: ``k / n`` (``None`` quando ``n`` é 0).
        baixo: Limite inferior do intervalo.
        alto: Limite superior do intervalo.
        metodo: ``wilson``, ``clopper-pearson`` (``k`` é 0 ou ``n``) ou ``sem_dados``.
    """

    k: int
    n: int
    valor: float | None
    baixo: float | None
    alto: float | None
    metodo: str

    @property
    def rotulo(self) -> str:
        """``k/n`` com a taxa e o intervalo, para o relatório."""
        if self.valor is None:
            return f"{self.k}/{self.n}"
        return f"{self.k}/{self.n} = {self.valor:.3f} [{self.baixo:.3f}; {self.alto:.3f}]"

    def contem(self, valor: float | None) -> bool:
        """``True`` quando ``valor`` está no intervalo (inclusive nas pontas)."""
        if valor is None or self.baixo is None or self.alto is None:
            return False
        return self.baixo - 1e-12 <= valor <= self.alto + 1e-12


def wilson(k: int, n: int) -> tuple[float, float]:
    """Intervalo de Wilson de 95 %."""
    p = k / n
    z2 = Z95 * Z95
    centro = (p + z2 / (2 * n)) / (1 + z2 / n)
    meia = Z95 * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n)) / (1 + z2 / n)
    return max(0.0, centro - meia), min(1.0, centro + meia)


def clopper_pearson_extremo(k: int, n: int) -> tuple[float, float]:
    """Clopper-Pearson de 95 % (bilateral) para ``k`` igual a 0 ou ``n``, em forma fechada."""
    if k == 0:
        return 0.0, 1 - (ALFA / 2) ** (1 / n)
    if k == n:
        return (ALFA / 2) ** (1 / n), 1.0
    raise ValueError(f"Clopper-Pearson em forma fechada só para k=0 ou k=n (k={k}, n={n}).")


def taxa(k: int, n: int) -> Taxa:
    """Taxa com o intervalo: Clopper-Pearson quando ``k`` é 0 ou ``n``, Wilson nos demais casos."""
    if n < 0 or k < 0 or k > n:
        raise ValueError(f"Contagem inválida: k={k}, n={n}.")
    if n == 0:
        return Taxa(k, n, None, None, None, "sem_dados")
    if k in (0, n):
        baixo, alto = clopper_pearson_extremo(k, n)
        return Taxa(k, n, k / n, baixo, alto, "clopper-pearson")
    baixo, alto = wilson(k, n)
    return Taxa(k, n, k / n, baixo, alto, "wilson")


def percentil(valores: list[float], p: float) -> float | None:
    """Percentil ``p`` (0 a 1) por interpolação linear; ``None`` sem valores."""
    if not valores:
        return None
    ordenados = sorted(valores)
    posicao = (len(ordenados) - 1) * p
    baixo, alto = int(posicao), min(int(posicao) + 1, len(ordenados) - 1)
    return ordenados[baixo] + (ordenados[alto] - ordenados[baixo]) * (posicao - baixo)


def resumo(valores: list[float]) -> dict[str, float | int | None]:
    """Mediana, p10 e p90 (``None`` sem valores) e a contagem."""
    return {"n": len(valores), "mediana": percentil(valores, 0.5), "p10": percentil(valores, 0.1),
            "p90": percentil(valores, 0.9)}
