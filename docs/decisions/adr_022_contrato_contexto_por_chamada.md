# ADR 022 — Contrato de Contexto por Chamada e Regimento da Pesquisa

**Status:** Aprovado (2026-10-15)
**Data:** 2026-10-15
**Autores:** Arquiteto de Soluções (GeminiClaw)
**Roadmaps relacionados:** `roadmaps/roadmap_V18.7.md` (criado junto com as mudanças OpenSpec)
**ADRs relacionados:** ADR 007 (papéis), ADR 010 (assistente de pesquisa), ADR 011 (provedores agnósticos), ADR 015 §8 (vocabulário de métricas), ADR 019 (localidade e egresso), ADR 020 (Validator), ADR 021 (exploração rastreável)

**O que este ADR muda em outros ADRs:**

| ADR | Mudança |
|---|---|
| 007 | O Developer passa a receber o contrato da subtarefa, não só o enunciado (§2). |
| 019 | O contrato herda a marcação de origem e contaminação do texto do Researcher e a regra de nomes de artefato (§6). |
| 020 | A revisão de subtarefa separa critérios de aceite (do contrato) de regras de integridade (sempre ativas) (§3). |
| Spec `agent-prompts` | Toda chamada passa a levar o recorte do regimento da pesquisa (comum a todos os agentes) e o prompt do papel com o que só ele faz, recebe, produz e por que é avaliado; regras com efeito no código vêm de uma fonte só (§4–§5). |
| Spec `pipeline-robustness` | "Propagação dos nomes reais" e "Revisão de critérios quantitativos" passam a usar o contrato (§2–§3). |

---

## Contexto

### Chamadas são stateless

Cada chamada a um provedor LLM é independente: o modelo só sabe o que vai naquela requisição. O sistema reenvia o prompt de sistema do papel em toda chamada, mas o resto do contexto depende de quem monta a mensagem, e hoje cada papel monta a sua de um jeito.

### O que a bateria V18.6 mostrou (2026-10-15)

Nos registros de egresso da `gemini-dev-sonnet-juiz` r1 (41 chamadas ao Developer), o Developer recebe o prompt de sistema completo (8,3 mil caracteres: reprodutibilidade, seed, `save_experiment_artifacts`, proibição de métricas literais, escopo), o texto `prompt` da subtarefa e o contexto do workspace (artefatos já existentes). Ele **nunca** recebe:

- `validation_criteria`: os critérios pelos quais o Validator vai julgar a subtarefa;
- `expected_artifacts`: os nomes dos arquivos que o Validator vai procurar no disco;
- `hypothesis`: o próprio prompt de sistema manda preencher a docstring `Hipótese` com esse campo;
- a tarefa original do pesquisador e o critério do `Problema` (métrica, alvo, baseline);
- o lugar da subtarefa no plano (quem consome os artefatos dela).

As reprovações das combinações com Gemini vêm daí: "artefato ausente no disco: `model_comparison.csv`", "a métrica `accuracy` não está em `metrics.json`" (o Developer gravou `dummybaseline_cv_acc_mean`), subtarefas que gravam o mesmo arquivo. Cada reprovação custa uma nova tentativa; o controle chegou a 56 minutos por execução. Os nós `Resultado` saem com nomes variados para a mesma métrica (`rf_test_accuracy`, `logreg_test_acuracia`, `acuracia`).

### Regras que divergem entre prompts

A investigação dos planos esvaziados (ADR 021, Contexto) achou a mesma regra escrita de três formas: no prompt do Researcher, no código (`_is_bound`) e no prompt do Validator do plano, que a contradiz. Cada prompt é texto mantido à mão; nada garante que diga o que o código faz.

### Decisão do pesquisador (2026-10-15)

Adicionaria uma inserção do prompt inicial do agente Developer quando enviar as subtarefas, para alinhar como deve ser o código esperado e as diretrizes que deve seguir. Sem esse contexto o código gerado pode não atender aos nossos requisitos. Para cada chamada de API temos que passar todo o contexto novamente, por ser uma chamada stateless.

