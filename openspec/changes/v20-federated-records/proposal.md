# Proposta: Registros Federados Assinados e Política de Publicação

**ID:** `v20-federated-records` · **Versão:** V20 · **Capacidade:** `federation-records`
**ADRs de origem:** [ADR 013](../../../docs/decisions/adr_013_federacao_rede_publica.md) §2
(registros assinados, histórico somente-acréscimo), §4 (descobertas e oportunidades
publicadas), §6 (IDs estáveis, proveniência, separação privado/compartilhável) e as questões
"Privacidade e propriedade intelectual" e "Governança" (formato dos registros);
[ADR 019](../../../docs/decisions/adr_019_localidade_dados_proveniencia_resultados.md) §2 e §3
(números com origem; dados brutos não saem do nó); [ADR 015](../../../docs/decisions/adr_015_modelo_dados_grafo_conhecimento.md)
§3 (`visibilidade`, `origem_no`)
**Depende de:** `v20-node-identity`; V18.5 (`v18.5-numeric-references`,
`v18.5-execution-provenance`, `v18.5-research-data-ingestion` para a marcação
`compartilhavel`)

## Por quê

O ADR 013 decide que nós publicam descobertas e oportunidades como registros assinados, que
não são reescritos. Falta definir **o que** é um registro, **como** ele é identificado e
canonicalizado para a assinatura, **o que pode** ser publicado sem ferir a propriedade
intelectual do pesquisador nem o ADR 019, e **quem decide** a publicação.

## O que muda

- **Novo:** formato `versao_formato: 1` de registro federado: envelope comum (tipo, autor,
  chave pública, data, conteúdo, referências, assinatura) e JSON canônico próprio; o
  identificador é o resumo do conteúdo (`cid = "sha256:<hex>"`).
- **Novo:** tipos `perfil_no`, `problema`, `descoberta`, `oportunidade`, `experimento`,
  `correcao`, `retratacao`, `rotacao_chave`, `revogacao_chave` (e `reproducao`, definido em
  `v20-reproduction-validation`), cada um com esquema estrito.
- **Novo:** **publicação opt-in por projeto, desligada por padrão**; só nós do grafo com
  `visibilidade="compartilhavel"` viram candidatos; código só com `publicar_codigo` no projeto;
  datasets só como referência (nome, sha256, URL pública) quando marcados `compartilhavel`.
- **Novo:** **caixa de saída com revisão humana**: o sistema monta os registros candidatos de
  forma determinística e o pesquisador aprova cada lote antes de assinar e enviar.
- **Novo:** histórico somente-acréscimo: correção e retratação são registros novos do mesmo
  autor que referenciam o anterior.
- **Novo:** tabela `federation_records` (saída e entrada), com o registro integral em JSONB.
- **Fora do escopo:** transporte (`v20-federation-transport`), recebimento e triagem
  (`v20-remote-knowledge-intake`), reprodução (`v20-reproduction-validation`).

## Impacto

- **Código:** `src/federation/records.py` (formato, canonicalização, validação),
  `src/federation/publication.py` (candidatos, política, caixa de saída), `src/cli.py`
  (`federation project share|unshare`, `federation outbox review`), `scripts/init_db.sql` e
  migração, `src/config.py`.
- **Grafo:** propriedade `publicado_cid` nos nós publicados.
- **Formato:** versionado neste repositório; evolui por PR (resposta proposta à questão de
  governança do formato).

## Aprovações necessárias

- **Alteração de schema do PostgreSQL:** tabela nova `federation_records` (migração
  `scripts/migrations/v20_federation_records.sql`).
- **Política de publicação** (o que sai do nó para a rede pública): decisão do pesquisador
  sobre as propostas do design §3; revisão do Analista de Segurança.
