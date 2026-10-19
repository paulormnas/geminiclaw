"""Explorações controladas com efeito conhecido (ADR 025, etapa 3; mudança ``v18.8-verdict-controlled-sessions``).

Gera dados sintéticos com resposta conhecida em quatro regimes (P efeito plantado, T teto abaixo do alvo, N ruído
puro, F falha de abordagem), o ``Problema`` e a tarefa de cada um e o arquivo de verdade, que fica fora do alcance dos
agentes. Não chama LLM, banco nem rede.
"""
