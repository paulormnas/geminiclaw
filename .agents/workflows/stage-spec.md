---
description: Especificação de nova etapa do roadmap do GeminiClaw, com ADRs e mudanças OpenSpec
---

# Workflow: Especificação de Nova Etapa do Roadmap

Este workflow define como o Arquiteto de Soluções transforma decisões aprovadas em uma etapa do
roadmap pronta para implementar. Cada tarefa da etapa vira uma **mudança OpenSpec**
(`openspec/changes/<id>/`): um pacote autocontido que qualquer agente consegue implementar sem
reler a conversa que originou a decisão.

```
Levantamento ──→ ADRs ──→ Roadmap ──→ Mudanças OpenSpec ──→ Revisão ──→ Aprovação ──→ new-feature.md
```

---

## Quando Usar

- Ao iniciar uma nova versão ou etapa do roadmap (ex.: V17, V18.5).
- Quando ADRs aprovados ainda não têm mudanças OpenSpec que os implementem
  (ver a seção "Lacunas de especificação" em `docs/decisions/README.md`).
- Quando uma etapa existente precisa ser decomposta em mudanças menores.
- Quando uma decisão nova do pesquisador altera mudanças já descritas e ainda não implementadas.

Para uma correção pontual, sem decisão arquitetural nem contrato novo, use
[`new-feature.md`](new-feature.md), [`fix-nc.md`](fix-nc.md) ou [`hotfix.md`](hotfix.md).

---

## Referências obrigatórias

| Arquivo | Para quê |
|---|---|
| `openspec/README.md` | Estrutura das mudanças, formato dos requisitos, ciclo de vida e tabela de mudanças |
| `openspec/project.md` | Contexto e convenções válidas para toda spec (stack, aprovações, definição de pronto) |
| `openspec/changes/` | Mudanças em aberto: evitar duplicar, detectar dependências e conflitos |
| `openspec/specs/` e `openspec/changes/archive/` | Verdade atual do sistema e mudanças já concluídas |
| `docs/decisions/README.md` | Índice e status dos ADRs (Proposto, Em revisão, Aprovado, Aceito, Deprecado) e lacunas de especificação |
| `roadmaps/roadmap_V*.md` | Etapas, ordem e critérios de validação |

---

## Processo

### 1. Levantamento

1. Ler os ADRs da etapa e confirmar o status no índice: **só se especifica a partir de ADR
   Aprovado ou Aceito.** ADR Proposto ou Em revisão volta ao pesquisador antes.
2. Ler as mudanças OpenSpec em aberto e o arquivo, para não duplicar capacidades e para mapear
   o que a nova etapa modifica (requisitos `MODIFIED` ou `REMOVED`).
3. Levantar no código o estado real (arquivos, contratos, tabelas, variáveis de configuração).
   A spec descreve a diferença entre o que existe e o que deve existir, com referência a
   arquivo e linha quando ajudar.
4. Listar dependências entre a etapa nova e as anteriores.

### 2. ADRs

Decisão arquitetural nova (contrato, tecnologia, papel de agente, política de dados, schema)
exige ADR antes da spec, no formato de `docs/decisions/README.md`, com a revisão adversarial
descrita em [`architect.md`](../rules/architect.md). Cada ADR termina com a lista das mudanças
OpenSpec que exige. Detalhes de implementação ficam na spec, não no ADR.

### 3. Roadmap da etapa

Criar ou atualizar `roadmaps/roadmap_V<versão>.md`. Cada tarefa aponta para a sua mudança
OpenSpec, e os critérios de aceite são um resumo dos requisitos da spec:

```markdown
# Roadmap V<versão> — <Título da Etapa>

## Objetivo
[O que a etapa entrega, com os ADRs de origem]

## Dependências
- [Etapas e mudanças que precisam estar concluídas]

## Tarefas

### Tarefa 1: <título>
- **Spec:** [`v<versão>-<nome>`](../openspec/changes/v<versão>-<nome>/proposal.md)
- **Critérios de aceite:** [ ] <critério> · [ ] <critério>
- **Complexidade estimada:** Baixa | Média | Alta

## Ordem de implementação
[Grafo das tarefas: o que pode ir em paralelo e o que depende do quê]

## Validação da Etapa
- [ ] Todos os testes unitários e de integração passam.
- [ ] Validação real no Raspberry Pi 5 quando a etapa afeta execução de sessões.
- [ ] Revisões do Analista de Segurança concluídas.
- [ ] ADRs da etapa marcados como Aceitos.
- [ ] PRs merged em `dev`; mudanças arquivadas.
```

### 4. Mudanças OpenSpec (uma por tarefa)

Para cada tarefa, criar `openspec/changes/<id>/` com os quatro arquivos descritos em
`openspec/README.md`:

