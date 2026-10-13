# Proposta: Independência do Julgamento no Roteador

**ID:** `v18.6-validator-independence` · **Versão:** V18.6 ·
**Capacidade:** `llm-providers` (reutilizada de `v16-model-catalog-router` e `v18.5-model-catalog-locality`)
**ADRs de origem:** [ADR 020](../../../docs/decisions/adr_020_independencia_validator.md) (itens 1 a 8
e 10), que revisa o [ADR 017](../../../docs/decisions/adr_017_catalogo_modelos_roteador.md) §2, §6 e
§7 e o [ADR 019](../../../docs/decisions/adr_019_localidade_dados_proveniencia_resultados.md) §6.
**Origem dos requisitos:** decisão do pesquisador de 2026-10-13: o Validator usa família de modelo
diferente da do Developer; Researcher e Developer podem coincidir.
**Depende de:** aprovação do ADR 020 (Proposto). Nenhuma outra mudança em aberto.
**Habilita:** o item "juiz declarado por combinação" de
[`v18.6-benchmark-harness`](../v18.6-benchmark-harness/proposal.md).

## Por quê

No benchmark de 2026-10-13, cada combinação usou um modelo para todos os papéis: o mesmo modelo
escreveu o plano, o código e as conclusões, e também os julgou. A família diferente só pesa hoje
como desempate do `validator` (`src/llm/routing.py:225-228`). Esse desempate nunca é aplicado com o
catálogo atual (um modelo por grupo de preferência) e é dispensado por pins (`routing.py:197-204`),
dicas de plano (`validate_hint`, `routing.py:285-316`) e pelo modelo de reserva no 429
(`fallback_for`, `src/llm/session.py:79`).

## O que muda

- **Novo:** `LLM_JUDGE_INDEPENDENCE=required|preferred|off`; padrão `required` com
  `LLM_DATA_POLICY=third_party_allowed` e `preferred` com `self_hosted_only`.
- **Novo:** requisito de inicialização: família do `validator` diferente da do `developer`.
- **Novo:** conferência no despacho: dica de plano aceita, subtarefa de `base` ou `reviewer` e
  modelo de reserva no 429 são conferidos contra os modelos efetivos dos juízes e julgados.
- **Modificado:** ordem de resolução (pins primeiro; juízes sem pin depois de `developer`/`base`) e
  motivo de descarte `mesma_familia_julgamento` com sugestão acionável.
- **Modificado:** `src/llm/catalog.yaml`: `validator` e `reviewer` com um modelo de nuvem de cada
  família (Claude, Gemini, GPT) antes dos locais.
- **Novo:** registro `independencia_julgamento` no payload da sessão, evento
  `independencia_julgamento` por conferência, banner, relatório e métricas de operação.
- **Novo:** conferência na retomada (V18).
- **Modificado:** juiz da avaliação de comunicação (`scripts/benchmark/comm_judge.py`) exclui as
  famílias de `developer` e `base`.
- **Modificado:** telemetria da revisão de subtarefa registra o papel `validator` (e
  `funcao=revisao_subtarefa`), não `reviewer`, para não confundir com o papel `reviewer`.
- **Fora do escopo:** regra para o Researcher; dois juízes com voto; matriz do benchmark
  (`v18.6-benchmark-harness`).

## Impacto

- **Código:** `src/llm/routing.py` (ordem, descarte, sugestão, `validate_hint`), `src/llm/session.py`
  (`fallback_for`), `src/llm/allocation.py` e o payload da sessão, `src/orchestrator.py` (conferência
  no despacho), `src/session*.py`/retomada, `src/llm/catalog.yaml`, `src/agents/validator_agent.py`
  (rótulo da telemetria), relatório final, `src/operation_metrics*` (resumo),
  `scripts/benchmark/comm_judge.py`, `src/config.py`, `.env.example`.
- **Contratos:** evento novo `independencia_julgamento`; payload da sessão com
  `independencia_julgamento`; motivo de descarte novo; o rótulo de papel das chamadas de revisão de
  subtarefa muda de `reviewer` para `validator` (consumidores da telemetria por papel conferidos na
  tarefa 6.2).
- **Schema de banco:** nenhum (eventos em `payload_json`).
- **Egresso:** com `third_party_allowed`, o juiz pode ir para um provedor de nuvem antes não usado;
  `LLM_PROVIDER_PRIORITY` e a camada de saída do ADR 019 continuam valendo; o banner mostra o
  provedor.
- **Compatibilidade:** `LLM_JUDGE_INDEPENDENCE=off` reproduz o roteamento atual.
- **Custo:** o juiz pode ficar num modelo mais caro que o do Developer.

## Aprovações necessárias

- **Aprovação do ADR 020** e das duas divergências registradas nele.
- Nenhuma alteração de schema, Dockerfile, `docker-compose.yml`, exclusão de arquivos ou `AGENTS.md`.
- **Parecer do Analista de Segurança** sobre o efeito no egresso (design §6).
