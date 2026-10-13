# ADR 020 — Independência do Julgamento: Família de Modelo do Validator Diferente da do Developer

**Status:** Aprovado (2026-10-13, pesquisador; as propostas adotadas nas duas divergências valem)
**Data:** 2026-10-13
**Autores:** Arquiteto de Soluções (GeminiClaw)
**Roadmaps relacionados:** `roadmaps/roadmap_V18.6.md`
**ADRs relacionados:** ADR 007 (papéis), ADR 017 (catálogo e roteador), ADR 019 §6 (diversidade de
modelo na verificação de afirmações)

**O que este ADR muda em outros ADRs:**

| ADR | Mudança |
|---|---|
| 019 §6 | Para o julgamento, a família diferente deixa de ser só desempate: vira regra (R1). |
| 019, tabela de impacto | A ordem de resolução muda: papéis com pin primeiro, juízes sem pin por último (§3). |
| 017 §2 e §7 | Nova condição de elegibilidade, que vale também para pins e dicas de plano. |
| 017 §6 | O modelo de reserva do Google no 429 (`GOOGLE_FALLBACK_MODEL`) passa pela regra. |
| 007 | O papel e o agente `reviewer` continuam no código e passam a ser papel de juiz. |

---

## Contexto

### Decisão do pesquisador (2026-10-13)

> O Validator deve usar modelo de família diferente da do Developer. O Researcher e o Developer
> podem ser o mesmo modelo.

### Por que a regra atual não basta

O ADR 019 §6 usa a família diferente só como **desempate** na escolha do `validator`
(`src/llm/routing.py:225-228`). Na prática, o desempate não protege nada:

- cada grupo de preferência do catálogo tem um só modelo, então o desempate nunca é aplicado;
- um pin (`VALIDATOR_MODEL`) é devolvido antes de qualquer checagem (`routing.py:197-204`);
- a dica `preferred_model` de subtarefa (`validate_hint`, `routing.py:285-316`) e a reserva do 429
  (`fallback_for`, `src/llm/session.py:79`) não olham a família;
- o benchmark de 2026-10-13 usou o mesmo modelo para todos os papéis (`{"*": ...}`,
  `scripts/benchmark/run_benchmark.py:33`).

Outro problema: o ADR 007 registrou que o Validator absorveu o Reviewer, mas o papel `reviewer`
continua no código (`src/agent_runtime/definitions.py:70`, `agents/reviewer/agent.py`,
`src/llm/catalog.py:36`). Além disso, a revisão de subtarefa feita pelo `validator` é registrada na
telemetria como `"reviewer"` (`src/agents/validator_agent.py:690`).

### Hipótese assumida

Um juiz da mesma família do autor tende a repetir os erros e os critérios do autor. O benchmark de
2026-10-13 não mede isso, porque a maior parte das reprovações veio de regras determinísticas. A
próxima rodada mede a hipótese com uma combinação de controle (§7).

---

## Decisão

### 1. Papéis e a regra

| Grupo | Papéis | O que fazem |
|---|---|---|
| **Juízes** | `validator`, `reviewer` | `validator`: valida o plano, revisa o resultado de cada subtarefa e verifica as afirmações do relatório. `reviewer`: agente de subtarefa que revisa código ou texto. |
| **Julgados** | `developer`, `base` | Produzem os resultados medidos (código, métricas, artefatos). |
| **Livres** | `researcher`, `summarizer`, `curator` | Não entram na regra. |

**Família** é o campo `familia_modelo` do catálogo (linhagem de treinamento: `claude`, `gemini`,
`gpt`, `qwen`...). Não é o provedor nem o tamanho do modelo.

> **R1.** Nenhum juiz pode usar um modelo da mesma família de um julgado em uso na sessão.

Para os papéis livres não há regra nova. O `researcher` pode usar o mesmo modelo do `developer`
ou do `validator`. Neste último caso, a validação do plano é feita pelo modelo que o escreveu, o
que é permitido e fica registrado (§6). A família diferente dos papéis livres continua só como
desempate do `validator` (ADR 019 §6).

