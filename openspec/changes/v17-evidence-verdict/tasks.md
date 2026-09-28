# Tarefas: v17-evidence-verdict

## 1. Módulo
- [x] 1.1 `src/knowledge/verdict.py`: `Criterion`, `Attempt`, `VerdictParams`, `EvidenceBreakdown`, `VerdictResult`, `compute_verdict`.
- [x] 1.2 Parâmetros em `src/config.py` e `.env.example`.

## 2. Testes-ouro
- [x] 2.1 Exemplo completo do ADR 015 §9.6 (pesos por evidência e veredito).
- [x] 2.2 Cenário "só E1 antes da réplica".
- [x] 2.3 As sete linhas da tabela de referência §9.7.
- [x] 2.4 Divisão por dataset do §9.6 (+0,28 e −0,08).

## 3. Testes de regra
- [x] 3.1 Sentido `menor_melhor` inverte Δ.
- [x] 3.2 Sem baseline usa `alvo` e `m = 0,5`; sem baseline e sem alvo vira ambígua.
- [x] 3.3 Falha de infraestrutura não altera o veredito e soma em `n_tentativas`.
- [x] 3.4 Uma falha de abordagem → ambígua; duas independentes com a mesma assinatura → negativas com `q = 0,3`.
- [x] 3.5 Fator `f` com 6 conclusivas e 2 ambíguas = 0,875.
- [x] 3.6 `nao_validado` não conta como evidência.
- [x] 3.7 Resultado independe da ordem de entrada (ordenado por `timestamp`).
- [x] 3.8 Nenhuma tentativa → veredito 0, `insuficiente`.

## 4. Fechamento
- [x] 4.1 Ruff, testes, revisão nos 7 eixos, PR.