---

## Decisão

### 1. Contrato de contexto por papel

Cada papel tem um **contrato de contexto**: a lista do que o modelo precisa ter diante de si em toda requisição daquele papel, montada por um único construtor por papel. O que é fixo do papel vai no prompt de sistema; o que é da tarefa vai num bloco estável no início da conversa da subtarefa.

| Papel | Sempre tem diante de si |
|---|---|
| Researcher (plano) | tarefa original; projeto e critério do `Problema`; formato do plano (prompt do papel); recorte do regimento (§4); hipóteses e sugestões abertas; retiradas e ligações derivadas do ciclo anterior (ADR 021 §7) |
| Developer | prompt de sistema do papel; contrato da subtarefa (§2); contexto do workspace |
| Validator (plano) | tarefa original; critério do `Problema`; recorte do regimento (§4); o plano |
| Validator (revisão de subtarefa) | o contrato da subtarefa (§2, completo), as regras de integridade (§3) e a evidência em disco |

**Como o contrato é reenviado.** O bloco do contrato entra **uma vez** no início da conversa de cada tentativa da subtarefa, num prefixo estável (antes do contexto do workspace), e o laço de ferramentas reenvia o histórico como já faz hoje: o contrato não é acrescentado de novo a cada volta, o que faria o custo crescer de forma quadrática. Numa nova tentativa, o contrato é reconstruído (o plano pode ter mudado). O prefixo estável permite o cache de prompt dos provedores que o oferecem, sem depender dele (ADR 011).

### 2. Contrato da subtarefa (Developer)

Toda tentativa de subtarefa do Developer leva, além do enunciado:

1. `task_name`, `task_type` e o papel do experimento (ADR 021 §2);
2. `validation_criteria`, identificados como os critérios de aceite que serão verificados;
3. `expected_artifacts`, com os nomes exatos de arquivo;
4. o enunciado da hipótese testada (ou "preparação: serve às hipóteses …" / "referência do Problema");
5. a tarefa original do pesquisador;
6. o critério do `Problema`: métrica principal, sentido, alvo, referência;
7. **as chaves de métrica exigidas**: o nome canônico (vocabulário, ADR 015 §8) de cada métrica que os critérios citam, com a instrução de gravá-la com esse nome em `metrics.json`. Quando a subtarefa mede vários modelos, cada um pode ser gravado com chave qualificada (`<modelo>.<metrica>`, por exemplo `rf.acuracia`), que a ingestão liga à mesma `Metrica` como informação; **o critério de aceite vale para a chave sem qualificador**, que o Developer grava para o modelo escolhido **na validação** (nunca no teste), ou para a chave qualificada que o próprio critério citar. O Validator nunca escolhe entre chaves qualificadas. O Validator do plano aponta, antes da execução, critério com limiar sem chave indicada em subtarefa que mede vários modelos; se mesmo assim a ambiguidade chegar à revisão, ela é registrada como `criterio_ambiguo`, o resultado fica não validado (não conta como evidência), a tentativa do Developer não é consumida e o caso volta ao Researcher como observação. Uma métrica citada que não exista no vocabulário segue o fluxo de termo novo do vocabulário e não bloqueia a subtarefa; as demais métricas que o Developer quiser gravar continuam livres;
8. os artefatos desta subtarefa que subtarefas posteriores consomem (pelo `depends_on` inverso), para que o Developer não os renomeie nem os mova;
9. a lembrança explícita de que o limiar dos critérios é avaliado no conjunto de teste e que **ajustar modelo, hiperparâmetros ou seleção usando o conjunto de teste é proibido** (regra de integridade do §3).

### 3. Critérios de aceite × regras de integridade

A revisão de subtarefa separa duas coisas:

