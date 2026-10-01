# Design: Researcher como Consultor nos Modos Autônomos

## 0. Estado atual (verificado em `dev`, commit `40419ea`, 2026-10-01)

| Ponto | Onde | Situação |
|---|---|---|
| Skill | `src/skills/human_feedback/skill.py:56-113` | Em `semi`/`auto`, devolve suposição e grava evento `ask_researcher` (`blocked: false`); em `assisted`, chama `ctx.ask_researcher`. |
| Núcleo humano | `src/orchestrator.py:414-460` | Deduplicação por `difflib` (`ASK_RESEARCHER_DEDUP_SIMILARITY`), pergunta no terminal, registro. |
| Registro | `src/orchestrator.py:491-520` | `payload["researcher_interactions"]`: `timestamp`, `question`, `why_cant_proceed`, `options`, `researcher_response`, `subtask_name`. |
| Contexto do agente | `src/agent_runtime/context.py:27-66` | `AgentContext.ask_researcher` (callback), `mode`, `session_id`, `execution_id`. |
| Busca na web | `src/skills/search_quick/skill.py` | `ddg`, `ddg_lite`, `brave` em cascata, cache por TTL. |
| Leitura de página | `src/skills/web_reader/skill.py` | Bloqueio de rede interna, DNS fixado, robots, até 5 redirecionamentos, `max_chars`. |
| Medição | `src/llm/metering.py` (`bind_execution`, `bound_execution_id`) | Tokens por `execution_id` lidos pelo `UsageTracker` (`src/usage.py:184-199`). |
| Instruções | `agents/developer/agent.py:85-90`, `agents/researcher/agent.py:101-115`, `agents/base/agent.py:267` | "Nos modos semi/auto, `ask_researcher` nunca bloqueia — documenta a suposição". |

## 1. Fluxo

```
agente ──ask_researcher──► skill
                            ├─ assisted ─► ctx.ask_researcher (humano, como hoje)
                            └─ semi/auto ─► ctx.consult_researcher
                                              │
                         orquestrador ◄───────┘
                           1. decisão reservada ao humano? → pendente (§5)
                           2. pergunta similar já respondida? → reutiliza
                           3. limite de consultas ou orçamento em fechamento? → suposição
                           4. Researcher consultor (§2), com timeout
                           5. registra (§6) e devolve a resposta formatada
```

A skill continua síncrona do ponto de vista do agente (aguarda a resposta). O consultor roda
no mesmo processo (ADR 014), dentro do `ResourceGuard` existente.

## 2. Researcher consultor (`agents/researcher/consult.py`)

- **Modelo:** o do papel `researcher` resolvido para a sessão (roteador atual ou o da
  `v16-model-catalog-router`, se já existir).
- **Entrada:** pergunta, contexto, motivo (`why_cant_proceed`), opções, papel e subtarefa do
  agente que perguntou, e o resumo do plano corrente (o mesmo que o Researcher já vê ao
  replanejar). **Não** recebe o histórico completo do agente que perguntou.
- **Ferramentas:** `quick_search(query, max_results)` e `web_reader(url, max_chars)`,
  embrulhadas pela guarda (§4); no máximo `RESEARCHER_CONSULT_MAX_SEARCHES` buscas e
  `RESEARCHER_CONSULT_MAX_READS` leituras por consulta. Nenhuma outra ferramenta.
- **Prompt:** papel de consultor técnico; responde de forma curta e verificável; prefere
  documentação oficial; diz quando não sabe; não faz busca bibliográfica (artigos, revisões);
  nunca inclui na busca valores, nomes de arquivos ou trechos de dados do projeto; não toma
  decisões reservadas ao humano.
- **Saída** (JSON validado; até 2 tentativas de correção de formato):

  ```json
  {"resposta": "…", "confianca": "alta|media|baixa",
   "fontes": [{"url": "https://…", "titulo": "…"}],
   "suposicoes": ["…"], "recomendacao": "…"}
  ```

- **Texto devolvido ao agente:** `"[Resposta do Researcher (consultor), confiança <c>] <resposta>"`
  + fontes numeradas + suposições. O agente continua livre para decidir; a instrução pede que
  registre em `scientific_rationale` que usou a consulta.
- **Timeout:** `RESEARCHER_CONSULT_TIMEOUT_SECONDS` (padrão 120).

## 3. Agente perguntando é o próprio Researcher

O consultor não tem `ask_researcher`, então não há recursão. Se o Researcher (planejando)
chama `ask_researcher` em `semi`/`auto`, a consulta é uma chamada separada, com o prompt do
consultor e sem o contexto de planejamento além do resumo do plano.

## 4. Guarda de consulta (`src/research_consult/query_guard.py`)

Aplicada a toda `query` de `quick_search` e a toda URL de `web_reader` antes de sair do nó.
Função pura `check_query(texto, nomes_protegidos) -> Ok | Recusa(motivo)`:

| Regra | Motivo |
|---|---|
| Número com separador decimal (`3.14`, `0,95`) | `numero_decimal` |
| Sequência de 4 ou mais dígitos que não seja ano entre 1900 e 2100 | `numero_longo` |
| Contém (sem diferenciar maiúsculas) o nome de um arquivo de `input_snapshot/` ou de `artifacts/` da sessão, com ou sem extensão | `nome_de_arquivo` |
| Mais de `RESEARCHER_CONSULT_QUERY_MAX_CHARS` (padrão 120) caracteres | `consulta_longa` |
| Mais de 3 linhas ou caracteres de controle | `formato` |

