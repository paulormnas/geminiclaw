# Tarefas: v17-graph-store

## 1. Infraestrutura (requer aprovação explícita)
- [ ] 1.1 Verificar imagem Apache AGE para PG16 ARM64; decidir entre imagem pronta e compilação.
- [ ] 1.2 **Aprovação:** `containers/Dockerfile.postgres` e alteração do serviço `postgres` no `docker-compose.yml`.
- [ ] 1.3 Subir no Pi 5 e confirmar que os dados existentes do volume continuam acessíveis.

## 2. Schema e migração (requer aprovação explícita)
- [ ] 2.1 `src/knowledge/schema.py` com nós, propriedades, enumerações e relações permitidas (fiel ao design).
- [ ] 2.2 `src/knowledge/ids.py` (UUIDv7) e `NODE_ID` persistido.
- [ ] 2.3 **Aprovação:** migração `v17_001` (extensão, grafo, rótulos, índices, papel `knowledge_reader`, tabela `knowledge_audit`).
- [ ] 2.4 `src/db.py`: configuração AGE por conexão e pool somente-leitura.

## 3. GraphStore
- [ ] 3.1 Interface `GraphStore`, `Actor`, `Node`, `Subgraph`.
- [ ] 3.2 `InMemoryGraphStore` para testes.
- [ ] 3.3 `AgeGraphStore` com operações tipadas e parâmetros `agtype`.
- [ ] 3.4 `read_query` com papel somente-leitura, transação READ ONLY e timeout.

## 4. Testes
- [ ] 4.1 Unitários: rótulo desconhecido, propriedade desconhecida, obrigatória ausente, enumeração inválida, relação não permitida, `criado_por` derivado do `Actor`, campos imutáveis, auditoria de `update_node`.
- [ ] 4.2 Segurança: valores com aspas, `})`, `$` e `MATCH` não alteram a consulta; `read_query` com `CREATE` é recusado pelo filtro e, com o filtro desligado, pelo banco.
- [ ] 4.3 Integração com AGE: criar nó, aresta, `neighbors`, `project_subgraph`.

## 5. Validação
- [ ] 5.1 **Revisão do Analista de Segurança.**
- [ ] 5.2 Carga sintética de 10 mil nós no Pi 5: medir `neighbors(depth=2)` e `project_subgraph`; registrar no PR.
- [ ] 5.3 Ruff, testes, revisão nos 7 eixos, PR.
