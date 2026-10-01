# Design: Identificação de Plataforma e Seleção de Imagens

## 0. Estado atual (verificado em `dev`, commit `40419ea`, 2026-10-01)

| Ponto | Onde | Situação |
|---|---|---|
| Build do sandbox | `scripts/build_images.sh` | Shell; `docker build -t geminiclaw-base:latest -f containers/Dockerfile`. |
| Plataforma fixa | `containers/Dockerfile` (`FROM --platform=linux/arm64`) | Sai com a `v16-sandbox-slim-image`. |
| Postgres/AGE | `docker-compose.yml` (`build: containers/Dockerfile.postgres`, `FROM apache/age:release_PG16_1.6.0`) | Multiarquitetura (amd64/arm64); a decisão de imagem é do ADR 016 (Proposto). |
| Qdrant | `docker-compose.yml` (`${QDRANT_IMAGE:-qdrant/qdrant:v1.19.1}`) | Multiarquitetura; validada no Pi 5 com páginas de 16K (PR #74). |
| Ollama | `docker-compose.yml` (perfil `local-llm`, `ollama/ollama:latest`) | Opcional; no Pi 5 recomenda-se Ollama nativo. |
| Utilitário de plataforma | `src/platform_utils.py` | `is_mac()`/`should_use_tcp_ipc()`; sem chamadores desde a remoção do IPC. |

## 1. Manifesto (`containers/images.yaml`)

```yaml
versao: 1
imagens:
  sandbox:
    obter: build
    dockerfile: containers/sandbox/Dockerfile
    tag_env: SANDBOX_IMAGE               # tag lida de src/config.py
    arquiteturas: [arm64, amd64]
    validada_em: []                      # preenchido após validação real
  postgres:
    obter: compose                       # construída pelo próprio compose (fora do escopo mudar)
    dockerfile: containers/Dockerfile.postgres
    arquiteturas: [arm64, amd64]         # da imagem-base apache/age
    validada_em: [linux/arm64/pi5/16k]
  qdrant:
    obter: pull
    referencia_env: QDRANT_IMAGE
    referencia_padrao: qdrant/qdrant:v1.19.1
    arquiteturas: [arm64, amd64]
    validada_em: [linux/arm64/pi5/16k]
  ollama:
    obter: pull
    referencia_padrao: ollama/ollama:latest
    arquiteturas: [arm64, amd64]
    opcional: true                       # só com --com-ollama
    validada_em: []
```

Esquema estrito (chaves desconhecidas são erro). `validada_em` usa o identificador de
plataforma do §2. A lista é atualizada por PR depois de uma validação real, como foi feito com o
Qdrant.

## 2. Detecção (`src/platform_info.py`)

```python
@dataclass(frozen=True)
class PlatformInfo:
    host_os: str          # darwin | linux | windows
    host_arch: str        # arm64 | amd64 (normalizado de aarch64/x86_64)
    daemon_os: str        # do `client.info()`; em geral linux
    daemon_arch: str      # arquitetura em que os containers rodam
    board: str | None     # "pi5" quando /proc/device-tree/model contém "Raspberry Pi 5"
    page_size: int | None # os.sysconf("SC_PAGE_SIZE") no Linux; None no macOS
    @property
    def id(self) -> str:  # ex.: "linux/arm64/pi5/16k", "linux/arm64", "linux/amd64"
```

- A arquitetura **alvo das imagens é a do daemon** (`daemon_arch`), não a do host: no macOS o
  Docker Desktop roda uma VM Linux.
- `page_size` e `board` entram no `id` só quando relevantes (Pi e página diferente de 4K), pois
  são o que já causou falha real (ADR 018 §4).
- Funções puras recebem as fontes (texto do `device-tree`, `info()` do daemon) como argumentos,
  para teste sem hardware.

## 3. Utilitário (`scripts/platform_images.py`)

| Subcomando | Faz |
|---|---|
| `detect` | Imprime `PlatformInfo` (texto ou `--json`). Não toca no Docker além de `info()`. |
| `plan` | Para cada imagem do manifesto: `ok` (presente e com a arquitetura certa), `pull`, `build` ou `sem_suporte`; e um aviso `nao_validada` quando o `id` da plataforma não está em `validada_em`. Não altera nada. |
| `ensure` | Executa o plano: `pull` com `platform=linux/<daemon_arch>`, `build` com a mesma plataforma; depois confere `image.attrs["Architecture"]` e grava `store/platform.json`. Pede confirmação antes de baixar/construir, salvo `--yes`. |

- `obter: compose`: o utilitário só confere se a arquitetura do daemon está em `arquiteturas`
  e se a plataforma está em `validada_em`; quem constrói é o `docker compose up`.
- `sem_suporte` (arquitetura fora de `arquiteturas`): `ensure` para com mensagem que lista as
  arquiteturas suportadas e não tenta emulação. `--permitir-emulacao` é explicitamente fora do
  escopo.
- Uma imagem `opcional` só entra com `--com-ollama` (ou o nome dela em `--imagens`).
- Saída sem cores quando não é terminal; código de saída 0 = tudo `ok`, 1 = erro, 2 = há
  `nao_validada` (com `--estrito`).
- **Onde roda:** comando explícito, executado na instalação (`SETUP.md`, `scripts/setup_pi.sh`
  passa a chamá-lo) e quando o pesquisador atualiza imagens. **Não** roda dentro do `docker
  compose up` nem automaticamente na inicialização do orquestrador (ver questão em aberto 1).

`store/platform.json`:

```json
{"gerado_em": "…", "plataforma": {"id": "linux/arm64/pi5/16k", "...": "..."},
 "manifesto_versao": 1,
 "imagens": {"sandbox": {"referencia": "code-sandbox:latest", "id": "sha256:…", "arquitetura": "arm64", "validada": false}}}
```

## 4. Verificação no início da sessão

O orquestrador (junto das checagens de `src/infrastructure.py`) confere apenas a imagem do
sandbox, que é a única que ele usa diretamente:

- ausente → erro acionável: `uv run python -m scripts.platform_images ensure --imagens sandbox`;
- arquitetura diferente da do daemon → mesmo erro, citando as duas arquiteturas;
- plataforma fora de `validada_em` → `WARNING` uma vez por sessão (não bloqueia).

Infraestrutura (Postgres, Qdrant) continua verificada pelos health checks existentes.

## 5. Análise de impacto (6 eixos)

| Eixo | Impacto |
|---|---|
| Orquestrador & Loop | Uma checagem a mais no início da sessão (uma chamada `images.get`). |
| Agentes & Prompts | Nenhum. |
| Sandboxes & Containers | Construção nativa por arquitetura; conferência de arquitetura após `pull`/`build`. |
| Persistência | `store/platform.json` (fora do controle de versão, como o resto de `store/`). |
| Segurança | Referências fixas por versão (sem `latest` para imagens obrigatórias); confirmação antes de baixar; nenhuma credencial envolvida. |
| Testes & Telemetria | Detecção e planejamento testáveis com entradas simuladas; integração no Mac e no Pi. |

## 6. Riscos

- **Imagem multiarquitetura que não funciona numa variante** (caso do Qdrant): coberto pelo
  aviso `nao_validada`, não por detecção automática de falha.
- **Ollama `latest`** não é reprodutível: aceitável por ser opcional; registrar o digest em
  `store/platform.json`.
- **Docker indisponível:** `detect` funciona parcialmente (host), `plan`/`ensure` falham com
  mensagem clara.

## 7. Questões em aberto para o pesquisador

1. **Onde o utilitário roda:** proposta = comando explícito na instalação e na atualização, com
   checagem só da imagem do sandbox no início da sessão. Alternativa: rodar `ensure`
   automaticamente no início da sessão (mais lento e baixaria imagens sem pedir).
2. **Publicar imagens prontas** (ex.: GitHub Container Registry, multiarquitetura) para o Pi não
   precisar construir: fica fora desta mudança? Exigiria decidir registro, assinatura e quem
   publica.
3. **Registro do resultado:** proposta = `store/platform.json`, sem tocar no `.env` (que guarda
   segredos). Confirmar.
