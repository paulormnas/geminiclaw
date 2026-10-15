# Design: v18.7-agent-system-prompts

## 1. Auditoria dos prompts contra o código (ADR 022 §4.6)

Auditoria preliminar feita na leitura do código em 2026-10-15. A tarefa 1 a confirma no início da implementação (o código pode ter mudado com as outras mudanças V18.7) e registra a versão final nesta seção. Coluna "Destino": `R` = regimento (comum), `P` = prompt do papel, `E` = gerado de esquema, `X` = sai.

### 1.1 Researcher (`agents/researcher/agent.py:41-171`, plano e replanejamento)

| Trecho | O que afirma | O que o código faz | Destino |
|---|---|---|---|
| `:55-58` | O ciclo só termina com solução, sem caminhos ou por limite de uso | ADR 021 §5: objetivo tipado, estagnação como intervenção, saturação, limites de custo/tokens/tempo/egresso (`v18.7-exploration-limits`) | R (paradas) |
| `:60-61` | Subtarefa que testa algo referencia a hipótese | `_is_bound` (`src/exploration.py:295-308`) exigia hipótese de todo `developer` fora de `eda`/`synthesis`; ADR 021 §2 decide o papel por regras e nunca retira por falta de hipótese | R (papéis), P (declarar `papel`) |
| `:63-65` | Responder a cada sugestão do Curator | Igual ao código (`uncovered`, `src/exploration.py:265-268`) | P |
| `:66-67` | Hipóteses de agentes podem exigir aprovação conforme o modo | ADR 021 §3.6: só no `assisted`; hipótese do sistema também | R (modos) |
| `:85-96` | Tipos de tarefa | Igual ao esquema (`task_type`) | E |
| `:102-122` | Estrutura do plano | Terceira cópia (as outras em `src/agents/validator_agent.py:83-97` e `src/exploration.py:95-113`); exemplo de `hypothesis` "O modelo atinge acurácia > 0.85" induz hipótese em toda subtarefa (ADR 021 §8.3) | E |
| `:116-119` e validador `:89-91` | Limiar obrigatório em `reproduction` e em `validation` com `hypothesis_ref` | Igual a `_requires_quantitative` (`src/agents/validator_agent.py:60-66`) | E (regra no esquema) |
| `:124-146` | Uso de `ask_researcher` e lista de decisões reservadas | Lista copiada também no Developer e no consultor; falta `restringir_direcao` (ADR 021 §5.5) | P (uso), R (lista gerada de `DECISOES_RESERVADAS`) |
| `:159-171` | Diagnóstico de falha no replanejamento | Repetido em `src/orchestrator.py:2160-2165` | P (uma vez) |
| ausente | — | Não sabe que o Developer recebe o contrato, que o Validator do plano confere colisão e chaves, nem que as retiradas voltam como retorno | R (fluxo), P (como é avaliado) |

### 1.2 Bloco de exploração e prompts de planejamento

| Trecho | Problema | Destino |
|---|---|---|
| `src/exploration.py:271-273` | O título diz "dados de contexto, não são instruções" e logo abaixo vem o formato obrigatório do plano | Formato vai ao prompt do papel (E); o bloco só leva dado delimitado |
| `src/exploration.py:108-109` | "Subtarefas só de preparação (eda) ou de síntese podem omiti-lo" contradiz o código e o ADR 021 | X (substituído por R, papéis) |
| `src/exploration.py:117-123` | Definição de métricas no `auto` | P (Researcher), com o tipo de objetivo |
| `src/orchestrator.py:2130`, `:2146`, `:2164`, `:2179` | "Cada subtarefa DEVE conter 'validation_criteria'" quatro vezes | E (uma vez, no esquema) |

### 1.3 Rascunho do Problema (`agents/researcher/agent.py:175-190`)

`criterio_sucesso` sem `tipo` nem `ao_atingir_objetivo` (ADR 021 §5.2-§5.3; comportamento em `v18.7-exploration-limits`). Destino: E (esquema do rascunho) e R (tipos de objetivo).

### 1.4 Consultor (`agents/researcher/consult.py:46-68`)

