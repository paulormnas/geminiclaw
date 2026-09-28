# Tarefas: v17-knowledge-semantic-index

## 1. Índice
- [ ] 1.1 `estado_vetorizacao` em `schema.py` para os rótulos vetorizados.
- [ ] 1.2 `src/knowledge/semantic_index.py`: `canonical_text`, `upsert`, `reconcile`, `similar`.
- [ ] 1.3 Gancho pós-escrita no `GraphStore` (falha não desfaz o nó).
- [ ] 1.4 Reconciliação no início da sessão e `geminiclaw knowledge reindex`.

## 2. Domínios
- [ ] 2.1 Função de domínios de um nó em nível `area` e predicados "entre domínios"/"entre projetos".

## 3. Consulta híbrida
- [ ] 3.1 `related_experience` com ranking por similaridade × confiança × recência.

## 4. Fila (requer aprovação explícita)
- [ ] 4.1 **Aprovação:** migração da tabela `similarity_queue`.
- [ ] 4.2 `src/knowledge/similarity_queue.py` (`enqueue`, `next_batch`, `mark_confirmed`, `mark_discarded`, `confirmation_rate`).
- [ ] 4.3 Geração de candidatos após `upsert`, com as regras de faixa, domínio e confiança.
- [ ] 4.4 Configurações em `src/config.py` e `.env.example`.

## 5. Estatísticas
- [ ] 5.1 `geminiclaw knowledge stats` com taxa de confirmação e sugestão de ajuste.

## 6. Testes (provedor de embedding falso e Qdrant de teste)
- [ ] 6.1 ID do ponto igual ao do nó; payload com metadados de embedding.
- [ ] 6.2 Alterar o texto do nó revetoriza; alterar só `status` não revetoriza (mas atualiza payload).
- [ ] 6.3 Falha no Qdrant deixa `pendente`; `reconcile` corrige.
- [ ] 6.4 Par 0,65 no mesmo domínio não entra; entre domínios entra.
- [ ] 6.5 Par 0,93 entra como `duplicata`.
- [ ] 6.6 `Descoberta→Problema` de outro projeto com `|veredito|` 0,2 não entra; com 0,35 entra.
- [ ] 6.7 Par descartado não volta; volta após mudança de texto.
- [ ] 6.8 Nenhum limite de quantidade: 50 vizinhos acima do limiar geram 50 candidatos.
- [ ] 6.9 `related_experience` ordena pelo rank definido.

## 7. Fechamento
- [ ] 7.1 Ruff, testes, revisão nos 7 eixos, PR.
