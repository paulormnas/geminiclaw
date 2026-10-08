# Tarefas: v16-research-assistant-prompts

**Estado (2026-10-08):** Implementada, com pendências — PR #63. Os itens abertos abaixo são validação em ambiente real (AGE/Qdrant/Pi 5, adiada para a bateria final) e débitos documentados.

## 1. Nome centralizado
- [x] 1.1 `APP_NAME` em `src/config.py` e `.env.example`.
- [x] 1.2 Criar `src/prompts.py::render_instruction`.
- [x] 1.3 `AGENT_NAME` dos agentes passa a ser o papel.

## 2. Instruções
- [x] 2.1 Researcher: propósito ADR 010, diretriz de formulação de hipóteses, citações ao ADR 010.
- [x] 2.2 Developer: sem container próprio; código só pelo sandbox; `packages`.
- [x] 2.3 Base, Validator (ambos os módulos), Summarizer, Reviewer, Planner: propósito e nome.

## 3. Política de prompts
- [x] 3.1 `tests/unit/test_prompt_policy.py` com as quatro verificações do design.

## 4. Validação de comportamento
- [ ] 4.1 Rodar duas sessões de referência (uma de reprodução, uma de EDA) antes e depois; registrar no PR diferenças de plano e resultado.
      **Não executado nesta implementação**: requer credenciais de provedor LLM reais e
      execução completa de sessão (fora do escopo de um ambiente de agente sandboxed sem
      acesso a rede/API keys). Ver observação no corpo do PR.

## 5. Fechamento
- [x] 5.1 Ruff, testes, revisão nos 7 eixos, PR.
      Ruff e `pytest -m unit -v` 100% verdes; revisão nos 7 eixos fica para o Revisor/Tech
      Lead na Fase 5 do workflow (não autoexecutada pelo mesmo agente que implementou).
