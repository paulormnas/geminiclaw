# ADR 020 — Independência do Julgamento: Família de Modelo do Validator Diferente da do Developer

**Status:** Proposto
**Data:** 2026-10-13
**Autores:** Arquiteto de Soluções (GeminiClaw)
**Roadmaps relacionados:** `roadmaps/roadmap_V18.6.md`
**ADRs relacionados:** ADR 007 (papéis), ADR 017 (catálogo e roteador), ADR 019 §6 (diversidade de
modelo na verificação de afirmações)
**Revisa:**
- ADR 019 §6: para o julgamento, a família diferente da do Developer deixa de ser só desempate, e
  um modelo de outra família, de preferência inferior, pode substituir o preferido;
- ADR 019, tabela de impacto (ordem de resolução "o Validator depois de Researcher e Developer"):
  papéis com pin passam a ser resolvidos primeiro;
- ADR 017 §2 e §7: uma condição de elegibilidade nova, que vale também para pins e dicas de plano;
- ADR 017 §6: o modelo de reserva do Google no 429 (`GOOGLE_FALLBACK_MODEL`) passa a respeitar a
  regra deste ADR;
- ADR 007: o papel e o agente `reviewer` continuam existindo no código e passam a ser papel de
  julgamento.

---

## Contexto

### Quem julga

| Papel | Funções de julgamento | Onde |
|---|---|---|
| `validator` | validação do plano (`validate_plan`), revisão do resultado de cada subtarefa (`review_result`) e verificação das afirmações do relatório (`ClaimService`) | `ValidatorAgent.provider` (`src/agents/validator_agent.py:362`); `verifier_info_from_allocation` (`src/claims/service.py:51`) |
| `reviewer` | agente de subtarefa que o plano pode chamar para revisar código ou texto | `src/agent_runtime/definitions.py:70`, `agents/reviewer/agent.py`; papel obrigatório do catálogo (`src/llm/catalog.py:36`) |

O ADR 007 registrou que o Validator absorveu o Reviewer, mas o papel e o agente `reviewer`
continuam no código. A telemetria da revisão de subtarefa registra a chamada como `"reviewer"`
(`validator_agent.py:690`), embora use o modelo do papel `validator`.

### Quem é julgado

`review_result` revisa subtarefas de qualquer agente de `AGENT_IDS` (`src/orchestrator.py:75-81`).
Os resultados medidos (código, métricas, artefatos) vêm do `developer` e do `base`.

### Como a família pesa hoje

O ADR 019 §6 definiu a família diferente como **desempate** do `validator`. O código compara com
as famílias de todos os papéis autores (`AUTHOR_ROLES`, `src/llm/routing.py:47`) e só desempata
dentro de um grupo de preferência (`routing.py:225-228`). Isso não garante independência:

- no catálogo atual, cada grupo de preferência tem um só modelo, então o desempate nunca é aplicado;
- um pin (`VALIDATOR_MODEL`) é devolvido antes de qualquer checagem de família (`routing.py:197-204`);
- a dica `preferred_model` de subtarefa (`validate_hint`, `routing.py:285-316`, aplicada em
  `src/orchestrator.py:1909`) e o modelo de reserva do Google no 429 (`fallback_for`,
  `src/llm/session.py:79`) não olham a família;
- o benchmark de 2026-10-13 fixou o mesmo modelo para todos os papéis (`{"*": ...}`, sintaxe do
  runner, `scripts/benchmark/run_benchmark.py:33`).

### Decisão do pesquisador (2026-10-13)

**O Validator deve usar modelo de família diferente da do Developer. O Researcher e o Developer
podem ser o mesmo modelo.**

### Hipótese que este ADR assume

Um juiz da mesma família do autor tende a repetir os erros e critérios do autor. O benchmark de
2026-10-13 não mede isso: a Haiku reprovou 6 de 8 planos da própria Haiku, e a maior parte das
reprovações das outras rodadas veio de regras determinísticas. A próxima rodada mede a hipótese com
uma combinação de controle (item 9).

