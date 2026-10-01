# Tarefas: v20-node-identity

## 0. Pré-requisitos
- [ ] 0.1 V16 a V19 concluídas e validadas; respostas às questões em aberto do design §9.

## 1. Identidade
- [ ] 1.1 `src/federation/identity.py`: geração Ed25519, gravação atômica com `0600`/`0700`, senha opcional, `id_federado`.
- [ ] 1.2 Falha fatal sem identidade efêmera com a federação ligada.
- [ ] 1.3 `sign`/`verify`; perfil público.
- [ ] 1.4 Rotação (dupla assinatura) e revogação.
- [ ] 1.5 CLI `geminiclaw federation identity show|init|rotate|revoke|export-public`.
- [ ] 1.6 Variáveis do design §6.

## 2. Testes
- [ ] 2.1 Primeira ativação, identidade estável, federação desligada.
- [ ] 2.2 Diretório sem escrita, chave corrompida.
- [ ] 2.3 Assinatura válida e payload alterado.
- [ ] 2.4 Varredura de logs e telemetria pela chave privada.
- [ ] 2.5 Rotação e revogação.

## 3. Fechamento
- [ ] 3.1 `.env.example`; `uv run ruff check .`; `uv run pytest -m "unit or integration" -v`.
- [ ] 3.2 Revisão do Analista de Segurança; revisão nos 7 eixos; PR para `dev`.