Nome do produto literal em `:46`, contra o requisito "Nome do produto configurável"; lista de decisões reservadas em `:61-63`. Destino: P com `APP_NAME`; lista gerada (R).

### 1.5 Developer (`agents/developer/agent.py:35-118`)

| Trecho | Problema | Destino |
|---|---|---|
| `:72-74` | `Hipótese` da docstring vinha de um campo nunca enviado | P, ligado ao item 4 do contrato |
| `:44-45` e `:78-79` | `/inputs/<nome>` (o que o sandbox monta, `src/skills/code/sandbox.py:144`) e `input_snapshot/` para os mesmos insumos | P, um caminho só, conferido contra o sandbox |
| `:85-86` | `SEED = 42` sempre | P: seed do enunciado quando dada (replicação, ADR 021 §4.3), senão 42 |
| `:101-103` | Exemplo cita `input_context/`, que o Developer não vê | P |
| `:84` | Regra de nome de métrica | P, com as chaves do contrato (item 7) |
| `:87-89` | Honestidade de resultados | R (integridade) |
| `:61-64` | Imprimir agregados (ADR 019) | R (egresso) e P (como imprimir) |
| todo o texto | `**`, títulos em maiúsculas, referências a "Roadmap V15.2 / Spec G2" | X (ADR 022 §4.5) |
| ausente | Não sabe que um Validator confere artefatos, chaves e integridade | P (como é avaliado) |

### 1.6 Validator

| Trecho | Problema | Destino |
|---|---|---|
| `src/agents/validator_agent.py:83-97` (`SCHEMA_INSTRUCTION`) | Cópia do formato do plano | E |
| `:716-735` (plano) | Não conhece papéis, retiradas da governança, colisão, critério sem chave, objetivo do Problema | P e R |
| `:989-1012` (revisão) | Revista em `v18.7-subtask-contract`; aqui só o texto passa ao padrão de seções | P |
| `:517-531` (afirmações) e `:536-548` (definição de métricas) | Definição de métricas sem tipo de objetivo | P, E |

### 1.7 Curator (`agents/curator/agent.py:28-92` e edição `:98+`)

Não sabe das hipóteses `origem = "sistema"` nem que pode sugerir reformulação (ADR 021 §3.7), nem que é acionado na estagnação para sugerir direções novas (ADR 021 §5.5). Destino: P; o fluxo vai para R.

### 1.8 Summarizer (`agents/summarizer/agent.py:26-65`) e revisão de conclusões (`src/claims/revision.py:29-37`)

Sem divergência com o código; a narrativa não cita o motivo de parada nem o objetivo do Problema. Destino: P, com o esquema da narrativa gerado (E).

### 1.9 Base (`agents/base/agent.py:84-118`) e modos (`:274-293`)

O prompt do `base` afirma rodar "em um Raspberry Pi 5" e manda usar `quick_search`/`web_reader`; o normalizador troca `base` por `developer` no plano (spec `agent-runtime`, "Papéis de subtarefa do plano"), e nenhum fluxo atual o aciona (questão §10.1). `_MODE_GUIDANCE` é regra comum fora de fonte versionada. Destino: modos para R; `base` conforme a questão.

## 2. Estrutura do regimento (ADR 022 §4.1, §5)

```
src/agents/regimento/
  regimento.md     prosa: orientação, uma seção por assunto
  regimento.yaml   parte estruturada: regras com efeito no código
```

### 2.1 `regimento.md`

Cada seção começa com um título de nível 2 e uma linha de metadados, que o carregador lê e remove antes da injeção:

```
## Como o sistema funciona
<!-- secao: fluxo; aplica: comum -->
Texto direto, frases curtas.

## Objetivo do tipo discriminacao
<!-- secao: objetivo_discriminacao; aplica: objetivo:discriminacao -->
...

## Modo auto
<!-- secao: modo_auto; aplica: modo:auto -->
...
```

