# Proposta: Catálogo de Modelos e Roteador por Papel

**ID:** `v16-model-catalog-router` · **Versão:** V16 (complemento) · **Capacidade:** `llm-providers`
**ADRs de origem:** [ADR 017](../../../docs/decisions/adr_017_catalogo_modelos_roteador.md) §1 a §10
(com a atualização de 2026-10-01: `planner` resolvido como `researcher`, Validator sem
exigência de `trust: self_hosted`); [ADR 011](../../../docs/decisions/adr_011_provedores_agnosticos.md) §1
(o catálogo só lista provedores registrados)
**Depende de:** `v16-provider-registry` (concluída) e do provedor `anthropic`/`openai` já
registrados (#79, #84)
**É pré-requisito de:** `v18.5-model-catalog-locality` (acrescenta `localidade`,
`aceita_dados_brutos` e `familia_modelo` a este catálogo)

## Por quê

A escolha de provedor e modelo por papel está espalhada em mais de 15 variáveis de ambiente
e em três caminhos de código que não se conversam:

- `src/model_config.py:22-50` mapeia papel → provedor/modelo com padrões fixos e lê
  `{PAPEL}_PROVIDER`/`{PAPEL}_MODEL` (`:80-81`). Uma combinação inválida (ex.: `google` com
  `gemma4:26b`) só aparece na primeira chamada.
- `src/llm/factory.py:10-17` mantém um singleton de `LLM_PROVIDER`/`LLM_MODEL`, usado por
  `src/llm/agent_loop.py:172` e `src/autonomous_loop.py:179-180` quando não há papel.
- `src/config.py:65-74` ainda define `LLM_PROVIDER`, `LLM_MODEL`, `DEFAULT_MODEL` e as variáveis
  de três papéis; `GEMINI_API_KEY` é obrigatória quando `LLM_PROVIDER=google` (`:83-86`), mesmo
  que nenhum papel use o Google.
- Os módulos de agente leem modelo por conta própria (`agents/researcher/agent.py:144-148`,
  `agents/developer/agent.py:104-108`, `agents/reviewer/agent.py:57`).
- O `preferred_model` do plano troca só o modelo, mantendo o provedor do papel
  (`src/model_router.py:48-50`, `src/orchestrator.py:584-585`): uma dica `qwen3:8b` num papel
  `google` gera uma chamada inválida.
- Nada impede que um prompt com dados do projeto vá a um provedor de nuvem só porque existe a
  chave no `.env`.

O ADR 017 decide substituir isso por um catálogo versionado, um roteador puro resolvido uma
vez por sessão e uma política de dados explícita.

## O que muda

- **Novo:** `src/llm/catalog.yaml` (dados versionados) com os modelos, seus fatos filtráveis
  (`ferramentas`, `saida_estruturada`, `janela_contexto`, `trust`) e os papéis com requisitos e
  ordem de preferência.
- **Novo:** `src/llm/catalog.py`: carga com `yaml.safe_load`, validação por esquema estrito,
  `catalog.local.yaml` opcional que só acrescenta modelos, hash e versão do catálogo.
- **Novo:** `src/llm/routing.py`: `resolve(papel, catalogo, disponiveis, politica, overrides)`
  puro; `resolve_session(...)` que resolve todos os papéis de uma vez e devolve o
  **mapa resolvido** da sessão.
- **Novo:** disponibilidade por provedor (credencial/endpoint, `LLM_PROVIDER_PRIORITY` como
  lista de permissão e health check com timeout curto e sem geração de texto), com cache por
  sessão.
- **Novo:** `LLM_DATA_POLICY=self_hosted_only|third_party_allowed` (padrão `self_hosted_only`),
  `LLM_ROUTING=flexible|strict` (padrão `flexible`) e `{PAPEL}_MODEL=provedor/modelo` como pin.
- **Novo:** mapa resolvido, política e hash do catálogo no banner e no payload da sessão.
- **Modificado:** `ModelRouter.get_provider(papel)` passa a ler o mapa resolvido da sessão;
  `get_provider()` sem papel delega para `researcher`; `preferred_model` vira dica
  `provedor/modelo` validada pelo roteador.
- **Modificado:** os agentes deixam de ler `AGENT_MODEL`, `{PAPEL}_MODEL` e `DEFAULT_MODEL`
  diretamente.
- **Modificado:** credenciais obrigatórias passam a seguir os provedores do mapa resolvido.
- **Removido:** `LLM_PROVIDER`, `LLM_MODEL`, `DEFAULT_MODEL` e o singleton de
  `src/llm/factory.py`. `{PAPEL}_PROVIDER`+`{PAPEL}_MODEL` (sem `/`) continuam aceitos durante a
  transição como pin equivalente, com `WARNING`.
- **Fora do escopo:** `localidade`, `aceita_dados_brutos`, `familia_modelo` e versão efetiva
  (`v18.5-model-catalog-locality`); troca de provedor no meio da sessão; ordenação por
  benchmark; o comando `models check` (trabalho futuro do ADR 017); embeddings (ADR 011 §3).

## Impacto

- **Código:** `src/llm/catalog.yaml` (novo), `src/llm/catalog.py` (novo),
  `src/llm/routing.py` (novo), `src/llm/availability.py` (novo), `src/model_router.py`,
  `src/model_config.py` (removido ou reduzido a adaptador), `src/llm/factory.py`,
  `src/llm/agent_loop.py`, `src/autonomous_loop.py`, `src/orchestrator.py`, `src/cli.py`
  (banner, `--model`), `src/config.py`, `agents/{researcher,developer,reviewer}/agent.py`,
  `src/llm/providers/google.py` (health check sem geração), `.env.example`,
  `pyproject.toml` (`pyyaml`, se ainda não for dependência direta).
- **Comportamento:** com o padrão `self_hosted_only`, quem usa Gemini, Claude ou GPT hoje precisa
  declarar `LLM_DATA_POLICY=third_party_allowed`. Sem nenhum modelo elegível para um papel, a
  sessão não começa (mensagem acionável), em vez de falhar na primeira chamada.
- **Custo:** um health check por provedor no início da sessão (sem tokens de geração).
- **Testes:** os testes que hoje patcham `LLM_PROVIDER`/`{PAPEL}_PROVIDER` passam a usar um
  catálogo e um mapa de disponibilidade de teste; nenhum teste faz chamada real a provedor
  pago (bloqueio do #85 continua).

## Aprovações necessárias

- **Remoção de variáveis de ambiente** (`LLM_PROVIDER`, `LLM_MODEL`, `DEFAULT_MODEL`) e mudança do
  padrão de política para `self_hosted_only`: altera o `.env` de quem já usa o projeto
  (inclusive o do Raspberry Pi). Exige aprovação explícita do pesquisador.
- Nenhuma alteração de schema de banco, Dockerfile ou `docker-compose.yml`.
