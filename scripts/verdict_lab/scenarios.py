"""Catálogo determinístico de cenários de evidência (design §4 de ``v18.8-verdict-lab``).

Cada cenário declara o desfecho esperado (``funciona``, ``nao_funciona`` ou ``indeciso``) pelas regras do
pesquisador de 2026-10-18: três variações com resultado positivo, cada uma melhor que a anterior, bastam para
``funciona``; variações que não indicam evolução ficam ``indeciso``. Os valores são do catálogo, não do caso de
pesquisa da dissertação.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from src.knowledge.verdict import Attempt, Criterion

FUNCIONA, NAO_FUNCIONA, INDECISO = "funciona", "nao_funciona", "indeciso"
ESPERADOS = (FUNCIONA, NAO_FUNCIONA, INDECISO)

ALVO = 0.95
DELTA = 0.01
BASELINE = 0.333
ABSOLUTO = Criterion(sentido="maior_melhor", delta_min=DELTA, alvo=ALVO)
ERRO = Criterion(sentido="menor_melhor", delta_min=DELTA, alvo=0.10)


@dataclass(frozen=True)
class Scenario:
    """Um cenário: tentativas, critério e desfecho esperado com justificativa."""

    nome: str
    familia: str
    descricao: str
    esperado: str
    justificativa: str
    criterion: Criterion
    attempts: tuple[Attempt, ...]
    sem_baseline: bool = True


@dataclass
class _Builder:
    """Monta tentativas em ordem cronológica, com semente própria por tentativa."""

    attempts: list[Attempt] = field(default_factory=list)

    def _base(self, config: str, node: str, session: str, seed: int | None, dataset: str) -> dict:
        n = len(self.attempts)
        return {
            "attempt_id": f"t{n + 1:03d}",
            "timestamp": f"2026-01-01T{n // 60:02d}:{n % 60:02d}:00+00:00",
            "node_id": node,
            "session_id": session,
            "seed": n + 1 if seed is None else seed,
            "dataset_ids": (dataset,),
            "config_hash": config,
        }

    def result(
        self,
        value: float,
        config: str,
        *,
        node: str = "n1",
        session: str = "s1",
        seed: int | None = None,
        dataset: str = "d1",
        baseline: float | None = None,
        validation: str = "validado",
        contract: bool = True,
    ) -> _Builder:
        self.attempts.append(
            Attempt(
                outcome_kind="resultado",
                value=value,
                baseline=baseline,
                validation=validation,
                contract_complete=contract,
                **self._base(config, node, session, seed, dataset),
            )
        )
        return self

    def failure(
        self,
        cause: str,
        config: str = "sem_config",
        *,
        signature: str | None = None,
        node: str = "n1",
        session: str = "s1",
        seed: int | None = None,
    ) -> _Builder:
        self.attempts.append(
            Attempt(
                outcome_kind="falha",
                failure_cause=cause,
                failure_signature=signature,
                **self._base(config, node, session, seed, "d1"),
            )
        )
        return self

    def variations(self, values: list[float], *, prefix: str = "c", start: int = 1, **kw) -> _Builder:
        for i, value in enumerate(values):
            self.result(value, f"{prefix}{start + i}", **kw)
        return self

    def done(self) -> tuple[Attempt, ...]:
        return tuple(self.attempts)


def _s(nome, familia, descricao, esperado, justificativa, builder, criterion=ABSOLUTO, sem_baseline=True):
    return Scenario(nome, familia, descricao, esperado, justificativa, criterion, builder.done(), sem_baseline)


def _b() -> _Builder:
    return _Builder()


def _increasing(n: int, start: float = 0.955, step: float = 0.005) -> list[float]:
    return [round(start + i * step, 6) for i in range(n)]


def catalog() -> list[Scenario]:
    """Os cenários do catálogo, em ordem de família."""
    out: list[Scenario] = []
    evolucao = "variações positivas com evolução"

    # E: exploração em um nó
    for n in (1, 2):
        out.append(
            _s(
                f"E{n}",
                "E",
                f"{n} variação(ões) acima do alvo, crescentes",
                INDECISO,
                f"menos de três {evolucao}",
                _b().variations(_increasing(n)),
            )
        )
    for n in (3, 5, 8):
        out.append(
            _s(
                f"E{n}",
                "E",
                f"{n} variações acima do alvo, crescentes",
                FUNCIONA,
                f"pelo menos três {evolucao}",
                _b().variations(_increasing(n, step=0.004)),
            )
        )
    out.append(
        _s(
            "E3-b",
            "E",
            "E3 com baseline 0,333",
            FUNCIONA,
            f"três {evolucao}",
            _b().variations([0.96, 0.97, 0.98], baseline=BASELINE),
            sem_baseline=False,
        )
    )

    # V: volume sem ganho
    for n in (3, 8, 20):
        out.append(
            _s(
                f"V{n}",
                "V",
                f"{n} variações com o mesmo valor (0,951)",
                INDECISO,
                "variações sem evolução",
                _b().variations([0.951] * n),
            )
        )
    out.append(
        _s(
            "V8-decrescente",
            "V",
            "8 variações acima do alvo, cada uma pior que a anterior",
            INDECISO,
            "sem evolução depois da primeira",
            _b().variations(_increasing(8, start=0.99, step=-0.004)),
        )
    )

    # R: réplica da mesma configuração entre nós
    for n, esperado in ((2, INDECISO), (3, FUNCIONA), (5, FUNCIONA)):
        b = _b()
        for k in range(n):
            b.result(0.96, "c1", node=f"n{k + 1}", session=f"s{k + 1}")
        out.append(
            _s(
                f"R{n}",
                "R",
                f"a mesma configuração (0,96) em {n} nós",
                esperado,
                "replicação independente em três ou mais nós confirma" if n >= 3 else "uma réplica só",
                b,
            )
        )

    # S: sementes e sessões
    for n in (3, 10):
        out.append(
            _s(
                f"S{n}",
                "S",
                f"a mesma configuração com {n} sementes na mesma sessão",
                INDECISO,
                "repetir sementes não explora nem replica em outro nó",
                _same_config(n, sessions=False),
            )
        )
    out.append(
        _s(
            "S3-sessoes",
            "S",
            "a mesma configuração em 3 sessões do mesmo nó",
            INDECISO,
            "mesmo nó e mesmos dados",
            _same_config(3, sessions=True),
        )
    )

    # N: refutação em um nó
    out.append(
        _s(
            "N1",
            "N",
            "1 variação abaixo do alvo (0,90)",
            INDECISO,
            "uma evidência negativa só",
            _b().variations([0.90]),
        )
    )
    out.append(
        _s(
            "N3",
            "N",
            "3 variações abaixo do alvo",
            NAO_FUNCIONA,
            "três variações sem alcançar o alvo",
            _b().variations([0.90, 0.91, 0.92]),
        )
    )
    out.append(
        _s(
            "N5",
            "N",
            "5 variações abaixo do alvo",
            NAO_FUNCIONA,
            "cinco variações sem alcançar o alvo",
            _b().variations([0.90, 0.91, 0.92, 0.915, 0.93]),
        )
    )
    b = _b()
    for k in range(2):
        b.failure("abordagem", "c1", signature="MemoryError", seed=100 + k)
    out.append(
        _s(
            "N-abordagem-2",
            "N",
            "falha de abordagem reproduzida 2 vezes",
            INDECISO,
            "reprodução mínima de uma falha",
            b,
        )
    )
    b = _b()
    for k in range(4):
        b.failure("abordagem", f"c{k + 1}", signature="MemoryError", seed=100 + k)
    out.append(
        _s(
            "N-abordagem-4",
            "N",
            "a mesma falha de abordagem em 4 configurações",
            NAO_FUNCIONA,
            "a abordagem não funciona nestas condições",
            b,
        )
    )

    # F: falhas
    out.append(
        _s(
            "F1-E3",
            "F",
            "1 falha ambígua e E3",
            FUNCIONA,
            f"três {evolucao}",
            _b().failure("ambigua").variations([0.96, 0.97, 0.98]),
        )
    )
    out.append(
        _s(
            "F3-E3",
            "F",
            "3 falhas ambíguas e E3",
            FUNCIONA,
            f"três {evolucao}",
            _b().failure("ambigua").failure("ambigua").failure("ambigua").variations([0.96, 0.97, 0.98]),
        )
    )
    b = _b()
    for _ in range(7):
        b.failure("ambigua")
    b.result(0.9667, "c1")
    out.append(
        _s(
            "F7-1",
            "F",
            "7 falhas ambíguas e 1 positiva sem baseline (etapa 1, hipótese …459203)",
            INDECISO,
            "uma evidência positiva só",
            b,
        )
    )
    b = _b()
    for _ in range(5):
        b.failure("infraestrutura")
    out.append(
        _s(
            "F-infra-E3",
            "F",
            "5 falhas de infraestrutura e E3",
            FUNCIONA,
            "infraestrutura não informa sobre a hipótese",
            b.variations([0.96, 0.97, 0.98]),
        )
    )

    # M: mistos
    out.append(
        _s(
            "M11",
            "M",
            "1 positiva (0,96) e 1 negativa (0,94)",
            INDECISO,
            "evidências em conflito",
            _b().variations([0.96, 0.94]),
        )
    )
    out.append(
        _s(
            "M21",
            "M",
            "2 positivas crescentes e 1 negativa",
            INDECISO,
            "evidências em conflito",
            _b().variations([0.96, 0.97, 0.93]),
        )
    )
    out.append(
        _s(
            "M33",
            "M",
            "3 positivas e 3 negativas alternadas",
            INDECISO,
            "evidências em conflito",
            _b().variations([0.96, 0.94, 0.97, 0.93, 0.98, 0.92]),
        )
    )

    # B: sem baseline, com folga pequena ou grande sobre o alvo
    out.append(
        _s(
            "B-folga-0,001",
            "B",
            "E3 com folga de 0,001 a 0,003 sobre o alvo",
            FUNCIONA,
            f"três {evolucao} (qualquer melhora conta)",
            _b().variations([0.951, 0.952, 0.953]),
        )
    )
    out.append(
        _s(
            "B-folga-0,05",
            "B",
            "E3 com folga de 0,03 a 0,05 sobre o alvo",
            FUNCIONA,
            f"três {evolucao}",
            _b().variations([0.98, 0.99, 1.0]),
        )
    )

    # C: critério com baseline e alvo
    out.append(
        _s(
            "C3-abaixo-do-alvo",
            "C",
            "3 variações crescentes acima do baseline e abaixo do alvo",
            NAO_FUNCIONA,
            "objetivo limiar exige alcançar o alvo",
            _b().variations([0.80, 0.85, 0.90], baseline=BASELINE),
            sem_baseline=False,
        )
    )
    out.append(
        _s(
            "C3-acima-do-alvo",
            "C",
            "3 variações crescentes acima do baseline e do alvo",
            FUNCIONA,
            f"três {evolucao}",
            _b().variations([0.96, 0.97, 0.98], baseline=BASELINE),
            sem_baseline=False,
        )
    )

    # D: métrica de erro (menor_melhor, alvo 0,10)
    out.append(
        _s(
            "D-E3",
            "D",
            "3 variações abaixo do alvo de erro, decrescentes",
            FUNCIONA,
            f"três {evolucao}",
            _b().variations([0.09, 0.08, 0.07]),
            criterion=ERRO,
        )
    )
    out.append(
        _s(
            "D-N3",
            "D",
            "3 variações acima do alvo de erro",
            NAO_FUNCIONA,
            "três variações sem alcançar o alvo",
            _b().variations([0.15, 0.14, 0.13]),
            criterion=ERRO,
        )
    )
    out.append(
        _s(
            "D-M21",
            "D",
            "2 positivas e 1 negativa, métrica de erro",
            INDECISO,
            "evidências em conflito",
            _b().variations([0.09, 0.08, 0.12]),
            criterion=ERRO,
        )
    )

    # P: exploração seguida de estagnação
    for n in (5, 15):
        out.append(
            _s(
                f"P-E3-V{n}",
                "P",
                f"E3 seguido de {n} variações sem ganho (0,955)",
                FUNCIONA,
                "as três melhoras continuam valendo; o volume não deve desfazê-las",
                _b().variations([0.96, 0.97, 0.98]).variations([0.955] * n, start=4),
            )
        )

    # Q: réplica que não confirma
    out.append(
        _s(
            "Q-E3-R1-neg",
            "Q",
            "E3 e a melhor configuração replicada em outro nó abaixo do alvo (0,93)",
            INDECISO,
            "a réplica não confirma a melhor variação",
            _b().variations([0.96, 0.97, 0.98]).result(0.93, "c3", node="n2", session="s2"),
        )
    )

    # G: métrica discreta (passo de um acerto em 30)
    passo = 1 / 30
    out.append(
        _s(
            "G-E2-passo",
            "G",
            "2 variações com um acerto de diferença (0,967 e 1,0)",
            INDECISO,
            "menos de três melhoras possíveis",
            _b().variations([round(29 * passo, 4), 1.0]),
        )
    )
    out.append(
        _s(
            "G-V5-repetidos",
            "G",
            "5 variações com o mesmo valor discreto (0,967)",
            INDECISO,
            "variações sem evolução",
            _b().variations([round(29 * passo, 4)] * 5),
        )
    )
    return out


def _same_config(n: int, *, sessions: bool) -> _Builder:
    b = _b()
    for k in range(n):
        b.result(0.96, "c1", session=f"s{k + 1}" if sessions else "s1")
    return b


def by_name() -> dict[str, Scenario]:
    """Cenários indexados pelo nome."""
    return {s.nome: s for s in catalog()}
