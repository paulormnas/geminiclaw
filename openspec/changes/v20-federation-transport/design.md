# Design: Transporte, Entrada e Sincronização da Federação

## 1. Escolha de tecnologia (proposta do Arquiteto, a confirmar)

| Opção (do ADR 013) | Entrada sem configuração | Funciona atrás de NAT/firewall | Custo no Pi 5 | Encaixe com registros assinados |
|---|---|---|---|---|
| Git (repositórios compartilhados) | Não: exige conta e permissão em cada repositório | Sim (saída HTTPS) | Baixo | Bom, mas centraliza em quem hospeda |
| IPFS | Sim (DHT) | Parcial (precisa de travessia de NAT ou retransmissão) | Alto: daemon residente, memória e disco | Bom (endereçamento por conteúdo), mas descoberta lenta e pesada |
| libp2p | Sim | Parcial (exige travessia de NAT e retransmissão) | Médio a alto; suporte em Python limitado | Bom, mas muito código de rede para manter |
| **Relays no modelo Nostr** | **Sim** (lista de relays de partida) | **Sim** (só conexões de saída `wss://`) | **Baixo** (cliente WebSocket) | **Bom**: eventos JSON assinados, relays sem autoridade |

Proposta: **relays no modelo Nostr (NIP-01)**. Encaixa nos princípios: participação aberta
(qualquer um publica), servidores que só fazem entrada e repasse, sem consenso global
(Alternativa C) e sem fonte central da verdade (Alternativa B), já que a validade de cada
registro é verificável por qualquer nó. Também resolve a questão de governança dos servidores:
qualquer instituição pode operar um relay de software livre, e um nó usa vários ao mesmo tempo.

**Duas assinaturas, papéis diferentes:** o evento do protocolo é assinado com uma chave de
transporte (exigência do protocolo, curva própria dele), gerada e guardada junto da identidade.
**A autoria científica vem só da assinatura Ed25519 do registro** que vai dentro do evento; a
chave de transporte não tem valor de autoria e pode ser trocada sem afetar a reputação.

**Spike obrigatório (tarefa 1):** antes de implementar, validar no Pi 5 (ARM64) uma biblioteca
cliente em Python para o protocolo, ou um cliente mínimo próprio sobre um cliente WebSocket,
medindo memória e CPU com 3 relays e 10 mil eventos. Se nenhuma opção passar, o plano B é um
relay HTTP mínimo próprio com a mesma interface (§2). A escolha final fica registrada no PR.

## 2. Interface

```python
class FederationTransport(ABC):
    async def publish(self, registro: dict) -> list[RelayAck]: ...
    async def fetch(self, relay: str, desde: datetime, tipos: list[str], limite: int) -> AsyncIterator[dict]: ...
    async def health(self, relay: str) -> RelayHealth: ...
```

O transporte entrega e recebe **envelopes de registro** (`v20-federated-records`), não eventos do
protocolo. Validação de esquema e assinatura acontece fora do transporte, na entrada
(`v20-remote-knowledge-intake`), para que trocar o transporte não mude as regras de confiança.

Mapeamento proposto para o protocolo: `content` = envelope em JSON canônico; tags
`["t", "<app>-registro-v1"]`, `["tipo", <tipo>]`, `["cid", <cid>]`, `["autor", <id_federado>]`;
o número do tipo de evento é definido no spike, numa faixa de uso por aplicação.

## 3. Entrada (plug-and-play)

1. `src/federation/bootstrap_relays.json`: lista de relays com a assinatura Ed25519 da **chave
   de partida do projeto** (chave pública embutida no código; a privada fica com o mantenedor do
   projeto). Atualizada por PR, como o catálogo de modelos.
2. `FEDERATION_RELAYS` (opcional) acrescenta relays do pesquisador ou da instituição; nunca
   remove a verificação da lista de partida.
3. Na primeira sincronização, o nó publica seu `perfil_no` e consulta relays recomendados por
   outros perfis (campo opcional `relays` no perfil), até `FEDERATION_MAX_RELAYS` (padrão 8).
4. "Validar-se junto a um servidor" (ADR 013 §1): o nó responde ao desafio de autenticação do
   relay quando o relay exige (NIP-42), assinando com a chave de transporte. Relays podem usar
   isso para limitar spam por chave.