Seções previstas: `fluxo` (plano, validação do plano, governança das hipóteses, execução no sandbox, revisão, ingestão no grafo, veredito, próxima volta ou parada, e o papel que faz cada passo), `exploracao` (hipóteses, papéis de experimento, variações, derivações, replicação, o que impede a execução), `objetivo_<tipo>` para `limiar`, `discriminacao`, `cobertura` e `fronteira`, `paradas` (paradas e retiradas), `integridade` (regras comuns e egresso) e `modo_<modo>` para `assisted`, `semi` e `auto`. A prosa não tem tabelas nem listas de códigos: elas são geradas do YAML (§3.2).

### 2.2 `regimento.yaml`

```yaml
versao: 1
papeis_experimento:
  - id: teste
    descricao: "mede algo que uma hipótese afirma"
  - id: preparacao
    descricao: "produz insumo ou caracteriza o problema"
  - id: referencia
    descricao: "mede o ponto de comparação do Problema"
ordem_decisao_papel:            # ADR 021 §2, regras 1 a 6, na ordem
  - {regra: declarado_no_plano, texto: "..."}
  - {regra: hypothesis_ref_resolvivel, papel: teste}
  - {regra: tipo_eda_ou_synthesis, papel: preparacao}
  - {regra: sinal_de_teste, papel: teste}
  - {regra: tem_dependentes, papel: preparacao}
  - {regra: caso_residual, papel: preparacao}
tipos_objetivo:
  - id: limiar
    implementado: true
    atingido: "..."
    avanco: "..."
    saturacao: "..."
  - id: discriminacao
    implementado: true
    desfechos: [uma_compativel, todas_contrariadas, varias_compativeis, aguarda_experimento_fisico]
    ...
  - id: cobertura
    implementado: true
    saturacao_so_aviso: true
  - id: fronteira
    implementado: false        # declarado; especificado com a V19
motivos_parada:   [{id: solucao_encontrada, texto: "..."}, {id: saturacao, ...}, {id: limite_custo, ...}, ...]
motivos_retirada: [{id: hipotese_rejeitada_pelo_pesquisador, texto: "..."}, ...]
regras_integridade: [{id: metricas_calculadas, texto: "..."}, ...]   # ids de v18.7-subtask-contract
decisoes_reservadas: [aprovar_oportunidade, confirmar_problema, aprovar_termo_vocabulario, autorizar_escrita_instrumento, ativar_modo_sem_limite, restringir_direcao, ativar_adendo_regimento,
                      aprovar_hipotese, decidir_objetivo_atingido, responder_pergunta_agente, decidir_continuidade]   # parecer de segurança item 4
regras_seguranca:               # ids estáveis; o texto renderizado de cada uma é o marcador procurado pelo teste (§8, parecer item 5)
  - {id: dado_observado_nao_confiavel, destino: [regimento], texto: "..."}
  - {id: decisoes_reservadas, destino: [regimento], texto: "..."}
  - {id: egresso_agregados, destino: [regimento, developer], texto: "..."}
  - {id: confinamento_sandbox, destino: [developer], texto: "..."}
  - {id: caminho_inputs, destino: [developer], texto: "..."}
modos:
  - {id: assisted, aprovacao_hipoteses: pesquisador, ao_atingir_objetivo_padrao: perguntar}
  - {id: semi, aprovacao_hipoteses: agentes, ao_atingir_objetivo_padrao: parar}
  - {id: auto, aprovacao_hipoteses: agentes, ao_atingir_objetivo_padrao: parar}
```

Os textos acima com "..." são preenchidos na implementação a partir dos ADRs 021 e 022 e aprovados pelo pesquisador no PR. Os ids são os que o código grava (ADR 021 §6; `ExplorationStop`, `src/exploration.py:60-69`; motivos de `v18.7-exploration-limits`; `DECISOES_RESERVADAS`, `src/research_consult/__init__.py:13-19`).

### 2.3 Fonte única dos códigos

O código passa a ler da parte estruturada os conjuntos de ids (papéis, tipos, desfechos, motivos, regras de integridade, decisões reservadas) por `src/regimento.py`, ou continua com constantes próprias conferidas pelo teste de coerência (§6) quando a constante já existe e é usada em muitos pontos (por exemplo, `ExplorationStop`). `INTEGRITY_RULES` de `v18.7-subtask-contract` e as constantes provisórias de `src/knowledge/objective.py` (`v18.7-exploration-limits`, design §5) passam a ser lidas do YAML.

