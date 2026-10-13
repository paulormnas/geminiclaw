"""Projeto de pesquisa semeado para o benchmark (um por combinação).

A sessão em modo ``auto`` exige um projeto com ``Problema`` confirmado (v17-research-project): sem terminal, ninguém
confirmaria. O benchmark é executado pelo pesquisador, que autoriza esta semeadura: o ``Problema`` é fixo (a tarefa
do ``run.sh``, o pipeline Iris), sem LLM, e a confirmação usa o mesmo caminho de produção
(``projects.confirm_problem`` com autoria ``pesquisador``). Cada combinação ganha o seu projeto, para medir a memória de
grafo de cada modelo sem contaminação entre execuções.
"""

from __future__ import annotations

from typing import Any

from src.knowledge import projects
from src.knowledge.problem import ProblemDraft
from src.knowledge.vocabulary import find_approved_metric


class VocabularyNotSeededError(RuntimeError):
    """O vocabulário controlado não foi carregado no grafo (``scripts/seed_vocabulary.py``)."""


BENCHMARK_DRAFT = ProblemDraft(
    titulo="Classificação supervisionada no dataset Iris",
    resumo=(
        "Dataset tabular clássico de flores com quatro medidas e três espécies. O objetivo é montar um pipeline de "
        "classificação reproduzível, comparar ao menos dois algoritmos e recomendar um modelo com justificativa. "
        "Um avanço seria um modelo com acurácia de teste superior ao baseline simples, com avaliação comparável."
    ),
    classe="classificacao",
    caracteristicas_dados={"tamanho": "150 amostras", "modalidade": "tabular", "classes": "3"},
    dominios=("Aprendizado de Máquina",),
    metrica="acurácia",
    alvo=0.95,
    delta_min=0.01,
    baseline_descricao="classificador que prediz a classe majoritária",
)


def seed_project(name: str, store: Any | None = None) -> str:
    """Cria o projeto ``Benchmark <name>`` com o ``Problema`` confirmado e devolve o ``projeto_id``.

    Args:
        name: Nome da combinação (entra no título).
        store: ``GraphStore`` (padrão: o de produção, com índice semântico, que vetoriza título, objetivo e domínios).

    Raises:
        ProjectError: Falha ao criar o projeto ou confirmar o ``Problema``.
        VocabularyNotSeededError: A ``Metrica`` do ``Problema`` não existe aprovada no vocabulário.
    """
    if store is None:
        from src.knowledge.factory import open_graph_store

        store = open_graph_store()
    # Sem a métrica canônica o Problema ganharia um candidato sem sinônimos e nenhum Resultado ganharia ``MEDE``
    # (veredito das hipóteses preso em 0): falha antes de criar qualquer nó.
    if find_approved_metric(store, BENCHMARK_DRAFT.metrica) is None:
        raise VocabularyNotSeededError(
            f"A métrica '{BENCHMARK_DRAFT.metrica}' não está aprovada no vocabulário do grafo; "
            "rode scripts/seed_vocabulary.py (ou use --reset-stores, que semeia o banco de benchmark)."
        )
    project_id = projects.create_project(
        store,
        f"Benchmark {name}",
        "Pipeline de classificação supervisionada para o dataset Iris (tarefa do run.sh).",
        list(BENCHMARK_DRAFT.dominios),
    )
    projects.confirm_problem(store, project_id, BENCHMARK_DRAFT, sentido_metrica="maior_melhor")
    return project_id
