# Proposta: Camada Única de Saída com Filtro de Egresso

**ID:** `v18.5-egress-gate` · **Versão:** V18.5 · **Capacidade:** `data-egress`
**ADRs de origem:** [ADR 019](../../../docs/decisions/adr_019_localidade_dados_proveniencia_resultados.md)
§3.4, §3.5, §3.6, §3.7, §3.8, §9; [ADR 014](../../../docs/decisions/adr_014_agentes_em_processo_sandbox_codigo.md) §3
**Depende de:** `v18.5-model-catalog-locality` (perfil de alocação e `aceita_dados_brutos`
efetivo por destino)

## Por quê

Hoje o sistema decide **para onde** enviar (política do ADR 017), mas não **o quê**:

- a skill de código devolve ao LLM o `stdout` completo e o `stderr`
  (`src/skills/code/skill.py:250-267`); um `print(df)` ou uma exceção como
  `could not convert string to float: '12,5'` envia registros ao provedor;
- a mensagem de erro também volta pelo bloco de contexto do workspace
  (`src/llm/context_injection.py:85-91`);
- há pelo menos cinco pontos de chamada a modelos sem camada comum (`src/llm/agent_loop.py:287`
  e `:500`, `src/llm/context_compression.py:149`, `src/autonomous_loop.py:180-193`,
  `src/agents/validator_agent.py:277` e `:435`), além da visão por chamada direta
  (`src/context_loader.py:472-488`) e das consultas de busca e leitura web
  (`src/skills/search_quick/skill.py:52-110`, `src/skills/web_reader/skill.py:304-372`);
- nada registra o que saiu, para onde, nem de que origem;
- o conteúdo observado (documentos, páginas, saídas) chega ao modelo misturado às instruções.

## O que muda

- **Novo:** módulo `src/egress/` com a classe `EgressGate`, ponto único de saída para LLM,
  visão, busca técnica e leitura web.
- **Novo:** trechos de prompt rotulados (`PromptFragment`) com origem `ContentOrigin`
  (instrucao, documento, esquema_agregado, codigo, saida_execucao, grafo, dado_de_pesquisa),
  marca `tainted` e marca `compartilhavel`.
- **Novo:** regras por destino, reaplicadas sobre o prompt inteiro (inclusive histórico) a
  cada envio: retenção de `dado_de_pesquisa`, filtro de saída de execução (tracebacks com
  marcadores tipados, retenção de despejos tabulares, estatísticas pela regra de k e extremos
  nunca exatos, elisão início/fim), números literais de texto contaminado trocados por
  marcadores tipados.
- **Novo:** conteúdo observado delimitado e identificado como dado (ADR 019 §9).
- **Novo:** tabela `egress_log` (PostgreSQL) e cópia local dos envios; limite de volume de
  egresso de saídas de execução como condição de parada.
- **Novo:** restrição de leitura no host: ferramentas do host não levam conteúdo de dados de
  pesquisa ao prompt; só a camada de ingestão (`v18.5-research-data-ingestion`).
- **Novo:** marca de contaminação persistida com o texto (payload, checkpoint, memória) e
  reaplicada na retomada, mesmo com outro catálogo; aviso de perfil misto no banner.
- **Modificado:** prompt do Developer instrui a imprimir agregados, não dados.
- **Fora do escopo:** modo sem limite (`v18.5-operation-metrics`, que também expõe
  `--max-egress-bytes` na CLI); resumos de `input_context/`, marcações de arquivo e visão sobre
  imagens (`v18.5-research-data-ingestion`); sandbox sem rede (`v18.5-sandbox-phases`).

## Impacto

- **Código:** `src/egress/` (novo: `fragments.py`, `gate.py`, `filters.py`, `classification.py`,
  `log.py`), `src/model_router.py` e roteador do ADR 017 (devolvem provedor envolvido),
  `src/llm/agent_loop.py`, `src/llm/context_injection.py`, `src/llm/context_compression.py`,
  `src/autonomous_loop.py`, `src/agents/validator_agent.py`, `src/orchestrator.py`,
  `src/skills/code/skill.py`, `src/skills/search_quick/skill.py`,
  `src/skills/web_reader/skill.py`, `src/skills/document_processor/skill.py`,
  `src/skills/memory/`, `agents/base/agent.py`, `agents/developer/agent.py`, `src/usage.py`,
  `src/config.py`, `src/cli.py`, `.env.example`.
- **Comportamento:** até `v18.5-research-data-ingestion` ser implementada, o bloco de
  `input_context/` inteiro é rotulado `dado_de_pesquisa` e **retido** para modelos sem
  `aceita_dados_brutos` (falha fechada). As duas mudanças devem ser liberadas juntas.
- **Custo:** o filtro roda no Pi 5 a cada envio; é textual e linear no tamanho do prompt.

## Aprovações necessárias

- **Alteração de schema do PostgreSQL:** nova tabela `egress_log` (migração
  `scripts/migrations/v18_5_egress_log.sql` e `scripts/init_db.sql`). Exige aprovação
  explícita do pesquisador antes da implementação (AGENTS.md §1.5).
- **Revisão do Analista de Segurança** (a mudança toca a fronteira de saída de dados e as
  ferramentas do host).
