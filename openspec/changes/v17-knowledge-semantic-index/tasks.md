# Tarefas: v17-knowledge-semantic-index

## 1. Índice
- [x] 1.1 `estado_vetorizacao` em `schema.py` para os rótulos vetorizados.
- [x] 1.2 `src/knowledge/semantic_index.py`: `canonical_text`, `upsert`, `reconcile`, `similar`.
- [x] 1.3 Gancho pós-escrita no `GraphStore` (falha não desfaz o nó).
- [x] 1.4 Reconciliação no início da sessão e `geminiclaw knowledge reindex`. (Entregue: `reconcile_on_session_start` em `semantic_runtime.py` e o comando; ligar o helper ao início de sessão do orquestrador depende da integração do grafo à sessão — nenhum código de sessão usa o grafo ainda.)

## 2. Domínios
- [x] 2.1 Função de domínios de um nó em nível `area` e predicados "entre domínios"/"entre projetos".

## 3. Consulta híbrida
- [x] 3.1 `related_experience` com ranking por similaridade × confiança × recência.

## 4. Fila (requer aprovação explícita)
- [x] 4.1 **Aprovação:** migração da tabela `similarity_queue` (aprovada pelo usuário em 2026-10-06; DDL idempotente em `scripts/init_db.sql`).
- [x] 4.2 `src/knowledge/similarity_queue.py` (`enqueue`, `next_batch`, `mark_confirmed`, `mark_discarded`, `confirmation_rate`).
- [x] 4.3 Geração de candidatos após `upsert`, com as regras de faixa, domínio e confiança.
- [x] 4.4 Configurações em `src/config.py` e `.env.example`.

## 5. Estatísticas
- [x] 5.1 `geminiclaw knowledge stats` com taxa de confirmação e sugestão de ajuste.

## 6. Testes (provedor de embedding falso e Qdrant de teste)
- [x] 6.1 ID do ponto igual ao do nó; payload com metadados de embedding.
- [x] 6.2 Alterar o texto do nó revetoriza; alterar só `status` não revetoriza (mas atualiza payload).
- [x] 6.3 Falha no Qdrant deixa `pendente`; `reconcile` corrige.
- [x] 6.4 Par 0,65 no mesmo domínio não entra; entre domínios entra.
- [x] 6.5 Par 0,93 entra como `duplicata`.
- [x] 6.6 `Descoberta→Problema` de outro projeto com `|veredito|` 0,2 não entra; com 0,35 entra.
- [x] 6.7 Par descartado não volta; volta após mudança de texto.
- [x] 6.8 Nenhum limite de quantidade: 50 vizinhos acima do limiar geram 50 candidatos.
- [x] 6.9 `related_experience` ordena pelo rank definido.

## 7. Fechamento
- [x] 7.1 Ruff, testes, revisão nos 7 eixos, PR.