## Decisão

1. **Requisito na inicialização.** A família (`familia_modelo`, linhagem de treinamento) do modelo
   resolvido para o `validator` MUST ser diferente da família do modelo resolvido para o
   `developer`.
2. **Requisito no despacho.** Quando uma subtarefa é despachada para `base` ou `reviewer`, ou uma
   dica de plano, ou o modelo de reserva no 429 é aceito, o roteador confere o modelo efetivo
   contra os modelos efetivos em uso: juízes (`validator`, `reviewer`) e julgados (`developer`,
   `base`) MUST ter famílias diferentes. O conflito de `reviewer` ou `base` nunca impede a
   inicialização, porque muitas sessões nunca os usam. No despacho, um `base` ou `reviewer` em
   conflito passa ao próximo modelo elegível de outra família na sua preferência; sem nenhum, aplica-se
   o modo (item 5): em `required`, **só aquela subtarefa** falha, com o motivo
   `mesma_familia_julgamento` e a sugestão; a sessão continua. Em `preferred`, a subtarefa roda e o
   evento registra `aceito_preferred`.
3. **Researcher livre.** Nenhuma regra nova se aplica a `researcher`, `summarizer` e `curator`. A
   família diferente da deles continua como desempate do `validator` (ADR 019 §6). Com o catálogo
   atual, `researcher` e `validator` podem resolver para o mesmo modelo, e então a validação do
   plano é feita pelo modelo que o escreveu. Isso é permitido e fica registrado (item 7).
4. **Ordem de resolução e conflitos.**
   - Papéis com pin são resolvidos primeiro. Os papéis sem pin são resolvidos depois, e os juízes sem
     pin por último.
   - Na inicialização, todos os papéis **evitam** conflito: julgados sem pin pulam as famílias dos
     juízes com pin, e juízes sem pin pulam as famílias de `developer` e `base`. Um modelo pulado
     recebe o motivo `mesma_familia_julgamento`, e um modelo de outra família de preferência
     inferior pode substituir o preferido. Quando não há alternativa, o papel fica com o preferido.
     **Só o par `validator`/`developer` é exigência de inicialização** (item 1); conflitos restantes
     de `reviewer` ou `base` são tratados no despacho (item 2).
   - Dois pins em conflito no par `validator`/`developer`: com `LLM_ROUTING=strict`, `PinError`; com
     `flexible`, o pin do `developer` prevalece, o pin do `validator` é ignorado com `WARNING` e o
     `validator` segue a preferência do catálogo. Pins de `reviewer` ou `base` em conflito ficam
     para o despacho.
   - Dica de plano em conflito (para qualquer papel, juiz ou julgado): rejeitada por
     `validate_hint` com o mesmo motivo; a subtarefa usa o modelo resolvido do papel. O juiz não
     troca de modelo no meio da sessão (ADR 017 §6).
   - Modelo de reserva no 429 em conflito: não é usado; o 429 segue o cooldown e as retentativas
     atuais. No modo `preferred` (item 5), é usado com `WARNING` e o registro `atendida=false`
     daquela chamada.
5. **Modos.** `LLM_JUDGE_INDEPENDENCE=required|preferred|off`:
   - `required`: sem modelo elegível, a sessão não inicia (`NoEligibleModelError`; `PinError` no
     caso de pin em `strict`), com a sugestão "configure um modelo de outra família para os papéis
     de julgamento (`validator`, `reviewer`) ou use `LLM_JUDGE_INDEPENDENCE=preferred`";
   - `preferred`: sem modelo elegível, o juiz usa a preferência normal, com `WARNING` e
     `atendida=false`;
   - `off`: os itens 1, 2 e 4 não se aplicam; o desempate do ADR 019 §6 continua.
   - **Padrão:** `required` quando `LLM_DATA_POLICY=third_party_allowed`; `preferred` quando
     `LLM_DATA_POLICY=self_hosted_only`. Com a política padrão (`self_hosted_only`,
     `src/config.py:70`), o catálogo versionado só tem a família `qwen` (`src/llm/catalog.yaml:69-84`);
     exigir duas famílias locais no Pi 5 significaria dois modelos residentes ou troca de modelo a
     cada alternância. O valor explícito na variável sempre vence o padrão.
   Em todos os modos o estado é registrado (item 7). Nada é desligado em silêncio.
