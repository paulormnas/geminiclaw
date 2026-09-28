# Proposta: Vocabulário Controlado — Domínios e Métricas

**ID:** `v17-controlled-vocabulary` · **Versão:** V17 · **Capacidade:** `vocabulary`
**ADRs de origem:** [ADR 015](../../../docs/decisions/adr_015_modelo_dados_grafo_conhecimento.md) §4, §8;
discussão, questões 2 e 3

## Por quê

O pesquisador decidiu que domínios e métricas vêm de vocabulário controlado, e não de texto
livre, para que buscas futuras e conexões entre áreas distantes funcionem. Domínios partem da
Tabela de Áreas do Conhecimento do CNPq — **ponto de partida, não restrição**. Métricas têm
catálogo com nome canônico, sinônimos e sentido, sem o qual o veredito (§9) não sabe se um
valor maior é melhor ou pior.

## O que muda

- **Novo:** carga inicial dos nós `Dominio` a partir da tabela oficial do CNPq, com hierarquia
  `SUBAREA_DE`, e dos nós `Metrica` a partir de um catálogo inicial.
- **Novo:** serviço `src/knowledge/vocabulary.py` que resolve um termo livre para um termo
  canônico (nome exato → sinônimo → similaridade semântica) ou cria um **candidato**.
- **Novo:** comandos determinísticos `geminiclaw vocab pending|approve|reject|map` para o
  pesquisador decidir sobre candidatos.
- **Fora do escopo:** mapeamento para a OCDE (fica para a federação, ADR 013).

## Impacto

- **Código:** `src/knowledge/vocabulary.py` (novo), `src/cli.py`, `data/vocabulary/` (novo:
  arquivos de carga), `src/agents/validator_agent.py` (reutilizar a normalização de nomes de
  métrica).
- **Dados:** carga inicial de nós no grafo.

## Aprovações necessárias

- A carga inicial escreve no grafo (dados, não schema) — coberta por esta proposta aprovada.
- **Fonte da tabela do CNPq:** a tabela oficial deve ser obtida da fonte do CNPq e sua versão
  registrada; não pode ser reconstruída de memória pelo agente implementador.
