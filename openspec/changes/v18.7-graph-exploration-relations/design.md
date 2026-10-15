# Design: v18.7-graph-exploration-relations

Esta mudança só define o que o grafo aceita e como os leitores interpretam nós antigos. Quem escreve cada nó e aresta, e quando, é especificado em `v18.7-hypothesis-linking`.

## 1. `Experimento.papel`

`NODE_SCHEMAS["Experimento"]` ganha `"papel": PropertySchema(enum=("teste", "preparacao", "referencia"))`, opcional. A ingestão (`ingestion.py:742`, `_experiment_props`) grava o valor que recebe em `SubtaskInput.papel` (campo criado em `v18.7-hypothesis-linking`).

Leitura compatível (ADR 021 §9): `experiment_role(node) -> str` devolve o valor gravado ou `"teste"` quando ausente. Nenhum nó antigo é reescrito.

O papel é imutável depois da criação do `Experimento`? Não: uma subtarefa reexecutada num ciclo posterior reaproveita o mesmo `Experimento` (`ingestion.py:636-643`, busca por `subtarefa_id`) e o papel não muda entre ciclos, porque o `subtarefa_id` é novo a cada plano (`autonomous_loop.py:1147`). A propriedade fica fora da lista de imutáveis para não bloquear correções auditadas pelo pesquisador.

## 2. Hipótese do sistema

### 2.1 Enum e propriedades

| Propriedade | Tipo | Regra |
|---|---|---|
| `origem` | enum, agora com `sistema` | já obrigatória |
| `chave_estruturada` | texto `"<problema_id>\|<abordagem_id>\|<metrica_id>"` | obrigatória quando `origem = "sistema"`; imutável |
| `referencia_fixada` | mapa | obrigatória quando `origem = "sistema"`; imutável |
| `abandonada_por` | enum `pesquisador`, `sistema`, `agente` | opcional; gravada junto com `status = "abandonada"` |
| `motivo_abandono` | texto (até 500 caracteres) | opcional |

A chave usa `|` como separador porque os identificadores aceitos pelo grafo seguem `^[A-Za-z0-9._-]{1,128}$` (`hypotheses.py:64`), sem `|`. O texto da chave permite a busca exata por `find_nodes("Hipotese", {"projeto_id": ..., "chave_estruturada": ...})`, que já valida o nome da propriedade contra o schema (`validation.py`, `validate_node_filter_keys`). `abordagem_id` é o da abordagem **canônica** (cadeia `FUNDIDA_EM` resolvida, `ingestion.py:554`).

`referencia_fixada`:

```json
{
  "valor": 0.62,
  "origem_referencia": "referencia_medida",
  "metrica_id": "met_...",
  "resultado_id": "res_...",
  "fixada_em": "2026-10-20T12:00:00+00:00"
}
```

`origem_referencia` ∈ `referencia_medida` (há `Resultado-REFERENCIA_DE->Problema` da métrica M), `criterio_problema` (valor do critério do `Problema`) ou `indisponivel` (nenhum dos dois; `valor = null`). `resultado_id` só existe com `referencia_medida`. A validação confere a forma do mapa (chaves conhecidas, `valor` número finito ou `null`, `origem_referencia` no enum); valor fora da forma é recusado.

### 2.2 Regra condicional e imutabilidade

`validate_node_properties` (`validation.py`) recebe uma regra por rótulo:

- `create_node("Hipotese", {..., "origem": "sistema"})` sem `chave_estruturada` ou sem `referencia_fixada` é recusado com `MissingPropertyError` indicando o campo.
- Cada componente de `chave_estruturada` é validado na escrita contra `^[A-Za-z0-9._-]{1,128}$` (§2.1); valor fora do padrão é recusado indicando `chave_estruturada` (parecer de segurança, item b).
- `IMMUTABLE_LABEL_FIELDS = {"Hipotese": frozenset({"chave_estruturada", "referencia_fixada"})}` em `schema.py`; `update_node` que tente alterar qualquer um dos dois (em qualquer hipótese, de qualquer origem) é recusado com `ImmutableFieldError`, como os campos comuns (`schema.py:94`). Gravar a propriedade pela primeira vez numa hipótese que não a tinha também é recusado: a chave e a referência só nascem com a hipótese do sistema.