6. **Catálogo.** A lista de preferência de `validator` e `reviewer` MUST ter, antes de qualquer
   modelo local de capacidade menor, ao menos um modelo de nuvem de cada família do catálogo
   versionado (hoje: Claude, Gemini, GPT). Isso só tem efeito com `third_party_allowed` (ver
   "Instalação padrão" em Consequências). A lista de permissão `LLM_PROVIDER_PRIORITY` continua
   limitando os provedores usados.
7. **Registro.** O payload da sessão ganha `independencia_julgamento`, ao lado do `desempate`
   existente:
   - na inicialização: modo efetivo e origem do modo (variável ou padrão pela política), famílias de
     `validator` e `developer`, origem de cada família no catálogo (versionado ou
     `catalog.local.yaml`) e `atendida`;
   - a cada conferência do item 2: um evento `independencia_julgamento` com subtarefa, papel, modelo,
     família, decisão (`aceito`, `rejeitado`, `aceito_preferred`) e motivo.
   O banner, o relatório final e as métricas de operação mostram o resumo. A verificação de
   afirmações continua registrando `familia_diferente` por conclusão (herdado por cada afirmação),
   em relação ao autor da conclusão (ADR 019 §6). Os dois registros medem coisas diferentes e podem
   divergir.
8. **Retomada.** Ao retomar uma sessão (V18), o roteador confere as famílias julgadas registradas
   na sessão original (todas as do item 7) contra os juízes resolvidos agora, e aplica o modo do
   item 5 antes de reverificar afirmações pendentes.
9. **Benchmark.** O runner não expande `*` para os papéis de julgamento: cada combinação declara o
   `validator` (e o `reviewer`, se a tarefa o usar). O runner recusa a combinação cuja família do
   juiz coincide com a do `developer`, salvo se marcada como controle
   (`"independencia_julgamento": "off"`). A matriz da próxima rodada inclui ao menos uma combinação
   de controle. `check_pins` trata como esperado o registro do item 7.
10. **Avaliação de comunicação.** O juiz LLM de `scripts/benchmark/comm_judge.py:183-190` passa a
    excluir as famílias de `developer` e `base` (não mais os modelos de Developer e Researcher),
    com a família do Researcher como desempate, como no item 3.

## Alternativas Consideradas

- **Manter a família como desempate (ADR 019 §6).** Não cobre pins, dicas, reserva nem grupos de um
  modelo, que são os casos atuais. Rejeitada.
- **Família diferente de todos os papéis autores.** Exige três ou mais famílias e contraria a
  decisão do pesquisador. Rejeitada nesta versão.
- **Conferir `reviewer` e `base` na inicialização.** Bloquearia sessões que nunca usam esses papéis.
  Rejeitada; conferência no despacho (item 2).
- **Trocar o juiz por subtarefa quando uma dica do Developer cai na família dele.** Preservaria a
  dica (ex.: Claude como Developer de uma subtarefa), mas troca o juiz no meio da sessão, o que o
  ADR 017 §6 não permite e complica a auditoria. Rejeitada; ver "Divergências" abaixo.
- **Independência por tamanho de modelo** (ex.: Haiku julgando Sonnet). Mesma linhagem, erros
  correlacionados. Rejeitada.
- **Independência por provedor.** Um provedor serve várias famílias, e uma família vem de vários
  provedores. Rejeitada.
