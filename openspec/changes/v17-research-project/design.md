# Design: Projeto de Pesquisa e Problema Confirmado

## 1. Projeto

`src/knowledge/projects.py`:

```python
def create_project(titulo: str, objetivo: str, dominios: list[str]) -> str   # projeto_id
def list_projects(status: str | None = None) -> list[ProjectSummary]
def get_project(projeto_id: str) -> ProjectDetail   # projeto + problema + nº sessões/hipóteses
def get_active_problem(projeto_id: str) -> Node | None   # Problema com status "confirmado"
```

CLI:

```
geminiclaw project new --titulo "..." --objetivo "..." [--dominio TERMO ...]
geminiclaw project list [--status ativo|pausado|concluido]
geminiclaw project show <projeto_id>
geminiclaw project use <projeto_id>          # define o projeto padrão das próximas sessões
geminiclaw --project <projeto_id> "<prompt>"
```

- O projeto padrão (`project use`) é guardado em `~/.config/<app>/active_project`.
- Sem `--project` e sem projeto padrão: cria um projeto com `titulo` = primeira linha do
  prompt (até 120 caracteres) e `objetivo` = prompt completo, e informa o ID ao pesquisador.
- `agent_sessions.payload` ganha a chave `project_id` (JSONB — sem mudança de schema).
- Domínios passados em `--dominio` são resolvidos por `vocabulary.resolve_domain`.

## 2. Rascunho do Problema pelo Researcher

Nova função em `agents/researcher/agent.py`:

```python
async def draft_problem(prompt: str, context: ContextBundle, projeto: ProjectDetail) -> ProblemDraft
```

Saída JSON exigida do LLM (validada; até 2 tentativas de reparo com `src/utils/json_parser.py`):

```json
{
  "titulo": "Previsão do rendimento de síntese orgânica a partir de condições de reação",
  "resumo": "Contexto, lacuna, objetivo e o que seria considerado um avanço — como o resumo de um artigo sem resultados.",
  "classe": "regressao",
  "caracteristicas_dados": {"tamanho": "~2 mil reações", "modalidade": "tabular", "ruido": "moderado"},
  "dominios": ["Química Orgânica", "Ciência da Computação"],
  "criterio_sucesso": {"metrica": "R2", "alvo": 0.8, "delta_min": 0.05,
                       "baseline_descricao": "regressão linear"}
}
```

Instrução do rascunho: problema **em alto nível**, independente de técnica; não citar a
abordagem que será usada; `delta_min` = menor melhoria que o pesquisador consideraria
relevante — se o contexto não permitir inferir, deixar `null` e sinalizar.

## 3. Confirmação do pesquisador (todos os modos)

Antes do planejamento da primeira sessão de um projeto sem `Problema` confirmado:

1. A CLI exibe o rascunho formatado.
2. O pesquisador escolhe **confirmar**, **editar campo** (título, resumo, classe, domínios,
   métrica, alvo, `delta_min`) ou **pedir novo rascunho** com um comentário.
3. `delta_min` é obrigatório para confirmar; se estiver `null`, a CLI pede o valor.
4. Na confirmação: `Problema` gravado com `status="confirmado"`, `criado_por` = researcher
   (rascunho) e auditoria da confirmação com autor `pesquisador`; métrica resolvida por
   `resolve_metric`; domínios por `resolve_domain`; arestas `Projeto-INVESTIGA->Problema` e
   `Problema-NO_DOMINIO->Dominio`.
5. Sessões seguintes do projeto reutilizam o problema confirmado, sem nova confirmação.

Nos modos `semi` e `auto` a confirmação também é exigida (decisão do pesquisador), mas ocorre
**uma vez por projeto**, antes do início da execução autônoma. Se a sessão não é interativa
(sem TTY), a execução é recusada com mensagem orientando `geminiclaw project show` e a
confirmação prévia.

Editar o problema depois (`geminiclaw project show` → alteração) é uma alteração do grafo e
segue a regra do ADR 015 §11 (via Curator, mudança `v17-graph-cli`).

## 4. Injeção no contexto

`ProjectDetail` (título, resumo, critério) é injetado no contexto do Researcher em todo
planejamento, ao lado do `ContextBundle`.

## Análise de impacto (6 eixos)

| Eixo | Impacto |
|---|---|
| Orquestrador & Loop | Sessão ligada a projeto; passo de confirmação antes do primeiro plano. |
| Agentes & Prompts | Nova tarefa de rascunho do Researcher; contexto do projeto no planejamento. |
| Sandboxes & Containers | Nenhum. |
| Persistência | Chave `project_id` no payload JSONB; nós `Projeto`/`Problema`. |
| Segurança | Confirmação humana obrigatória antes de gastar recursos. |
| Testes & Telemetria | Testes da CLI e do fluxo de confirmação com entrada simulada. |

## Decisões de implementação (revisão do PR #103)

- **`projeto_id` x `id` do nó:** `projeto_id` é um UUIDv7 gerado em `create_project` e gravado na
  propriedade imutável `projeto_id` do nó `Projeto`; o `id` do nó é outro UUID, atribuído pelo
  `GraphStore`. Todos os nós do projeto carregam o `projeto_id`; `get_project`/`--project` usam-no.
- **Assinaturas:** as funções de `projects.py` recebem o `store` como primeiro argumento;
  `draft_problem` aceita `comentario` opcional (novo rascunho com comentário).
- **Confirmação humana na porta única:** `validation.validate_human_only`, chamada por
  `create_node` e `update_node` dos dois stores, recusa que qualquer ator diferente de
  `pesquisador` crie `Problema` com `status="confirmado"`, o promova ou o rebaixe. Não há
  `confirmado_por` no schema (sem mudança de schema); a trilha é a auditoria com autor
  `pesquisador`. `Projeto` não tem esse gate (o ADR 015 §3 não o exige).
- **Atomicidade:** `confirm_problem` cria o `Problema` como `rascunho`, liga `INVESTIGA` e os
  domínios e **promove por último**; `get_active_problem` levanta erro se houver mais de um
  confirmado (nunca escolhe em silêncio) e a promoção que cria um segundo é desfeita.
- **Autoria no vocabulário:** domínios e métrica vindos do rascunho entram como candidatos do
  ator `researcher/<modelo>`; o `pesquisador` aparece só na confirmação e nos domínios de
  `project new`.
- **Grafo fora do ar:** erro de driver (Postgres/Qdrant) vira `ProjectFlowError` acionável.
  `RESEARCH_PROJECT_GRAPH_OPTIONAL` (padrão `false`): ligada, e somente se o grafo não abrir, a
  sessão roda sem projeto (banner e `payload["project_mode"] = "sem_grafo"`); com o grafo
  acessível, a confirmação continua obrigatória.
- **Sem TTY:** a recusa ocorre antes de criar projeto automático (nenhum `Projeto` órfão).
- **`project new` x ADR 015 §11:** `project new` é operação tipada e determinística do
  pesquisador (sem LLM), gravada direto com autor `pesquisador`; alterar um `Problema` já
  confirmado continua sendo via Curator (`v17-graph-cli`).
- **Contexto por sessão:** o bloco do problema é guardado por sessão mestra no orquestrador
  (`_project_blocks`), não como estado único da instância.