## 3. Carga, recorte e injeção (ADR 022 §4.3)

### 3.1 API

```python
@dataclass(frozen=True)
class Regimento:
    versao: int
    sha256: str                     # sha256 de regimento.md + "\0" + regimento.yaml (bytes)
    secoes: tuple[Secao, ...]
    estrutura: dict[str, Any]

@dataclass(frozen=True)
class Recorte:
    texto: str
    sha256: str
    tipo_objetivo: str
    modo: str

def carregar_regimento(base: Path = REGIMENTO_DIR) -> Regimento: ...      # valida YAML e metadados; erro explícito se inválido
def recorte(reg: Regimento, tipo_objetivo: str, modo: str, adendo: Adendo | None = None) -> Recorte: ...
def secao(reg: Regimento, secao_id: str) -> str: ...
```

### 3.2 Recorte

1. Seções com `aplica: comum`, mais `objetivo:<tipo>` do tipo do `Problema` e `modo:<modo>` da sessão, na ordem do arquivo.
2. Tabelas geradas do YAML, filtradas: tipo de objetivo da sessão, motivos de parada que valem para o modo, decisões reservadas, regras de integridade, papéis de experimento e ordem de decisão.
3. Sem projeto ou sem `Problema`: só as seções comuns e a do modo. `Problema` sem tipo (dados antigos): `limiar`, como o comportamento atual.
4. O adendo aprovado (§5), quando houver, vem no fim, sob o título "Regras adicionais do projeto".
5. O recorte de qualquer combinação de tipo e modo tem no máximo `REGIMENTO_EXCERPT_MAX_CHARS` (padrão 8000); acima disso, `carregar_regimento` falha com erro que cita a combinação, e o teste de coerência o pega antes do merge.

### 3.3 Injeção

O `system` de toda chamada de agente passa a ser: prompt do papel, linha em branco, cabeçalho `REGIMENTO DA PESQUISA (versão <v>; objetivo <tipo>; modo <modo>)`, recorte. Chamadas cobertas: Researcher (plano, replanejamento, rascunho do Problema, consultor), Developer, Validator (plano, revisão, verificação de afirmações, definição de métricas), Curator (execução e edição), Summarizer (narrativa e revisão de conclusões). Ficam fora: prompt de visão, sumarização de contexto e chamadas que não são de papel. O recorte é calculado uma vez por sessão e combinação, e é o mesmo em todas as chamadas, o que dá prefixo estável para o cache de prompt dos provedores que o oferecem, sem depender dele (ADR 011).

Para o Developer, o `system` com prompt e recorte vai em toda chamada do laço da subtarefa (a API não guarda estado), como já acontece com o prompt do papel (`src/llm/agent_loop.py:305-309`); o contrato da subtarefa vai uma vez por tentativa, no histórico (`v18.7-subtask-contract`).

### 3.4 Ferramenta `ler_regimento`

`ler_regimento(secao: str = "") -> str`, em `agents/base/tools.py`, registrada para Researcher, Developer e Curator. Sem argumento, devolve a lista de seções com id e título; com um id, o texto da seção mais as tabelas geradas que ela cita; id desconhecido devolve a lista de ids válidos. A saída é `instrucao` sem contaminação (arquivo do repositório), limitada a `REGIMENTO_EXCERPT_MAX_CHARS`. A ferramenta lê o `Regimento` carregado na sessão, nunca o disco de novo, para que a versão seja a registrada. O adendo não é lido por ela (já vem no recorte).

## 4. Versão por sessão (ADR 022 §4.4)

