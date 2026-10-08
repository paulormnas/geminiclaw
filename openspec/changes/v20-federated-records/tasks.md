# Tarefas: v20-federated-records

**Estado (2026-10-08):** Não iniciada — nenhum código mergeado.

## 0. Pré-requisitos
- [ ] 0.1 `v20-node-identity` e V18.5 concluídas.
- [ ] 0.2 Aprovação da tabela `federation_records` e da política de publicação (design §3); respostas às questões do design §8.

## 1. Formato
- [ ] 1.1 `src/federation/records.py`: envelope, JSON canônico, `cid`, assinatura, validação estrita por tipo.
- [ ] 1.2 Fixtures de vetor de teste em `tests/fixtures/federation/` (chave de teste, bytes canônicos, `cid`, assinatura).

## 2. Publicação
- [ ] 2.1 `federation project share|unshare`; flag `publicar_codigo`.
- [ ] 2.2 `src/federation/publication.py`: montagem determinística de candidatos a partir do grafo e do registro de execução.
- [ ] 2.3 Datasets como referência; varredura de vazamentos; números com origem.
- [ ] 2.4 `federation outbox review` (aprovar, rejeitar, adiar; JSON exato exibido); `publicado_cid` no grafo.
- [ ] 2.5 `correcao` e `retratacao` pela CLI.

## 3. Persistência
- [ ] 3.1 Migração `scripts/migrations/v20_federation_records.sql` e `scripts/init_db.sql`; imutabilidade da coluna `registro` (gatilho ou checagem no repositório).

## 4. Testes
- [ ] 4.1 Vetor de teste; ordem das chaves; decimal como float.
- [ ] 4.2 Autor falso; registro grande.
- [ ] 4.3 Projeto não federado; nó privado.
- [ ] 4.4 Dataset privado; caminho absoluto; número literal.
- [ ] 4.5 Candidato não revisado; aprovação; correção por outro autor; registro imutável.

## 5. Fechamento
- [ ] 5.1 `.env.example`; `uv run ruff check .`; `uv run pytest -m "unit or integration" -v`.
- [ ] 5.2 Revisão do Analista de Segurança; revisão nos 7 eixos; PR para `dev`.