### 2.3 Autoridade sobre `abandonada_por`

`HUMAN_ONLY_TRANSITIONS` (`validation.py:263`) passa a ter `"Hipotese": ("abandonada_por", "pesquisador")`. Pelo mecanismo existente, qualquer `Actor` que não seja `pesquisador` é recusado ao gravar `abandonada_por = "pesquisador"` ou ao trocar esse valor por outro. Isso garante, no grafo, que só o pesquisador cria o abandono que bloqueia e que o sistema não reabre uma hipótese abandonada por ele (ADR 021 §3.5, §6). Para não depender só do campo, `update_node` que mude o `status` de uma hipótese com `abandonada_por = "pesquisador"` para outro valor, por actor diferente de `pesquisador`, também é recusado.

Valores e quem os grava (detalhado em `v18.7-hypothesis-linking`):

| Valor | Quem grava | Situação | Bloqueia novos testes? |
|---|---|---|---|
| `pesquisador` | `Actor(kind="pesquisador")` | rejeição no lote do `assisted` (`hypothesis_cycle.py:401`) e abandono pelo pesquisador | sim |
| `sistema` | orquestrador | ciclo de vida da hipótese do sistema (ADR 021 §3.5) | não; reabre pela chave |
| `agente` | Researcher (via orquestrador) | sugestão do Curator recusada (`hypotheses.py:711`) e alternativa descartada numa decisão (`hypotheses.py:786`) | ver questão 2 |

### 2.4 Leitura compatível

`abandoned_by(node) -> str | None`: `None` se a hipótese não está `abandonada`; o valor gravado se existir; senão `"pesquisador"`. Esta é a regra provisória adotada na spec (requisito "Autor do abandono", cenário "Hipótese abandonada antiga (regra provisória da questão 1)") até a decisão da questão 1: mantém o bloqueio que essas hipóteses têm hoje, e a decisão pode trocar só esta função, sem mudar o schema. `Hipotese.origem` existente não muda.

## 3. Relações novas

```python
_rel("Experimento", "PREPARA", ("Hipotese", "Problema")),
_rel("Resultado", "REFERENCIA_DE", "Problema"),
_rel("Hipotese", "DERIVADA_DE", ("Insumo", "Descoberta", "Oportunidade", "Hipotese")),
```

- `PREPARA` é gravada com `origem = "derivado"` (o sistema a deduz do DAG; enum de `COMMON_EDGE_PROPERTIES`, `schema.py:99`).
- `REFERENCIA_DE` é gravada com `origem = "afirmado"` (vem da declaração `papel: referencia` do Researcher).
- `DERIVADA_DE` de uma hipótese para ela mesma é recusada (`create_edge` com `src_id == dst_id` para esse tipo). Ciclos longos (h1 → h2 → h1) não são verificados nesta mudança: a leitura da árvore usa profundidade limitada (questão 3).
- As três relações carregam as propriedades comuns de aresta; `PREPARA` e `REFERENCIA_DE` não têm propriedades próprias.

`PREPARA` e `REFERENCIA_DE` não entram em `collect_attempts` (`service.py:331`), que segue usando `TESTA`, `PRODUZIU` e `MEDE`: preparação e referência não são evidência a favor nem contra hipótese (ADR 021 §3.2: o valor medido da referência é registrado e não entra no veredito nesta etapa).

## 4. Migração

`scripts/migrate_v17_knowledge.py` já cria um `create_elabel` por tipo de `schema.RELATION_TYPES` e pula os existentes (`migrate_v17_knowledge.py:118-135`). Basta reexecutá-la: cria `PREPARA` e `REFERENCIA_DE`. Os grants do papel `knowledge_reader` usam `ALTER DEFAULT PRIVILEGES` e `GRANT SELECT ON ALL TABLES` no schema do grafo, o que cobre as tabelas novas de rótulo; a tarefa 4.2 confirma isso com `read_query` sobre as arestas novas.

