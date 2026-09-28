"""Domínio de conhecimento (grafo de hipóteses, evidências e veredito).

Este pacote é a **única porta de acesso** ao grafo de conhecimento (Apache AGE
sobre PostgreSQL 16). Nenhum outro módulo deve montar consultas Cypher
diretamente — toda escrita e leitura estruturada passa pela interface
``GraphStore`` definida em :mod:`src.knowledge.graph_store` (Roadmap V17 /
ADR 009, ADR 015).
"""