1. No início da sessão, o orquestrador carrega o regimento e o adendo e grava o evento `regimento_sessao` com `versao`, `regimento_sha256`, `adendo_sha256` (ou vazio) e, a cada recorte novo calculado, `recorte_sha256` com `tipo_objetivo` e `modo`. O payload da sessão guarda o mesmo em `regimento`.
2. `AgentContext` ganha `regimento_sha256` e `recorte_sha256`, para que `v18.7-exploration-metrics` os registre junto com o hash do contrato de cada tentativa.
3. Na retomada, se o hash do regimento do disco difere do registrado, a sessão usa o do disco e grava o evento `regimento_alterado` com os dois hashes.
4. O regimento é carregado uma vez por sessão; uma mudança no arquivo durante a sessão só vale na sessão seguinte.

## 5. Adendo de projeto

1. **Arquivo:** `REGIMENTO_ADDENDUM_FILE` (padrão `regimento_adendo.yaml`), procurado em `INPUT_CONTEXT_DIR` (insumos do pesquisador, fora do repositório). O arquivo é excluído da indexação de insumos e da ingestão de dados de pesquisa.
2. **Formato:** só as chaves `versao`, `regras` e `proibicoes`; cada item tem `id` (`^[a-z][a-z0-9_]{2,63}$`) e `texto` (até 500 caracteres). Qualquer outra chave torna o adendo inválido. Não há chave capaz de alterar a parte estruturada (tipos, motivos, limites, integridade): o adendo só acrescenta.
3. **Precedência:** o regimento declara, na seção `integridade`, que em conflito vale a regra mais restritiva e que o adendo nunca desliga paradas, limites nem regras de integridade.
4. **Ativação:** decisão reservada nova `ativar_adendo_regimento`, pelo gate persistente de `v18.7-persistent-human-gate` (mergeada antes desta mudança). O pedido tem `referencia` igual ao sha256 dos bytes do adendo e mostra o texto, o hash e a linha fixa sobre egresso: "Depois de aprovado, o adendo é enviado como instrução a todos os provedores da sessão." Quando o texto cita ids de motivo de parada, de limite ou de regra de integridade da parte estruturada, o pedido traz, para cada classe citada, a linha fixa "Aviso: o adendo cita <ids> (<classe>). Confira se o texto afrouxa alguma regra; o adendo nunca desliga paradas, limites nem regras de integridade.", com `<ids>` em ordem alfabética separados por vírgula e `<classe>` em `motivo de parada`, `limite` ou `regra de integridade`.
5. **Prova da aprovação (parecer item 1):** a sessão só injeta o adendo quando existe em `gate_requests` um pedido `ativar_adendo_regimento` com `referencia` igual ao sha256 dos bytes lidos, `estado = 'autorizada'` e `resolvido_por` em `terminal` ou `cli`. A consulta é a única fonte da decisão; a cópia do hash aprovado no projeto é só informativa e nunca é lida para decidir a injeção. A forma da consulta (consumo de uso único ligado à cadeia da sessão ou leitura por `referencia`) depende da questão §10.6.
6. **Leitura única (parecer item 2):** o arquivo é lido uma vez por sessão, com `O_NOFOLLOW`; link simbólico ou caminho resolvido fora do diretório de insumos é recusado e a sessão não começa. O hash é calculado sobre esses bytes e são os mesmos bytes que entram no recorte.
7. **Na sessão:** adendo com o hash aprovado é injetado como `instrucao` sem contaminação. Adendo presente e não aprovado (novo ou alterado) não é injetado, e a sessão não executa subtarefas enquanto o pedido estiver pendente: no `assisted` e no `semi`, registra o pedido e espera; no `auto`, a sessão registra o pedido, não começa e sai com o código 1 ("sessão recusada antes de começar", tabela única de `v18.7-background-sessions/design.md` §1.4), com mensagem que cita `ativar_adendo_regimento` e o hash. Adendo inválido: a sessão não começa, com o erro de formato e o mesmo código 1.

## 6. Coerência (ADR 022 §5) e redação (§4.5)

Testes unitários em `tests/unit/test_regimento_coerencia.py`, sem LLM:

