# Delta: platform-images

## ADDED Requirements

### Requirement: Detecção de plataforma
O sistema SHALL identificar o sistema operacional e a arquitetura do host, a arquitetura do
daemon Docker, a placa (Raspberry Pi 5) e o tamanho de página, normalizando `aarch64` para
`arm64` e `x86_64` para `amd64`, e SHALL usar a arquitetura do **daemon** como alvo das imagens
(ADR 018 §5).

#### Scenario: Raspberry Pi 5
- **GIVEN** `device-tree` com "Raspberry Pi 5 Model B", `uname -m=aarch64`, página de 16384 bytes e daemon `aarch64`
- **WHEN** a plataforma é detectada
- **THEN** o identificador é `linux/arm64/pi5/16k`

#### Scenario: macOS com Docker Desktop
- **GIVEN** host `darwin`/`arm64` e daemon `linux`/`aarch64`
- **WHEN** a plataforma é detectada
- **THEN** o alvo das imagens é `linux/arm64`

#### Scenario: Linux x86_64
- **GIVEN** host e daemon `x86_64`, página de 4096 bytes
- **WHEN** a plataforma é detectada
- **THEN** o identificador é `linux/amd64`

### Requirement: Manifesto de imagens validado
O sistema SHALL ler as imagens do projeto de `containers/images.yaml`, com esquema estrito
(forma de obtenção `pull`, `build` ou `compose`, arquiteturas suportadas e plataformas
validadas), e SHALL recusar o manifesto com chave desconhecida ou forma de obtenção inválida.

#### Scenario: Manifesto do repositório
- **WHEN** o teste carrega `containers/images.yaml`
- **THEN** a validação passa e existem as entradas `sandbox`, `postgres` e `qdrant`

#### Scenario: Chave desconhecida
- **GIVEN** uma entrada com `emular: true`
- **WHEN** o manifesto é carregado
- **THEN** o carregamento falha citando a chave e a imagem

### Requirement: Plano sem efeitos
O sistema SHALL calcular, sem baixar nem construir nada, um plano com o estado de cada imagem
(`ok`, `pull`, `build`, `sem_suporte`) e o aviso `nao_validada` quando a plataforma não está em
`validada_em`.

#### Scenario: Imagem presente com a arquitetura certa
- **GIVEN** a imagem do sandbox existe localmente com arquitetura `arm64` e o daemon é `arm64`
- **WHEN** o plano é calculado
- **THEN** o estado do sandbox é `ok`

#### Scenario: Imagem de outra arquitetura
- **GIVEN** a imagem do sandbox existe com arquitetura `amd64` e o daemon é `arm64`
- **WHEN** o plano é calculado
- **THEN** o estado do sandbox é `build`

#### Scenario: Plataforma não validada
- **GIVEN** a plataforma `linux/amd64` e o Qdrant com `validada_em: [linux/arm64/pi5/16k]`
- **WHEN** o plano é calculado
- **THEN** o Qdrant recebe o aviso `nao_validada`
- **AND** nenhuma chamada de `pull` ou `build` é feita

### Requirement: Obtenção conferida
O sistema SHALL, no subcomando `ensure`, pedir confirmação antes de baixar ou construir (salvo
`--yes`), SHALL baixar e construir com `platform=linux/<arquitetura do daemon>`, SHALL conferir a
arquitetura da imagem obtida e SHALL gravar o resultado em `store/platform.json`. Arquitetura
fora das suportadas SHALL interromper sem tentar emulação.

#### Scenario: Build nativo
- **GIVEN** daemon `arm64` e a imagem do sandbox ausente
- **WHEN** `ensure --yes` roda com o cliente simulado
- **THEN** o build é chamado com `platform="linux/arm64"` e o Dockerfile do manifesto
- **AND** `store/platform.json` registra a referência, o ID e a arquitetura da imagem

#### Scenario: Arquitetura divergente após pull
- **GIVEN** um `pull` que devolve imagem `amd64` num daemon `arm64`
- **WHEN** `ensure --yes` roda
- **THEN** o comando falha com mensagem que cita as duas arquiteturas

#### Scenario: Sem suporte
- **GIVEN** daemon `s390x`
- **WHEN** `ensure --yes` roda
- **THEN** o comando falha listando as arquiteturas suportadas e nenhuma imagem é baixada

### Requirement: Imagem do sandbox conferida no início da sessão
O sistema SHALL conferir, no início de cada sessão, que a imagem do sandbox existe e tem a
arquitetura do daemon, SHALL impedir o início com erro acionável que traz o comando
`uv run python -m scripts.platform_images ensure --imagens sandbox` quando não tiver, e SHALL
emitir um `WARNING` por sessão quando a plataforma não estiver validada para o sandbox.

#### Scenario: Imagem ausente
- **GIVEN** a imagem configurada em `SANDBOX_IMAGE` não existe
- **WHEN** uma sessão inicia
- **THEN** a sessão não começa e a mensagem traz o comando de `ensure`

#### Scenario: Plataforma não validada
- **GIVEN** a imagem existe com a arquitetura certa e a plataforma não está em `validada_em`
- **WHEN** uma sessão inicia
- **THEN** a sessão começa e um único `WARNING` é registrado

## REMOVED Requirements

### Requirement: Escolha de IPC por plataforma
**Motivo:** `src/platform_utils.py` decidia TCP/Unix para o IPC removido pelo ADR 014; não tem
chamadores.

#### Scenario: Módulo removido
- **WHEN** o teste de política procura importações de `src.platform_utils`
- **THEN** nenhuma é encontrada