O `InMemoryGraphStore` não precisa de migração.

## 5. Contratos

- `src/knowledge/schema.py`: `IMMUTABLE_LABEL_FIELDS: dict[str, frozenset[str]]`; constantes `PAPEIS_EXPERIMENTO = ("teste", "preparacao", "referencia")`, `ORIGEM_SISTEMA = "sistema"`, `ABANDONADA_POR = ("pesquisador", "sistema", "agente")`, `ORIGENS_REFERENCIA = ("referencia_medida", "criterio_problema", "indisponivel")`.
- `src/knowledge/exploration_reads.py` (novo, só leitura): `experiment_role(node: Node) -> str`, `abandoned_by(node: Node) -> str | None`, `structured_key(problem_id: str, approach_id: str, metric_id: str) -> str`.
- Nenhum evento novo.

### 5.1 Construtores compartilhados de grafo em memória para testes

Esta mudança cria `tests/support/exploration_graph.py`, sobre `HypothesisWorld` (`tests/support/hypothesis_world.py`) e `CuratorGraph` (`tests/support/curator_graph.py`), sem duplicá-los. As mudanças seguintes da V18.7 (`v18.7-hypothesis-linking`, `v18.7-exploration-limits`, `v18.7-exploration-metrics`, `v18.7-subtask-contract`) reutilizam estes construtores e só os estendem; não criam construtores próprios para os mesmos nós.

| Construtor | Monta no `InMemoryGraphStore` |
|---|---|
| `problema(tipo="limiar" \| "discriminacao" \| "cobertura" \| None, **campos)` | `Problema` confirmado com `criterio_sucesso` no formato de `v18.7-exploration-limits` (design §4.1); `tipo=None` monta o critério antigo, sem `tipo`. Até aquela mudança, o schema não confere a estrutura por tipo, e o construtor só grava o mapa |
| `hipotese(origem=..., status=..., abandonada_por=None, chave=None, referencia=None, actor=None)` | `Hipotese` com `SOBRE->Problema`; `origem="sistema"` preenche `chave_estruturada` por `structured_key` e uma `referencia_fixada` válida; o `Actor` padrão segue a origem (pesquisador, agente ou orquestrador) |
| `experimento(papel=None, testa=None, prepara=(), subtarefa=...)` | `Experimento` com `papel` opcional (ausente = nó antigo), `TESTA` e `PREPARA` |
| `resultado(experimento, valor, metrica=None, validado=True)` | `Resultado` com `PRODUZIU` e `MEDE` para a métrica do `Problema` |
| `referencia(valor, metrica=None)` | `Experimento` `papel = "referencia"` e `Resultado` com `REFERENCIA_DE->Problema` |

Os construtores gravam com o `Actor` que o caminho real usaria, para que os testes exercitem a validação, e nunca chamam provedor LLM.

## 6. Análise de impacto nos 6 eixos

| Eixo | Impacto | Detalhes |
|---|---|---|
| Orquestrador & Loop | Nenhum | O laço não muda nesta mudança; quem usa o schema é `v18.7-hypothesis-linking` |
| Agentes & Prompts | Baixo | O Curator e o `graph-cli` passam a ver `origem = "sistema"`, `papel` e as relações novas; nenhum prompt muda aqui |
| Sandboxes & Containers | Nenhum | — |
| Persistência de Estado | Médio | Dois rótulos de aresta AGE novos, um valor de enum e cinco propriedades opcionais; leitura compatível para nós antigos; nenhuma reescrita |
| Segurança & Hardening | Médio | Autoridade sobre `abandonada_por = "pesquisador"` passa a ser garantida no grafo; imutabilidade da chave e da referência evita que um agente reescreva a referência da comparação |
| Testes & Telemetria | Baixo | Testes de schema e validação com `InMemoryGraphStore`; teste de integração da migração com AGE real |

