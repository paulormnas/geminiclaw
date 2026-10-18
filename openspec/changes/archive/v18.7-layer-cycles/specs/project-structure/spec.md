# Capacidade: project-structure

## MODIFIED Requirements

### Requirement: Contrato de camadas verificado
O projeto SHALL declarar um contrato de camadas com a ordem final do design §3 desta mudança, em que `src.egress` fica acima de `src.llm`, e SHALL verificá-lo com a ferramenta de contratos de importação junto com o `ruff` e os testes; importações dentro de funções MUST contar e as que estão sob `TYPE_CHECKING` MUST NOT contar. A lista de exceções do contrato MUST estar vazia (ADR 024 §3.5 e §4).

#### Scenario: Contrato sem exceções
- **WHEN** o teste `unit` lê o contrato em `pyproject.toml` e executa a verificação
- **THEN** a lista de importações ignoradas está vazia e a verificação termina com sucesso

#### Scenario: Importação de llm para egress é acusada
- **GIVEN** um pacote temporário em `tmp_path` (fora da árvore do repositório) com os subpacotes `egress` e `llm`, em que `llm/mod.py` importa `egress` dentro de uma função, e um contrato temporário com as mesmas opções do projeto e as camadas `egress` acima de `llm`, com a raiz trocada pelo pacote temporário
- **WHEN** a verificação roda em subprocesso sobre esse contrato, com `tmp_path` no `PYTHONPATH`
- **THEN** ela termina com código diferente de 0 e a saída cita `llm` e `egress`
