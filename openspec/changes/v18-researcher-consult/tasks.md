# Tarefas: v18-researcher-consult

## 0. Pré-requisitos
- [x] 0.1 Respostas do pesquisador às questões em aberto do design §11: ADIADAS pelo pesquisador; adotados os defaults propostos (ver PR).
- [x] 0.2 Conferir se `v18-hypothesis-loop` já está em implementação; se estiver, combinar a ordem dos PRs (ambas tocam `src/orchestrator.py`). (nenhuma mudança v18-hypothesis-loop em implementação; PR único)

## 1. Guarda de consulta
- [x] 1.1 `src/research_consult/query_guard.py`: `check_query` puro com as regras do design §4.
- [x] 1.2 Nomes protegidos a partir de `input_snapshot/` e `artifacts/` da sessão.

## 2. Consultor
- [x] 2.1 `agents/researcher/consult.py`: prompt, ferramentas embrulhadas pela guarda e pelos limites, saída JSON validada, texto devolvido ao agente.
- [x] 2.2 Classificação de decisão reservada (`{"reservada": true}`) e lista constante de decisões reservadas.

## 3. Orquestração e skill
- [x] 3.1 `AgentContext.consult_researcher` (callback) e núcleo no orquestrador (design §1).
- [x] 3.2 `HumanFeedbackSkill`: `semi`/`auto` chamam o consultor; parâmetro opcional `decisao_reservada`.
- [x] 3.3 Deduplicação considerando respostas do consultor; registro com os campos do design §6; evento `researcher_consult`.
- [x] 3.4 Limite por sessão, orçamento (`UsageTracker`), timeout e fallbacks com `motivo_fallback`.
- [x] 3.5 Medição dos tokens com o `execution_id` do agente que perguntou.
- [x] 3.6 Variáveis do design §8 em `src/config.py`.
- [x] 3.7 Texto de `ask_researcher` nos prompts (`agents/developer`, `agents/researcher`, `agents/base`).

## 4. Testes (provedor LLM e busca simulados; nenhuma rede real)
- [x] 4.1 Modo `auto` com resposta; `assisted` inalterado; consultor desligado.
- [x] 4.2 Ferramentas exatas; excesso de buscas; web desligada.
- [x] 4.3 Guarda: decimal, nome de arquivo, ano permitido, URL com dado.
- [x] 4.4 Decisão reservada por parâmetro e por classificação.
- [x] 4.5 Registro com buscas e leituras; evento sem texto de página; pergunta repetida.
- [x] 4.6 Tokens contados; limite por sessão; orçamento em fechamento; timeout.
- [x] 4.7 Nenhuma leitura de `stdin` em `semi`.

## 5. Fechamento
- [x] 5.1 `.env.example`; nota na Spec G5 (`roadmaps/specs/G5_human_feedback_loop.md`) apontando para esta mudança.
- [x] 5.2 `uv run ruff check .`; `uv run pytest -m "unit or integration" -v`.
- [ ] 5.3 Sessão `auto` real (tarefa de referência) com ao menos uma consulta registrada; anexar o trecho de `researcher_interactions` ao PR.
- [ ] 5.4 Revisão do Analista de Segurança (guarda de consulta); revisão nos 7 eixos; PR para `dev`.
