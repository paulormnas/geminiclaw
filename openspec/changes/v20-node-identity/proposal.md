# Proposta: Identidade Criptográfica do Nó

**ID:** `v20-node-identity` · **Versão:** V20 · **Capacidade:** `node-identity`
**ADRs de origem:** [ADR 013](../../../docs/decisions/adr_013_federacao_rede_publica.md) §1
(entrada sem configuração manual), §2 (identidade criptográfica, autoria verificável), §6
(identificadores estáveis)
**Depende de:** V16 a V19 concluídas e validadas (ADR 013, Revisão); `v17-graph-store`
(`origem_no` em todo nó)
**É pré-requisito de:** todas as demais mudanças `v20-*`

## Por quê

A federação só funciona se cada nó puder assinar o que publica e verificar o que recebe. Hoje
o nó tem apenas o `NODE_ID` (UUIDv7 local, `src/knowledge/ids.py:115-160`), que:

- não prova autoria: qualquer um pode declarar o mesmo UUID;
- cai para um valor **efêmero** quando não consegue gravar em disco (`ids.py:140-145`,
  `:155-159`), o que numa rede faria o mesmo computador aparecer como autores diferentes;
- é privado por natureza (identifica a máquina), não um identificador público de autoria.

## O que muda

- **Novo:** par de chaves Ed25519 do nó (biblioteca `cryptography`, já dependência do núcleo),
  gerado na primeira ativação da federação e guardado com permissão `0600` fora do repositório.
- **Novo:** identificador federado `id_federado = "ed25519:" + base32(sha256(chave_publica))[:32]`,
  derivado da chave pública; é o valor de `origem_no` dos registros que este nó publica.
- **Novo:** serviço `NodeIdentity` com `sign(bytes)`, `verify(chave_publica, bytes, assinatura)`
  e o perfil público do nó (chave, `id_federado`, nome exibido e instituição opcionais).
- **Novo:** rotação de chave por registro de rotação assinado pela chave antiga; revogação por
  registro assinado (para chave comprometida, ver design §4).
- **Novo:** comando `geminiclaw federation identity show|init|rotate|export-public`.
- **Modificado:** com a federação ativada, falha ao ler ou gravar a chave é **fatal** (sem
  identidade efêmera).
- **Fora do escopo:** atestados institucionais (`v20-remote-knowledge-intake`, lista local de
  nós confiáveis); formato dos registros (`v20-federated-records`).

## Impacto

- **Código:** `src/federation/identity.py` (novo), `src/federation/__init__.py`, `src/cli.py`,
  `src/config.py`, `.env.example`.
- **Dados:** arquivo de chave em `~/.config/<app>/federation/node_ed25519.pem` (ou
  `$XDG_CONFIG_HOME`); nenhum schema.
- **Segurança:** a chave privada é o ativo mais sensível da federação (assina em nome do
  pesquisador e da instituição).

## Aprovações necessárias

- Revisão do Analista de Segurança (guarda da chave, rotação e revogação) antes do merge.
- Nenhuma alteração de schema, Dockerfile ou compose.
