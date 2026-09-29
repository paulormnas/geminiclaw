# Roadmap V18.5 — Localidade dos Dados e Proveniência dos Resultados

## Objetivo

Tornar verificáveis duas garantias do assistente (ADR 019): **quais dados de pesquisa saem do
nó de referência, e para onde**, e **de onde vem cada número entregue**. Inclui a camada única
de saída, o registro de execuções encadeado por hash, o sandbox em fases de rede, as
referências numéricas no relatório, a verificação das conclusões por afirmações, as métricas de
operação e o modo sem limite.

## Dependências

- V18 concluída (limites de uso, continuidade e ciclo de hipóteses).
- Mudanças em andamento dos ADRs 017 e 018 concluídas; em especial, o catálogo e o roteador
  do ADR 017 (`src/llm/catalog.yaml`, `resolve`), que a Tarefa 1 estende.
- `v17-research-project` concluída (todo registro de execução pertence a um projeto).
- Esta etapa precede a V19 (controle de equipamentos) e é pré-requisito da V20 (federação).

## Tarefas

### Tarefa 1: Localidade declarada no catálogo e versão efetiva do modelo
- **Spec:** [`v18.5-model-catalog-locality`](../openspec/changes/v18.5-model-catalog-locality/proposal.md)
- **Critérios de aceite:** [ ] `localidade`, `aceita_dados_brutos` e `familia_modelo` no catálogo · [ ] perfil de alocação no banner, na sessão e no relatório · [ ] `versao_efetiva` por chamada
- **Complexidade estimada:** Média

### Tarefa 2: Camada única de saída
- **Spec:** [`v18.5-egress-gate`](../openspec/changes/v18.5-egress-gate/proposal.md)
- **Critérios de aceite:** [ ] todo envio externo passa pelo `EgressGate` · [ ] filtro da saída do sandbox · [ ] contaminação entre papéis · [ ] registro de egresso e limite de volume
- **Complexidade estimada:** Alta

### Tarefa 3: Ingestão de dados de pesquisa
- **Spec:** [`v18.5-research-data-ingestion`](../openspec/changes/v18.5-research-data-ingestion/proposal.md)
- **Critérios de aceite:** [ ] sem linhas brutas nem extremos exatos para modelos sem `aceita_dados_brutos` · [ ] tamanho mínimo de grupo · [ ] marcações de arquivo · [ ] visão pela camada de saída
- **Complexidade estimada:** Média

### Tarefa 4: Sandbox em fases de rede
- **Spec:** [`v18.5-sandbox-phases`](../openspec/changes/v18.5-sandbox-phases/proposal.md)
- **Critérios de aceite:** [ ] instalação e busca de ativos sem dados · [ ] execução sem rede · [ ] erro acionável para download não declarado
- **Complexidade estimada:** Média

### Tarefa 5: Registro de execuções encadeado por hash
- **Spec:** [`v18.5-execution-provenance`](../openspec/changes/v18.5-execution-provenance/proposal.md)
- **Critérios de aceite:** [ ] registros de início e término · [ ] acréscimo serializado · [ ] `provenance verify` · [ ] ponta da cadeia no checkpoint e no relatório
- **Complexidade estimada:** Alta

### Tarefa 6: Referências numéricas
- **Spec:** [`v18.5-numeric-references`](../openspec/changes/v18.5-numeric-references/proposal.md)
- **Critérios de aceite:** [ ] `{{res}}`, `{{calc}}` e `{{src}}` renderizados · [ ] verificador de números · [ ] métricas literais sinalizadas
- **Complexidade estimada:** Alta

### Tarefa 7: Verificação das conclusões por afirmações
- **Spec:** [`v18.5-claim-verification`](../openspec/changes/v18.5-claim-verification/proposal.md)
- **Critérios de aceite:** [ ] status por afirmação · [ ] refutação só por LLM vira contestada · [ ] pendentes verificadas na retomada
- **Complexidade estimada:** Alta

### Tarefa 8: Métricas de operação e modo sem limite
- **Spec:** [`v18.5-operation-metrics`](../openspec/changes/v18.5-operation-metrics/proposal.md)
- **Critérios de aceite:** [ ] métricas por sessão no relatório · [ ] modo sem limite explícito com confirmação · [ ] limites de retentativas mantidos
- **Complexidade estimada:** Média

## Ordem de implementação

```
Tarefa 1 ─► Tarefa 2 ─► Tarefa 3
Tarefa 4 ─► Tarefa 5 ─► Tarefa 6 ─► Tarefa 7
                    (2, 5, 7) ─► Tarefa 8
```

As trilhas 1–3 e 4–7 podem avançar em paralelo. A Tarefa 7 depende também da Tarefa 1.
As Tarefas 2 e 3 devem ser entregues juntas: sem a ingestão nova, a camada de saída retém
todo o `input_context/` para modelos sem `aceita_dados_brutos`.

## Validação da Etapa

- [ ] Todos os testes unitários e de integração passam.
- [ ] Sessão com modelo sem `aceita_dados_brutos` cujo registro de egresso não contém linhas
      brutas nem extremos exatos.
- [ ] Relatório final sem números de origem desconhecida, ou com eles marcados.
- [ ] `provenance verify` íntegro após sessão interrompida e retomada.
- [ ] Revisão do Analista de Segurança (egresso, sandbox e schema).
- [ ] ADR 019 marcado como Aceito; PRs merged em `dev`; mudanças arquivadas.
