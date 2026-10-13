# Tarefas: v18.5-claim-verification

**Estado (2026-10-13):** Mergeada em `dev` (#121). Validada no Pi 5 em sessões reais do benchmark de 2026-10-13: a verificação classificou quase tudo como `nao_verificavel` (investigar).
Pendentes, por dependerem de execução real ou de papel humano: 5.1 (sessões de referência, na bateria do Pi) e
5.2 (revisão do Analista de Segurança). O rótulo `Afirmacao` e as duas relações exigem rodar de novo
`scripts/migrate_v17_knowledge.py` no banco (idempotente) antes do primeiro uso em produção; sem isso o nó não é
gravado (aviso no log) e o arquivo `afirmacoes.json` da sessão continua sendo a fonte. Desvios em relação ao design
registrados abaixo (3.1, 3.7).

Pré-requisitos: `v18.5-numeric-references` (parser, valores resolvidos, `ReportPipeline`) e
`v18.5-model-catalog-locality` (alocação e desempate do `validator`). **Aprovação do schema do
grafo** (nó `Afirmacao` e relações) antes da tarefa 1.3.

## 1. Modelo e armazenamento
- [x] 1.1 `src/claims/model.py`: `Afirmacao`, `StatusAfirmacao`, conclusões.
- [x] 1.2 `src/claims/store.py`: `afirmacoes.json` atômico, histórico somente acréscimo.
- [x] 1.3 `src/knowledge/schema.py`: nó `Afirmacao`, `EXTRAIDA_DE`, `CONFERIDA_CONTRA` (após aprovação).

## 2. Verificação
- [x] 2.1 `src/claims/decompose.py`: conclusões do relatório e de `Descoberta`; segmentação pt-BR; cobertura.
- [x] 2.2 `src/claims/deterministic.py`: comparadores, igualdade por precisão exibida, `sentido` da métrica, atribuição, negação.
- [x] 2.3 `ValidatorAgent.verify_claims`: pacote de evidência delimitado, `EgressGate`, JSON validado.
- [x] 2.4 `src/claims/service.py`: regras do orquestrador (§5), mapeamento `refutada → contestada`, precedência determinística.
- [x] 2.5 Registro do verificador (família, versão efetiva, família do autor).

## 3. Integração
- [x] 3.1 Estágio `claims` e seção `claims` no `ReportPipeline`; marcas nos conversores. *Desvio:* o estágio roda depois de `verify` (as marcas `[A<n> · …]` têm dígito e não podem ser vistas pelo verificador de números); a verificação assíncrona é despachada ao laço do orquestrador com `run_coroutine_threadsafe`.
- [x] 3.2 Verificação após `curator.consolidate`/`close_session`; sinalização ao Curator em refutação determinística.
- [x] 3.3 Ciclos de correção do Summarizer (`CLAIM_REVISION_MAX_CYCLES`).
- [x] 3.4 Orçamento: `UsageTracker.check()` antes de cada chamada; `pendente` ao esgotar.
- [x] 3.5 `afirmacoes_pendentes` no `checkpoint.json` e verificação na retomada.
- [x] 3.6 CLI `claims list` / `claims resolve`.
- [x] 3.7 `ClaimVerificationReader`. *Desvio:* vive em `src/claims/metrics.py` (o módulo `src/operation_metrics.py` ainda não existe; `v18.5-operation-metrics` o registra como produtor do grupo `verificacao`).
- [x] 3.8 Configurações `CLAIM_*` em `src/config.py` e `.env.example`.

## 4. Testes (um por cenário da spec, no mínimo; LLM simulado)
- [x] 4.1 Decomposição e cobertura.
- [x] 4.2 Determinístico: ordem, igualdade, aproximação, melhor/pior com `sentido`, métricas diferentes, atribuição errada, negação; nenhuma chamada LLM.
- [x] 4.3 Lote: número de chamadas por conclusão; divisão por tamanho; evidência ausente ou inventada; resposta inválida → `pendente`.
- [x] 4.4 Efeitos: `contestada` sem mudar arestas nem `Descoberta.status`; parcial; sinalização ao Curator.
- [x] 4.5 Invariante: `compute_verdict` idêntico para os seis status (propriedade sobre combinações).
- [x] 4.6 Invariante: ingestão de `Resultado` com registro independe do status.
- [x] 4.7 Relatório: tabela com todas as afirmações, marcas inline, texto preservado; conversores.
- [x] 4.8 Orçamento esgotado e modo sem limite.
- [x] 4.9 Retomada com pendentes.
- [x] 4.10 Modelo verificador: famílias diferentes/iguais registradas; sem modelo elegível.
- [x] 4.11 CLI de revisão.
- [x] 4.12 Ciclos de correção e contestada fora do ciclo.
- [x] 4.13 Leitor de métricas.

## 5. Fechamento
- [ ] 5.1 Sessões de referência: distribuição de status e custo em tokens no PR.
- [ ] 5.2 Revisão do Analista de Segurança (evidência como dado, egresso).
- [x] 5.3 Ruff, `uv run pytest -m "unit or integration"`; revisão nos 7 eixos; PR para `dev`.