| | Critérios de aceite | Regras de integridade |
|---|---|---|
| O que são | `validation_criteria`, `expected_artifacts`, chaves de métrica (itens 2, 3, 7) | Métricas calculadas, não literais; sem vazamento treino/teste nem ajuste no teste; seed registrada; `divergence_note` honesto; verificação de afirmações; filtros de egresso |
| De onde vêm | Do plano, via contrato | Do prompt de sistema do Developer e das regras do sistema, iguais para toda subtarefa |
| Podem reprovar? | Sim, **se estavam no contrato enviado** | Sim, sempre |

O Validator recebe o contrato completo (itens 1–9), inclusive a tarefa original e o critério do Problema. Um problema que o Validator veja fora dos critérios de aceite e das regras de integridade (por exemplo, um critério fraco escrito pelo Researcher) não reprova a subtarefa: volta ao Researcher como observação, no replanejamento seguinte.

### 4. Regimento da pesquisa e prompts por papel

Decisões do pesquisador (2026-10-15): *"Um ponto importante é atualizar os prompts dos agentes para que eles tenham conhecimento de como funciona o sistema e as regras pertinentes para cada papel."* *"Faz sentido que parte do prompt seja uma consulta a um documento que estabeleça as regras para condução da pesquisa (exploração, critérios de parada etc.) de acordo com o tipo, além de regras comuns."* *"Esse deve ser um arquivo comum para todos os agentes; regras de comportamento e estruturas de comunicação específicas de cada agente devem ser inseridas em seus respectivos prompts iniciais."*

Hoje cada prompt descreve o papel isoladamente e não o lugar dele no fluxo: o Developer não sabe que um Validator vai conferir artefatos e chaves de métrica; o Validator do plano não sabe que a governança retira subtarefas; o Researcher não sabe como o papel de cada subtarefa é decidido. A instrução passa a ter duas fontes, com fronteira clara:

**4.1 Regimento da pesquisa (comum a todos os agentes).** Um único documento versionado no repositório (`agents/regimento/`), que contém só o que vale para todos:

1. como o sistema funciona: plano, validação do plano, governança das hipóteses, execução no sandbox, revisão, ingestão no grafo, veredito, próxima volta ou parada, e qual papel faz cada passo;
2. como conduzir a exploração: hipóteses, papéis de experimento, variações e derivações, o que impede a execução (ADR 021);
3. os tipos de objetivo do Problema e, para cada um, quando o objetivo é atingido, o que conta como avanço e como se mede a saturação (ADR 021 §5);
4. os critérios e motivos de parada e de retirada;
5. as regras de integridade comuns (métricas calculadas, sem ajuste no conjunto de teste, honestidade de resultados, dados de pesquisa e egresso).

O regimento tem uma parte em prosa e uma parte estruturada (tipos de objetivo e seus critérios, papéis de experimento, códigos de motivo). O código lê a parte estruturada; um teste falha se o código aplicar uma regra que o regimento não declara, ou o contrário.

**4.2 Prompt de sistema de cada papel (específico).** Fica no prompt do papel, e não no regimento, o que só aquele papel faz: comportamento, ferramentas, o que recebe e produz, os formatos que produz (por exemplo, o JSON do plano no Researcher, o parecer no Validator, `metrics.json` no Developer) e os critérios pelos quais é avaliado. Os formatos estruturados do prompt de cada papel são gerados dos mesmos esquemas que o código valida, com o mesmo teste de coerência.

**4.3 Injeção, não consulta.** O sistema monta o prompt de cada chamada com o prompt do papel e o **recorte do regimento** que se aplica àquela chamada: as seções comuns e só as do tipo de objetivo do Problema e do modo da sessão (um Problema de `discriminacao` no `auto` não recebe as regras de `fronteira` nem as do `assisted`). O agente não precisa decidir consultar nada para receber o essencial. O texto completo fica disponível por uma ferramenta de leitura, para quando o agente precisar de algo fora do recorte.