| Arquivo | Conteúdo mínimo |
|---|---|
| `proposal.md` | Cabeçalho com **ID**, **Versão**, **Capacidade**, **ADRs de origem** (com seções) e **Depende de**; seções *Por quê*, *O que muda* (Novo / Modificado / Removido / Fora do escopo), *Impacto* (código, contratos, schema, custo) e **Aprovações necessárias** quando houver schema, Dockerfile base, `docker-compose.yml`, exclusão de arquivos ou `AGENTS.md` |
| `design.md` | Decisões técnicas, contratos (assinaturas, formatos de arquivo, eventos), análise de impacto nos 6 eixos ([`impact-analysis.md`](impact-analysis.md)), segurança, riscos e mitigações, questões em aberto |
| `tasks.md` | Checklist ordenado e numerado (`- [ ] 1.1 ...`), com tarefas de teste junto das de código e uma tarefa final de validação; o desenvolvedor marca as caixas no PR |
| `specs/<capacidade>/spec.md` | Requisitos em `## ADDED`, `## MODIFIED` ou `## REMOVED Requirements`, cada um com `SHALL`/`MUST` e ao menos um `#### Scenario` em GIVEN/WHEN/THEN |

Convenções:

- **ID:** `v<versão>-<nome-curto>` em kebab-case (ex.: `v17-curator-agent`). A capacidade é o
  nome da pasta em `specs/` e deve reutilizar uma capacidade existente quando o assunto for o
  mesmo (ex.: `llm-providers`).
- **Cenários testáveis:** cada cenário vira ao menos um teste. Valores verificáveis (limiares,
  nomes de campos, mensagens) entram no cenário; nada de "deve funcionar bem".
- **Configuração:** todo valor ajustável é declarado na spec com variável de ambiente e
  padrão (regra de `openspec/project.md`).
- **Testes sem rede paga:** a spec indica como simular provedores LLM; nenhum cenário depende
  de chamada real a provedor pago.
- **Rastreabilidade:** cada requisito cita o ADR e a seção de origem quando vier de um.
- **Decisões abertas:** o que o pesquisador ainda precisa decidir fica em "Questões em aberto"
  no `design.md`, nunca resolvido por suposição silenciosa.

Atualizar a tabela "Mudanças propostas" de `openspec/README.md` (versão, mudança, capacidade,
ADRs, dependências) e remover a lacuna correspondente de `docs/decisions/README.md`.

Para muitas mudanças independentes, o Arquiteto pode rascunhá-las em paralelo, um sub-agente
por domínio (ver "Especificação Paralela de OpenSpec por Domínio" em
[`architect.md`](../rules/architect.md)), consolidando os conflitos antes de apresentar.

### 5. Revisão

1. **Consistência:** o Arquiteto confere as mudanças entre si e contra os ADRs, `AGENTS.md` e as
   mudanças em aberto (dependências circulares, capacidades duplicadas, requisitos que se
   contradizem).
2. **Segurança:** o Analista de Segurança revisa `proposal.md` e `design.md` de toda mudança que
   toca sandbox, rede, permissões, segredos, banco ou dados de pesquisa
   ([`security-analyst.md`](../rules/security-analyst.md)) e registra o parecer no `design.md`
   (seção "Segurança") ou no PR das specs.
3. **Testabilidade:** o Tester confirma que cada cenário é verificável com os recursos de teste
   do projeto ([`tester.md`](../rules/tester.md)).

### 6. Aprovação e publicação

1. Abrir um PR `docs(openspec): ...` com roadmap, ADRs e mudanças, apontando para `dev`
   ([`do-pull-request.md`](do-pull-request.md)). O corpo lista as mudanças, a ordem de
   implementação e as aprovações necessárias.
2. O pesquisador responsável aprova a etapa e cada "Aprovações necessárias" de forma explícita.
   Sem essa aprovação, nenhuma mudança é implementada.

### 7. Passagem para a implementação

Cada mudança aprovada é implementada por [`new-feature.md`](new-feature.md): um worktree e um PR
por mudança, ou ondas paralelas de mudanças independentes. Ao final de cada mudança, após o
merge, a pasta vai para `openspec/changes/archive/` e os requisitos são consolidados em
`openspec/specs/<capacidade>/spec.md`. Divergência entre spec e implementação encontrada no
caminho volta ao Arquiteto, que atualiza a spec antes de o código seguir.

---

## Entregáveis

1. ADRs novos ou revisados, com status atualizado no índice.
2. Roadmap da etapa em `roadmaps/roadmap_V<versão>.md`, com uma mudança OpenSpec por tarefa.
3. Mudanças em `openspec/changes/<id>/` (quatro arquivos cada) e a tabela de
   `openspec/README.md` atualizada.
4. Ordem de implementação (ondas) e lista de aprovações necessárias.
5. PR de especificação aberto para `dev`.

---

## Regras

- Nunca especifique a partir de ADR que não esteja Aprovado ou Aceito.
- Nunca inicie a implementação sem as mudanças OpenSpec aprovadas pelo pesquisador.
- Todo requisito tem ao menos um cenário verificável; todo cenário vira teste.
- A spec descreve comportamento e contratos; não copia código de produção.
- Uma decisão nova do pesquisador que afete specs já escritas é aplicada nelas antes da
  implementação, com nota de data no `proposal.md` ou no `design.md`.
- A CLI do OpenSpec (Node.js) não é usada; a estrutura e o formato são conferidos na revisão.
