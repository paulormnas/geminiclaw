# Delta: execution-provenance

## ADDED Requirements

### Requirement: Registros de início e término por execução
O sistema SHALL gravar, para cada chamada da skill de código que passa da validação, um
registro `inicio` antes de qualquer container e um registro `termino` em qualquer desfecho
(sucesso, falha, timeout, falha de instalação ou de busca de ativos, erro do sandbox), ambos
com o mesmo `exec_id` no formato `exec_<uuid4>`.

#### Scenario: Execução bem-sucedida
- **WHEN** um script grava `metrics.json` e termina com código 0
- **THEN** existem um `inicio` e um `termino` com o mesmo `exec_id`
- **AND** o `termino` tem `status="sucesso"`, `hash_codigo`, `hash_params`, `seed`, `entradas`, `saidas`, `imagem`, `pacotes`, `ativos`, `exit_code`, `inicio_execucao`, `fim_execucao` e `prev_hash`

#### Scenario: Timeout
- **WHEN** o script excede `CODE_SANDBOX_TIMEOUT_SECONDS`
- **THEN** o `termino` é gravado com `status="timeout"`

#### Scenario: Falha de instalação
- **WHEN** a fase `install` falha
- **THEN** o `termino` é gravado com `status="falha_install"` e `fase_falha="install"`

#### Scenario: Código recusado pela validação
- **WHEN** o código contém um padrão proibido e é recusado antes do sandbox
- **THEN** nenhum registro é gravado

### Requirement: Cadeia de hash por projeto
O sistema SHALL encadear os registros por projeto: cada registro tem `seq` consecutivo e
`prev_hash` igual ao `record_hash` do registro anterior do mesmo projeto (64 zeros no
primeiro), com `record_hash` = sha256 da serialização canônica do registro, sem valores de
ponto flutuante.

#### Scenario: Encadeamento entre sessões
- **GIVEN** um projeto com ponta `seq=10` gravada por uma sessão anterior
- **WHEN** uma sessão retomada do mesmo projeto executa código
- **THEN** o novo `inicio` tem `seq=11` e `prev_hash` igual ao `record_hash` do `seq=10`

#### Scenario: Ida e volta pelo banco
- **WHEN** um registro é lido de `execution_records` e seu hash é recalculado
- **THEN** o resultado é igual ao `record_hash` gravado

#### Scenario: Métricas como texto
- **GIVEN** `metrics.json` com `{"metrics": {"r2": 0.8}}`
- **WHEN** o `termino` é gravado
- **THEN** `corpo.metricas.r2` é o texto `"0.8"`

### Requirement: Acréscimo serializado
O sistema SHALL serializar o acréscimo de registros por projeto com *advisory lock* de
transação do PostgreSQL, de modo que execuções paralelas e sessões concorrentes nunca criem
bifurcação ou lacuna na cadeia.

#### Scenario: Subtarefas paralelas
- **GIVEN** 8 execuções concorrentes no mesmo projeto, em duas sessões
- **WHEN** todas terminam
- **THEN** a cadeia tem 16 registros com `seq` de 1 a 16, sem repetição, e o `verify` a declara íntegra
- **AND** cada `termino` tem `seq` maior que o do seu `inicio`

### Requirement: Somente-acréscimo no banco
A tabela `execution_records` SHALL recusar `UPDATE`, `DELETE` e `TRUNCATE`.

#### Scenario: Tentativa de alteração
- **WHEN** um `UPDATE execution_records SET corpo = '{}'` é executado
- **THEN** o PostgreSQL levanta erro e o registro não muda

### Requirement: Fail-fast na gravação
O sistema MUST NOT iniciar a execução quando o registro `inicio` não puder ser gravado, e SHALL
guardar em `outputs/<sessão>/provenance_pending.jsonl` o `termino` que não puder ser gravado,
acrescentando-o à cadeia na próxima gravação possível.

#### Scenario: Banco indisponível no início
- **GIVEN** o PostgreSQL indisponível
- **WHEN** a skill de código é chamada
- **THEN** nenhum container é criado e a skill devolve erro "registro de início indisponível; execução não iniciada"

#### Scenario: Banco cai durante a execução
- **GIVEN** o `inicio` gravado e o banco indisponível ao fim da execução
- **WHEN** o `termino` é gravado
- **THEN** ele vai para `provenance_pending.jsonl` e o resultado traz `provenance_pending=True`
- **AND** na próxima chamada da skill com o banco disponível, o `termino` entra na cadeia antes do novo `inicio` e sai do arquivo

#### Scenario: Pendência já acrescentada
- **GIVEN** um pendente cujo `termino` já está na cadeia com o mesmo corpo
- **WHEN** o acréscimo é repetido
- **THEN** nenhum registro novo é criado e o pendente é removido do arquivo

#### Scenario: Sem banco e sem disco
- **WHEN** nem o banco nem o arquivo de pendências aceitam o `termino`
- **THEN** a skill devolve `success=False` com erro explícito

### Requirement: Verificação da cadeia
O sistema SHALL oferecer `geminiclaw provenance verify <projeto>`, que recalcula a cadeia,
confere pares `inicio`/`termino`, confere os hashes das entradas e saídas em disco, lista
execuções órfãs (distinguindo término pendente local), confere as pontas gravadas nos
checkpoints e termina com código 0 (íntegra), 1 (inconsistência) ou 2 (verificação
impossível).

