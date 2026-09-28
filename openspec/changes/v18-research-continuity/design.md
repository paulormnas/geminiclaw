# Design: Continuidade da Pesquisa entre Execuções

## 1. Checkpoint

Arquivo `outputs/<sessão>/checkpoint.json`, gravado de forma **atômica** (arquivo temporário
no mesmo diretório → `fsync` → `os.replace`), com `versao_checkpoint` para evolução.

```json
{
  "versao_checkpoint": 1,
  "session_id": "…", "project_id": "…", "continues_session_id": null,
  "atualizado_em": "ISO-8601",
  "estado": "em_execucao | fechado | interrompido",
  "motivo_parada": null,
  "prompt_original": "…", "modo": "assisted",
  "orcamento": {"…": "…"}, "consumo": {"tokens": 0, "minutos": 0, "retentativas_conexao": 0},
  "plano": {
    "versao": 3,
    "subtarefas": [
      {"task_name": "…", "subtask_id": "…", "agent_id": "developer",
       "status": "concluida | em_andamento | pendente | abandonada | falhou",
       "tentativas": 1, "depends_on": ["…"], "hypothesis_id": "…",
       "artefatos": ["…"], "resultado_resumo": "…"}
    ]
  },
  "hipoteses": [{"id": "…", "status": "em_teste", "veredito": 0.12}],
  "decisoes": ["<ids de Decisao>"],
  "descobertas_sessao": ["<ids>"],
  "sinalizacoes_pendentes": 2,
  "curator_pendente": false
}
```

O checkpoint referencia IDs do grafo, mas é **autossuficiente** para retomar o plano mesmo com
o grafo indisponível (resumos textuais incluídos).

**Momentos de gravação:** criação/alteração do plano; início e fim de cada subtarefa;
abandono de tarefa; checkpoint do Curator; fechamento. Nunca depende do encerramento normal.

## 2. Batimento e paradas inesperadas

- `SessionManager.heartbeat(session_id)` atualiza `updated_at` a cada
  `SESSION_HEARTBEAT_SECONDS` (30) enquanto a sessão roda.
- Na inicialização do orquestrador (e antes de `resume`/`continue`): sessões `active` com
  `updated_at` mais antigo que `SESSION_STALE_SECONDS` (300) são marcadas `interrompida`; o
  checkpoint recebe `estado="interrompido"`, `motivo_parada="interrompida"`; subtarefas
  `em_andamento` viram `falhou` com causa `infraestrutura` e o evento é ingerido no grafo
  (`v17-structural-fact-ingestion`).

## 3. Retomada

```
geminiclaw resume --session <id>          # retoma uma sessão específica
geminiclaw continue --project <id>        # retoma a sessão mais recente do projeto
```

Sessões retomáveis: `suspended`, `interrompida`, ou fechadas por `limite_*`. Fechadas com
`solucao_encontrada` podem ser continuadas com confirmação ("a pesquisa foi dada como
resolvida; continuar explorando?").

Passos:

1. Carregar o checkpoint da sessão de origem (validar `versao_checkpoint`).
2. Criar **nova sessão** com `continues_session_id` no payload, orçamento novo e o mesmo
   projeto e modo (o modo pode ser alterado por opção).
3. `AgentContext.readable_dirs` inclui os diretórios de saída das sessões anteriores da
   cadeia — o Developer lê artefatos anteriores; escreve só na sessão nova.
4. Montar o **contexto de retomada** do Researcher:
   - estado do plano (concluídas com resumo; abandonadas com motivo; pendentes);
   - hipóteses abertas e seus vereditos;
   - `Descoberta`s `caminho_sem_conclusao` com `proximo_passo_sugerido`;
   - `related_experience` do problema do projeto (grafo);
   - sinalizações ao Curator ainda pendentes.
5. O Researcher replaneja em modo `REPLAN`: subtarefas concluídas **nunca** são repetidas
   (regra existente); pendentes podem ser mantidas ou reformuladas; abandonadas só voltam com
   justificativa de mudança de abordagem.
6. Se `curator_pendente` era `true`, o Curator executa `close_session` da sessão anterior
   antes do novo planejamento.

O comando `resume` atual (reinício a partir do prompt) é substituído; o texto de "limitação
conhecida" em `resume_session` é removido.

## Análise de impacto (6 eixos)

| Eixo | Impacto |
|---|---|
| Orquestrador & Loop | Gravação de checkpoint; retomada com plano existente; detecção de paradas. |
| Agentes & Prompts | Contexto de retomada no Researcher. |
| Sandboxes & Containers | Nenhum. |
| Persistência | `checkpoint.json`; status `interrompida` e `continues_session_id` no payload. |
| Segurança | Leitura de sessões anteriores restrita às do mesmo projeto; escrita só na sessão atual. |
| Testes & Telemetria | Testes de gravação atômica, interrupção simulada e retomada. |

## Riscos

- **Checkpoint corrompido** por falta de energia no meio da escrita — mitigado pela escrita
  atômica; se inválido, usar o `.bak` anterior mantido a cada gravação.
- **Plano retomado desatualizado** frente ao grafo — mitigado pelo replanejamento obrigatório
  na retomada.