### 2. Modos

`LLM_JUDGE_INDEPENDENCE` define o que acontece quando R1 não pode ser cumprida:

| Modo | Sem alternativa que cumpra R1 |
|---|---|
| `required` | Falha. O alcance da falha depende do ponto de conferência (§4). |
| `preferred` | Segue com o modelo em conflito, com `WARNING` e o registro `atendida=false`. |
| `off` | R1 não é conferida. Só o desempate do ADR 019 §6 continua valendo. |

**Padrão** (quando a variável não está definida):

- `required` com `LLM_DATA_POLICY=third_party_allowed`;
- `preferred` com `LLM_DATA_POLICY=self_hosted_only` (o padrão do projeto, `src/config.py:70`).

O padrão é `preferred` porque o catálogo versionado só tem uma família local (`qwen`,
`src/llm/catalog.yaml:69-84`). Exigir duas famílias locais no Pi 5 significaria manter dois modelos
residentes ou trocar de modelo a cada alternância. Um valor explícito na variável sempre vence o
padrão, e um valor inválido impede a inicialização.

Em nenhum modo a conferência é desligada em silêncio: o estado é sempre registrado (§6).

### 3. Procedimento único de conferência

Toda escolha de modelo para um juiz ou um julgado passa pelo mesmo procedimento:

1. **Sem conflito com R1:** o modelo é usado (`aceito`).
2. **Com conflito:** procura-se uma **alternativa**, que é outro modelo elegível que cumpra R1, na
   ordem definida para aquele ponto (§4). Se há alternativa, ela é usada (`substituido`, ou
   `rejeitado` quando o que se descarta é uma dica ou a reserva). O modelo descartado recebe o
   motivo `mesma_familia_julgamento`.
3. **Sem alternativa:** aplica-se o modo (§2).

Uma alternativa pode estar num grupo de preferência inferior ao do modelo descartado: a
independência vence a preferência.

**Precedência:** quando dois papéis disputam a mesma família, quem **cede** é quem procura a
alternativa:

- um papel com pin vence um papel sem pin;
- entre dois papéis com pin, ou dois sem pin, o **juiz cede** ao julgado.

Disso decorre a ordem de resolução na inicialização: (a) papéis com pin; (b) julgados sem pin,
evitando as famílias dos juízes com pin; (c) livres sem pin; (d) juízes sem pin, evitando as
famílias dos julgados já resolvidos.

**Pins e `LLM_ROUTING`:** com `strict`, um pin nunca é trocado, então um papel com pin não tem
alternativa. Com `flexible`, o pin de quem cede pode ser ignorado (com `WARNING`) e o papel segue
a preferência do catálogo.

### 4. Pontos de conferência

| Ponto | O que é conferido | Alternativa (passo 2) | `required` sem alternativa | `preferred` sem alternativa |
|---|---|---|---|---|
| **Inicialização: `validator` × `developer`** | O par principal. É a única exigência de inicialização. | O próximo modelo elegível do papel que cede (§3). | A sessão não inicia: `NoEligibleModelError`, ou `PinError` com dois pins em `strict`. | Usa o preferido, ou mantém o pin. |
| **Inicialização: `reviewer` e `base`** | Os demais pares juiz × julgado. | O próximo modelo elegível do papel. | O papel fica com o preferido. O conflito é tratado no despacho, porque muitas sessões nunca usam esses papéis. | Igual a `required`. |
| **Despacho de subtarefa para `reviewer` ou `base`** | O modelo do papel contra os modelos efetivos em uso. | O próximo modelo elegível de outra família na preferência do papel (`substituido`). | **Só aquela subtarefa** falha, com `mesma_familia_julgamento` e a sugestão. A sessão continua. | A subtarefa roda (`aceito_preferred`). |
| **Dica de plano (`preferred_model`)**, para qualquer juiz ou julgado | O modelo da dica. | O modelo já resolvido do papel (`rejeitado`). Sempre existe. | Nunca ocorre. | Nunca ocorre. |
| **Reserva do 429** | O modelo de reserva. | Nenhuma: a reserva é o único outro modelo. | A reserva não é usada (`rejeitado`). O 429 segue o cooldown e as retentativas atuais. | A reserva é usada, com `WARNING` e `atendida=false` naquela chamada. |
| **Retomada de sessão (V18)** | Os juízes resolvidos agora contra as famílias julgadas registradas na sessão original (§6). | Como na inicialização. | A retomada não inicia, e nenhuma afirmação pendente é reverificada. | Retoma com `atendida=false`. |

