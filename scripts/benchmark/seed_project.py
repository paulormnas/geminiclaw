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
    caracteristicas_dados={"tamanho": "150 amostras", "atributos": "4", "modalidade": "tabular", "classes": "3"},
    dominios=("Aprendizado de Máquina",),
    metrica="acurácia",
    alvo=0.95,
    delta_min=0.01,
    baseline_descricao="classificador que prediz a classe majoritária",
)

WINE_DRAFT = ProblemDraft(
    titulo="Classificação supervisionada no dataset Wine",
    resumo=(
        "Dataset tabular de análises químicas de vinhos italianos de três cultivares, com treze medidas por amostra. "
        "O objetivo é montar um pipeline de classificação reproduzível, comparar ao menos dois algoritmos e recomendar "
        "um modelo com justificativa. Um avanço seria um modelo com acurácia de teste superior ao baseline simples, "
        "com avaliação comparável."
    ),
    classe="classificacao",
    caracteristicas_dados={"tamanho": "178 amostras", "atributos": "13", "modalidade": "tabular", "classes": "3"},
    dominios=("Aprendizado de Máquina",),
    metrica="acurácia",
    alvo=0.95,
    delta_min=0.01,
    baseline_descricao="classificador que prediz a classe majoritária",
)

# Problemas do corpus de memória entre projetos (``v18.9-memory-evaluation``): chave usada em ``combo["problem"]``.
PROBLEMS: dict[str, tuple[ProblemDraft, str]] = {
    "iris": (BENCHMARK_DRAFT, "Pipeline de classificação supervisionada para o dataset Iris (tarefa do run.sh)."),
    "wine": (WINE_DRAFT, "Pipeline de classificação supervisionada para o dataset Wine (tarefa do run_wine.sh)."),
}


def seeder_for(problem: str):
    """Semeador do problema registrado em :data:`PROBLEMS` (``seed_project`` com o ``Problema`` e a descrição dele).

    Raises:
        KeyError: Problema desconhecido (a mensagem lista os registrados).
    """
    if problem not in PROBLEMS:
        raise KeyError(f"Problema '{problem}' desconhecido; registrados: {', '.join(sorted(PROBLEMS))}.")
    draft, description = PROBLEMS[problem]
    return lambda name: seed_project(name, draft=draft, description=description)


def seed_project(
    name: str, store: Any | None = None, draft: ProblemDraft | None = None, description: str | None = None
) -> str:
    """Cria o projeto ``Benchmark <name>`` com o ``Problema`` confirmado e devolve o ``projeto_id``.

    Args:
        name: Nome da combinação (entra no título).
        store: ``GraphStore`` (padrão: o de produção, com índice semântico, que vetoriza título, objetivo e domínios).
        draft: ``Problema`` a confirmar (padrão: o do Iris, ``BENCHMARK_DRAFT``); as explorações controladas passam o do
            regime (``v18.8-verdict-controlled-sessions``).
        description: Descrição do projeto (padrão: a do pipeline Iris).

    Raises:
        ProjectError: Falha ao criar o projeto ou confirmar o ``Problema``.
        VocabularyNotSeededError: A ``Metrica`` do ``Problema`` não existe aprovada no vocabulário.
    """
    draft = draft or BENCHMARK_DRAFT
    if store is None:
        from src.knowledge.factory import open_graph_store

        store = open_graph_store()
    # Sem a métrica canônica o Problema ganharia um candidato sem sinônimos e nenhum Resultado ganharia ``MEDE``
    # (veredito das hipóteses preso em 0): falha antes de criar qualquer nó.
    if find_approved_metric(store, draft.metrica) is None:
        raise VocabularyNotSeededError(
            f"A métrica '{draft.metrica}' não está aprovada no vocabulário do grafo; "
            "rode scripts/seed_vocabulary.py (ou use --reset-stores, que semeia o banco de benchmark)."
        )
    project_id = projects.create_project(
        store,
        f"Benchmark {name}",
        description or "Pipeline de classificação supervisionada para o dataset Iris (tarefa do run.sh).",
        list(draft.dominios),
    )
    projects.confirm_problem(store, project_id, draft, sentido_metrica="maior_melhor")
    return project_id
