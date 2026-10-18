# Delta: operation-metrics

## ADDED Requirements

### Requirement: Instantâneo de hardware sem valores fixos
O instantâneo de hardware gravado após cada subtarefa (`hardware_snapshots`) SHALL conter somente valores lidos pelo `HealthMonitor`, com `NULL` para o que a plataforma não expõe; `is_throttled` SHALL ser a temperatura frente a `TEMPERATURE_LIMIT` e SHALL ser `NULL` sem limite configurado ou sem leitura de temperatura; os picos de CPU, RAM e temperatura nas métricas de operação SHALL ser `null` quando não houver leitura (ADR 023 §1.1, itens 1 e 2).

#### Scenario: macOS sem sensor
- **GIVEN** um monitor simulado sem temperatura e com memória e CPU lidas
- **WHEN** uma subtarefa termina com `HEALTH_CHECK_ENABLED=true`
- **THEN** o instantâneo gravado tem `cpu_temp_c=NULL` e `is_throttled=NULL`, e `mem_available_mb` igual à leitura
- **AND** `custo_recursos` nas métricas de operação traz pico de temperatura `null`

#### Scenario: Limitação derivada
- **GIVEN** `TEMPERATURE_LIMIT=75` e temperatura lida de 77,0 °C
- **WHEN** o instantâneo é gravado
- **THEN** `is_throttled=true`