- Para `web_reader`, a guarda se aplica à URL inteira (caminho e query string) e o bloqueio de
  rede interna do próprio `web_reader` continua valendo.
- Consulta recusada: não é enviada; o consultor recebe a recusa com o motivo e pode reformular
  (conta no limite de buscas). Todas as recusas são registradas.
- Quando `v18.5-egress-gate` existir, a guarda passa a ser uma etapa do `EgressGate` com destino
  `buscador` (terceiro, sem dados brutos), sem mudar as regras acima.

A guarda é deliberadamente conservadora: ela bloqueia a forma mais comum de vazamento (valores
e nomes copiados para a busca), não prova ausência de dados. Isso fica explícito na revisão de
segurança.

## 5. Decisões reservadas ao humano

O consultor não responde quando a pergunta pede uma destas decisões, identificadas por um
campo novo e opcional da skill, `decisao_reservada`, preenchido pelas ferramentas que exigem
humano, e também por classificação no próprio consultor (saída `{"reservada": true}`):

`aprovar_oportunidade`, `confirmar_problema`, `aprovar_termo_vocabulario`,
`autorizar_escrita_instrumento`, `ativar_modo_sem_limite`.

Nesses casos a interação é registrada como `pendente_pesquisador`, o agente recebe "decisão
reservada ao pesquisador; registrada como pendente" e segue com a suposição documentada. A
lista é constante no código e testada.

## 6. Registro

Em `payload["researcher_interactions"]` (mesma lista da G5), com campos novos:

| Campo | Valor |
|---|---|
| `respondido_por` | `pesquisador` (assisted), `researcher` (consultor), `suposicao` (fallback) ou `pendente_pesquisador` |
| `agente`, `subtask_name`, `execution_id` | quem perguntou |
| `question`, `context`, `why_cant_proceed`, `options` | como hoje |
| `researcher_response` | texto devolvido ao agente |
| `consulta` | JSON do consultor (§2), `buscas_realizadas` (texto da consulta e backend), `leituras` (URLs), `recusas` (texto e motivo), `modelo`, `tokens`, `duracao_s` |
| `motivo_fallback` | `limite_consultas`, `orcamento`, `timeout`, `erro`, `desligado` ou `null` |

Telemetria: evento `researcher_consult` com os mesmos campos, sem o texto das páginas lidas.
A deduplicação (`_find_similar_researcher_answer`) passa a considerar respostas do consultor e
do pesquisador.

## 7. Limites e orçamento

- `RESEARCHER_CONSULT_MAX_PER_SESSION` (padrão 10) consultas por sessão. Só contam as que
  chamam o consultor; respostas reutilizadas pela deduplicação não contam.
- As chamadas do consultor são medidas com o `execution_id` do agente que perguntou
  (`bind_execution`), logo entram nos tokens da sessão que o `UsageTracker` já soma.
- Se `UsageTracker.check()` indicar fechamento (ou o teto de exploração), não há consulta:
  `motivo_fallback="orcamento"`.

## 8. Configuração (`src/config.py`, `.env.example`)

| Variável | Padrão | Uso |
|---|---|---|
| `RESEARCHER_CONSULT_ENABLED` | `true` | Desliga o consultor (volta à suposição documentada) |
| `RESEARCHER_CONSULT_WEB_ENABLED` | `true` | Desliga só as ferramentas web (consultor responde com o que sabe) |
| `RESEARCHER_CONSULT_MAX_PER_SESSION` | 10 | Consultas por sessão |
| `RESEARCHER_CONSULT_MAX_SEARCHES` | 3 | Buscas por consulta |
| `RESEARCHER_CONSULT_MAX_READS` | 2 | Páginas lidas por consulta |
| `RESEARCHER_CONSULT_TIMEOUT_SECONDS` | 120 | Timeout por consulta |
| `RESEARCHER_CONSULT_QUERY_MAX_CHARS` | 120 | Tamanho máximo da consulta |

## 9. Análise de impacto (6 eixos)

| Eixo | Impacto |
|---|---|
| Orquestrador & Loop | Núcleo novo de consulta ao lado do humano; nenhuma mudança no laço. |
| Agentes & Prompts | Prompt novo do consultor; texto de `ask_researcher` atualizado nos agentes. |
| Sandboxes & Containers | Nenhum. |
| Persistência | Campos novos em `researcher_interactions` (JSONB). |
| Segurança | Saída de consultas a buscadores com guarda; ferramentas do consultor sem escrita; decisões humanas protegidas. |
| Testes & Telemetria | Consultor testado com provedor LLM simulado e busca simulada; evento `researcher_consult`. |

## 10. Riscos

- **Vazamento por paráfrase** (consulta descreve o dado sem copiá-lo): a guarda não detecta.
  Mitigação: instrução do prompt, registro de toda consulta para auditoria, e a
  `v18.5-egress-gate` depois. Residual aceito pelo ADR 012 §8.
- **Resposta errada com confiança alta**: o agente recebe fontes e confiança; a avaliação
  posterior (`v16-agent-communication-eval`) mede se a consulta ajudou.
- **Laço de perguntas**: limite por sessão e deduplicação.
- **Buscador público instável**: cascata de backends já existente; falha vira fallback.

## 11. Questões em aberto para o pesquisador

1. Valores padrão de `RESEARCHER_CONSULT_MAX_PER_SESSION` (10), buscas (3) e leituras (2).
2. Em `semi`, o pesquisador quer **ver** as respostas do consultor no terminal (sem bloquear),
   ou só no registro e no relatório?
3. As consultas devem aparecer no relatório final (Spec G8) como seção própria?
