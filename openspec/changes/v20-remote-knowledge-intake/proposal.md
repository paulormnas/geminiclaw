# Proposta: Entrada de Conhecimento Remoto e Oportunidades para Decisão Humana

**ID:** `v20-remote-knowledge-intake` · **Versão:** V20 · **Capacidade:** `remote-knowledge`
**ADRs de origem:** [ADR 013](../../../docs/decisions/adr_013_federacao_rede_publica.md) §4
(documentar oportunidades; o humano decide; nunca iniciar pesquisa sozinho), §5 (conhecimento
remoto é sempre dado não confiável) e as questões "Nós maliciosos" e "Descoberta de
oportunidades"; [ADR 015](../../../docs/decisions/adr_015_modelo_dados_grafo_conhecimento.md)
§3 (`origem_no`), §6 (faixas de similaridade, prioridade entre domínios) e a regra de que
oportunidades não avançam sem decisão humana
**Depende de:** `v20-federated-records`, `v20-federation-transport`,
`v17-knowledge-semantic-index` (embeddings locais e consulta híbrida)

## Por quê

Registros chegam de nós desconhecidos numa rede aberta. Eles podem ser valiosos (uma descoberta
de química que abre uma oportunidade em história), irrelevantes, falsos, repetidos em massa
(ataque Sybil) ou escritos para manipular os agentes (injeção de prompt). O ADR 013 exige que
nada remoto vire instrução e que nenhuma pesquisa comece sem o pesquisador decidir, e deixa em
aberto como mostrar ao pesquisador o que importa sem sobrecarregá-lo.

## O que muda

- **Novo:** validação completa de cada registro recebido (esquema, autor, assinatura, data,
  revogação de chave) e **quarentena**: registros remotos ficam em `federation_records`, fora
  do grafo do projeto, até uma decisão humana.
- **Novo:** relevância calculada localmente, sem LLM (embeddings locais contra os problemas e
  domínios dos projetos do nó), com prioridade extra para pares entre domínios diferentes.
- **Novo:** **resumo periódico** com no máximo `FEDERATION_DIGEST_MAX` itens
  (`geminiclaw federation inbox`), ordenados por relevância e confiança do autor.
- **Novo:** decisões do pesquisador: `import` (traz para um projeto como `Oportunidade`
  `documentada` ou como `Descoberta` externa, com `origem_no` do autor), `dismiss`, `mute-author`.
  Investigar uma oportunidade importada segue o fluxo normal de aprovação (ADR 015).
- **Novo:** confiança local, sem consenso global: lista de nós confiáveis definida pelo
  pesquisador e reputação calculada só a partir de reproduções feitas por nós confiáveis ou
  pelo próprio nó (`v20-reproduction-validation`). Novos nós começam sem peso.
- **Novo:** texto remoto, quando chega a um modelo, vai sempre como dado delimitado, com origem
  `remoto`, e nunca como instrução nem como argumento de ferramenta.
- **Novo:** tratamento de `correcao`, `retratacao`, `rotacao_chave` e `revogacao_chave`.
- **Fora do escopo:** reprodução de experimentos (`v20-reproduction-validation`); agentes
  vasculhando a rede por conta própria (proibido pelo ADR 013 §4).

## Impacto

- **Código:** `src/federation/intake.py` (validação, quarentena, estados),
  `src/federation/relevance.py`, `src/federation/trust.py`, `src/federation/importer.py`,
  `src/cli.py` (`federation inbox|show|import|dismiss|trust|mute-author`),
  `src/egress/classification.py` (origem `remoto`), `src/config.py`, `.env.example`.
- **Grafo:** nós importados com `origem_no=<id_federado>` e `registro_cid`.
- **Dados:** coluna `triagem JSONB` em `federation_records` e tabela `federation_trust`.

## Aprovações necessárias

- **Alteração de schema:** tabela `federation_trust` (nós confiáveis e silenciados) e coluna
  `triagem JSONB` em `federation_records`.
- Revisão do Analista de Segurança e do Pentester (injeção de prompt por registro remoto,
  Sybil, inundação) antes do merge.