Em `off`, nenhum ponto é conferido.

Consequência da linha de dica: **o juiz nunca troca de modelo no meio da sessão** (ADR 017 §6).
Uma dica que cairia na família do juiz é descartada; o juiz não muda para acomodá-la.

### 5. Catálogo

A lista de preferência de `validator` e `reviewer` MUST ter, antes de qualquer modelo local de
capacidade menor, ao menos um modelo de nuvem de cada família do catálogo versionado (hoje: Claude,
Gemini, GPT). Isso garante uma alternativa sempre que a nuvem é permitida e só tem efeito com
`third_party_allowed`. A lista de permissão `LLM_PROVIDER_PRIORITY` continua limitando os
provedores usados.

### 6. Registro

| Onde | O que |
|---|---|
| Payload da sessão, campo `independencia_julgamento` (ao lado do `desempate`) | Modo efetivo e origem do modo (variável ou padrão da política); modelo, família e origem da família (catálogo versionado ou `catalog.local.yaml`) de `validator` e `developer`; `atendida`. |
| Evento `independencia_julgamento`, a cada conferência dos pontos de despacho, dica, reserva e retomada | Subtarefa, papel, modelo, família, decisão (`aceito`, `substituido`, `rejeitado`, `aceito_preferred`) e motivo. |
| Banner, relatório final e métricas de operação | O resumo, por exemplo "Julgamento: gemini (validator) ≠ claude (developer)", ou o aviso quando `atendida=false`. |

`atendida` é `false` sempre que o modo `preferred` aceitou um conflito.

A verificação de afirmações continua registrando `familia_diferente` por conclusão, em relação ao
autor da conclusão (ADR 019 §6). Os dois registros medem coisas diferentes e podem divergir.

A telemetria da revisão de subtarefa passa a registrar o papel `validator` com
`funcao = "revisao_subtarefa"`, em vez de `"reviewer"`.

### 7. Benchmark e avaliação de comunicação

- **Runner:** não expande `*` para os juízes. Cada combinação declara o `validator`, e o `reviewer`
  se a tarefa o usar. O runner recusa a combinação em que a família do juiz coincide com a do
  `developer`, salvo se ela estiver marcada como controle (`"independencia_julgamento": "off"`). A
  matriz da próxima rodada inclui ao menos uma combinação de controle. `check_pins` trata como
  esperado o registro do §6.
- **Juiz da avaliação de comunicação** (`scripts/benchmark/comm_judge.py:183-190`): exclui as
  famílias de `developer` e `base` (antes excluía os modelos de Developer e Researcher). A família
  do Researcher fica como desempate, como no §1.

---

## Alternativas Consideradas