## 7. Segurança

Parecer do Analista de Segurança (2026-10-15): **Aprovado.** Respostas aos pontos:

- (a) **Baixo:** a regra do §2.3 é testada em todos os caminhos de escrita: `KnowledgeService`, ingestão, ferramentas do Curator e `graph edit`. O `Actor` nunca deriva de saída de LLM; as ferramentas de agente usam sempre um actor de agente.
- (b) Adequado: a chave usa só ids validados por `^[A-Za-z0-9._-]{1,128}$`.
- (c) `ALTER DEFAULT PRIVILEGES` só cobre tabelas criadas pelo papel que o executou. A migração roda com esse mesmo papel, e a tarefa 4.2 confirma, nas arestas novas, que o `knowledge_reader` lê e não grava.

Sobre a Questão 1, ler as hipóteses antigas como `pesquisador` é a escolha segura.

Rastreio: item (a) no requisito "Autoridade sobre o abandono em todos os caminhos de escrita" (tarefa 2.7); item (b) no requisito "Hipótese de origem sistema com chave e referência fixadas", cenário "Chave com componente inválido" (tarefa 2.6); item (c) no cenário "Grafo anterior à V18.7" (tarefa 4.2).

Pontos para o parecer: (a) a regra de autoridade do §2.3 cobre todos os caminhos de escrita de `Hipotese.status` e `abandonada_por`, inclusive `graph-cli edit`; (b) a escrita de `chave_estruturada` e `referencia_fixada` usa só identificadores conferidos no grafo, nunca texto do LLM; (c) os rótulos novos não alteram os privilégios do `knowledge_reader`.

## 8. Riscos e mitigações

| Risco | Mitigação |
|---|---|
| Hipóteses antigas abandonadas pelo Researcher (alternativas descartadas) ficam bloqueadas para sempre se lidas como `pesquisador` | Proposta conservadora mantém o comportamento atual; a questão 1 pede a decisão do pesquisador |
| Leitor do grafo que assume `origem` em quatro valores quebra com `sistema` | Busca por usos de `origem` nos leitores (tarefa 2.4) e teste de cada um com uma hipótese do sistema |
| Migração não roda no Pi e a escrita de `PREPARA` falha no AGE | A ingestão já enfileira falhas do grafo (`knowledge_pending.jsonl`); a tarefa 4.3 inclui a migração no roteiro de preparação do Pi |
| Ciclo `DERIVADA_DE` entre hipóteses distintas | Leituras de árvore com profundidade limitada; questão 3 |

## 9. Questões em aberto

1. **Hipóteses `abandonada` antigas sem `abandonada_por`.** Proposta: ler como `pesquisador` (continuam bloqueando, como hoje). Até a decisão, a spec adota essa proposta como regra provisória (requisito "Autor do abandono"); a alternativa, se escolhida, muda só `abandoned_by` e esse cenário. Alternativa: inspecionar a trilha de auditoria (`record_audit_note` com `decisao = "rejeitada"` pelo pesquisador, `hypothesis_cycle.py:403`) e ler como `agente` as que não têm essa nota. A alternativa libera alternativas descartadas pelo Researcher em sessões antigas.
2. **Abandono pelo agente (`agente`) bloqueia?** O ADR 021 diz que só o abandono pelo pesquisador bloqueia, mas não trata a sugestão do Curator recusada pelo Researcher nem a alternativa descartada numa decisão, que hoje nascem `abandonada`. Proposta: não bloqueia; se um plano posterior trouxer a mesma hipótese, ela volta como `proposta` e passa pela governança do modo. Alternativa: bloqueia, como hoje. A regra de reabertura fica em `v18.7-hypothesis-linking`; aqui só existe o valor do enum.
3. **Ciclos em `DERIVADA_DE` entre hipóteses.** Proposta: só recusar o laço para o próprio nó nesta etapa. Alternativa: recusar qualquer ciclo na escrita (consulta de alcance a cada aresta nova).
