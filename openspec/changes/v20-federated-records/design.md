# Design: Registros Federados Assinados e Política de Publicação

## 1. Envelope

```json
{
  "versao_formato": 1,
  "tipo": "descoberta",
  "autor": "ed25519:…",
  "chave_publica": "<base64url, 32 bytes>",
  "criado_em": "2027-03-01T12:00:00Z",
  "conteudo": { "...": "esquema do tipo" },
  "refs": ["sha256:…"],
  "assinatura": "<base64url, 64 bytes>"
}
```

- **Bytes assinados:** JSON canônico do envelope **sem** `assinatura`.
- **`cid`:** `"sha256:" + hex(sha256(bytes assinados))`. Como inclui autor e data, dois nós que
  publicam o mesmo texto geram registros distintos (autoria é parte do registro).
- **JSON canônico (próprio, subconjunto do RFC 8785):** objetos com chaves em ordem de ponto de
  código, sem espaços, UTF-8, strings em NFC; **números só inteiros** (até 2^53). Valores
  decimais vão como string decimal (`"0.953"`) para evitar ambiguidade de ponto flutuante entre
  implementações. `null` só onde o esquema permite.
- **Limites:** registro inteiro ≤ `FEDERATION_RECORD_MAX_BYTES` (padrão 65536).
- **Validação ao montar e ao receber:** esquema estrito por tipo (chave desconhecida = recusa),
  `autor` coerente com `chave_publica`, assinatura válida, `criado_em` não mais que
  `FEDERATION_CLOCK_SKEW_MINUTES` (padrão 10) no futuro.

## 2. Tipos e conteúdo

| Tipo | Origem local | Conteúdo publicado |
|---|---|---|
| `perfil_no` | `v20-node-identity` §3 | nome, instituição, áreas, versão do software |
| `problema` | nó `Problema` confirmado | título, resumo, classe, características dos dados (sem valores), critério de sucesso, domínios |
| `experimento` | `Experimento` + registro de execução (`v18.5-execution-provenance`) | `params` (JSON de `params.json`), `seed`, `hash_codigo`, código inline (opcional), métricas com nome canônico e valor decimal, `ambiente` (Python, pacotes e versões, arquitetura; sem caminhos nem host), datasets como referência (§3), tolerâncias de reprodução por métrica (opcional) |
| `descoberta` | `Descoberta` | tipo, enunciado, condições, veredito e confiança (decimais em string), `n_evidencias`, domínios; `refs` para os `experimento` e `problema` de origem |
| `oportunidade` | `Oportunidade` | enunciado, justificativa, domínios, abordagem sugerida; `refs` para a descoberta de origem |
| `correcao` | ação do pesquisador | `substitui: cid`, novo conteúdo completo do tipo original |
| `retratacao` | ação do pesquisador | `retira: cid`, motivo |
| `rotacao_chave`, `revogacao_chave` | `v20-node-identity` §4 | chaves e data |

Números em texto livre (`enunciado`, `condicoes`, `justificativa`) precisam ser referências
resolvidas (`v18.5-numeric-references`); a montagem substitui cada referência pelo valor e pelo
`cid` do `experimento` publicado. Número literal sem origem bloqueia o candidato.

`correcao` e `retratacao` só são aceitas se o `autor` for o mesmo do registro referenciado (ou
a continuação por `rotacao_chave`).

## 3. Política de publicação (proposta para as questões de privacidade e PI)

1. **Opt-in por projeto, desligado por padrão:** `geminiclaw federation project share
   <projeto_id>` marca o projeto como federado; `unshare` para novas publicações (o que já saiu
   não volta, ADR 013 §2).
2. **Só nós `compartilhavel`:** dentro de um projeto federado, cada nó continua `privado` até o
   pesquisador marcá-lo (pela CLI do grafo, `v17-graph-cli`). O Curator pode **sugerir** a
   marcação, nunca aplicá-la.
3. **Código:** publicado inline só com `publicar_codigo=true` no projeto e se couber no limite;
   caso contrário, o `experimento` sai só com `hash_codigo` (não reproduzível por outros).
4. **Dados:** nunca há dados brutos no registro (ADR 019 §3). Um dataset entra como
   `{nome, sha256, url}` somente se estiver marcado `compartilhavel` no `dados.yaml`
   (`v18.5-research-data-ingestion`) e a URL pública for informada pelo pesquisador; senão,
   `{"nome": "...", "privado": true}`.
5. **Varredura antes de assinar:** caminhos absolutos, nomes de host, endereços IP, e-mails e
   valores de variáveis `*_KEY`/`*_TOKEN` no conteúdo bloqueiam o candidato com o motivo.
6. **Revisão humana obrigatória:** `federation outbox review` mostra cada candidato renderizado
   (e o JSON exato) e o pesquisador aprova, rejeita ou adia. Só aprovados são assinados e
   enfileirados para envio. Não há publicação automática na v1.

## 4. Tabela `federation_records`

| Coluna | Tipo | Observação |
|---|---|---|
| `cid` | `TEXT PRIMARY KEY` | |
| `direcao` | `TEXT` | `saida` / `entrada` |
| `tipo`, `autor` | `TEXT` | indexados |
| `criado_em` | `TIMESTAMPTZ` | do envelope |
| `estado` | `TEXT` | saída: `candidato` / `aprovado` / `enviado` / `rejeitado`; entrada: definido em `v20-remote-knowledge-intake` |
| `registro` | `JSONB` | envelope completo (assinado, quando aplicável) |
| `no_local_id` | `TEXT` | nó do grafo de origem (saída) ou importado (entrada) |
| `atualizado_em` | `TIMESTAMPTZ` | |

Registros assinados são imutáveis: só `estado` e `atualizado_em` mudam.

## 5. Configuração

| Variável | Padrão | Uso |
|---|---|---|
| `FEDERATION_RECORD_MAX_BYTES` | 65536 | Tamanho máximo do registro |
| `FEDERATION_CLOCK_SKEW_MINUTES` | 10 | Tolerância de data futura |

## 6. Análise de impacto (6 eixos)

| Eixo | Impacto |
|---|---|
| Orquestrador & Loop | Nenhum; a montagem de candidatos é um comando da CLI. |
| Agentes & Prompts | Curator ganha a possibilidade de sugerir `compartilhavel` (texto, sem ferramenta de escrita nova). |
| Sandboxes & Containers | Nenhum. |
| Persistência | Tabela nova; `publicado_cid` no grafo. |
| Segurança | Opt-in, revisão humana, varredura de vazamentos, sem dados brutos. |
| Testes & Telemetria | Vetores de teste de canonicalização e assinatura; evento `federation_publish`. |

## 7. Riscos

- **Publicação irreversível** de algo indevido: mitigada pela revisão obrigatória e pela
  `retratacao` (que sinaliza, mas não apaga cópias já propagadas; dito na tela de revisão).
- **Divergência de canonicalização** entre versões: vetores de teste fixos no repositório.

## 8. Questões em aberto para o pesquisador

1. Publicar `problema` (resumo do problema de pesquisa) é aceitável, ou só descobertas e
   oportunidades?
2. Valores de métricas no `experimento`: publicar sempre (necessário para reprodução) ou só
   faixas?
3. Publicação automática futura (sem revisão por lote) para nós marcados `compartilhavel` deve
   ser prevista?
4. Licença dos registros publicados (ex.: CC BY 4.0 declarada no `perfil_no`)?
