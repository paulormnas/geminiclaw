# Proposta: Localidade, Família e Versão Efetiva dos Modelos no Catálogo

**ID:** `v18.5-model-catalog-locality` · **Versão:** V18.5 · **Capacidade:** `llm-providers`
**ADRs de origem:** [ADR 019](../../../docs/decisions/adr_019_localidade_dados_proveniencia_resultados.md)
§1, §6 (campo `familia_modelo` e regra de desempate no roteador), §7;
[ADR 017](../../../docs/decisions/adr_017_catalogo_modelos_roteador.md) §1, §5, §8, §9, §10
**Depende de:** V18 (em especial `v18-usage-limits` e `v18-research-continuity`) e da
implementação do catálogo e do roteador do ADR 017 (`src/llm/catalog.yaml`, `resolve(...)`)

## Por quê

O ADR 017 decide **para onde** cada papel envia prompts (`trust`, `LLM_DATA_POLICY`), mas não
diz **onde o modelo roda** nem se ele pode receber dados brutos de pesquisa. Sem essa
declaração, a camada de saída (`v18.5-egress-gate`) não tem como decidir o que filtrar por
destino. Além disso:

- o registro de cada chamada guarda só `provedor/modelo`, não a **versão efetivamente servida**
  (`src/llm/agent_loop.py:304-317`; `token_usage` em `scripts/init_db.sql:154-171`), o que
  impede reproduzir um experimento ou notar uma troca silenciosa de versão pelo provedor;
- a verificação de conclusões (`v18.5-claim-verification`) precisa escolher, entre modelos
  equivalentes, um de **família diferente** da do autor, e o catálogo não tem esse dado.

## O que muda

- **Novo (catálogo):** campos `localidade: no_no | fora_do_no` (padrão `fora_do_no`),
  `aceita_dados_brutos: bool` (padrão `false`; `true` só com `trust: self_hosted`; `no_no`
  implica `true`) e `familia_modelo: str` (obrigatório).
- **Novo (validação):** regras de coerência entre `trust`, `localidade` e
  `aceita_dados_brutos`; `WARNING` quando a `localidade` declarada diverge do endpoint
  (loopback × não loopback), sem inferir a localidade da URL.
- **Novo (roteador):** posições de preferência com empate (grupo) e desempate por
  `familia_modelo` para o Validator, resolvido depois dos papéis autores de afirmações (Researcher, Developer, Summarizer e Curator).
- **Novo:** **perfil de alocação** da sessão (`allocation_profile` no payload), exibido no
  banner e disponível para o relatório final.
- **Novo:** `versao_efetiva` por chamada de LLM, com fonte definida por provedor e valor literal
  `desconhecida` quando o provedor não informa; evento e aviso quando a versão muda na sessão;
  em `LLM_ROUTING=strict`, parada no próximo checkpoint.
- **Fora do escopo:** o uso desses campos para filtrar conteúdo (`v18.5-egress-gate`); a
  verificação de afirmações em si (`v18.5-claim-verification`); métricas agregadas
  (`v18.5-operation-metrics`).

## Impacto

- **Código:** `src/llm/catalog.yaml` e o esquema/validador do catálogo (ADR 017),
  roteador (`resolve`), `src/llm/base.py` (`LLMResponse.versao_efetiva`),
  `src/llm/providers/{google,ollama,openai_compatible}.py`, `src/llm/agent_loop.py`
  (telemetria), `src/telemetry.py`, `src/usage.py` (`StopReason`), `src/autonomous_loop.py`
  (verificação antes do despacho), `src/orchestrator.py` (payload), `src/cli.py` (banner),
  `.env.example`.
- **Dados:** coluna nova `versao_efetiva` em `token_usage`; chave `allocation_profile` e lista
  `eventos_versao_modelo` no payload da sessão (JSONB, sem schema).
- **Compatibilidade:** entradas de catálogo sem `localidade`/`aceita_dados_brutos` assumem os
  padrões seguros; `familia_modelo` passa a ser obrigatório (o catálogo versionado é
  atualizado nesta mudança; um `catalog.local.yaml` antigo sem o campo falha na validação com
  mensagem acionável).

## Aprovações necessárias

- **Alteração de schema do PostgreSQL:** `ALTER TABLE token_usage ADD COLUMN IF NOT EXISTS
  versao_efetiva TEXT` (migração `scripts/migrations/v18_5_model_version.sql` e atualização de
  `scripts/init_db.sql`). Exige aprovação explícita do pesquisador antes da implementação
  (AGENTS.md §1.5).
