"""Laboratório do veredito (ADR 025, etapas 1 e 2; mudança ``v18.8-verdict-lab``).

Calcula o veredito das hipóteses sob variantes da fórmula do ADR 015 §9, sem chamada de LLM, sem banco e
sem rede, e sem alterar o comportamento do sistema: ``src/knowledge/verdict.py`` é usado como está, e as
alternativas de estrutura existem só aqui. Comandos: ``replay``, ``grade``, ``simulacao`` e ``sensibilidade``
(``uv run python -m scripts.verdict_lab --help``).
"""