## 4. Sincronização

- **Puxada:** para cada relay, `fetch(desde=cursor - FEDERATION_SYNC_OVERLAP_MINUTES)` com os
  tipos de interesse; cada envelope vai para a fila de entrada; cursor salvo em
  `federation_sync_state(relay, cursor, ultimo_erro, atualizado_em)`.
- **Deduplicação** por `cid` antes de qualquer processamento.
- **Publicação:** registros `aprovado` são enviados a todos os relays saudáveis; o estado passa a
  `enviado` com ao menos `FEDERATION_PUBLISH_MIN_ACKS` (padrão 2) confirmações; os demais relays
  recebem reenvio com recuo exponencial.
- **Quando roda:** `geminiclaw federation sync` (uma vez) ou `--loop` com intervalo
  `FEDERATION_SYNC_INTERVAL_MINUTES` (padrão 60), pensado para temporizador do sistema. Não roda
  dentro de sessões de pesquisa, para não disputar CPU e rede com experimentos (questão
  "Custo computacional").
- **Limites:** `FEDERATION_FETCH_MAX_PER_RELAY` (padrão 500 registros por rodada),
  `FEDERATION_INBOX_MAX_MB` (padrão 200; ao atingir, para de buscar e avisa),
  taxa máxima por autor (`FEDERATION_MAX_RECORDS_PER_AUTHOR_DAY`, padrão 100; excedente
  descartado e contado).

## 5. Segurança

- Só `wss://` (TLS); `ws://` só para `localhost` em testes.
- Nenhuma porta de entrada aberta no nó.
- Conteúdo recebido é tratado como bytes não confiáveis até a validação completa; tamanho
  máximo aplicado antes de decodificar o JSON.
- Relay malicioso pode omitir ou atrasar registros, mas não forjá-los (assinatura). Usar vários
  relays reduz a omissão.
- Metadados expostos ao relay: IP do nó e quais tipos ele consulta. Documentado; uso de proxy
  fica como opção futura.

## 6. Configuração

| Variável | Padrão | Uso |
|---|---|---|
| `FEDERATION_RELAYS` | vazio | Relays adicionais (`wss://`, separados por vírgula) |
| `FEDERATION_MAX_RELAYS` | 8 | Relays usados ao mesmo tempo |
| `FEDERATION_SYNC_INTERVAL_MINUTES` | 60 | Intervalo em `--loop` |
| `FEDERATION_SYNC_OVERLAP_MINUTES` | 10 | Sobreposição do cursor |
| `FEDERATION_PUBLISH_MIN_ACKS` | 2 | Confirmações para `enviado` |
| `FEDERATION_FETCH_MAX_PER_RELAY` | 500 | Registros por relay por rodada |
| `FEDERATION_INBOX_MAX_MB` | 200 | Teto da caixa de entrada |
| `FEDERATION_MAX_RECORDS_PER_AUTHOR_DAY` | 100 | Taxa máxima por autor |

## 7. Análise de impacto (6 eixos)

| Eixo | Impacto |
|---|---|
| Orquestrador & Loop | Nenhum: a sincronização é um processo separado. |
| Agentes & Prompts | Nenhum. |
| Sandboxes & Containers | Nenhum. |
| Persistência | `federation_sync_state`; registros recebidos em `federation_records`. |
| Segurança | Rede de saída permanente; TLS; sem portas de entrada; limites contra inundação. |
| Testes & Telemetria | Relay falso em processo para testes; evento `federation_sync` com contagens por relay. |

## 8. Riscos

- **Relays públicos instáveis ou extintos:** vários relays, lista de partida atualizável,
  relays institucionais.
- **Biblioteca do protocolo imatura em Python/ARM64:** spike com plano B.
- **Chave de partida do projeto comprometida:** só afeta a lista de relays (não a autoria); a
  rotação segue o mesmo mecanismo de `v20-node-identity`.

## 9. Questões em aberto para o pesquisador

1. Aprovar o modelo de relays no estilo Nostr, condicionado ao spike, ou preferir outra opção da
   tabela do §1?
2. Quem guarda a chave de partida do projeto (assina a lista de relays)?
3. O projeto deve operar um relay próprio no início, até haver relays institucionais?
4. A sincronização periódica pode rodar no Pi enquanto não há sessão, ou só manualmente?
