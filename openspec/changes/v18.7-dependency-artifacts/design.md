# Design: v18.7-dependency-artifacts

## 1. Estado atual e diferença

| Ponto | Hoje | Depois |
|---|---|---|
| Saídas das dependências no sandbox | Ausentes: `/outputs` é só a pasta da subtarefa (`sandbox.py`, volume `abs_output_dir`) | Cada dependência montada somente leitura em `/deps_out/<projeto>/<task_name>/` |
| Dependência concluída em sessão anterior | Visível só como `/prior/<sessão>/...` (a sessão inteira), sem que o Developer saiba qual pasta é a da dependência | Montada no mesmo caminho `/deps_out/<projeto>/<task_name>/`, a partir da pasta da sessão anterior |
| O que o Developer sabe | Nome e caminho do host no prefixo de contexto; a regra 2 do prompt manda ler de `/outputs/` | Item 10 do contrato com o caminho montado e os arquivos de cada dependência; regra 2 aponta para `/deps_out/` |
| Rede na execução | Sem rede quando há dados produzidos em `/outputs` ou `/prior` montado | Também sem rede quando há dependência montada |
| Proveniência | `collect_inputs` lista `input_snapshot/`, `/prior/*` e a pasta da tarefa | Também os arquivos das dependências montadas, com o `task_name` e a sessão de origem |

## 2. Contratos

```python
# src/utils/agent_context.py
@dataclass(frozen=True)
class DependencyMount:
    task_name: str            # subtarefa produtora (nome seguro, _SAFE_NAME_RE)
    source: Path              # <saída>/<sessão>/<task_name>, resolvido
    session_id: str           # sessão onde a produtora executou (a atual ou uma da cadeia de continuidade)

AgentContext.dependency_dirs: tuple[DependencyMount, ...] = ()

# destino no container (constante em src/skills/code/sandbox.py)
SANDBOX_DEPS_OUT_DIR = "/deps_out"
def dependency_target(project_id: str | None, task_name: str) -> str:
    return f"{SANDBOX_DEPS_OUT_DIR}/{project_id or 'sem_projeto'}/{task_name}"
```

`SandboxCodeRunner.run(..., dependency_mounts: list[DependencyMount] | None = None, project_id: str | None = None)` monta cada uma com `{"bind": dependency_target(...), "mode": "ro"}`. `SandboxResult.dependencias_montadas` lista os `task_name` montados.

O registro `inicio` da proveniência ganha `dependencias: [{"task_name", "sessao"}]` e as entradas das pastas montadas entram em `entradas` (mesmo formato de hoje, caminho relativo à raiz de saída).

`SubtaskContract` ganha `dependency_artifacts: tuple[tuple[str, str, tuple[str, ...]], ...]` (`task_name`, caminho montado, arquivos) e `CONTRACT_VERSION` passa a 2.

## 3. Quem são as dependências

1. O laço (`_execute_task_in_dag`) calcula as dependências da subtarefa no plano vigente: com `DEPENDENCY_ARTIFACTS_SCOPE=transitivas` (padrão), o fecho de `depends_on`; com `diretas`, só `depends_on`.
2. Só entram dependências concluídas (`success` ou `concluded_negative` no DAG, ou concluídas na sessão anterior pela retomada). As canceladas ou falhas já impedem a execução da consumidora, como hoje.
3. A pasta de origem é `<saída>/<sessão atual>/<task_name>` ou, para a concluída na sessão anterior, `<saída>/<sessão de origem>/<task_name>` (`resume.completed[...]` e `resume.source_session_id`). Pasta inexistente (dependência concluída sem gravar nada) não é montada; o item 10 diz "sem arquivos".
4. Acima de `DEPENDENCY_ARTIFACTS_MAX_MOUNTS` dependências, a execução é recusada antes de criar o container, com a mensagem "a subtarefa depende de N subtarefas; o teto é DEPENDENCY_ARTIFACTS_MAX_MOUNTS=M". Nunca se monta parte em silêncio.
5. O orquestrador passa a lista em `AgentContext.dependency_dirs`; a skill de código a lê do contexto (como `readable_dirs`) e a repassa ao sandbox.

## 4. Validação da origem (antes de qualquer container)

Para cada `DependencyMount`, além de `check_mount_source(source, output_root)`:

- `source` é exatamente `<output_root>/<sessão>/<task_name>` (profundidade 2): nunca a raiz de saída, nunca a pasta da sessão, nunca uma subpasta de outra subtarefa;
- `source.parent.name` é a sessão atual ou uma das sessões em `readable_dirs` (cadeia de continuidade do mesmo projeto);
- `task_name` casa com `_SAFE_NAME_RE`, sem `..`, e é diferente da subtarefa em execução;
- sem repetição de `task_name` (colidiria o destino);
- `source` não é link simbólico e não contém link simbólico no caminho (a pasta da produtora já é limpa de links e FIFOs ao fim de cada execução, `sandbox.py`).

Qualquer violação recusa a execução com `MountSourceError` (falha explícita, AGENTS.md §1.6), como para `/prior`.

## 5. Item 10 do contrato

```
10. Artefatos das dependências (somente leitura; grave os seus em /outputs/):
  - /deps_out/<projeto>/dividir_dados/: X_train.csv, y_train.csv
  - /deps_out/<projeto>/baseline/: baseline_metrics.json
```

- Os arquivos listados são os `expected_artifacts` da dependência, trocados pelo nome real quando há alias resolvido (`SubtaskOutput.artifact_aliases`), mais os arquivos efetivamente presentes na pasta, até `DEPENDENCY_ARTIFACTS_LIST_MAX` por dependência (padrão 20; o excedente vira "e mais N").
- Os nomes vão como fragmento de fonte `artefatos` (`ARTIFACT_NAMES_SOURCE`), sujeitos à regra de nomes do ADR 019 para destino sem dados brutos; o caminho montado é texto fixo do sistema.
- Sem dependência: "10. Artefatos das dependências: não se aplica."
- O item entra no hash do contrato; com `DEPENDENCY_ARTIFACTS_ENABLED=false` o item some e o contrato volta ao formato da versão 1.

## 6. Prompt do Developer e prefixo de contexto

- Regra 2 do prompt do Developer: "Artefatos de etapas anteriores estão em `/deps_out/<projeto>/<subtarefa>/`, somente leitura, listados no item 10 do contrato. Leia-os de lá; grave os seus em `/outputs/`. Nunca recrie o que uma dependência já salvou." Só essa frase muda; o resto do prompt é de `v18.7-agent-system-prompts`.
- `SubtaskOutput.to_context_string` passa a mostrar o caminho no container quando a dependência é montada (o laço sabe quais foram), em vez do caminho do host.

## 7. Segurança

### 7.1 Ameaças

1. **Leitura além do declarado.** Uma subtarefa ler a pasta de outra que não é dependência (por exemplo, para copiar um resultado e passar na revisão). Mitigação: só as dependências declaradas no plano vigente são montadas, uma montagem por pasta; a raiz da sessão nunca é montada.
2. **Escrita na produtora.** Alterar o artefato de uma dependência depois de ela ter sido revisada e ingerida. Mitigação: montagem `ro`; o único gravável continua sendo `/outputs` (requisito "Saída por bind mount restrito à subtarefa").
3. **Fuga por link simbólico ou FIFO na pasta da produtora.** Mitigação: `check_mount_source` (origem sem link e dentro da raiz de saída); a limpeza de links e FIFOs ao fim de cada execução da produtora continua; o container não segue links para fora porque só vê as montagens.
4. **Exfiltração de dados produzidos.** Dados derivados de insumos de pesquisa ficam visíveis ao script. Mitigação: execução sem rede sempre que houver dependência montada (ADR 019 §5); a saída impressa continua passando pelos filtros de egresso.
5. **Injeção pelo nome de arquivo no contrato.** Um arquivo com nome hostil gravado pela produtora aparece no item 10. Mitigação: nomes como fragmento `artefatos`, regra de nomes e `strip_marks`; nomes fora de `ARTIFACT_NAME_RE` são omitidos e contados ("e mais N").
6. **Contenção de recursos.** Muitas montagens. Mitigação: teto `DEPENDENCY_ARTIFACTS_MAX_MOUNTS` com recusa explícita.

### 7.2 Parecer do Analista de Segurança (2026-10-18)

Aprovado com ressalvas. As mitigações 1 a 6 são exigidas como escritas, mais:

