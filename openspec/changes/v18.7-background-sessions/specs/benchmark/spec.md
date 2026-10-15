# Delta: benchmark

## ADDED Requirements

### Requirement: Comando direto em primeiro plano no runner
O runner SHALL continuar executando cada combinação pelo comando direto em primeiro plano (`main.py --mode auto ... <tarefa>`), uma sessão por vez, esperando o fim do processo. O comando SHALL ser iniciado em grupo de processos próprio e, no tempo limite, o runner SHALL encerrar o grupo inteiro (`SIGTERM` e, depois da carência `kill_grace_seconds`, padrão 10 s, parâmetro da função que roda a combinação, `SIGKILL`), para que nenhum processo de sessão continue depois da combinação (ADR 023 §1; caso 12).

#### Scenario: Tempo limite encerra o processo da sessão
- **GIVEN** um comando simulado que cria um processo filho que ignora `SIGTERM` e dorme 600 s, um tempo limite de 2 s e `kill_grace_seconds=1`
- **WHEN** a combinação roda
- **THEN** o resultado tem `status="timeout"` e, 5 s depois do início, nenhum processo do grupo existe

#### Scenario: Uma sessão por vez
- **GIVEN** duas combinações na matriz, cada uma com um comando simulado que grava o próprio PID e o instante de início e de fim num arquivo e dorme 1 s
- **WHEN** o runner executa
- **THEN** o início da segunda é posterior ao fim da primeira e nenhum processo do grupo da primeira existe quando a segunda começa

### Requirement: Código de saída coerente com o motivo de parada
`anomalies()` SHALL tratar como anomalia o código de saída 4 ("aguarda o pesquisador": a sessão `auto` não terminou) e todo código de saída que não corresponda à classe do `motivo_parada` gravado (`exit_code_for`, ADR 023 §1, contrato de `v18.7-background-sessions`); código 0 com motivo de parada de pesquisa continua sem anomalia. `stop_class` SHALL classificar como `interrupcao` todo motivo terminado em `_pesquisador` (`interrompida_pesquisador`, `aguarda_pesquisador`, `suspensa_sem_pesquisador`, `encerrada_pesquisador` e `pausada_pesquisador`, este de `v18.7-session-events-terminal`), sem mudar as demais classes do requisito "Classificação dos motivos de parada".

#### Scenario: Aguarda o pesquisador
- **GIVEN** uma execução com `status="exit 4"` e `stop_reason="aguarda_pesquisador"`
- **WHEN** `anomalies()` avalia a execução
- **THEN** há um problema que cita "aguarda o pesquisador"

#### Scenario: Código divergente
- **GIVEN** uma execução com `status="exit 0"` e `stop_reason="limite_tokens"`
- **WHEN** `anomalies()` avalia a execução
- **THEN** há um problema que cita "código de saída divergente"

#### Scenario: Parada de pesquisa
- **GIVEN** uma execução com `status="exit 0"` e `stop_reason="solucao_encontrada"`
- **WHEN** `anomalies()` avalia a execução
- **THEN** nenhum problema de parada ou de código é reportado

#### Scenario: Motivos de ausência do pesquisador são interrupção
- **WHEN** `stop_class` recebe `aguarda_pesquisador`, `suspensa_sem_pesquisador`, `encerrada_pesquisador` e `pausada_pesquisador`
- **THEN** devolve `interrupcao` para os quatro, e `anomalies()` reporta a execução como anomalia de parada
