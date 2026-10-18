# Delta: execution-provenance

## ADDED Requirements

### Requirement: Dependências montadas na proveniência da execução
O registro `inicio` de cada execução SHALL listar as dependências montadas em `dependencias` (`{task_name, sessao}`) e SHALL incluir em `entradas` os arquivos das pastas montadas, com hash, no mesmo formato das demais entradas (parecer de segurança item 3).

#### Scenario: Entradas da dependência na proveniência
- **GIVEN** `treinar` lê `/deps_out/<projeto>/dividir_dados/y_train.csv`
- **WHEN** o `inicio` da execução de `treinar` é gravado
- **THEN** `dependencias` contém `{"task_name": "dividir_dados", "sessao": "<sessão>"}`
- **AND** `entradas` contém `dividir_dados/y_train.csv` com o hash do arquivo

#### Scenario: Troca de arquivo entre execuções
- **GIVEN** duas execuções de `treinar` e o `y_train.csv` da dependência alterado entre elas
- **WHEN** os dois `inicio` são comparados
- **THEN** os hashes da entrada `dividir_dados/y_train.csv` diferem