1. **Médio: sessão de origem.** A pasta de uma dependência concluída em sessão anterior só pode vir de uma sessão da cadeia de continuidade do mesmo projeto (`readable_dirs`), nunca de um caminho calculado a partir de texto do plano. Um teste cobre a recusa de uma sessão fora da cadeia.
2. **Médio: rede.** A decisão de rede (`_network_decision`) trata dependência montada como dado produzido: sem exceção, mesmo que todas as entradas de `/inputs` sejam `compartilhavel`. Um teste cobre o caso.
3. **Baixo: proveniência.** Os arquivos lidos das dependências entram em `entradas` com hash, para a cadeia mostrar o que a consumidora viu; sem isso, uma troca de arquivo entre execuções não seria detectável.
4. **Baixo: registro.** `SandboxResult.dependencias_montadas` e o evento `sandbox_run` registram os `task_name` montados (nunca o conteúdo).

## 8. Configuração

| Variável | Padrão | Uso |
|---|---|---|
| `DEPENDENCY_ARTIFACTS_ENABLED` | `true` | Liga a montagem e o item 10; `false` volta ao comportamento atual |
| `DEPENDENCY_ARTIFACTS_SCOPE` | `transitivas` | `transitivas` (fecho de `depends_on`) ou `diretas` |
| `DEPENDENCY_ARTIFACTS_MAX_MOUNTS` | `16` | Teto de dependências montadas por execução; acima, recusa explícita |
| `DEPENDENCY_ARTIFACTS_LIST_MAX` | `20` | Arquivos listados por dependência no item 10 |

Todas em `src/config.py` e `.env.example`; valor inválido falha na inicialização.

## 9. Questões em aberto (decisão do pesquisador)

1. **Escopo padrão.** Proposta: `transitivas`, porque a falha da `haiku-dev-sol-juiz` envolveu um arquivo de preparação lido duas etapas adiante (`y_train.csv`), e o Researcher nem sempre repete a dependência indireta em `depends_on`. Alternativa: `diretas`, que obriga o plano a declarar tudo e deixa o contrato menor.
2. **Retomada.** Proposta: montar a dependência concluída na sessão anterior em `/deps_out/<projeto>/<task_name>/`, a partir da pasta daquela sessão; `/prior/<sessão>` continua montado como hoje. Alternativa: só `/prior`, com o caminho exato no item 10.
3. **Prompt do Developer.** Proposta: corrigir aqui só a regra 2 (hoje errada) e deixar a revisão do prompt para `v18.7-agent-system-prompts`. Alternativa: esperar aquela mudança, aceitando o erro até lá.

## 10. Análise de impacto nos 6 eixos

| Eixo | Impacto |
|---|---|
| 1. Orquestrador e laço autônomo | O laço resolve as dependências concluídas e a pasta de cada uma (inclusive na retomada) e as passa no `AgentContext`; o contrato ganha o item 10. |
| 2. Agentes e prompts | Regra 2 do Developer corrigida; item 10 no contrato. |
| 3. Sandbox e containers | Montagens `ro` novas em `/deps_out`; decisão de rede; validação da origem. Sem mudança de imagem nem de Dockerfile. |
| 4. Persistência de estado | Sem schema novo; registro de proveniência com `dependencias` e entradas das pastas montadas. |
| 5. Segurança e hardening | §7: leitura restrita às dependências declaradas, somente leitura, sem rede, origem conferida, teto. |
| 6. Testes e telemetria | Cliente Docker simulado (mesmo dos testes de `/prior`) para conferir volumes e `network_disabled`; harness do laço para o item 10 e a retomada; `sandbox_run` com `dependencias_montadas`. Teste de integração no Pi: script que lê `/deps_out/.../y_train.csv` de uma dependência real. |

## 11. Riscos e mitigações

| Risco | Mitigação |
|---|---|
| Plano com dependência não declarada (a consumidora lê de uma subtarefa fora de `depends_on`) | O arquivo não aparece; o item 10 lista o que está disponível; o Validator do plano já confere coerência das dependências |
| Contrato mais longo em planos com muitas dependências | `DEPENDENCY_ARTIFACTS_LIST_MAX` e o teto de montagens; o item 10 não entra no teto `CONTRACT_FIELD_MAX_CHARS` porque é texto do sistema |
| Developer continua lendo de `/outputs/` por hábito | Regra 2 corrigida e item 10 explícito; a bateria mede |
| Diferença entre `mount` e `copy` de entrega de insumos | `/deps_out` é sempre bind `ro`, independentemente de `SANDBOX_INPUT_DELIVERY` (como `/prior`) |
