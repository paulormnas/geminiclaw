"""Famílias de Problemas relacionados no gerador controlado (design §5; ADR 026 §7).

Uma família **relacionada** tem ``k`` membros que compartilham a abordagem que funciona (a mesma estrutura de
não linearidade plantada, ou seja, o mesmo regime de rótulo) e variam em semente, tamanho e ruído de rótulo. Uma
família de **controle** reúne regimes diferentes: a abordagem que funciona difere entre os membros, e a transferência
entre eles só pode prejudicar. Rodar as sessões de uma família em sequência dá o histórico de que o E0 precisa
(com custo de LLM: só com a confirmação do pesquisador).

Cada membro ganha ``dados.csv`` e ``dados.yaml`` em ``<destino>/entrada/<membro>/`` e ``verdade.json`` (com a
``familia`` e a abordagem plantada) em ``<destino>/verdade/<membro>/``, **fora** do alcance dos agentes.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from scripts.verdict_lab.controlled import generator, regimes

TipoFamilia = Literal["relacionada", "controle"]
TAMANHOS = (1000, 2000, 3000)
RUIDOS = (0.0, 0.02, 0.05)
REGIMES_CONTROLE = ("P", "T", "N")


class FamilyError(ValueError):
    """Família inválida (``k`` pequeno demais, regime desconhecido ou diretórios incompatíveis)."""


@dataclass(frozen=True)
class Member:
    """Um Problema da família."""

    nome: str
    regime: str
    semente: int
    n_linhas: int
    ruido: float


@dataclass(frozen=True)
class Family:
    """Conjunto de Problemas gerados juntos."""

    nome: str
    tipo: TipoFamilia
    membros: tuple[Member, ...]


def build_family(nome: str, tipo: TipoFamilia, k: int, semente_base: int, *, regime: str = "P") -> Family:
    """Define os ``k`` membros (determinístico em ``nome``, ``tipo``, ``k`` e ``semente_base``).

    Args:
        nome: Nome da família.
        tipo: ``relacionada`` (todos no ``regime``) ou ``controle`` (regimes P, T e N em rodízio).
        k: Número de membros (>= 2).
        semente_base: Semente única da qual saem as sementes dos membros.
        regime: Regime dos membros de uma família relacionada.
    """
    if k < 2:
        raise FamilyError(f"Uma família precisa de pelo menos 2 membros (k={k}).")
    if tipo not in ("relacionada", "controle"):
        raise FamilyError(f"Tipo de família desconhecido: {tipo!r}.")
    regimes.regime(regime)
    seeds = generator.sementes_das_repeticoes(semente_base, k)
    members = []
    for i, seed in enumerate(seeds):
        members.append(
            Member(
                nome=f"{nome}-m{i + 1}",
                regime=regime if tipo == "relacionada" else REGIMES_CONTROLE[i % len(REGIMES_CONTROLE)],
                semente=seed,
                n_linhas=TAMANHOS[i % len(TAMANHOS)],
                ruido=RUIDOS[(i // len(TAMANHOS)) % len(RUIDOS)],
            )
        )
    return Family(nome, tipo, tuple(members))


def _rows(member: Member) -> Any:
    familia_rotulo = regimes.regime(member.regime).familia
    flip = random.Random(f"memory-eval-ruido:{member.nome}:{member.semente}")
    for x, y in generator.linhas(familia_rotulo, member.n_linhas, member.semente):
        if member.ruido and flip.random() < member.ruido:
            y = 1 - y
        yield x, y


def _write_csv(dest: Path, member: Member) -> str:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("w", encoding="utf-8", newline="") as handle:
        handle.write(",".join(generator.COLUNAS) + "\n")
        for x, y in _rows(member):
            handle.write(",".join(f"{v:.6f}" for v in x) + f",{y}\n")
    return generator.sha256_arquivo(dest)


def prepare(family: Family, destino: Path) -> dict[str, Any]:
    """Grava os dados e as verdades da família e devolve o manifesto (sem as verdades).

    Raises:
        FamilyError: ``destino`` não é um diretório próprio (entrada e verdade seriam os mesmos).
    """
    entrada, verdade = destino / "entrada", destino / "verdade"
    manifest: dict[str, Any] = {"familia": family.nome, "tipo": family.tipo, "membros": []}
    for member in family.membros:
        sha = _write_csv(entrada / member.nome / "dados.csv", member)
        generator.escrever_manifesto(entrada / member.nome / "dados.yaml")
        regime = regimes.regime(member.regime)
        content = regimes.verdade(member.regime, member.semente, sha)
        content.update(
            {
                "familia": family.nome, "tipo_familia": family.tipo, "membro": member.nome,
                "n_linhas": member.n_linhas, "ruido_rotulo": member.ruido,
                "abordagem_que_funciona": regime.familia,
            }
        )
        verdade_dir = verdade / member.nome
        verdade_dir.mkdir(parents=True, exist_ok=True)
        (verdade_dir / "verdade.json").write_text(
            json.dumps(content, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        manifest["membros"].append({"nome": member.nome, "regime": member.regime, "sha256_dados": sha})
    return manifest