#### Scenario: Registro adulterado
- **GIVEN** o `corpo` de um registro alterado diretamente no banco com os gatilhos desativados
- **WHEN** `verify` é executado
- **THEN** a saída aponta o `seq` com hash divergente e o código de saída é 1

#### Scenario: Arquivo de saída alterado
- **GIVEN** `metrics.json` de uma execução registrada editado no disco
- **WHEN** `verify` é executado
- **THEN** o arquivo aparece como `alterado` e o código de saída é 1

#### Scenario: Execução órfã após queda
- **GIVEN** um `inicio` sem `termino` e sem pendência local (processo morto durante a execução)
- **WHEN** `verify` é executado
- **THEN** o `exec_id` aparece em `orfas` como `sem_termino` e o código de saída é 0

#### Scenario: Banco indisponível
- **WHEN** `verify` é executado sem acesso ao PostgreSQL e sem `--from-export`
- **THEN** o código de saída é 2 com mensagem explicando a causa

#### Scenario: Verificação de exportação
- **GIVEN** o diretório `provenance/` exportado de uma sessão
- **WHEN** `verify --from-export <dir>` é executado sem banco
- **THEN** os elos do segmento são conferidos e o primeiro `prev_hash` é exibido como âncora

### Requirement: Cache de hash por tamanho e data de modificação
O sistema SHALL reutilizar o sha256 de arquivos com tamanho a partir de
`PROVENANCE_HASH_CACHE_MIN_BYTES` quando caminho, dispositivo, inode, tamanho e `mtime_ns` não
mudaram, e `verify --full` SHALL ignorar o cache.

#### Scenario: Entrada grande inalterada
- **GIVEN** um dataset de 100 MB já hasheado
- **WHEN** uma nova execução o recebe como entrada
- **THEN** o hash vem do cache, sem releitura do arquivo

#### Scenario: Verificação completa
- **GIVEN** um arquivo alterado preservando tamanho e `mtime_ns`
- **WHEN** `verify --full` é executado
- **THEN** o arquivo aparece como `alterado`

### Requirement: Ponta da cadeia no checkpoint, no relatório e na exportação
O sistema SHALL gravar `provenance_chain_tip` (`project_id`, `seq`, `record_hash`) e
`provenance_pending` em cada `checkpoint.json`, SHALL acrescentar ao `relatorio_final.md`, pelo
orquestrador e sem LLM, uma seção de proveniência com a ponta e o resultado da verificação da
sessão, e SHALL exportar no fechamento o segmento da cadeia da sessão para
`outputs/<sessão>/provenance/`.

#### Scenario: Fechamento da sessão
- **WHEN** uma sessão com três execuções fecha
- **THEN** `checkpoint.json` e `session_metadata.json` têm `provenance_chain_tip` igual à ponta do projeto
- **AND** `relatorio_final.md` contém a seção "Proveniência das execuções" com a ponta e a contagem por `status`
- **AND** `outputs/<sessão>/provenance/execution_records.jsonl` e `chain_tip.json` existem

#### Scenario: Ponta divergente na retomada
- **GIVEN** um checkpoint cuja ponta não existe na cadeia
- **WHEN** a sessão é retomada
- **THEN** o banner mostra aviso, o evento `proveniencia_divergente` é registrado e o relatório o menciona

### Requirement: Experimento e Resultado derivados do registro
O sistema SHALL derivar `hash_codigo`, `hash_params`, `seed` e `ambiente` do `Experimento` do
`termino` principal da subtarefa, SHALL gravar `exec_id` e `exec_ids` no `Experimento` e
`exec_id` e `hash_metrics` no `Resultado`, e MUST NOT criar `Resultado` quando o
`metrics.json` em disco divergir do hash registrado.

#### Scenario: Subtarefa com retentativa
- **GIVEN** uma subtarefa com uma execução `falha_execucao` seguida de uma `sucesso`
- **WHEN** o `Experimento` é ingerido
- **THEN** `exec_ids` lista as duas, e `exec_id`, `hash_codigo` e `seed` vêm da execução com `sucesso`

#### Scenario: Valor do Resultado vem do registro
- **WHEN** um `Resultado` é criado para a métrica `r2`
- **THEN** seu `valor` corresponde a `corpo.metricas.r2` do `termino` principal

#### Scenario: metrics.json editado antes da ingestão
- **GIVEN** `metrics.json` alterado depois do `termino`
- **WHEN** a ingestão roda
- **THEN** nenhum `Resultado` é criado e o evento `proveniencia_inconsistente` é registrado

### Requirement: Consulta de métrica registrada
O sistema SHALL oferecer `ExecutionLedger.get_metric(exec_id, nome)`, que devolve o valor
registrado no `termino`, o `seq` e o `record_hash`, e levanta erro explícito quando a execução
ou a métrica não existem.

#### Scenario: Métrica inexistente
- **WHEN** `get_metric("exec_…", "f1")` é chamado para uma execução sem `f1`
- **THEN** um erro explícito é levantado, sem valor padrão
