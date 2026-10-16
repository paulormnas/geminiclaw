"""Instruções de prompt da exploração ativa (v18-hypothesis-loop, v18.6-auto-metrics-and-stop-reasons).

Movidas de ``exploration.py`` sem alterar o texto (v18.7-hypothesis-linking, tarefa 0.9; ADR 024 §5).
"""

from __future__ import annotations

PLAN_FORMAT_INSTRUCTION = """FORMATO DO PLANO NESTE PROJETO (obrigatório): retorne UM objeto JSON com as chaves
"hipoteses", "decisoes", "respostas_sugestoes" e "subtarefas" (lista; as subtarefas seguem o formato de sempre e
ganham "hypothesis_ref").
- "hipoteses": cada item {"ref": "h1", "id": null, "enunciado": "...", "justificativa": "...", "origem": "researcher",
  "derivada_de": ["<id de Descoberta|Oportunidade|Insumo>"], "custo_estimado": "baixo|medio|alto",
  "abordagem": {"nome": "...", "tipo": "algoritmo"}}. Use "id" para continuar uma hipótese existente (listada abaixo);
  "ref" para as novas. A origem real é decidida pelo sistema, não por você.
- "decisoes": TODA escolha entre alternativas gera uma decisão: {"contexto": "...", "escolhido": {"tipo": "Hipotese",
  "ref": "h1"}, "descartados": [{"tipo": "Abordagem", "nome": "...", "motivo": "..."}], "criterio": "evidencia_previa",
  "justificativa": "...", "informada_por": ["<id de Descoberta>"]}. Inclua ao menos uma decisão ao introduzir hipótese
  nova.
- "respostas_sugestoes": responda a CADA sugestão pendente do Curator: {"sugestao_id": "...", "decisao": "aceita" ou
  "recusada", "motivo": "...", "hipotese_ref": "h2"} ("aceita" exige a hipótese correspondente em "hipoteses").
- Cada subtarefa que testa uma hipótese DEVERIA ter "hypothesis_ref" (o "ref" ou o "id" da hipótese); sem ele o
  sistema deriva a ligação e a registra (nenhuma subtarefa é retirada por falta de "hypothesis_ref").
- Declare o "papel" de cada subtarefa: "teste" (testa uma hipótese), "preparacao" (prepara dados ou ambiente para
  outras subtarefas) ou "referencia" (baseline do Problema, medido com a métrica principal). O campo é opcional;
  sem ele o sistema decide o papel pela estrutura do plano.
- Hipóteses de agentes dependem de aprovação do pesquisador conforme o modo da sessão; oportunidades só viram
  hipótese depois de aprovadas pelo pesquisador.
- Subtarefas já concluídas continuam no plano, inalteradas (para manter as dependências); não são reexecutadas.
- Se você não vê mais nenhum caminho promissor, devolva o plano só com as subtarefas já concluídas e sem hipótese
  nova: a sessão será encerrada como "sem caminhos promissores"."""


METRIC_DEFINITION_PLAN_INSTRUCTION = """DEFINIÇÃO DE MÉTRICAS (obrigatória neste plano): o Problema deste projeto não
tem métrica aprovada ({motivo}). Inclua no plano a chave "metricas": a métrica (ou o conjunto de métricas) que melhor
expressa o sucesso para ESTE problema, cada item {{"nome": "...", "sentido": "maior_melhor" ou "menor_melhor",
"limiar": <número a alcançar>, "delta_min": <menor melhoria relevante, opcional>, "justificativa": "por que esta
métrica e este limiar servem a este problema"}}. A primeira é a principal (define o veredito das hipóteses). Escolha
métricas adequadas ao tipo de problema e aos dados, com limiar plausível; evite métrica de vaidade ou calculada sobre
dados de treino. O Validator avalia a definição junto com o plano; ela só vale depois de aprovada, e um plano sem
"metricas" é reprovado."""
