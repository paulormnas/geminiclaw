# Tarefas: v18.5-claim-verification

**Estado (2026-10-08):** Não iniciada — nenhum código mergeado.

Pré-requisitos: `v18.5-numeric-references` (parser, valores resolvidos, `ReportPipeline`) e
`v18.5-model-catalog-locality` (alocação e desempate do `validator`). **Aprovação do schema do
grafo** (nó `Afirmacao` e relações) antes da tarefa 1.3.

## 1. Modelo e armazenamento
- [ ] 1.1 `src/claims/model.py`: `Afirmacao`, `StatusAfirmacao`, conclusões.
- [ ] 1.2 `src/claims/store.py`: `afirmacoes.json` atômico, histórico somente acréscimo.
- [ ] 1.3 `src/knowledge/schema.py`: nó `Afirmacao`, `EXTRAIDA_DE`, `CONFERIDA_CONTRA` (após aprovação).

## 2. Verificação
- [ ] 2.1 `src/claims/decompose.py`: conclusões do relatório e de `Descoberta`; segmentação pt-BR; cobertura.
- [ ] 2.2 `src/claims/deterministic.py`: comparadores, igualdade por precisão exibida, `sentido` da métrica, atribuição, negação.
- [ ] 2.3 `ValidatorAgent.verify_claims`: pacote de evidência delimitado, `EgressGate`, JSON validado.
- [ ] 2.4 `src/claims/service.py`: regras do orquestrador (§5), mapeamento `refutada → contestada`, precedência determinística.
- [ ] 2.5 Registro do verificador (família, versão efetiva, família do autor).

## 3. Integração
- [ ] 3.1 Estágio `claims` e seção `claims` no `ReportPipeline`; marcas nos conversores.
- [ ] 3.2 Verificação após `curator.consolidate`/`close_session`; sinalização ao Curator em refutação determinística.
- [ ] 3.3 Ciclos de correção do Summarizer (`CLAIM_REVISION_MAX_CYCLES`).
- [ ] 3.4 Orçamento: `UsageTracker.check()` antes de cada chamada; `pendente` ao esgotar.
- [ ] 3.5 `afirmacoes_pendentes` no `checkpoint.json` e verificação na retomada.
- [ ] 3.6 CLI `claims list` / `claims resolve`.
- [ ] 3.7 `ClaimVerificationReader` em `src/operation_metrics.py`.
- [ ] 3.8 Configurações `CLAIM_*` em `src/config.py` e `.env.example`.

## 4. Testes (um por cenário da spec, no mínimo; LLM simulado)
- [ ] 4.1 Decomposição e cobertura.
- [ ] 4.2 Determinístico: ordem, igualdade, aproximação, melhor/pior com `sentido`, métricas diferentes, atribuição errada, negação; nenhuma chamada LLM.
- [ ] 4.3 Lote: número de chamadas por conclusão; divisão por tamanho; evidência ausente ou inventada; resposta inválida → `pendente`.
- [ ] 4.4 Efeitos: `contestada` sem mudar arestas nem `Descoberta.status`; parcial; sinalização ao Curator.
- [ ] 4.5 Invariante: `compute_verdict` idêntico para os seis status (propriedade sobre combinações).
- [ ] 4.6 Invariante: ingestão de `Resultado` com registro independe do status.
- [ ] 4.7 Relatório: tabela com todas as afirmações, marcas inline, texto preservado; conversores.
- [ ] 4.8 Orçamento esgotado e modo sem limite.
- [ ] 4.9 Retomada com pendentes.
- [ ] 4.10 Modelo verificador: famílias diferentes/iguais registradas; sem modelo elegível.
- [ ] 4.11 CLI de revisão.
- [ ] 4.12 Ciclos de correção e contestada fora do ciclo.
- [ ] 4.13 Leitor de métricas.

## 5. Fechamento
- [ ] 5.1 Sessões de referência: distribuição de status e custo em tokens no PR.
- [ ] 5.2 Revisão do Analista de Segurança (evidência como dado, egresso).
- [ ] 5.3 Ruff, `uv run pytest -m "unit or integration"`; revisão nos 7 eixos; PR para `dev`.
