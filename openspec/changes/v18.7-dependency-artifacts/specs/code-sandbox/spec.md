# Delta: code-sandbox

Os cenários usam o cliente Docker simulado dos testes de `/prior` (registra volumes, `network_disabled` e chamadas) e um teste de integração no Raspberry Pi; nenhum chama provedor LLM.

## ADDED Requirements

### Requirement: Saídas das dependências somente leitura
O sistema SHALL montar, para cada dependência concluída da subtarefa (ADR 022 §9), a pasta `<saída>/<sessão>/<task_name>/` em `/deps_out/<projeto>/<task_name>/` com modo somente leitura, em que `<projeto>` é o `project_id` da sessão ou `sem_projeto`. O escopo SHALL seguir `DEPENDENCY_ARTIFACTS_SCOPE` (`transitivas`, padrão, ou `diretas`). O sistema MUST NOT montar a raiz de saída, a pasta da sessão, a pasta da própria subtarefa nem subtarefa que não seja dependência declarada no plano vigente. Com `DEPENDENCY_ARTIFACTS_ENABLED=false`, nenhuma montagem é feita.

#### Scenario: Leitura da dependência
- **GIVEN** `treinar_regressao_logistica` depende de `dividir_dados`, que gravou `y_train.csv`
- **WHEN** o script da consumidora lê `/deps_out/<projeto>/dividir_dados/y_train.csv`
- **THEN** a leitura devolve o conteúdo gravado pela produtora
- **AND** o resultado traz `dependencias_montadas = ["dividir_dados"]`

#### Scenario: Escrita recusada
- **WHEN** o script tenta gravar em `/deps_out/<projeto>/dividir_dados/y_train.csv`
- **THEN** a gravação falha por sistema de arquivos somente leitura e o arquivo do host fica intacto

#### Scenario: Dependência transitiva
- **GIVEN** `avaliar` depende de `treinar`, que depende de `dividir_dados`, e `DEPENDENCY_ARTIFACTS_SCOPE=transitivas`
- **WHEN** `avaliar` executa
- **THEN** as pastas de `treinar` e de `dividir_dados` são montadas

#### Scenario: Escopo direto
- **GIVEN** a mesma cadeia e `DEPENDENCY_ARTIFACTS_SCOPE=diretas`
- **WHEN** `avaliar` executa
- **THEN** só a pasta de `treinar` é montada

#### Scenario: Própria subtarefa
- **GIVEN** um `DependencyMount` cujo `task_name` é o da subtarefa em execução
- **WHEN** a execução é preparada
- **THEN** a execução é recusada antes de criar o container

#### Scenario: Pasta fora da sessão
- **GIVEN** um `DependencyMount` cuja origem é a raiz de saída, a pasta da sessão ou um link simbólico
- **WHEN** a execução é preparada
- **THEN** a execução é recusada antes de criar o container, com `MountSourceError` na mensagem

#### Scenario: Dependência sem pasta
- **GIVEN** `dividir_dados` concluiu sem gravar nenhum arquivo (pasta inexistente) e `treinar` depende dela
- **WHEN** `treinar` executa
- **THEN** nada é montado para `dividir_dados` e o item 10 do contrato diz "sem arquivos" para ela

#### Scenario: Teto de montagens
- **GIVEN** uma subtarefa com 17 dependências concluídas e `DEPENDENCY_ARTIFACTS_MAX_MOUNTS=16`
- **WHEN** a execução é preparada
- **THEN** a execução é recusada com a mensagem que cita `DEPENDENCY_ARTIFACTS_MAX_MOUNTS=16`
- **AND** nenhuma montagem parcial é feita

### Requirement: Dependência concluída em sessão anterior
Uma dependência concluída numa sessão anterior da cadeia de continuidade SHALL ser montada em `/deps_out/<projeto>/<task_name>/` a partir de `<saída>/<sessão de origem>/<task_name>/`. A sessão de origem MUST pertencer a `AgentContext.readable_dirs` (mesmo projeto); qualquer outra origem SHALL ser recusada.

#### Scenario: Dependência da sessão anterior
- **GIVEN** uma retomada em que `dividir_dados` concluiu na sessão `s1` e `treinar` executa na sessão `s2`
- **WHEN** `treinar` executa
- **THEN** `/deps_out/<projeto>/dividir_dados/` mostra os arquivos de `s1/dividir_dados/`

#### Scenario: Sessão fora da cadeia
- **GIVEN** um `DependencyMount` com origem numa sessão que não está em `readable_dirs`
- **WHEN** a execução é preparada
- **THEN** a execução é recusada antes de criar o container

### Requirement: Execução sem rede com dependência montada
A fase `execute` SHALL rodar sem rede sempre que houver dependência montada, mesmo que todas as entradas de `/inputs` sejam `compartilhavel` (ADR 019 §5; parecer de segurança item 2).

#### Scenario: Sem rede com dependência
- **GIVEN** `needs_network=True`, classificador que autoriza rede, todas as entradas `compartilhavel` e uma dependência montada
- **WHEN** a execução chega à fase `execute`
- **THEN** o container é criado com `network_disabled=True`
- **AND** a nota de rede diz que há saídas de dependências visíveis em `/deps_out`
