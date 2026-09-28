# Tarefas: v16-research-assistant-prompts

## 1. Nome centralizado
- [ ] 1.1 `APP_NAME` em `src/config.py` e `.env.example`.
- [ ] 1.2 Criar `src/prompts.py::render_instruction`.
- [ ] 1.3 `AGENT_NAME` dos agentes passa a ser o papel.

## 2. Instruções
- [ ] 2.1 Researcher: propósito ADR 010, diretriz de formulação de hipóteses, citações ao ADR 010.
- [ ] 2.2 Developer: sem container próprio; código só pelo sandbox; `packages`.
- [ ] 2.3 Base, Validator (ambos os módulos), Summarizer, Reviewer, Planner: propósito e nome.

## 3. Política de prompts
- [ ] 3.1 `tests/unit/test_prompt_policy.py` com as quatro verificações do design.

## 4. Validação de comportamento
- [ ] 4.1 Rodar duas sessões de referência (uma de reprodução, uma de EDA) antes e depois; registrar no PR diferenças de plano e resultado.

## 5. Fechamento
- [ ] 5.1 Ruff, testes, revisão nos 7 eixos, PR.
