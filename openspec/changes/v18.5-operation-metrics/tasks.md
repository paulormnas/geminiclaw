# Tarefas: v18.5-operation-metrics

> Pré-requisitos: V18 concluída (`v18-usage-limits`, `v18-research-continuity`,
> `v18-hypothesis-loop`). Os grupos de métricas de `v18.5-egress-gate`,
> `v18.5-execution-provenance`, `v18.5-numeric-references` e `v18.5-claim-verification` podem
> ficar `indisponivel` até essas mudanças serem implementadas; o limite de egresso (seção 3)
> exige `v18.5-egress-gate`.

## 1. Orçamento com modo sem limite
- [ ] 1.1 `UsageBudget`: campo `unlimited` (o campo `max_egress_bytes` vem de `v18.5-egress-gate`); limites de tokens, tempo e egresso opcionais só com `unlimited=True`; validação e `to_payload()` (design §2.1).
- [ ] 1.2 `from_config(unlimited=...)` recusa overrides de tokens, tempo e egresso junto com `unlimited`.
- [ ] 1.3 `UsageTracker`/`LimitStatus`: flags de tokens, tempo e egresso sempre falsas e `*_pct=None` no modo sem limite; `tokens_hard_exhausted()` falso; retentativas inalteradas.
- [ ] 1.4 `AutonomousLoop`: sem `gather_timeout` no modo sem limite (`src/autonomous_loop.py:941-945`).
- [ ] 1.5 Garantir que não existe variável de ambiente nem chave de `config` que ative o modo.

## 2. Ativação, confirmação e exibição
- [ ] 2.1 `--unlimited` na CLI principal, em `resume` e em `continue`; confirmação digitando "sem limite"; recusa sem TTY.
- [ ] 2.2 `geminiclaw project unlimited <id> --on|--off` (auditado) e leitura da marcação ao iniciar a sessão; erro acionável se o nó `Projeto` não existir.
- [ ] 2.3 Recusar `--unlimited` se os critérios `solucao_encontrada`/`sem_caminhos_promissores` não estiverem disponíveis.
- [ ] 2.4 `payload["budget"]` com `unlimited`, origem e instante; evento `unlimited_mode_confirmed`.
- [ ] 2.5 Banner com "SEM LIMITE", retentativas mantidas e cadência dos avisos (`src/cli.py:771-778`).

## 3. Limite de egresso no orçamento
- [ ] 3.1 Usar `max_egress_bytes`, `egress_bytes_for_session` e `StopReason.EGRESS` de `v18.5-egress-gate` (design §3).
- [ ] 3.2 Prioridade em `stop_reason`: tokens > tempo > egresso > conexão.
- [ ] 3.3 `--max-egress-bytes` na CLI; default de `EGRESS_SESSION_MAX_BYTES`.
- [ ] 3.4 Acrescentar `limite_egresso`, `interrompida_pesquisador` (e `sem_caminhos_promissores`, se ausente) em `Sessao.motivo_parada` (`src/knowledge/schema.py:127-136`), após confirmação do pesquisador.

## 4. Avisos periódicos
- [ ] 4.1 `UNLIMITED_NOTICE_INTERVAL_MINUTES` e `UNLIMITED_NOTICE_TOKEN_STEP` em `src/config.py` e `.env.example`, com validação > 0.
- [ ] 4.2 Verificação da cadência nos pontos de checagem do loop; aviso no terminal em todos os modos; suspensão no `assisted`.
- [ ] 4.3 Evento `unlimited_notice` e contador em `operation_metrics`.
- [ ] 4.4 `_check_operational_thresholds` usa o orçamento efetivo; omite tokens, tempo e custo no modo sem limite.

## 5. Interrupção graciosa
- [ ] 5.1 Primeiro Ctrl+C sinaliza o loop e executa `_close_session` com `interrompida_pesquisador`; segundo Ctrl+C mantém o comportamento atual (`src/cli.py:1102-1130`).
- [ ] 5.2 Interrupção registrada como intervenção humana.

## 6. Agregação de métricas
- [ ] 6.1 `src/operation_metrics.py`: `MetricsGroupReader`, `MetricsUnavailable`, `aggregate_operation_metrics`, estados `disponivel`/`indisponivel`/`erro`.
- [ ] 6.2 Leitores existentes: `custo_recursos` (token_usage, subtask_metrics, hardware_snapshots; consulta nova de média de CPU em `src/telemetry.py`) e `intervencoes_humanas` (payload da sessão, eventos de hipótese/oportunidade, suspensões, interrupções), `verificacao.ciclos_rejeicao_plano`.
- [ ] 6.3 Pontos de extensão para os leitores de egress-gate, numeric-references, execution-provenance e claim-verification (cada mudança registra o seu).
- [ ] 6.4 Agregação no fechamento e no fim normal; gravação em `payload["operation_metrics"]` e `session_metadata.json`.
- [ ] 6.5 `geminiclaw --metrics <id>` mostra `operation_metrics` e recalcula com `parcial=true` para sessões interrompidas.

## 7. Relatório
- [ ] 7.1 `render_operation_metrics_section` (Markdown determinístico, delimitado) e anexação ao `relatorio_final.md` após o Summarizer.
- [ ] 7.2 Remover `get_summarized_stats` do prompt do Summarizer (`src/autonomous_loop.py:1476-1478`).
- [ ] 7.3 Combinar com `v18.5-numeric-references` o tratamento da seção delimitada como contagens do orquestrador.
- [ ] 7.4 Soma informativa da cadeia de sessões continuadas.

## 8. Testes
- [ ] 8.1 `UsageBudget`: validação nos dois modos; overrides incompatíveis; `to_payload()`.
- [ ] 8.2 Modo sem limite: tokens e tempo acima dos defaults não fecham; conexão fecha com `limite_conexao`; tarefa abandonada por retentativas.
- [ ] 8.3 Critérios `solucao_encontrada` e `sem_caminhos_promissores` fecham a sessão no modo sem limite.
- [ ] 8.4 Confirmação: resposta errada e ausência de TTY não iniciam a sessão; retomada não herda o modo; marcação de projeto pede confirmação.
- [ ] 8.5 Plano, resposta ou mensagem IPC de agente não altera o orçamento.
- [ ] 8.6 Limite de egresso fecha com `limite_egresso` fora do modo sem limite; não fecha no modo sem limite.
- [ ] 8.7 `EgressGate` retém despejo tabular no modo sem limite (integração, quando egress-gate existir).
- [ ] 8.8 Avisos por tempo e por tokens (relógio e leitor injetados); cadência ≤ 0 falha; suspensão no `assisted`.
- [ ] 8.9 Avisos G5 com `--max-tokens` respeitam o orçamento efetivo.
- [ ] 8.10 Primeiro Ctrl+C grava checkpoint com `interrompida_pesquisador`; segundo encerra imediatamente.
- [ ] 8.11 Agregação: grupos com dados sintéticos de teste nos leitores injetados; produtor ausente vira `indisponivel`; exceção vira `erro` sem bloquear o fechamento; custo `null` não é somado como zero.
- [ ] 8.12 Relatório: seção delimitada com os mesmos números do payload; prompt do Summarizer sem estatísticas.

## 9. Fechamento
- [ ] 9.1 `.env.example` atualizado; Ruff; `uv run pytest -m "unit or integration" -v`.
- [ ] 9.2 Revisão do Analista de Segurança (ativação do modo, ausência de ativação por agente).
- [ ] 9.3 Revisão nos 7 eixos, PR para `dev` destacando a mudança de comportamento do Ctrl+C.