1. **Código e parte estruturada:** os conjuntos de ids do YAML são iguais aos do código: `ExplorationStop` e motivos de parada de uso; motivos de retirada gravados pela exploração; papéis de experimento; tipos de objetivo e desfechos (`src/knowledge/objective.py`); `INTEGRITY_RULES`; `DECISOES_RESERVADAS`; modos de sessão. Um id no código sem declaração no YAML, ou o contrário, falha o teste.
2. **Prosa:** todo identificador entre crases na prosa que pertença a um dos conjuntos acima existe no YAML; a prosa não tem linhas de tabela (`|`); toda seção tem metadados válidos; todo tipo e modo do YAML tem a sua seção.
3. **Formatos gerados:** o texto de formato em cada prompt é igual ao renderizado do esquema correspondente (plano, parecer do Validator do plano e da revisão, rascunho do Problema, resposta do consultor, narrativa do Summarizer, `metrics.json`), e os campos do esquema são os que o código valida (`MANDATORY_KEYS`, normalizador do plano, `parse_problem_draft`, parser da narrativa, `save_experiment_artifacts`).
4. **Uma regra, um lugar:** nenhuma frase normalizada (minúsculas, sem pontuação, com 40 caracteres ou mais) aparece duas vezes no conjunto regimento mais prompts de papel.
5. **Redação:** regimento e prompts renderizados não têm emoji nem pictograma (categorias Unicode `So` e `Sk`, exceto `°`), `**`, `===`, `---` decorativo, setas Unicode, palavras inteiras em maiúsculas com 4 letras ou mais fora da lista de siglas permitidas (JSON, CSV, YAML, ADR, URL, API, DAG, LLM, PNG, SHA), nem referências a roadmap ou spec antiga ("Roadmap V", "Spec G").
6. **Tamanho:** o recorte de cada combinação de tipo e modo cabe em `REGIMENTO_EXCERPT_MAX_CHARS`.

## 7. Prompts por papel (ADR 022 §4.2)

Todo prompt de papel tem as mesmas seções, nesta ordem, com títulos curtos em texto simples: `Papel`, `O que você recebe`, `O que você produz` (formato gerado do esquema), `Ferramentas`, `Como você é avaliado`, `Regras do papel`. O que é comum fica no regimento e não se repete.

| Papel | Recebe | Produz | Como é avaliado |
|---|---|---|---|
| Researcher (plano) | Construtor do plano (`v18.7-subtask-contract`): tarefa, projeto e objetivo, hipóteses e sugestões, retorno do ciclo | Plano JSON do esquema, com `papel` declarado quando souber | Validator do plano; colisões e campos longos são reprovados; retiradas voltam como retorno |
| Researcher (rascunho do Problema) | Tarefa e contexto | `criterio_sucesso` com tipo de objetivo | Confirmação pelo gate ou pelo Validator, conforme o modo |
| Researcher (consultor) | Pergunta de outro agente | JSON da resposta | Nunca decide decisão reservada |
| Developer | Contrato da subtarefa, contexto do workspace | Código executado no sandbox, `metrics.json` e `params.json` com as chaves do contrato, resposta final curta com os artefatos e as chaves gravadas | Validator: critérios de aceite do contrato e regras de integridade |
| Validator (plano) | Tarefa, objetivo, plano | Parecer JSON do plano | Independência de família (ADR 020) |
| Validator (revisão) | Contrato, integridade, evidência | Parecer tipado (`v18.7-subtask-contract`) | Guarda determinística dos ids |
| Curator | Resumo da sessão, sinalizações, sugestões pendentes, hipóteses do sistema | Chamadas de ferramenta e resumo final | Ferramentas recusam duplicatas e referências inválidas |
| Summarizer | Catálogo de referências, contexto do relatório, motivo de parada e objetivo | JSON da narrativa | Verificação de afirmações |

O Developer recebe a regra de seed: a do enunciado da subtarefa quando houver (replicação), senão 42, sempre registrada em `params.json`. O caminho dos insumos é só `/inputs/<nome>`.

## 8. Segurança

**Ameaças e mitigações:**