**4.4 Versão e adendo de projeto.** Mudanças no regimento passam por PR com aprovação do pesquisador. Cada sessão registra a versão (hash) do regimento e do recorte usados, junto com o contrato de cada subtarefa (§7). Regras próprias de um projeto (por exemplo, restrições de segurança de um laboratório) entram como adendo do projeto, nos insumos do pesquisador e fora do repositório, e são injetadas junto do recorte. O adendo só pode **restringir** (acrescentar regras ou proibições), nunca afrouxar o regimento nem desligar paradas; ativá-lo e cada mudança nele são decisão reservada do pesquisador, pelo gate; o hash do adendo é registrado junto com o do regimento.

**4.5 Redação.** Regimento e prompts são escritos de forma direta: frases curtas, sem emojis, sem decoração tipográfica e sem repetir a mesma regra em lugares diferentes. Cada regra aparece uma vez, na fonte a que pertence (regimento ou prompt do papel).

**4.6 Auditoria.** A mudança que implementa esta seção começa por uma auditoria de cada prompt atual contra o código (o que cada um afirma, o que o código faz, o que falta), registrada no `design.md` da mudança; dela saem o regimento v1 e os prompts revisados. Termina com uma bateria curta comparada à V18.6.

### 5. Coerência entre regimento, prompts e código

A fronteira do §4 vale também para o teste: as regras com efeito no código (papéis de experimento, o que exige hipótese, o que impede a execução, chaves de métrica, critérios de parada por tipo de objetivo, formatos de mensagem) existem uma vez, na parte estruturada do regimento ou nos esquemas dos papéis, e o texto injetado é gerado delas. Texto livre continua permitido para orientação, nunca para uma regra que o código aplica.

### 6. Egresso, contaminação e tamanho

1. **Origem e contaminação.** Os itens 2, 3, 4 e 8 são escritos pelo Researcher, que leu dados não confiáveis (colunas, web). O contrato herda a marcação já usada para o texto do Researcher (`instrucao` com `tainted = role_tainted("researcher")`, como em `src/agents/validator_agent.py:744`) e é entregue ao modelo como dado delimitado, nunca como instrução; os nomes de artefato seguem a regra de nomes (`ARTIFACT_NAMES_SOURCE`, `src/egress/fragments.py:46`). Os filtros de localidade (ADR 019) valem como para as demais instruções.
2. **Tamanho.** Cada bloco tem teto configurável. Só o item 5 (tarefa original) pode ser truncado, por corte literal registrado (nunca resumido por LLM); os demais itens não são cortados.
3. **Custo.** O custo extra estimado é de 1 a 3 mil tokens de entrada por tentativa de subtarefa (não por chamada), contra o custo das reprovações que ele evita; o relatório do benchmark passa a medi-lo por execução.

### 7. Registro

O início de cada tentativa registra `(tentativa, hash do contrato)`; a revisão registra o hash do contrato usado no julgamento. Hash divergente dentro da mesma tentativa é registrado como anomalia e não reprova a subtarefa.

### 8. Artefatos repetidos entre subtarefas

Duas subtarefas do mesmo plano com o mesmo arquivo em `expected_artifacts`, **sem que uma dependa da outra**, são uma colisão real (a ordem de execução decide qual sobrevive, e a proveniência da outra fica inconsistente): o Validator do plano aponta a colisão como problema corrigível, com os nomes envolvidos. Quando uma depende da outra (por exemplo, um `results.csv` cumulativo), é atualização intencional: gera aviso, não reprovação, e a proveniência registra cada versão.

---

## Consideradas e Rejeitadas

### A. Repetir no `prompt` da subtarefa o que o Developer precisa
Pedir ao Researcher que escreva critérios, artefatos e chaves no texto do enunciado.
**Rejeitada:** depende de o modelo do Researcher lembrar sempre; cada modelo escreve o enunciado de um jeito, e o Validator continuaria julgando por campos que o Developer não viu.

### B. Estado de conversa no provedor
Usar sessões com estado (threads) para não reenviar o contrato.
**Rejeitada:** nem todos os provedores oferecem estado, e o projeto é agnóstico de provedor (ADR 011). O cache de prompt reduz o custo do reenvio, mas é otimização.

