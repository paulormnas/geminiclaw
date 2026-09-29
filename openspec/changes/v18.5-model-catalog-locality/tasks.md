# Tarefas: v18.5-model-catalog-locality

## 0. Pré-requisitos
- [ ] 0.1 Confirmar que o catálogo e o roteador do ADR 017 estão implementados em `dev`; se não estiverem, parar e avisar o pesquisador.
- [ ] 0.2 Obter aprovação explícita do pesquisador para a coluna `token_usage.versao_efetiva`.

## 1. Catálogo
- [ ] 1.1 Esquema: `localidade`, `aceita_dados_brutos`, `familia_modelo`; padrões e regras de coerência (design §1).
- [ ] 1.2 `WARNING` de coerência com o endpoint (loopback × não loopback), sem alterar a declaração.
- [ ] 1.3 `WARNING` para entradas de `catalog.local.yaml` que aceitam dados brutos.
- [ ] 1.4 Atualizar `src/llm/catalog.yaml` versionado com os três campos em todas as entradas.

## 2. Roteador
- [ ] 2.1 Posições de preferência com grupo (`id` ou lista de `id`s).
- [ ] 2.2 Ordem de resolução com `validator` por último; desempate por família; pin desliga o desempate.
- [ ] 2.3 `src/llm/allocation.py` (`RoleAllocation`, `current_allocation`); `allocation_profile` no payload antes do primeiro envio.
- [ ] 2.4 Bloco "Alocação" no banner.

## 3. Versão efetiva
- [ ] 3.1 `LLMResponse.versao_efetiva`; leitura por provedor (design §4).
- [ ] 3.2 Digest do Ollama no início da sessão e a cada checkpoint.
- [ ] 3.3 Migração `scripts/migrations/v18_5_model_version.sql` e `scripts/init_db.sql`; `record_token_usage` com `versao_efetiva`.
- [ ] 3.4 `VersionTracker`: evento `versao_modelo_alterada`, `payload["eventos_versao_modelo"]`, `WARNING`.
- [ ] 3.5 `StopReason.VERSAO_MODELO` e `parada_pendente` verificada no `AutonomousLoop` com os limites de uso.

## 4. Testes
- [ ] 4.1 Esquema: padrões, `no_no` implica dados brutos, três erros de coerência, família ausente.
- [ ] 4.2 Avisos de endpoint (loopback e remoto) sem alterar a declaração.
- [ ] 4.3 Roteador: empate por família, família em posição inferior não vence, pin desliga desempate.
- [ ] 4.4 Perfil de alocação no payload e no banner.
- [ ] 4.5 Versão por provedor com respostas simuladas (Google, compatível com e sem campo, Ollama por digest).
- [ ] 4.6 Troca de versão em modo flexível (evento) e em `strict` (fechamento com `versao_modelo`); versão desconhecida em `strict`.
- [ ] 4.7 Teste do catálogo versionado (todas as entradas válidas).

## 5. Fechamento
- [ ] 5.1 `.env.example` (nenhuma variável nova; comentário sobre os campos do catálogo).
- [ ] 5.2 `uv run ruff check .`; `uv run pytest -m "unit or integration" -v`.
- [ ] 5.3 Revisão nos 7 eixos; PR para `dev`.
