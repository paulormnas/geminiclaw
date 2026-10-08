# Tarefas: v20-reproduction-validation

**Estado (2026-10-08):** Não iniciada — nenhum código mergeado.

## 0. Pré-requisitos
- [ ] 0.1 `v20-federated-records`, `v20-remote-knowledge-intake` e `v18.5-sandbox-phases` concluídas.
- [ ] 0.2 Respostas às questões do design §8.

## 1. Reprodução
- [ ] 1.1 `src/federation/reproduction.py`: pré-checagem (código, hash, datasets, pacotes), resumo e confirmação.
- [ ] 1.2 Execução no sandbox com pacotes fixos, ativos com sha256, params e seed; diretório próprio; limites de tempo e por dia.
- [ ] 1.3 Comparação com tolerâncias e classificação.
- [ ] 1.4 Tipo `reproducao` em `src/federation/records.py`; candidato na caixa de saída.
- [ ] 1.5 CLI `geminiclaw federation reproduce <cid>`.

## 2. Testes
- [ ] 2.1 Confirmação negada; nenhum gatilho automático.
- [ ] 2.2 Sem LLM; hash divergente; dataset privado; sem dados locais montados.
- [ ] 2.3 Dentro, fora, tolerância exagerada, falha de execução.
- [ ] 2.4 Registro montado; limite diário; tempo excedido.
- [ ] 2.5 Integração: reprodução real no Pi 5 de um experimento publicado pelo Mac (classificação no conjunto Iris com dataset público).

## 3. Fechamento
- [ ] 3.1 `.env.example`; `uv run ruff check .`; `uv run pytest -m "unit or integration" -v`.
- [ ] 3.2 Revisão do Analista de Segurança e testes do Pentester (código remoto hostil); revisão nos 7 eixos; PR para `dev`; ADR 013 → Aceito quando as cinco mudanças `v20-*` estiverem no `dev`.