### C. Só aliases de métrica na ingestão
Mapear `accuracy`, `acc`, `rf_test_accuracy` para `acuracia` ao gravar o `Resultado`.
**Rejeitada como solução única:** a ingestão não sabe qual das métricas de um `metrics.json` é a que o critério cobra. Os aliases do vocabulário continuam úteis, mas o Developer precisa saber a chave.

### D. Contrato acrescentado a cada chamada do laço de ferramentas
**Rejeitada na revisão:** custo quadrático no número de voltas do laço; o histórico já leva o contrato.

### E. Validator restrito aos critérios do contrato
**Rejeitada na revisão:** desligaria as verificações de integridade (métricas literais, vazamento, afirmações), que não são critérios do plano.

### F. Não enviar o limiar ao Developer (só a chave e o sentido)
Evitaria o incentivo a ajustar o modelo no conjunto de teste.
**Não adotada:** o Developer precisa saber o alvo para escolher o protocolo de avaliação, e o problema real é o ajuste no teste, que passa a ser regra de integridade explícita (§2.9, §3). Decidido pelo pesquisador (2026-10-15): enviar chave e limiar.

### G. Regimento consultado por ferramenta, quando o agente quiser
**Rejeitada:** alguns modelos não chamam a ferramenta e seguem só a letra do prompt (bateria V18.6); o essencial é injetado em toda chamada (§4.3), e a ferramenta fica para o que está fora do recorte.

### H. Regimento com as regras e formatos de cada papel
**Rejeitada pelo pesquisador:** o regimento é comum a todos; o que é de um papel fica no prompt dele (§4.2), para não inflar todas as chamadas com regras que só um agente usa.


---

## Consequências

### Positivas
- O Developer escreve o código para os critérios que serão verificados; menos reprovações e retentativas.
- O julgamento do Validator fica auditável: o que foi pedido e o que foi julgado têm o mesmo hash.
- Os resultados chegam ao grafo com o nome canônico da métrica do Problema.
- Prompts e código deixam de divergir nas regras com efeito.

### Negativas / Trade-offs
- Mais tokens de entrada por tentativa de subtarefa.
- O contrato expõe ao modelo mais detalhes do projeto; mitigado pela marcação de contaminação e pelos filtros de egresso.
- Os prompts passam a ter partes geradas, menos livres para edição manual.

---

## Decisão do pesquisador sobre a questão levantada (2026-10-15)

1. **Chave e limiar visíveis ao Developer.** Enviar os dois, com regras: *"A ideia é sempre explorar, mas é importante para o Developer também ter um norte, um objetivo a alcançar."* O limiar vai com a proibição explícita de ajuste no conjunto de teste (§2.9), verificada pelo Validator como regra de integridade (§3).

---

## Mudanças OpenSpec exigidas

| Mudança | Capacidade | O que cobre |
|---|---|---|
| `v18.7-subtask-contract` | `agent-prompts`, `pipeline-robustness`, `data-egress` | §1–§3, §6, §8: construtores de contexto por papel, contrato da subtarefa, separação critérios × integridade, chaves de métrica, contaminação e tamanho do contrato, colisão de artefatos |
| `v18.7-agent-system-prompts` | `agent-prompts`, `agent-runtime` | §4–§5: auditoria de cada prompt contra o código; regimento da pesquisa v1 (prosa e parte estruturada); prompts revisados de todos os papéis; recorte por tipo de objetivo e modo; ferramenta de leitura do regimento; versão por sessão; adendo de projeto; teste de coerência |
| (dentro de `v18.7-exploration-metrics`, ADR 021) | `operation-metrics` | §6.3, §7: hash do contrato por tentativa, tokens do contrato por execução |

---

## Revisão

Revisar depois da primeira bateria com este ADR implementado: taxa de aprovação na revisão de subtarefa, retentativas por subtarefa e tokens de entrada por execução do Developer, comparados à bateria V18.6.
