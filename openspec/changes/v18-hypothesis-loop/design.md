# Design: Ciclo de Hipóteses e Exploração Ativa

## 1. O ciclo

```
início (projeto com Problema confirmado; retomada se houver checkpoint)
│
├─► 1. Researcher: formula/atualiza hipóteses + decisões + plano (DAG)
│       entrada: problema, insumos, related_experience, caminhos sem conclusão,
│                oportunidades aprovadas, sugestões do Curator, vereditos atuais
├─► 2. Governança por SessionMode (aprovação no assisted)
├─► 3. Execução do DAG (Developer no sandbox) → ingestão → recálculo de vereditos
├─► 4. Curator: consolida (descobertas) + suggest_paths
├─► 5. Checkpoint
└─► 6. Parada? solução encontrada | sem caminhos promissores | limite de uso (v18-usage-limits)
        não → volta a 1 (modo REPLAN)
```

`MAX_PLAN_RETRIES` deixa de encerrar a exploração: passa a contar apenas **planos
consecutivos rejeitados pelo Validator**. O circuit breaker de progresso zero (V12.5.1)
permanece.

## 2. Formato do plano

Acrescenta ao JSON do Researcher:

```json
{
  "hipoteses": [
    {"ref": "h1", "id": null, "enunciado": "Gradient boosting supera a regressão linear em R² ≥ 0,05",
     "justificativa": "…", "origem": "researcher",
     "derivada_de": ["<id Descoberta|Oportunidade|Insumo>"],
     "custo_estimado": "baixo | medio | alto",
     "abordagem": {"nome": "gradient boosting", "tipo": "algoritmo"}}
  ],
  "decisoes": [
    {"contexto": "Escolha do modelo inicial",
     "escolhido": {"tipo": "Hipotese", "ref": "h1"},
     "descartados": [{"tipo": "Abordagem", "nome": "rede neural profunda",
                      "motivo": "dataset pequeno (~2 mil linhas); risco de sobreajuste"}],
     "criterio": "evidencia_previa",
     "justificativa": "…",
     "informada_por": ["<id Descoberta>"]}
  ],
  "respostas_sugestoes": [
    {"sugestao_id": "…", "decisao": "aceita | recusada", "motivo": "…", "hipotese_ref": "h2"}
  ],
  "subtarefas": [ { "...campos atuais...": "…", "hypothesis_ref": "h1", "approach": {"…": "…"} } ]
}
```

- `id` preenchido quando a hipótese já existe (continuação); `ref` para as novas.
- Planos antigos (lista simples de subtarefas) continuam aceitos pelo parser — as subtarefas
  caem na regra provisória da V17.
- Toda escolha entre alternativas **deve** gerar uma `decisao` (a instrução exige ao menos uma
  por plano ou replanejamento que introduza hipótese nova).

## 3. Gravação

`src/knowledge/hypotheses.py`:

- Hipóteses novas: `Hipotese(status="proposta", origem=...)` + `SOBRE->Problema` +
  `PROPOE->Abordagem` (resolvida como na ingestão) + `DERIVADA_DE`. Antes de criar, busca
  semântica entre hipóteses do projeto: ≥ 0,90 → reutiliza a existente (o plano é reescrito
  para o ID existente).
- Decisões: `Decisao` + `TOMADA_EM->Sessao` + `ESCOLHEU` + `DESCARTOU {motivo}` (alternativas
  descartadas que não existem como nó são criadas como `Abordagem` ou `Hipotese` com status
  `abandonada`, para que o caminho não seguido fique registrado) + `INFORMADA_POR`.
- Subtarefas: `Experimento-TESTA->Hipotese` pelo `hypothesis_ref`.
- **Avaliação posterior:** quando uma hipótese escolhida atinge `|veredito| ≥ 0,3`,
  `Decisao.resultado_posterior` é preenchido deterministicamente (`"acertada"` se veredito
  positivo, `"nao_acertada"` se negativo, com o valor). O Curator transforma decisões avaliadas
  em `Descoberta(tipo="licao_de_caminho")` quando houver lição transferível.

## 4. Governança por SessionMode

| Origem da hipótese | `assisted` | `semi` | `auto` |
|---|---|---|---|
| `pesquisador` | executa | executa | executa |
| `researcher` / `curator` / `oportunidade` | **aprovação obrigatória** antes de executar (CLI: aprovar, rejeitar com motivo, editar enunciado) | executa as de maior prioridade; notifica | executa as de maior prioridade |

Hipótese rejeitada: `status="abandonada"` com motivo (auditado, autor `pesquisador`).
Aprovação é pedida em lote, uma vez por ciclo.

## 5. Prioridade de hipóteses

