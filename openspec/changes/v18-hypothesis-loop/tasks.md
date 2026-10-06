# Tarefas: v18-hypothesis-loop

## 1. Plano e gravação
- [ ] 1.1 Formato do plano com `hipoteses`, `decisoes`, `respostas_sugestoes`, `hypothesis_ref`; parser retrocompatível.
- [ ] 1.2 Instrução do Researcher: formular hipóteses, registrar decisões com alternativas descartadas, responder a sugestões.
- [ ] 1.3 `src/knowledge/hypotheses.py`: gravação de hipóteses (com deduplicação), decisões e `TESTA`.
- [ ] 1.4 Substituir a regra provisória de hipóteses da ingestão V17.
- [ ] 1.5 Avaliação posterior determinística de `Decisao`.

## 2. Governança e prioridade
- [ ] 2.1 Aprovação em lote no `assisted`; execução por prioridade no `semi`/`auto`.
- [ ] 2.2 Cálculo de prioridade e configurações (`HYPOTHESIS_PRIORITY_WEIGHTS`, `HYPOTHESES_PER_CYCLE`).

## 3. Curator
- [ ] 3.1 `suggest_paths` com fontes permitidas; `curator_suggestions.jsonl`.
- [ ] 3.2 Lições de caminho a partir de decisões avaliadas.

## 4. Oportunidades
- [ ] 4.1 `geminiclaw opportunities list|approve|reject`; transições de status e `GEROU`.

## 5. Ciclo e parada
- [ ] 5.1 Reescrever o laço do `AutonomousLoop._run_complex_path` conforme o design; novo significado de `MAX_PLAN_RETRIES`.
- [ ] 5.2 Critérios "solução encontrada" (com confirmação no `assisted`) e "sem caminhos promissores".
- [ ] 5.3 **Aprovação:** valor `sem_caminhos_promissores` em `Sessao.motivo_parada`.

## 6. Testes
- [ ] 6.1 `assisted`: hipótese do Researcher não executa sem aprovação; hipótese do pesquisador executa.
- [ ] 6.2 `auto`: executa as `HYPOTHESES_PER_CYCLE` de maior prioridade.
- [ ] 6.3 Decisão registra `ESCOLHEU` e `DESCARTOU` com motivo; alternativa descartada inexistente vira nó `abandonada`.
- [ ] 6.4 Sugestão não respondida faz o plano voltar ao Researcher uma vez.
- [ ] 6.5 Oportunidade `documentada` nunca é sugerida; após `approve`, pode ser.
- [ ] 6.6 Parada por solução (veredito ≥ 0,3 e alvo atingido); no `assisted` pergunta antes.
- [ ] 6.7 Parada por falta de caminhos.
- [ ] 6.8 Hipótese quase idêntica (≥ 0,90) a uma existente reutiliza o nó.
- [ ] 6.9 Plano no formato antigo continua funcionando.

- [ ] 6.99 Gate humano não pode aceitar resposta do consultor: aprovação de Oportunidade, confirmação de Problema, aprovação de termo de vocabulário, autorização de escrita em instrumento e ativação do modo sem limite exigem ação explícita do pesquisador (terminal/CLI); a resposta de `ask_researcher` (inclusive do Researcher consultor, `v18-researcher-consult`) nunca conta como autorização. Teste: gate com resposta do consultor continua pendente.

## 7. Fechamento
- [ ] 7.1 Ruff, testes, revisão nos 7 eixos, PR.
