---
description: Ciclo completo de desenvolvimento de nova feature no GeminiClaw
---

# Workflow: Ciclo de Nova Feature

Fluxo ponta a ponta desde a concepção até o merge de uma nova funcionalidade no GeminiClaw. A especificação de cada funcionalidade é uma mudança OpenSpec (`openspec/changes/<id>/`); etapas inteiras do roadmap são especificadas antes por [`stage-spec.md`](stage-spec.md).

---

## Visão Geral

```
Design ──→ Segurança ──→ Implementação ──→ Testes ──→ PR & Merge
```

Para lotes de mudanças OpenSpec independentes já especificadas (várias ADRs
já desdobradas em `openspec/changes/`), a Fase 3 pode ser executada em modo
paralelo por onda — ver [Modo Paralelo](#modo-paralelo-ondas-de-mudanças-openspec-independentes)
mais abaixo.

---

## Fase 1: Design & Especificação (Arquiteto)

**Regras:** [`architect.md`](../rules/architect.md)

1. Consultar roadmaps (`roadmaps/`), ADRs (`docs/decisions/`) e `openspec/` (README, `project.md`, mudanças em aberto e arquivadas). Se a funcionalidade já tem mudança OpenSpec aprovada, ir para a Fase 2.
2. Avaliar impacto nos 6 eixos conforme [`impact-analysis.md`](impact-analysis.md).
3. Produzir:
   - ADR em `docs/decisions/adr_<NNN>_<titulo>.md` (se decisão arquitetural relevante).
   - Mudança OpenSpec em `openspec/changes/<id>/` (`proposal.md`, `design.md`, `tasks.md`, `specs/<capacidade>/spec.md`), no formato de [`stage-spec.md`](stage-spec.md), com a proposta técnica, a análise de impacto e o plano de implementação dentro dela.
4. Obter aprovação explícita do usuário antes de prosseguir.

---

## Fase 2: Avaliação de Segurança (Analista de Segurança)

**Regras:** [`security-analyst.md`](../rules/security-analyst.md)

1. Ler `proposal.md` e `design.md` da mudança e aplicar STRIDE adaptado para agentes de IA nos componentes afetados.
2. Verificar eixos de segurança: sandbox, segredos, contenção de recursos, rede.
3. Emitir parecer com mitigações necessárias, registrado no `design.md` (mitigação obrigatória vira requisito com cenário na spec).
4. Hardening obrigatório antes da implementação para features que envolvam containers, IPC ou acesso a dados.

---

## Fase 3: Implementação (Desenvolvedor Core/Agentes)

**Regras:** [`backend-dev.md`](../rules/backend-dev.md)

1. Criar worktree dedicada:
   ```bash
   git worktree add .worktrees/<nome-da-feature> -b feat/<nome-da-feature> dev
   cd .worktrees/<nome-da-feature>
   uv sync
   ```

2. Implementar a mudança OpenSpec na ordem de `tasks.md`, marcando as caixas à medida que concluir; divergência ou ambiguidade da spec volta ao Arquiteto antes de seguir. Respeitar:
   - Clean Architecture e DDD.
   - Type hints obrigatórios em funções públicas.
   - Docstrings Google Style.
   - Logging estruturado (JSON), nunca `print()`.
   - `async/await` para I/O, nunca `time.sleep()`.

3. Escrever testes junto com o código:
   - Ao menos um teste por `#### Scenario` da spec.
   - Unitários para cada módulo/classe nova.
   - De integração para fluxos com containers/banco.

4. Commits semânticos ao longo do desenvolvimento:
   ```bash
   git add -A && git commit -m "feat(<escopo>): <descrição>"
   ```

---

## Fase 4: Validação (Tester / QA)

**Regras:** [`tester.md`](../rules/tester.md)

1. Rodar todos os testes:
   ```bash
   uv run pytest -m "unit or integration" -v
   ```

2. Validar cobertura nos módulos afetados:
   ```bash
   uv run pytest --cov=src --cov=agents --cov-report=term-missing
   ```

3. Verificar regressões em testes existentes e a rastreabilidade cenário → teste da spec.
4. Reportar NCs (Não Conformidades) se encontradas. O desenvolvedor corrige seguindo [`fix-nc.md`](fix-nc.md).

---

## Fase 5: Pull Request & Merge

**Workflow:** [`do-pull-request.md`](do-pull-request.md)

1. Garantir que todos os testes passam.
2. Push da branch e criação do PR apontando para `dev`.
3. Code Review conforme [`reviewer.md`](../rules/reviewer.md), incluindo a conformidade com a spec.
4. Ciclo de melhorias se necessário.
5. Merge, sincronização local e limpeza da worktree.
6. Arquivar a mudança: mover `openspec/changes/<id>/` para `openspec/changes/archive/`, consolidar os requisitos em `openspec/specs/<capacidade>/spec.md` e atualizar o status do ADR se a implementação dele estiver completa.

---

## Modo Paralelo: Ondas de Mudanças OpenSpec Independentes

**Quando usar:** há múltiplas mudanças pendentes em `openspec/changes/` (tipicamente
resultado de um desdobramento de ADRs em specs por domínio) que podem ser
implementadas sem depender umas das outras. Em vez de rodar a Fase 3 uma mudança
de cada vez, o Desenvolvedor orquestra uma onda de sub-agentes, um por mudança,
cada um em sua própria worktree.

Este modo substitui a Fase 3 (Implementação) e a Fase 4 (Validação) por execução
paralela; as Fases 1, 2 e 5 continuam sequenciais e sob controle do
usuário — em especial, **nenhum PR é mergeado automaticamente**.

### 1. Orquestrador: mapear dependências e definir a onda

1. Ler todas as mudanças pendentes em `openspec/changes/`.
2. Construir um grafo de dependências entre elas (uma mudança que referencia
   contrato, schema ou módulo criado por outra é dependente dela).
3. Agrupar na **primeira onda** apenas as mudanças sem dependência não resolvida.
4. Confirmar com o usuário a lista de mudanças da onda antes de disparar os
   sub-agentes.

### 2. Um sub-agente por mudança

Para cada mudança da onda, disparar um sub-agente (via Agent tool) com o
seguinte contrato — cada sub-agente deve:

1. Criar worktree e branch dedicadas para a mudança:
   ```bash
   git worktree add .worktrees/<nome-da-mudança> -b feat/<nome-da-mudança> dev
   cd .worktrees/<nome-da-mudança>
   uv sync
   ```
2. Implementar a mudança respeitando `AGENTS.md` e [`backend-dev.md`](../rules/backend-dev.md).
3. Rodar os testes unitários e iterar até 100% verde:
   ```bash
   uv run ruff check .
   uv run pytest -m unit -v
   ```
4. Rodar os testes de integração relevantes — **antes**, verificar espaço em
   disco do Docker e parar para reportar se houver menos de 10GB livres (ver
   incidente de disco cheio travando o Docker em [`tester.md`](../rules/tester.md)):
   ```bash
   docker system df
   df -h /
   uv run pytest -m integration -v
   ```
5. Commitar (Conventional Commits), dar push e abrir o PR apontando para `dev`,
   linkando a mudança OpenSpec de origem no corpo do PR.
6. Retornar ao orquestrador um resumo: URL do PR, contagem de testes
   (unit/integration, passed/skipped/failed) e quaisquer ambiguidades da spec
   encontradas durante a implementação.

Um sub-agente **nunca** aprova nem faz merge do próprio PR — isso permanece na
Fase 5, sob revisão do usuário ou do Revisor.

### 3. Orquestrador: consolidar a onda

Ao final da onda, o Desenvolvedor:

1. Apresenta uma tabela com os resultados de cada sub-agente (mudança, PR,
   testes, status).
2. Lista qualquer ambiguidade de spec reportada pelos sub-agentes, para
   decisão do usuário antes da próxima onda.
3. Propõe a próxima onda (mudanças que dependiam apenas das que acabaram de
   ser implementadas).
4. Aguarda aprovação explícita do usuário antes de seguir para revisão e
   merge de cada PR (Fase 5) — nenhuma mudança é mergeada sem essa aprovação.

### Prompt de referência

```
Read all pending OpenSpec changes under openspec/changes/ and build a
dependency graph between them. Group the changes that have no unmet
dependencies into a first wave. For each change in that wave, launch a
sub-agent with the Agent tool. Each sub-agent should: (1) create a dedicated
git worktree and branch named after the change, (2) implement the change
following AGENTS.md conventions, (3) run the unit tests and iterate until
they pass, (4) run the relevant integration tests, checking Docker disk
space with `docker system df` first and stopping to report if less than
10GB is free, (5) commit, push, and open a PR that links the spec, and
(6) return a summary with the PR URL, test counts, and any open questions.
When the wave finishes, give me a table of results, flag any spec
ambiguities the agents hit, and propose the next wave. Do not merge
anything without my approval.
```

---

## Checklist de Saída

- [ ] Todos os testes unitários e de integração passam
- [ ] Cobertura mínima atingida nos módulos afetados
- [ ] ADR criado (se decisão arquitetural relevante)
- [ ] Mudança OpenSpec aprovada antes da implementação, `tasks.md` marcado (caixas e linha `**Estado**`) e cada cenário coberto por teste
- [ ] Implementação confirmada com o Arquiteto de Soluções, que atualizou o status dos ADRs de origem e o `docs/decisions/README.md`
- [ ] Mudança arquivada em `openspec/changes/archive/` e `openspec/specs/` consolidado
- [ ] Commits seguem Conventional Commits
- [ ] PR aprovado e merged em `dev`
- [ ] Worktree removida e branch local limpa
- [ ] Roadmap atualizado (se necessário)
