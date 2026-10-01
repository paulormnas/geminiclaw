# Proposta: Transporte, Entrada e Sincronização da Federação

**ID:** `v20-federation-transport` · **Versão:** V20 · **Capacidade:** `federation-transport`
**ADRs de origem:** [ADR 013](../../../docs/decisions/adr_013_federacao_rede_publica.md) §1
(plug-and-play: conectar, validar-se num servidor, sincronizar; servidor não é fonte da
verdade), §2 (rede pública, participação aberta), Alternativas B e C (sem servidor central como
verdade, sem consenso global) e as questões "Tecnologia" e "Governança" (servidores de entrada)
**Depende de:** `v20-node-identity`, `v20-federated-records`

## Por quê

Nós em instituições diferentes ficam atrás de NAT e firewalls que ninguém do projeto controla,
e o ADR exige entrada sem configuração manual. O ADR deixou a tecnologia em aberto (Git, IPFS,
Nostr, libp2p). Esta mudança escolhe um **modelo**, isola-o atrás de uma interface e define a
entrada e a sincronização.

## O que muda

- **Novo:** interface `FederationTransport` (`publish`, `fetch`, `health`); o resto da
  federação depende só dela.
- **Novo (proposta de tecnologia):** **relays** no modelo do protocolo Nostr (NIP-01): nós são
  **apenas clientes** que se conectam por WebSocket com TLS a relays públicos ou institucionais,
  publicam registros e assinam filtros por tipo. Nenhum nó abre porta de entrada. Os relays
  armazenam e repassam; **não** são fonte da verdade, porque a autoria e a integridade vêm da
  assinatura Ed25519 do registro (`v20-federated-records`).
- **Novo:** entrada plug-and-play: lista de relays de partida assinada pela chave do projeto e
  embutida no software; o nó publica seu `perfil_no` e começa a sincronizar.
- **Novo:** sincronização por puxada com cursor por relay, deduplicação por `cid`, publicação em
  vários relays e reenvio com recuo exponencial.
- **Novo:** comando `geminiclaw federation sync` (execução única ou periódica por temporizador
  do sistema), fora das sessões de pesquisa, com limites de banda, armazenamento e taxa.
- **Fora do escopo:** triagem do que chega (`v20-remote-knowledge-intake`); operação de relays
  (feita por instituições participantes; o projeto documenta, não opera).

## Impacto

- **Código:** `src/federation/transport/base.py` (interface), `src/federation/transport/relay.py`
  (implementação proposta), `src/federation/bootstrap.py`, `src/federation/sync.py`,
  `src/federation/bootstrap_relays.json` (lista assinada, versionada), `src/cli.py`,
  `src/config.py`, `.env.example`, `pyproject.toml` (cliente WebSocket e, se o protocolo for
  adotado, a biblioteca de eventos; decididas no spike da tarefa 1).
- **Dados:** cursores de sincronização em `federation_sync_state` (tabela nova).
- **Rede:** conexões de saída `wss://` para os relays configurados.

## Aprovações necessárias

1. **Escolha de tecnologia** (design §1): modelo de relays no estilo Nostr, condicionado ao
   spike no Pi 5. Decisão do pesquisador.
2. **Alteração de schema:** tabela `federation_sync_state`.
3. **Dependências novas** decididas no spike.
4. Primeira funcionalidade com **rede de saída permanente** do nó: revisão do Analista de
   Segurança (STRIDE) e do Pentester antes do merge (ADR 013, Consequências).
