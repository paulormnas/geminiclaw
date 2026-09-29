# ADR 017 — Catálogo de Modelos e Roteador de Provedores por Papel

**Status:** Proposto
**Data:** 2026-09-29
**Relacionados:** ADR 007 (papéis e Model Router), ADR 011 (registro de provedores), limites de uso da V18 (PR #68)
**Revisa:** o Model Router do ADR 007 (mapeamento fixo papel → provedor/modelo por variável de ambiente)

## Contexto

Hoje cada papel lê `{PAPEL}_PROVIDER` e `{PAPEL}_MODEL` do `.env` (`src/model_config.py`), e o Planner e o fallback de `agent_loop` usam o singleton de `LLM_PROVIDER`/`LLM_MODEL`/`DEFAULT_MODEL`. São mais de 15 variáveis, e combinações inválidas passam despercebidas (ex.: provedor `google` com modelo `gemma4:26b` num `.env` real; o `preferred_model` do Planner sugere modelos locais sem trocar o provedor). Novos modelos surgem quase toda semana.

O objetivo é que o `.env` guarde só credenciais e endpoints, que o orquestrador escolha provedor e modelo por papel a partir de uma lista de modelos elegíveis, e que exista um modo fixo para reproduzir experimentos.

## Decisão

1. **Catálogo versionado** (`src/llm/catalog.yaml`, dados). Cada modelo registra só fatos que algum requisito filtra: provedor, nome, tool calling, saída estruturada, janela de contexto e `local`.
2. **Papéis no catálogo.** Todo chamador de LLM resolve pelo roteador: `planner`, `researcher`, `developer`, `reviewer`, `summarizer`, `validator` e `base`. Cada papel declara requisitos (ex.: Researcher exige tool calling; Validator exige `local: true`, mantendo a escolha do ADR 007) e uma ordem de preferência. `get_provider()` sem papel passa a delegar para `planner`. Embeddings ficam fora do escopo (ADR 011 §3).
3. **Política de localidade explícita.** `LLM_DATA_POLICY=local_only|cloud_allowed`, padrão `local_only`. Sob `local_only`, modelos com `local: false` são descartados antes de qualquer outra regra; ter uma chave de nuvem no `.env` não basta para enviar dados à nuvem. A política aparece no banner e no registro da sessão.
4. **Disponibilidade.** Um provedor está disponível quando tem credencial ou endpoint no `.env`, está em `LLM_PROVIDER_PRIORITY` (que é lista de permissão) e passa num health check com timeout curto. Para provedores locais o check confirma que o modelo está instalado (ex.: `/api/tags` do Ollama), não só o endpoint. Offline, o provedor sai da lista. `DEPLOYMENT_PROFILE=pi5` define a prioridade padrão.
5. **Roteador puro.** `resolve(papel, catálogo, disponíveis, política, overrides)` filtra por política, requisitos e lista de permissão e escolhe pela preferência. Sem estado e testável por unidade. Se nenhum modelo servir para um papel, a sessão falha com mensagem acionável.
6. **Resolvido uma vez por sessão.** Não há troca de provedor no meio da sessão nesta versão. Um 429 segue o cooldown e as retentativas atuais e conta no orçamento da V18. Isso evita escalada automática de custo.
7. **Modo fixo.** `{PAPEL}_MODEL=provedor/modelo` (divide só no primeiro `/`) é override opcional com precedência, mas continua sujeito à política e à lista de permissão. Com `LLM_ROUTING=strict`, pin indisponível ou em conflito faz a sessão falhar. O `preferred_model` do Planner vira dica no formato `provedor/modelo`: aceito se atender aos requisitos e estiver disponível, ignorado com `WARNING` caso contrário, e sempre ignorado em `strict`.
8. **Catálogo local e endpoints.** `catalog.local.yaml` (não versionado) só pode adicionar modelos, nunca alterar os existentes; ao ser carregado gera `WARNING` com seu hash. Para `openai_compatible`, `local` é derivado do host (loopback ou rede privada), nunca declarado; endpoints fora da máquina exigem `https`, e a chave só é enviada ao host configurado.
9. **Validação e segredos.** Os catálogos são lidos com `yaml.safe_load` e validados por esquema estrito (provedor desconhecido, papel sem modelo elegível, duplicatas e campos extras param a inicialização; o catálogo versionado também tem teste unitário). Banner, logs e telemetria registram apenas `provedor/modelo`, o host do endpoint e a versão e o hash do catálogo; erros do health check são sanitizados.
10. **Auditoria.** O mapa resolvido fica no banner e no payload da sessão, e cada chamada de LLM registra `provedor/modelo` na telemetria.

## Alternativas rejeitadas

- **Manter `{PAPEL}_PROVIDER/_MODEL` no `.env`:** é o problema atual.
- **Níveis fixos (`fast`/`strong`) por provedor:** esconde requisitos reais do papel e ainda exige um modelo por nível e provedor no `.env`.
- **Troca de provedor no meio da sessão:** complica custo e auditoria; adiada.
- **Pontuação automática por benchmark:** sem conjunto de avaliação a ordem seria arbitrária; adiada.
- **LiteLLM ou similar:** rejeitado no ADR 011.

## Consequências

- O `.env` encolhe para credenciais, endpoints, prioridade e política. Durante a transição, `{PAPEL}_PROVIDER`+`{PAPEL}_MODEL` são lidos como override equivalente com `WARNING`; `LLM_PROVIDER`, `LLM_MODEL` e `DEFAULT_MODEL` são removidos. As credenciais exigidas passam a seguir os provedores do mapa resolvido, e `.env.example` é atualizado na mesma mudança.
- Com `local_only` como padrão, quem usa Gemini hoje precisa declarar `cloud_allowed`.
- Manter o catálogo vira tarefa recorrente, revisada por PR.
- O health check adiciona latência à inicialização, com timeout curto e cache pela sessão.

## Trabalho futuro

- `geminiclaw models check <provedor/modelo>` para sondar um modelo novo (prompt sintético, sem dados do projeto, respeitando política e lista de permissão).
- Orçamento de custo ao lado do de tokens; proveniência de modelo por nó do grafo.

## Revisão

Reabrir quando houver conjunto de avaliação para ordenar modelos por qualidade, ou se o custo de manter o catálogo superar o de configurar o `.env`.
