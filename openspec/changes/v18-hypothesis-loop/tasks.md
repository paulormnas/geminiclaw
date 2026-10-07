# Tarefas: v18-hypothesis-loop

## 1. Plano e gravação
- [x] 1.1 Formato do plano com `hipoteses`, `decisoes`, `respostas_sugestoes`, `hypothesis_ref`; parser retrocompatível.
- [x] 1.2 Instrução do Researcher: formular hipóteses, registrar decisões com alternativas descartadas, responder a sugestões.
- [x] 1.3 `src/knowledge/hypotheses.py`: gravação de hipóteses (com deduplicação), decisões e `TESTA`.
- [x] 1.4 Substituir a regra provisória de hipóteses da ingestão V17.
- [x] 1.5 Avaliação posterior determinística de `Decisao`.

## 2. Governança e prioridade
- [x] 2.1 Aprovação em lote no `assisted`; execução por prioridade no `semi`/`auto`.
- [x] 2.2 Cálculo de prioridade e configurações (`HYPOTHESIS_PRIORITY_WEIGHTS`, `HYPOTHESES_PER_CYCLE`).

## 3. Curator
- [x] 3.1 `suggest_paths` com fontes permitidas; `curator_suggestions.jsonl`.
- [x] 3.2 Lições de caminho a partir de decisões avaliadas.

## 4. Oportunidades
- [x] 4.1 `geminiclaw opportunities list|approve|reject`; transições de status e `GEROU`.

## 5. Ciclo e parada
- [x] 5.1 Reescrever o laço do `AutonomousLoop._run_complex_path` conforme o design; novo significado de `MAX_PLAN_RETRIES`.
- [x] 5.2 Critérios "solução encontrada" (com confirmação no `assisted`) e "sem caminhos promissores".
- [x] 5.3 **Aprovação:** valor `sem_caminhos_promissores` em `Sessao.motivo_parada`.

## 6. Testes
- [x] 6.1 `assisted`: hipótese do Researcher não executa sem aprovação; hipótese do pesquisador executa.
- [x] 6.2 `auto`: executa as `HYPOTHESES_PER_CYCLE` de maior prioridade.
- [x] 6.3 Decisão registra `ESCOLHEU` e `DESCARTOU` com motivo; alternativa descartada inexistente vira nó `abandonada`.
- [x] 6.4 Sugestão não respondida faz o plano voltar ao Researcher uma vez.
- [x] 6.5 Oportunidade `documentada` nunca é sugerida; após `approve`, pode ser.
- [x] 6.6 Parada por solução (veredito ≥ 0,3 e alvo atingido); no `assisted` pergunta antes.
- [x] 6.7 Parada por falta de caminhos.
- [x] 6.8 Hipótese quase idêntica (≥ 0,90) a uma existente reutiliza o nó.
- [x] 6.9 Plano no formato antigo continua funcionando.

- [x] 6.99 Gate humano não pode aceitar resposta do consultor: aprovação de Oportunidade, confirmação de Problema, aprovação de termo de vocabulário, autorização de escrita em instrumento e ativação do modo sem limite exigem ação explícita do pesquisador (terminal/CLI); a resposta de `ask_researcher` (inclusive do Researcher consultor, `v18-researcher-consult`) nunca conta como autorização. Teste: gate com resposta do consultor continua pendente.

## 7. Fechamento
- [x] 7.1 Ruff, testes, revisão nos 7 eixos, PR. (revisão nos 7 eixos: a cargo do revisor, após o PR)

## 8. Pendências registradas na implementação (2026-10-07)
- [ ] 8.1 **Pendente (sem AGE neste ambiente):** validar com Apache AGE real as leituras novas do ciclo — `find_nodes` por
  `projeto_id`/`status` em `Hipotese`/`Decisao`/`Oportunidade`/`Descoberta`, `neighbors` das relações `PROPOE`,
  `ESCOLHEU`, `DESCARTOU`, `GEROU`, `FUNCIONOU_PARA`/`FALHOU_PARA`, e as escritas `Decisao-DESCARTOU {motivo}` e
  `Oportunidade.status` (`aprovada` -> `em_investigacao` -> `concluida`). Hoje só o `InMemoryGraphStore` as cobre.
- [ ] 8.2 **Pendente:** as decisões reservadas `autorizar_escrita_instrumento` e `ativar_modo_sem_limite` seguem sem
  ponto de decisão no código (`v19-equipment-control` e `v18-usage-limits`); o gate e o teste 6.99 já as tratam como
  pendentes para o pesquisador.
- [ ] 8.3 **Pendente (Arquiteto):** ver "Notas de implementação" em `design.md` (resultado_posterior, alvo ausente,
  formato antigo, motivo de planos rejeitados, ciclos ociosos).