```
prioridade = 0,35·relevancia + 0,30·apoio_previo + 0,20·novidade + 0,15·(1 − custo)
```

| Termo | Cálculo (sem LLM, exceto custo) |
|---|---|
| `relevancia` | similaridade entre a hipótese e o `Problema` do projeto |
| `apoio_previo` | `max(0, veredito)` da melhor `Descoberta`/atalho `FUNCIONOU_PARA` da abordagem proposta em problemas similares (`related_experience`); 0,5 se não há experiência; 0 se há `FALHOU_PARA` forte (≤ −0,5) em problema com similaridade ≥ 0,8 |
| `novidade` | 1 − maior similaridade com hipóteses já testadas (`validada`/`refutada`) no projeto |
| `custo` | `custo_estimado` do Researcher: baixo 0, médio 0,5, alto 1 |

Pesos em configuração (`HYPOTHESIS_PRIORITY_WEIGHTS`). No `semi`/`auto`, executam-se por ciclo
as `HYPOTHESES_PER_CYCLE` (default 2) de maior prioridade.

## 6. Sugestões do Curator

Após consolidar, o Curator chama `suggest_paths(max=CURATOR_MAX_SUGGESTIONS)` (default 3).
Fontes permitidas:

- `caminho_sem_conclusao` com `proximo_passo_sugerido`;
- variações de abordagens com veredito positivo em problemas similares (`related_experience`);
- alternativas a hipóteses refutadas, a partir de `licao_de_caminho`;
- **oportunidades com `status="aprovada"`** (nunca `documentada`).

Cada sugestão: `{id, texto, fundamento_ids, tipo}` em `outputs/<sessão>/curator_suggestions.jsonl`.
O Researcher recebe as pendentes no próximo `REPLAN` e **deve responder a cada uma**
(`respostas_sugestoes`); respostas sem cobertura fazem o plano voltar ao Researcher uma vez.
Aceitas geram hipóteses com `origem="curator"` e `DERIVADA_DE` o fundamento; recusadas ficam
registradas com motivo (e viram `DESCARTOU` numa `Decisao`).

## 7. Oportunidades — decisão humana

```
geminiclaw opportunities list [--project ID] [--status documentada]
geminiclaw opportunities approve <id> [--motivo TEXTO]
geminiclaw opportunities reject <id> --motivo TEXTO
```

Comandos determinísticos (`Actor` pesquisador, auditados), como os de vocabulário. Aprovar
muda para `aprovada` com `decidido_por`, `decidido_em`, `motivo_decisao`; a oportunidade passa
a ser elegível como sugestão; quando vira hipótese, `Oportunidade-GEROU->Hipotese` e status
`em_investigacao`; quando a hipótese conclui, `concluida`. Nenhuma oportunidade é investigada
sem aprovação, em nenhum modo.

## 8. Critérios de parada

- **Solução encontrada:** alguma hipótese `SOBRE` o problema tem
  `veredito ≥ SOLUTION_MIN_VERDICT` (default 0,3 — evidência moderada) **e** o melhor
  resultado validado atinge o `alvo` do `criterio_sucesso`. No `assisted`, o pesquisador
  confirma se para ou continua explorando; no `semi`/`auto`, para com
  `motivo_parada="solucao_encontrada"`.
- **Sem caminhos promissores:** o Researcher não propõe hipótese nova, não há hipótese
  aprovada pendente e o Curator não tem sugestões → `motivo_parada="sem_caminhos_promissores"`
  (novo valor de enumeração).
- **Limite de uso:** `v18-usage-limits`.

Em todos os casos, o fechamento grava checkpoint e registra caminhos sem conclusão.

## Análise de impacto (6 eixos)

| Eixo | Impacto |
|---|---|
| Orquestrador & Loop | Ciclo contínuo com critérios de parada; `MAX_PLAN_RETRIES` com novo significado. |
| Agentes & Prompts | Formato do plano com hipóteses, decisões e respostas; `suggest_paths` do Curator. |
| Sandboxes & Containers | Nenhum. |
| Persistência | `Hipotese`, `Decisao` e arestas de raciocínio; novo valor em `motivo_parada`. |
| Segurança | Oportunidades e hipóteses de agentes sob decisão humana conforme o modo. |
| Testes & Telemetria | Contagem de ciclos, hipóteses, sugestões aceitas/recusadas por sessão. |

## Riscos

- **Ciclo improdutivo** Curator ↔ Researcher — mitigação: limites de uso, circuit breaker de
  progresso zero, critério "sem caminhos promissores", novidade na prioridade.
- **Plano mais complexo para LLMs locais** — mitigação: parser tolerante, reparo de JSON,
  retrocompatibilidade com o formato antigo.
