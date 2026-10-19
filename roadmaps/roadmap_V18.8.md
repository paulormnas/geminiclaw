# Roadmap V18.8 — Calibração do Veredito

> **Estado (2026-10-19):** Tarefa 1 (`v18.8-verdict-lab`) implementada e mergeada (#222, #224, #225); relatórios da etapa 1 e da etapa 2 em `docs/calibracao-veredito/`. Tarefa 2 (`v18.8-verdict-calibration`) implementada. Tarefa 3 sem spec.

## Objetivo

Calibrar o veredito das hipóteses com dados e erros medidos, para que uma exploração em um único nó consiga chegar a um veredito de solução ou de falha, sem premiar o volume de tentativas, e para que validações em outros nós continuem contribuindo. ADR de origem: [025](../docs/decisions/adr_025_calibracao_do_veredito.md), com a equação do [ADR 015](../docs/decisions/adr_015_modelo_dados_grafo_conhecimento.md) §9.

## Decisões do pesquisador (2026-10-18)

- Variar a configuração conta como exploração (configuração ainda não executada em outro nó); replicar em outro nó conta como validação, com peso menor que a variação.
- Grade sintética antes de mudar a fórmula; a fórmula é ajustada depois, até resultados significativos.
- Relatórios de calibração em `docs/calibracao-veredito/`, escritos para servir à dissertação.

## Dependências

- V18.7 implementada (atendido em 2026-10-18). A bateria da V18.7 e o arquivamento das mudanças dela correm em paralelo e não bloqueiam a Tarefa 1.

## Tarefas

### Tarefa 1: Laboratório do veredito
- **Spec:** [`v18.8-verdict-lab`](../openspec/changes/v18.8-verdict-lab/proposal.md)
- **Critérios de aceite:** [x] variante `atual` idêntica a `compute_verdict` · [x] `replay` reproduz o relatório da etapa 1 · [x] grade, simulação e sensibilidade reprodutíveis pela semente, sem LLM · [x] relatório da etapa 2 em `docs/calibracao-veredito/`
- **Complexidade estimada:** Média

### Tarefa 2: Calibração da fórmula e dos valores
- **Spec:** [`v18.8-verdict-calibration`](../openspec/changes/v18.8-verdict-calibration/proposal.md) (modelo v2 da equação, variante `completa2`; revisão do ADR 015 §9 aprovada pelo pesquisador antes de implementar)
- **Complexidade estimada:** Média

### Tarefa 3: Direção da evidência pela predição
- **Spec:** `v18.8-verdict-direction` (a especificar se os resultados confirmarem a lacuna; ADR 025 §2, pergunta 6)
- **Complexidade estimada:** a definir

## Ordem de implementação

Tarefa 1 → revisão dos resultados com o pesquisador → Tarefa 2 (e 3, se confirmada) → sessões controladas (ADR 025 §3, etapa 3) → bateria no Raspberry Pi (etapa 4, com confirmação).

## Validação da Etapa
- [ ] Todos os testes unitários e de integração passam.
- [ ] Sessões controladas e bateria no Raspberry Pi 5 com a configuração escolhida (com confirmação do pesquisador).
- [ ] ADR 025 marcado como Aceito; ADR 015 §9 revisado, se a fórmula mudar.
- [ ] PRs merged em `dev`; mudanças arquivadas.