- **Validator fixo em modelo local.** Qualidade e latência insuficientes no Pi 5 para planos de 8 a
  11 subtarefas. Rejeitada; modelo local continua elegível.
- **Dois juízes e voto.** Dobra o custo de julgamento. Fora de escopo.
- **`required` como padrão em qualquer política.** A instalação padrão (só `qwen`) não iniciaria.
  Rejeitada; padrão por política (item 5).

## Consequências

- **Positivas:** o julgamento de resultados deixa de ser feito pela mesma família que os produziu, e
  o benchmark separa autor de juiz.
- **Instalação padrão** (`self_hosted_only`): inicia em `preferred`, com o registro
  `atendida=false` e o aviso no banner, até o operador incluir outra família local ou mudar a
  política.
- **Egresso:** com `third_party_allowed`, o item 6 pode levar o juiz a um provedor de nuvem que antes
  não era usado. A lista `LLM_PROVIDER_PRIORITY` continua limitando os provedores, a camada de saída
  do ADR 019 continua valendo para todo envio, e o banner mostra o provedor escolhido.
- **Dicas de plano:** uma dica do Developer na família do juiz é rejeitada. Se o juiz for Claude,
  o planejador não consegue mandar uma subtarefa para Claude como Developer.
- **`familia_modelo` é declarada pelo operador.** Uma entrada de `catalog.local.yaml` pode declarar
  qualquer família. A regra protege contra erro de configuração, não contra quem edita o catálogo
  local; por isso a origem da família é registrada (item 7).
- **Custo:** o juiz pode ficar num modelo mais caro que o do Developer; o custo por papel já está na
  telemetria.
- **Pins existentes:** um `.env` com o mesmo modelo em `VALIDATOR_MODEL` e `DEVELOPER_MODEL` passa a
  gerar `WARNING` (`flexible`) ou falha (`strict`) em `required`.
- **ADRs 007, 017 e 019** recebem nota de atualização apontando para este ADR quando ele for
  aprovado. O comentário de ordem de resolução em `routing.py:250` muda.

## Divergências para decisão do pesquisador

1. **Dica de plano do Developer na família do juiz.** A revisão adversarial divergiu: rejeitar a dica
   (adotado, mantém o juiz fixo na sessão) ou aceitar a dica e trocar o juiz daquela subtarefa
   (preserva o melhor modelo de código, mas troca o juiz no meio da sessão). Uma terceira opção
   reduz o conflito sem trocar o juiz: pôr um modelo de nuvem que não seja Claude (Gemini ou GPT)
   em primeiro lugar na preferência de `validator` e `reviewer`, deixando Claude livre para as dicas
   do Developer. Ela muda o juiz padrão de quem usa o catálogo sem pins.
2. **Padrão por política (item 5).** A proposta usa `preferred` em `self_hosted_only`. A alternativa
   é incluir um segundo modelo local de outra família no catálogo e manter `required` sempre, com
   custo de memória no Pi 5.

## Mudanças OpenSpec exigidas

| Mudança | Escopo |
|---|---|
| [`v18.6-validator-independence`](../../openspec/changes/v18.6-validator-independence/proposal.md) | Itens 1 a 8 e 10: roteador, despacho, dicas, reserva, modos, catálogo, registro, retomada, juiz da avaliação de comunicação |
| [`v18.6-benchmark-harness`](../../openspec/changes/v18.6-benchmark-harness/proposal.md) | Item 9: juiz declarado por combinação, combinação de controle, `check_pins` |

## Revisão

Revisar depois da próxima rodada com 3 repetições. Gatilho: se a taxa de reprovação do juiz e a
acurácia validada não diferirem entre as combinações com família diferente e a de controle, o modo
padrão volta a ser discutido (`preferred` ou desempate). Revisar também se a validação do plano pelo
mesmo modelo do Researcher mostrar viés.
