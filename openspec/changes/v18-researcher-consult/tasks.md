# Tarefas: v18-researcher-consult

## 0. Pré-requisitos
- [ ] 0.1 Respostas do pesquisador às questões em aberto do design §11.
- [ ] 0.2 Conferir se `v18-hypothesis-loop` já está em implementação; se estiver, combinar a ordem dos PRs (ambas tocam `src/orchestrator.py`).

## 1. Guarda de consulta
- [ ] 1.1 `src/research_consult/query_guard.py`: `check_query` puro com as regras do design §4.
- [ ] 1.2 Nomes protegidos a partir de `input_snapshot/` e `artifacts/` da sessão.

## 2. Consultor
- [ ] 2.1 `agents/researcher/consult.py`: prompt, ferramentas embrulhadas pela guarda e pelos limites, saída JSON validada, texto devolvido ao agente.
- [ ] 2.2 Classificação de decisão reservada (`{"reservada": true}`) e lista constante de decisões reservadas.

## 3. Orquestração e skill
- [ ] 3.1 `AgentContext.consult_researcher` (callback) e núcleo no orquestrador (design §1).
- [ ] 3.2 `HumanFeedbackSkill`: `semi`/`auto` chamam o consultor; parâmetro opcional `decisao_reservada`.
- [ ] 3.3 Deduplicação considerando respostas do consultor; registro com os campos do design §6; evento `researcher_consult`.
- [ ] 3.4 Limite por sessão, orçamento (`UsageTracker`), timeout e fallbacks com `motivo_fallback`.
- [ ] 3.5 Medição dos tokens com o `execution_id` do agente que perguntou.
- [ ] 3.6 Variáveis do design §8 em `src/config.py`.
- [ ] 3.7 Texto de `ask_researcher` nos prompts (`agents/developer`, `agents/researcher`, `agents/base`).

## 4. Testes (provedor LLM e busca simulados; nenhuma rede real)
- [ ] 4.1 Modo `auto` com resposta; `assisted` inalterado; consultor desligado.
- [ ] 4.2 Ferramentas exatas; excesso de buscas; web desligada.
- [ ] 4.3 Guarda: decimal, nome de arquivo, ano permitido, URL com dado.
- [ ] 4.4 Decisão reservada por parâmetro e por classificação.
- [ ] 4.5 Registro com buscas e leituras; evento sem texto de página; pergunta repetida.
- [ ] 4.6 Tokens contados; limite por sessão; orçamento em fechamento; timeout.
- [ ] 4.7 Nenhuma leitura de `stdin` em `semi`.

## 5. Fechamento
- [ ] 5.1 `.env.example`; nota na Spec G5 (`roadmaps/specs/G5_human_feedback_loop.md`) apontando para esta mudança.
- [ ] 5.2 `uv run ruff check .`; `uv run pytest -m "unit or integration" -v`.
- [ ] 5.3 Sessão `auto` real (tarefa de referência) com ao menos uma consulta registrada; anexar o trecho de `researcher_interactions` ao PR.
- [ ] 5.4 Revisão do Analista de Segurança (guarda de consulta); revisão nos 7 eixos; PR para `dev`.
