# Design: Identidade Criptográfica do Nó

## 0. Estado atual (verificado em `dev`, commit `40419ea`, 2026-10-01)

| Ponto | Onde | Situação |
|---|---|---|
| Identificador da máquina | `src/knowledge/ids.py:115-160`; `src/config.py:359-364` | `NODE_ID` UUIDv7 persistido em `~/.config/geminiclaw/node_id`; valor efêmero se o disco falhar. |
| Origem dos nós do grafo | `v17-graph-store` design (propriedades comuns) | `origem_no` com padrão `local`; `visibilidade` `privado`/`compartilhavel`. |
| Criptografia | `pyproject.toml` | `cryptography>=46` já é dependência do núcleo. |

## 1. Chave e identificador

- **Algoritmo:** Ed25519 (assinatura determinística, chave de 32 bytes, rápida no Pi 5,
  disponível em `cryptography` sem dependência nova).
- **Arquivo:** PEM PKCS#8 em `<config_dir>/federation/node_ed25519.pem`, permissão `0600`,
  diretório `0700`. Opcionalmente cifrado com senha (`FEDERATION_KEY_PASSPHRASE`, lida do `.env`);
  sem senha, o arquivo depende da proteção do sistema operacional (ver questão em aberto 1).
- **`id_federado`:** `"ed25519:" + base32_minúsculo_sem_padding(sha256(chave_publica_raw))[:32]`.
  Curto o bastante para exibição, com 160 bits de resumo.
- O `NODE_ID` local continua existindo para fins internos (sessões, execução); a federação
  nunca o publica. A ligação entre os dois fica só no disco local.

## 2. Ativação

`geminiclaw federation identity init` (ou a primeira execução com `FEDERATION_ENABLED=true`):

1. Se a chave existe e é válida → carrega.
2. Se não existe → gera, grava atomicamente (arquivo temporário + `os.replace`) e exibe o
   `id_federado` com aviso para fazer cópia de segurança.
3. Se existe e não pode ser lida, ou não pode ser gravada → **erro fatal** com o caminho. Nunca
   gera identidade efêmera com a federação ligada.

Com `FEDERATION_ENABLED=false` (padrão), nenhuma chave é criada e nenhuma rede é usada.

## 3. Perfil público

Registro `perfil_no` (formato em `v20-federated-records`) com `chave_publica`,
`id_federado`, `nome_exibicao` e `instituicao` (ambos opcionais, preenchidos pelo pesquisador em
`FEDERATION_DISPLAY_NAME`/`FEDERATION_INSTITUTION`), `areas` (domínios do vocabulário controlado
que o pesquisador escolhe divulgar) e `versao_software`. Nada sobre hardware, IP ou caminhos.

## 4. Rotação e revogação

- **Rotação:** `identity rotate` gera chave nova e publica `rotacao_chave` com
  `{chave_antiga, chave_nova}` assinado **pelas duas** chaves. Quem recebe passa a aceitar a
  nova como continuação da mesma identidade; registros antigos continuam válidos.
- **Revogação:** `identity revoke` publica `revogacao_chave` assinado pela chave a revogar, com
  data a partir da qual registros dessa chave não são aceitos. Serve para chave comprometida
  ainda em posse do pesquisador.
- **Chave perdida:** não há recuperação na v1; o nó começa nova identidade (reputação zero).
  Ver questão em aberto 2.

## 5. Assinatura

`sign(payload_canonico: bytes) -> bytes` e `verify(...) -> bool`. A canonicalização dos bytes é
responsabilidade de `v20-federated-records` (JSON canônico). A chave privada nunca sai do
processo: não aparece em logs, `repr`, telemetria nem mensagens de erro.

## 6. Configuração

| Variável | Padrão | Uso |
|---|---|---|
| `FEDERATION_ENABLED` | `false` | Liga a federação (identidade, transporte, caixa de entrada) |
| `FEDERATION_KEY_PATH` | `<config_dir>/federation/node_ed25519.pem` | Caminho da chave |
| `FEDERATION_KEY_PASSPHRASE` | vazio | Senha opcional da chave (só no `.env`) |
| `FEDERATION_DISPLAY_NAME` | vazio | Nome exibido no perfil |
| `FEDERATION_INSTITUTION` | vazio | Instituição exibida no perfil |

## 7. Análise de impacto (6 eixos)

| Eixo | Impacto |
|---|---|
| Orquestrador & Loop | Nenhum com a federação desligada. |
| Agentes & Prompts | Nenhum. |
| Sandboxes & Containers | Nenhum; a chave nunca é montada no sandbox. |
| Persistência | Arquivo de chave fora do repositório. |
| Segurança | Chave privada como segredo de maior valor; permissões, cópia de segurança, rotação, revogação. |
| Testes & Telemetria | Testes com diretório temporário; nenhuma rede. |

## 8. Riscos

- **Roubo da chave** (Pi acessível na rede local): permissões `0600`, senha opcional, revogação.
- **Perda da chave:** aviso de cópia de segurança na criação; `export-public` não exporta a
  privada; a exportação da privada exige comando explícito com confirmação.

## 9. Questões em aberto para o pesquisador

1. Senha da chave obrigatória ou opcional? A proposta é opcional, porque o Pi roda sem
   ninguém digitando senha.
2. Recuperação de identidade perdida (ex.: chave de recuperação offline gerada junto e
   impressa) entra na v1?
3. O perfil deve permitir anonimato (sem nome nem instituição) ou exigir instituição?
