# ADR 016 — Imagem do PostgreSQL para Apache AGE (Alpine/musl → Debian/glibc) e colação de índices

**Status:** Proposto
**Data:** 2026-09-29
**Relacionados:** ADR 005 (persistência), ADR 009 §4 (Apache AGE), PR #64 (`openspec/changes/v17-graph-store/`)

## Contexto

O PR #64 troca `postgres:16-alpine` (musl) por `apache/age:release_PG16_1.6.0` (Debian, glibc), a imagem oficial com suporte a ARM64. O projeto Apache AGE não publica variante Alpine.

A troca de libc sob um volume `postgres_data` existente pode tornar os índices B-tree sobre `TEXT` inconsistentes com a nova colação. O PostgreSQL não os reconstrói sozinho, e até buscas por igualdade podem retornar linhas erradas sem nenhum erro. Quase todas as tabelas pré-V17 (`scripts/init_db.sql`) usam PK e índices em `TEXT`, então o risco atinge o schema inteiro.

Por isso a tarefa 1.3 do `tasks.md` ("confirmar que os dados continuam acessíveis") é insuficiente: dado acessível não prova índice correto.

O projeto está em fase de MVP e não há dados de produção a preservar. Perda de dados é aceitável por enquanto.

## Decisão

1. **Adotar a imagem oficial `apache/age`** conforme o PR #64.
2. **Aplicação agora (MVP):** recriar o volume do zero (`docker compose down`, `docker volume rm <projeto>_postgres_data`, `docker compose up --build`). `init_db.sql` e `migrate_v17_knowledge.py` recriam tudo já sob a nova colação, sem índice legado. Não é preciso `REINDEX` nem dump/restore.
3. **Política futura (quando houver dados reais):** toda troca de imagem base do PostgreSQL que possa mudar a libc (nova versão do AGE, outra arquitetura ou fornecedor) deve ser seguida de `REINDEX DATABASE CONCURRENTLY <db>;` antes de liberar tráfego. Se a troca incluir upgrade de versão major, usar `pg_upgrade` ou dump/restore.
4. **Corrigir a tarefa 1.3 do `tasks.md`:** a verificação passa a ser "volume recriado do zero" (MVP) ou "`REINDEX` executado e validado por amostragem de consultas" (produção).

## Alternativas rejeitadas

- **`REINDEX` sobre o volume atual:** sem vantagem enquanto os dados são descartáveis. Vira a política futura (item 3).
- **Dump/restore como padrão:** mais caro (janela maior, disco duplicado) e não resolve nada além do `REINDEX` quando a versão major não muda.
- **Compilar o AGE contra `postgres:16-alpine`:** combinação não suportada pelo upstream e com manutenção recorrente. O ganho de footprint do Alpine está no tamanho da imagem em disco, não na RAM em operação, que é dominada por `shared_buffers`/`work_mem`.
- **Copiar o `.so` do AGE para a imagem Alpine (multi-stage):** inviável, pois o binário é linkado contra glibc e não carrega sob musl.

## Consequências

- Desbloqueia as tarefas 1.2 e 2.3 do PR #64. A migração `v17_001` só cria objetos novos, então não sofre o risco de colação.
- A imagem Debian é maior em disco que a Alpine, custo aceito em troca do suporte oficial do AGE.
- Nada impede que alguém pule o `REINDEX` numa troca futura. Quando houver produção, vale um checklist ou script de implantação.

## Revisão

Reabrir quando houver implantação com dados reais, quando o AGE publicar imagem Alpine ou quando o PostgreSQL migrar de versão major.
