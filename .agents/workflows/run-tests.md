---
description: Sequência de passos para execução de testes
---

# Workflow de Testes — GeminiClaw

Guia para execução de testes em diferentes níveis, garantindo a
qualidade e integridade do framework.

---

## 1. Testes Unitários

Execução rápida de testes que não dependem de Docker ou API externa.
Use mocks para lógica de negócio e SQLite `:memory:`.

```bash
uv run pytest -m unit -v
```

---

## 2. Testes de Integração

Testes que validam a integração entre componentes, ciclo de vida de
containers e banco de dados local. Requer Docker rodando.

```bash
uv run pytest -m integration -v
```

---

## 3. Cobertura de Código

Geração de relatório de cobertura para os módulos `src` e `agents`.

```bash
uv run pytest --cov=src --cov=agents --cov-report=term-missing
```

---

## 4. Testes E2E (Smoke Test)

Execução de testes de ponta a ponta com API real do Gemini.
**Atenção:** Consome tokens reais. Use com moderação.

```bash
uv run pytest -m e2e -v -s
```

---

## 5. Limpeza de Ambiente

Comandos para limpar containers e bancos de dados de teste residuais.

```bash
# Limpar containers de teste
docker rm -f $(docker ps -aq --filter "name=geminiclaw-test")

# Limpar dbs de teste
rm store/test-*.db
```

---

## Referência de Níveis

| Nível | Marker | Local | Requisitos |
|---|---|---|---|
| Unitário | `unit` | `tests/unit/` | Nenhum |
| Integração | `integration` | `tests/integration/` | Docker |
| E2E | `e2e` | `tests/e2e/` | API Key |
