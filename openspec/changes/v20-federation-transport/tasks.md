# Tarefas: v20-federation-transport

## 0. Pré-requisitos
- [ ] 0.1 `v20-node-identity` e `v20-federated-records` concluídas.
- [ ] 0.2 Decisão do pesquisador sobre a tecnologia e as questões do design §9.

## 1. Spike (antes de qualquer código de produção)
- [ ] 1.1 Avaliar no Pi 5 um cliente do protocolo em Python (biblioteca ou cliente mínimo sobre WebSocket): memória e CPU com 3 relays e 10 mil eventos; registrar no PR.
- [ ] 1.2 Decidir o tipo de evento e as dependências (`uv add`); se o spike falhar, adotar o plano B (relay HTTP mínimo) e atualizar este design antes de seguir.

## 2. Transporte
- [ ] 2.1 `src/federation/transport/base.py` (interface) e transporte falso em memória para testes.
- [ ] 2.2 `src/federation/transport/relay.py`: `wss://` apenas, chave de transporte, autenticação do relay quando exigida, tamanho máximo antes de decodificar.

## 3. Entrada e sincronização
- [ ] 3.1 `bootstrap_relays.json` assinado e verificação com a chave de partida embutida.
- [ ] 3.2 `src/federation/sync.py`: cursores (`federation_sync_state`, migração), sobreposição, deduplicação, limites por relay, por autor e da caixa de entrada.
- [ ] 3.3 Publicação em vários relays com confirmações mínimas e reenvio com recuo.
- [ ] 3.4 `geminiclaw federation sync [--loop]`, adiamento com sessão ativa; exemplo de temporizador do sistema no `SETUP.md`.

## 4. Testes (relays falsos em processo; nenhuma rede externa)
- [ ] 4.1 Troca de transporte; relay sem TLS; nenhuma porta em escuta.
- [ ] 4.2 Primeira sincronização; lista adulterada.
- [ ] 4.3 Mesmo registro em dois relays; autor inundando; caixa cheia.
- [ ] 4.4 Relay fora do ar na publicação; sessão em andamento.

## 5. Fechamento
- [ ] 5.1 `.env.example`; `uv run ruff check .`; `uv run pytest -m "unit or integration" -v`.
- [ ] 5.2 Teste real entre dois nós (Pi 5 e Mac) por um relay de teste.
- [ ] 5.3 Revisão STRIDE do Analista de Segurança e testes do Pentester; revisão nos 7 eixos; PR para `dev`.