1. **Adendo como vetor de injeção ou de afrouxamento.** Quem escreve em `INPUT_CONTEXT_DIR` poderia pôr instruções que o sistema trataria como regra. Mitigações: o adendo só entra com o hash aprovado pelo pesquisador, conferido em `gate_requests` (§5.5); mudança de um byte exige nova aprovação; formato fechado só com acréscimos; aviso quando cita ids de parada, limite ou integridade; precedência da regra mais restritiva declarada no regimento; o adendo não muda nenhum valor que o código aplica (limites, paradas e integridade continuam no código e no YAML do repositório).
2. **Adendo classificado como dado de pesquisa.** Arquivos de `input_context/` são `dado_de_pesquisa` por padrão (spec `data-egress`); o adendo é excluído dessa classificação só depois de aprovado, e só ele (nome exato configurado).
3. **Ferramenta `ler_regimento`.** Só lê o `Regimento` em memória, por id de seção validado contra a lista; não aceita caminho, não lê o adendo nem outro arquivo.
4. **Regimento alterado por PR.** Mudanças passam por PR com aprovação do pesquisador (ADR 022 §4.4); o hash por sessão mostra qual versão conduziu cada sessão.
5. **Prompts mais curtos não podem perder as regras de segurança atuais** (dado não confiável, decisões reservadas, egresso, sandbox). O teste de política existente ("Política de prompts") continua, e um teste novo confere que cada regra de segurança tem destino (R ou P) na versão final: as regras ficam em `regras_seguranca` do YAML com id estável e destino; o texto de cada uma é renderizado do YAML e é o marcador que o teste procura no recorte ou no prompt do papel de destino.
6. **Egresso.** O recorte e os prompts são texto do repositório (`instrucao`, sem contaminação); nenhum dado de pesquisa entra neles.

**Parecer do Analista de Segurança (2026-10-15):** Aprovado com ressalvas.

1. **Médio: fonte da aprovação do adendo.** Pelo §5.4, o hash aprovado fica registrado no projeto, ou seja, a prova da aprovação ficaria num nó que o processo da sessão grava. Requisito: a sessão só injeta o adendo se houver em `gate_requests` (de `v18.7-persistent-human-gate`) um pedido `ativar_adendo_regimento` com `referencia` igual ao sha256 dos bytes, `estado = 'autorizada'` e `resolvido_por` humano. A cópia no projeto é só informativa. Sem o gate persistente, o adendo não é injetado, por isso esta parte é implementada depois daquela mudança.
2. **Baixo: verificação e uso dos mesmos bytes.** O arquivo é lido uma vez; o hash é calculado sobre esses bytes e são esses mesmos bytes que entram no prompt. Link simbólico ou arquivo fora de `INPUT_CONTEXT_DIR` é recusado.
3. **Baixo: egresso do adendo.** Depois de aprovado, o adendo vira `instrucao` enviada a todos os provedores da sessão. O pedido informa isso ao pesquisador.
4. **Baixo: lista de decisões reservadas.** `decisoes_reservadas` do YAML deriva de `DECISOES_RESERVADAS` e inclui os tipos de `v18.7-persistent-human-gate` (`aprovar_hipotese`, `decidir_objetivo_atingido`, `responder_pergunta_agente`, `decidir_continuidade`), que faltam no esboço do §2.2.
5. **Exigido como está escrito:** o teste da ameaça 5 acima usa uma lista nominal das regras de segurança: dado observado não confiável, decisões reservadas, egresso e impressão só de agregados, confinamento do sandbox e caminho `/inputs`. O teste falha se alguma delas ficar sem destino. A ferramenta `ler_regimento` está adequada.

## 8a. Configuração

| Variável | Padrão | Uso |
|---|---|---|
| `REGIMENTO_EXCERPT_MAX_CHARS` | `8000` | Teto do recorte de cada combinação de tipo e modo e da saída de `ler_regimento` |
| `REGIMENTO_ADDENDUM_FILE` | `regimento_adendo.yaml` | Nome do adendo de projeto, procurado nos insumos do pesquisador |

O diretório do regimento é fixo (`src/agents/regimento/`), não configurável, para que a versão registrada seja sempre a do repositório. Ambas as variáveis em `src/config.py` e `.env.example`.

## 9. Análise de impacto nos 6 eixos

