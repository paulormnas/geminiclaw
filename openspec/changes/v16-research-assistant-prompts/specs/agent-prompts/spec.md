# Delta: agent-prompts

## ADDED Requirements

### Requirement: Propósito de assistente de pesquisa
O sistema SHALL apresentar, nas instruções de todos os agentes, o propósito do ADR 010:
conduzir experimentos, formular hipóteses, validar suposições e relatar resultados.

#### Scenario: Researcher pode formular hipóteses
- **WHEN** a instrução do Researcher é renderizada
- **THEN** ela permite formular hipóteses a partir dos insumos do pesquisador e dos resultados obtidos, exigindo `scientific_rationale`

#### Scenario: Busca bibliográfica continua proibida
- **WHEN** a instrução do Researcher é renderizada
- **THEN** ela proíbe busca bibliográfica autônoma e restringe a busca web a dúvidas técnicas

### Requirement: Nome do produto configurável
O sistema SHALL obter o nome do produto exibido nos prompts de `config.APP_NAME`.

#### Scenario: Troca de nome
- **GIVEN** `APP_NAME=NovoNome`
- **WHEN** as instruções são renderizadas
- **THEN** todas exibem "NovoNome" e nenhuma exibe "GeminiClaw"

### Requirement: Prompts coerentes com a execução em sandbox
As instruções MUST NOT orientar execução de comandos no host nem citar container próprio do
agente.

#### Scenario: Política de prompts
- **WHEN** o teste de política percorre as instruções renderizadas
- **THEN** nenhuma contém "ADR 001", "Google ADK", "subprocess" ou "pip install"
- **AND** a instrução do Developer afirma que o código roda somente pela ferramenta de execução em sandbox

### Requirement: Formato do plano preservado
O sistema SHALL manter o formato JSON das subtarefas (`agent_id`, `task_name`, `task_type`,
`prompt`, `hypothesis`, `scientific_rationale`, `validation_criteria`, `expected_artifacts`,
`depends_on`).

#### Scenario: Plano compatível
- **WHEN** o Researcher gera um plano após a mudança
- **THEN** o plano é aceito pelo parser e pelo Validator existentes sem alteração
