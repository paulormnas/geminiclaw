# Proposta: Cálculo do Veredito de Evidência

**ID:** `v17-evidence-verdict` · **Versão:** V17 · **Capacidade:** `evidence-scoring`
**ADRs de origem:** [ADR 015](../../../docs/decisions/adr_015_modelo_dados_grafo_conhecimento.md) §9;
discussão, questão 4

## Por quê

O pesquisador e o arquiteto definiram uma equação de confiança com pesos objetivos: cada
evidência recebe peso por qualidade da validação, magnitude do efeito, independência e
penalidade de busca; o resultado é um **veredito de −1 a +1** (positivo = funciona, negativo =
não funciona, perto de zero = insuficiente). Tentativas sem resultado são tratadas por causa.
Essa conta precisa ser implementada **uma única vez**, de forma determinística e testável, e
usada por todos os consumidores (Curator, CLI, ranking de busca, fila de similaridade).

## O que muda

- **Novo:** módulo puro `src/knowledge/verdict.py` — sem acesso a banco, rede ou LLM — que
  recebe as evidências de uma hipótese e devolve o veredito com o detalhamento por evidência.
- **Novo:** parâmetros calibráveis em `src/config.py` (ADR 015 §9.8).
- **Novo:** testes-ouro com o exemplo completo e a tabela de referência do ADR 015.
- **Fora do escopo:** coletar as evidências do grafo e gravar o veredito nos nós — feito pelo
  Curator (`v17-curator-agent`), usando este módulo.

## Impacto

- **Código:** `src/knowledge/verdict.py` (novo), `src/config.py`, `.env.example`.
- **Dependências:** nenhuma nova (apenas `math`).
- Pode ser implementada em paralelo com as demais mudanças da V17.

## Aprovações necessárias

Nenhuma.
