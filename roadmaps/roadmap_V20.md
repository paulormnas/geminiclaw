# Roadmap V20 — Federação entre Nós (a especificar)

## Objetivo

Rede pública e plug-and-play de nós do assistente em diferentes instituições, com registros
assinados, validação por reprodução e oportunidades de pesquisa documentadas para decisão
humana (ADR 013).

## Dependências

- V16 a V19 concluídas e **validadas** — decisão do pesquisador: a federação é a última etapa.

## Estado

**Sem spec.** As questões em aberto do ADR 013 precisam ser discutidas com o pesquisador
responsável antes de qualquer especificação:

- [ ] Privacidade e propriedade intelectual (o que é publicado; opt-in por projeto).
- [ ] Nós maliciosos (descobertas falsas, spam, ataques Sybil).
- [ ] Custo computacional aceito por nó para reproduzir experimentos alheios.
- [ ] Descoberta de oportunidades relevantes sem sobrecarregar o pesquisador.
- [ ] Governança dos servidores de entrada e do formato dos registros.
- [ ] Tolerância de reprodução entre hardwares diferentes.
- [ ] Tecnologia de rede, identidade e sincronização.

## Requisitos já atendidos pelas etapas anteriores (ADR 013 §6)

- IDs estáveis (UUIDv7) e `origem_no` em todo nó — `v17-graph-store`.
- Proveniência obrigatória e auditoria — `v17-graph-store`.
- Embeddings locais versionados; vetores nunca compartilhados — `v16-local-embeddings`.
- `visibilidade` (`privado` por padrão) em todo nó — `v17-graph-store`.
- Oportunidades só avançam com decisão humana — `v18-hypothesis-loop`.
