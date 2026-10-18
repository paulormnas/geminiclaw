"""Instruções de prompt da exploração ativa (v18-hypothesis-loop, v18.6-auto-metrics-and-stop-reasons).

Movidas de ``exploration.py`` sem alterar o texto (v18.7-hypothesis-linking, tarefa 0.9; ADR 024 §5). O formato do
plano deixou de ser instrução da chamada: é gerado do esquema e fica no prompt do Researcher
(v18.7-agent-system-prompts).
"""

from __future__ import annotations

OBJECTIVE_DEFINITION_PLAN_INSTRUCTION = """DEFINIÇÃO DE OBJETIVO (obrigatória neste plano): o Problema deste
projeto não tem objetivo válido ({motivo}). Inclua no plano a chave "objetivo":
{{"tipo": "limiar" | "discriminacao" | "cobertura",
"justificativa": "por que este objetivo serve a este problema"}}.
- "limiar": alcançar um valor da métrica principal (a métrica, o limiar e "delta_min" vêm da chave "metricas").
- "discriminacao": decidir entre explicações rivais. Acrescente "hipoteses_concorrentes": ao menos 2 itens
  {{"ref": "<ref de uma hipótese declarada em hipoteses>", "predicao": "o que se observaria se ela fosse a correta"}};
  as predições devem ser testáveis e diferentes entre si.
- "cobertura": explorar o espaço de hipóteses, sem alvo; só o pesquisador a dá por atingida.
Não escreva a política ao atingir o objetivo (é do pesquisador) e não use "fronteira" (ainda não suportado). O Validator
avalia o objetivo junto com o plano; ele só vale depois de aprovado, e um plano sem "objetivo" é reprovado."""

METRIC_DEFINITION_PLAN_INSTRUCTION = """DEFINIÇÃO DE MÉTRICAS (obrigatória neste plano): o Problema deste projeto não
tem métrica aprovada ({motivo}). Inclua no plano a chave "metricas": a métrica (ou o conjunto de métricas) que melhor
expressa o sucesso para ESTE problema, cada item {{"nome": "...", "sentido": "maior_melhor" ou "menor_melhor",
"limiar": <número a alcançar>, "delta_min": <menor melhoria relevante, opcional>, "justificativa": "por que esta
métrica e este limiar servem a este problema"}}. A primeira é a principal (define o veredito das hipóteses). Escolha
métricas adequadas ao tipo de problema e aos dados, com limiar plausível; evite métrica de vaidade ou calculada sobre
dados de treino. O Validator avalia a definição junto com o plano; ela só vale depois de aprovada, e um plano sem
"metricas" é reprovado."""