| Alternativa | Motivo da rejeição |
|---|---|
| Manter a família só como desempate (ADR 019 §6) | Não cobre pins, dicas, reserva nem grupos de um modelo, que são os casos atuais. |
| Família diferente de todos os papéis autores | Exige três ou mais famílias e contraria a decisão do pesquisador. |
| Conferir `reviewer` e `base` já na inicialização | Bloquearia sessões que nunca usam esses papéis. |
| Trocar o juiz por subtarefa quando uma dica cai na família dele | Troca o juiz no meio da sessão, o que o ADR 017 §6 não permite e complica a auditoria (ver Divergência 1). |
| Independência por tamanho de modelo (ex.: Haiku julgando Sonnet) | Mesma linhagem, erros correlacionados. |
| Independência por provedor | Um provedor serve várias famílias, e uma família vem de vários provedores. |
| Validator fixo num modelo local | Qualidade e latência insuficientes no Pi 5 para planos de 8 a 11 subtarefas. O modelo local continua elegível. |
| Dois juízes e voto | Dobra o custo de julgamento. Fora de escopo. |
| `required` como padrão em qualquer política | A instalação padrão (só `qwen`) não iniciaria. |

## Consequências

- **Positivas:** o resultado deixa de ser julgado pela mesma família que o produziu, e o benchmark
  passa a separar autor de juiz.
- **Instalação padrão** (`self_hosted_only`): inicia em `preferred`, com `atendida=false` e o aviso
  no banner, até o operador incluir outra família local ou mudar a política.
- **Egresso:** com `third_party_allowed`, o §5 pode levar o juiz a um provedor de nuvem antes não
  usado. A lista `LLM_PROVIDER_PRIORITY` continua limitando os provedores, a camada de saída do ADR
  019 vale para todo envio, e o banner mostra o provedor escolhido.
- **Dicas de plano:** uma dica do Developer na família do juiz é descartada. Se o juiz for Claude, o
  planejador não consegue mandar uma subtarefa para Claude como Developer.
- **A família é declarada pelo operador:** uma entrada de `catalog.local.yaml` pode declarar
  qualquer família. A regra protege contra erro de configuração, não contra quem edita o catálogo
  local; por isso a origem da família é registrada (§6).
- **Custo:** o juiz pode ficar num modelo mais caro que o do Developer. O custo por papel já está
  na telemetria.
- **Pins existentes:** um `.env` com a mesma família em `VALIDATOR_MODEL` e `DEVELOPER_MODEL` passa a
  gerar `WARNING` (`flexible`) ou falha (`strict`) no modo `required`.
- **ADRs 007, 017 e 019** recebem uma nota apontando para este ADR quando ele for aprovado. O
  comentário sobre a ordem de resolução em `routing.py:250` muda.

## Divergências (decididas em 2026-10-13: valem as propostas adotadas)

1. **Dica do Developer na família do juiz.** Há três opções:
   - descartar a dica (adotado no §4): o juiz fica fixo na sessão;
   - aceitar a dica e trocar o juiz daquela subtarefa: preserva o melhor modelo de código, mas troca
     o juiz no meio da sessão;
   - pôr um modelo de nuvem que não seja Claude (Gemini ou GPT) em primeiro lugar na preferência de
     `validator` e `reviewer`: reduz o conflito sem trocar o juiz e deixa Claude livre para as dicas
     do Developer, mas muda o juiz padrão de quem usa o catálogo sem pins.
2. **Padrão em `self_hosted_only`.** A proposta usa `preferred`. A alternativa é incluir no catálogo
   um segundo modelo local de outra família e manter `required` sempre, com custo de memória no
   Pi 5.

## Mudanças OpenSpec exigidas

| Mudança | Escopo |
|---|---|
| [`v18.6-validator-independence`](../../openspec/changes/v18.6-validator-independence/proposal.md) | §1 a §6 e o juiz da avaliação de comunicação (§7): roteador, despacho, dicas, reserva, modos, catálogo, registro, retomada |
| [`v18.6-benchmark-harness`](../../openspec/changes/v18.6-benchmark-harness/proposal.md) | Runner do §7: juiz declarado por combinação, combinação de controle, `check_pins` |

## Revisão

Revisar depois da próxima rodada com 3 repetições. Se a taxa de reprovação do juiz e a acurácia
validada não diferirem entre as combinações com família diferente e a de controle, o modo padrão
volta a ser discutido (`preferred` ou só desempate). Revisar também se a validação do plano pelo
mesmo modelo do Researcher mostrar viés.