| Eixo | Impacto |
|---|---|
| 1. Orquestrador e laço autônomo | Carga do regimento e do adendo no início da sessão; espera do pedido do adendo; montagem do bloco de exploração sem o formato. |
| 2. Agentes e prompts | Todos os prompts reescritos; recorte injetado em toda chamada de papel; ferramenta nova; formatos gerados de esquemas. Risco de mudança de comportamento dos modelos, medido na bateria curta. |
| 3. Sandbox e containers | Nenhum. |
| 4. Persistência de estado | Evento `regimento_sessao` e `regimento_alterado`; payload da sessão com `regimento`; aprovação do adendo lida de `gate_requests` (schema de `v18.7-persistent-human-gate`), com cópia informativa do hash no projeto. Sem schema novo. |
| 5. Segurança e hardening | Adendo com gate e hash; ferramenta só de leitura em memória; regras de segurança preservadas por teste (§8). |
| 6. Testes e telemetria | Testes de coerência e redação; provedor falso que grava o `system` de cada chamada; bateria curta comparada à V18.6. |

## 10. Questões em aberto

1. **Papel `base`.** O prompt é obsoleto e o papel não recebe subtarefas do plano. Proposta: remover o papel e `agents/base/agent.py` numa mudança própria (exige revisar a spec `agent-runtime`, que o lista como executável); aqui, só tirar o texto específico de hardware e as regras repetidas.
2. **Adendo pendente no `auto`.** A proposta (§5.5) impede a sessão de começar. Alternativa: começar sem o adendo e registrar o aviso. Proposta: impedir, porque o adendo existe para restringir.
3. **Local do adendo.** `INPUT_CONTEXT_DIR` é um diretório só; se houver insumos por projeto, o adendo deveria ficar no diretório do projeto. Proposta: usar o diretório de insumos do projeto quando a sessão tem projeto.
4. **Registro por sessão e por tentativa (resolvida na revisão de consistência de 2026-10-15).** O ADR 022 §4.4 pede o hash do regimento e do recorte "junto com o contrato de cada subtarefa (§7)". Esta mudança registra por sessão (`regimento_sessao`) e põe `regimento_sha256` e `recorte_sha256` no `AgentContext`; `v18.7-exploration-metrics` grava por tentativa, no evento `subtask_attempt`, o `contrato_sha256` e o `recorte_sha256` lido do `AgentContext` (nulo enquanto esta mudança não existir).
5. **Teto do recorte.** 8000 caracteres por padrão, a confirmar depois de escrito o texto v1.
6. **Aprovação do adendo entre sessões (alinhar com `v18.7-persistent-human-gate`).** O gate exige que todo consumidor chame `consume_authorized`, de uso único e ligado à cadeia da sessão. Para o adendo isso obrigaria nova aprovação a cada sessão nova do projeto e, no `auto`, deixaria a sessão sem saída: a sessão recusada registra o pedido, e a sessão seguinte, fora da cadeia, não pode consumi-lo. Adotado (requisito em `v18.7-persistent-human-gate`): o adendo é a exceção documentada, com leitura sem consumo por `referencia` (o sha256 liga a aprovação ao conteúdo exato), por um método novo `PersistentGate.authorized_reference(decisao, referencia)` que aquela mudança acrescenta, também no `FakeGate`. Alternativa: manter o uso único e aprovar o adendo a cada sessão. Os cenários desta mudança usam a proposta.

## 11. Riscos e mitigações

| Risco | Mitigação |
|---|---|
| Modelo segue pior um prompt mais curto | Bateria curta comparada à V18.6 antes de aceitar o ADR; `ler_regimento` para o que estiver fora do recorte |
| Recorte aumenta o custo de entrada em toda chamada | Teto por combinação; prompts de papel sem repetições; cache de prompt quando houver |
| Esquema e código divergem depois | Teste de coerência no CI |
| Ordem de merge com `v18.7-exploration-limits` e `v18.7-hypothesis-linking` | Esta mudança é a última das três; os ids que ainda não existirem no código bloqueiam o teste de coerência e são resolvidos antes do merge |
