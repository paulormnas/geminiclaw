# ADR 018 — Imagem Enxuta do Sandbox de Código e Seleção de Imagens por Plataforma

**Status:** Aprovado em 2026-10-01 pelo pesquisador responsável — direção aprovada; implementação pendente, exceto o item 4 e a limpeza da infraestrutura de agentes (verificação abaixo). As questões "Em aberto" de cada item serão decididas na spec
**Data:** 2026-09-29
**Autores:** Arquiteto de Soluções (GeminiClaw)
**Relacionados:** ADR 014 (agentes em processo; sandbox como único uso de container), ADR 003 §2 (sandbox de código), ADR 016 (imagem do PostgreSQL), ADR 005 (persistência)
**Specs relacionadas:** `openspec/changes/v16-in-process-agents` (fase 2)

> **Aprovado como direção em 2026-10-01.** A segunda onda do ADR 014 foi concluída (#80 e #81),
> então a retomada prevista na seção "Revisão" começou. Os itens 1, 2, 3 e 5 ainda precisam de
> OpenSpec (`v16-sandbox-slim-image` e `v16-platform-images`); as perguntas "Em aberto" são
> decididas lá.

### Verificação do que está implementado (2026-10-01)

| Item | Estado |
|---|---|
| 1. Imagem mínima do sandbox com pacotes sob demanda | **Pendente.** `containers/Dockerfile` ainda instala os extras `deep_search`, `google` e `documents` e copia `src/` e `agents/`; a imagem `geminiclaw-base` tem 10,8 GB |
| 2. Internet e usuário sem privilégios | **Pendente.** `src/skills/code/sandbox.py` executa a instalação de pacotes como root; a rede fica ligada sempre que há comandos de setup, e o script roda no mesmo container, ainda com rede (a separação por fases é o escopo de `v18.5-sandbox-phases`) |
| 3. Montagem do `/outputs` | **Pendente** a conciliação com usuário não-root: o código ainda usa `chmod 777` e `chown` por `exec_run` como root, e `HOST_PROJECT_PATH` segue no sandbox |
| 4. Qdrant em ARM64 | **Feito** (PR #74): imagem oficial `qdrant/qdrant:v1.19.1` |
| 5. Identificação de plataforma e seleção de imagens | **Pendente.** Não há script; os Dockerfiles fixam `--platform=linux/arm64`; `src/platform_utils.py` só decide TCP/Unix para IPC, que foi removido |
| Limpeza da infraestrutura de agentes | **Feito** (#80 e #81): sem Dockerfiles de agente e `slim`, sem o serviço `geminiclaw` e a rede do compose, sem `DOCKER_IMAGE_BASE` |
| Portas em `127.0.0.1` | **Parcial.** Postgres e Ollama já publicam em `127.0.0.1`; o Qdrant segue em `0.0.0.0` por decisão do pesquisador durante o desenvolvimento, com `TODO(segurança)` no compose |

> **Atualização 2026-09-29 (Qdrant):** o item 4 foi resolvido e implementado no PR #74. A imagem
> oficial `qdrant/qdrant:v1.19.1` roda no Raspberry Pi 5 com o kernel padrão (páginas de 16K), o
> `Dockerfile.qdrant` foi removido e o Qdrant deixou de ser compilado. Os demais itens seguem
> como ideias em aberto.

---

## Contexto

Com o ADR 014, agentes e orquestrador passam a rodar como processos locais e o container fica
restrito ao sandbox de código do Developer. A revisão do repositório mostrou que a infraestrutura
de container ainda reflete o modelo anterior:

- A imagem `geminiclaw-base` ocupa **10,8 GB**. Ela é a imagem-pai de todos os agentes
  (`planner`, `researcher`, `reviewer`, `summarizer`, `validator`, `developer`) e também é a
  imagem **padrão do sandbox** (`PythonSandbox.__init__`, `src/skills/code/sandbox.py`).
- Ela é construída com os extras `deep_search`, `google` e `documents` (`docling`, `fastembed`,
  `qdrant-client`, entre outros), além de `src/` e `agents/`. Nada disso é necessário para
  executar o código gerado pelo Developer.
- O serviço `geminiclaw` do `docker-compose.yml` (o próprio orquestrador em container, com o
  `docker.sock` montado) deixa de fazer sentido.
- O `docker-compose.yml` publica o Qdrant em `0.0.0.0` e usa a rede `geminiclaw-net`, criada
  para os containers de agente.
- *(Resolvido no PR #74.)* O `Dockerfile.qdrant` compilava o Qdrant do código-fonte (Rust), porque
  uma imagem pré-compilada testada meses atrás **não funcionou no Raspberry Pi**. A compilação
  derrubava o Pi (memória/temperatura) e o arquivo foi removido.
- Não há hoje uma forma única de descobrir a plataforma em que o projeto roda (macOS/ARM64 em
  desenvolvimento, Raspberry Pi 5/ARM64, x86_64) e obter as imagens corretas para ela. Os
  Dockerfiles fixam `--platform=linux/arm64`.

---

## Ideias registradas

### 1. Sandbox com imagem mínima e pacotes sob demanda

- A imagem do sandbox deve ser **mínima**: interpretador Python, `uv` e o mínimo para executar
  scripts. Sem `docling`, `fastembed`, `qdrant-client`, `google-genai`, e sem `src/` ou `agents/`.
- Bibliotecas pesadas (documentos, embeddings, aprendizado de máquina etc.) são **instaladas
  conforme o problema a ser resolvido**, pelo parâmetro `packages` da skill de código, e não
  embutidas na imagem.
- Em aberto: se um conjunto científico básico (numpy, pandas, matplotlib, scikit-learn) entra na
  imagem ou também é instalado sob demanda; e como evitar reinstalar os mesmos pacotes a cada
  execução (cache de pacotes, imagens derivadas por tipo de experimento, ambientes reutilizados).

### 2. Acesso à internet e usuário sem privilégios

- O container do sandbox **precisa de acesso à internet** para baixar pacotes novos.
- O código **não deve rodar como root**, para evitar escalada de privilégios. Isso vale também
  para a etapa de instalação de pacotes, que hoje é executada como root.
- Em aberto: como instalar pacotes sem root (ambiente virtual gravável pelo usuário do
  sandbox, `uv pip install --target`, ou diretório de pacotes montado); e se a instalação e a
  execução do script ficam em fases distintas de rede (com internet para instalar, sem internet
  para executar).

### 3. Montagem do `/outputs` é necessária

- O diretório `/outputs` continua **montado** no sandbox, para exportar código, gráficos e
  demais artefatos gerados nos experimentos.
- Isso diverge do texto do ADR 014 §2 ("sem bind mounts"), que precisa ser revisto se esta ideia
  for adotada. O sandbox atual já usa bind mount de `/outputs`.
- Em aberto: como conciliar a montagem com um usuário não-root (propriedade e permissões sem
  `chmod 777`), e como confinar a montagem ao diretório da sessão.

### 4. Qdrant em ARM64 — resolvido (PR #74)

- A imagem pré-compilada falhava no Raspberry Pi por causa do jemalloc: o kernel padrão do Pi 5
  usa páginas de 16K e o jemalloc das versões relatadas nos issues (1.7.4, 1.11.4 e o `latest` de
  fev/2025) abortava com `<jemalloc>: Unsupported system page size` (issues
  [#5952](https://github.com/qdrant/qdrant/issues/5952) e
  [#7246](https://github.com/qdrant/qdrant/issues/7246) do Qdrant). Não foi verificado em qual
  release exata o problema deixou de ocorrer; as notas da 1.19.1 não o mencionam.
- Validado em 2026-09-29: `qdrant/qdrant:v1.19.1` sobe no Pi 5 com o kernel padrão
  (`getconf PAGESIZE` = 16384, kernel `6.12.109+rpt-rpi-2712`), sem trocar para o kernel de 4K.
  O serviço fica `healthy` em cerca de 10 s e os testes de integração do Qdrant passam.
- Decisão aplicada: o compose usa a imagem oficial (sobrescrevível por `QDRANT_IMAGE`), o
  `qdrant-client` foi alinhado à 1.19.1 e o `Dockerfile.qdrant` foi removido.
- Se uma versão futura voltar a falhar no Pi, o caminho de contingência é compilar com
  `JEMALLOC_SYS_WITH_LG_PAGE=16` (aceita páginas de 4K a 64K), de preferência fora do Pi.
- Precedente: o ADR 016 adota a imagem oficial `apache/age` justamente por ter suporte a ARM64.

### 5. Script de identificação de plataforma e seleção de imagens

- Um **script** identifica a plataforma em que o projeto roda (sistema operacional e arquitetura,
  por exemplo macOS/ARM64, Raspberry Pi 5/ARM64, Linux/x86_64) e obtém as imagens corretas para
  ela: baixando a variante publicada para a arquitetura, ou construindo localmente quando não
  houver.
- Substituiria os `--platform=linux/arm64` fixos nos Dockerfiles e o `scripts/build_images.sh`
  atual, e passaria a cobrir também as imagens de infraestrutura (Postgres/AGE, Qdrant, e o
  Ollama quando usado em container).
- Em aberto: onde o script roda (na instalação, no `docker compose up`, na inicialização do
  orquestrador); como registra o resultado (arquivo de configuração/`.env`); e como trata
  plataformas sem imagem disponível.

---

## Pontos de atenção levantados na revisão (para a discussão)

Observados no código durante o levantamento; não são decisões:

- O sandbox atual roda **sem usuário definido** (root) e executa a instalação de pacotes como
  root, com `chown`/`chmod 777` no diretório de saída.
- A rede do sandbox é habilitada sempre que há comandos de setup, e o script principal roda no
  mesmo container, ainda com rede.
- `HOST_PROJECT_PATH` e o mapeamento de volumes existem por causa do orquestrador em container
  (Docker-in-Docker); saem junto com o serviço `geminiclaw` do compose.
- A variável `DOCKER_IMAGE_BASE` (`geminiclaw-agent-base:latest`) está definida em
  `src/config.py` e `.env.example`, mas o sandbox não a usa. Falta uma variável para a imagem do
  sandbox.
- Para o Qdrant e o Postgres, considerar publicar as portas apenas em `127.0.0.1`.

---

## Alternativas a considerar na discussão

- Manter uma única imagem "completa" do sandbox, apenas reduzida (sem extras de documentos e
  embeddings), contra uma imagem mínima com instalação sob demanda.
- Imagens do sandbox por perfil de experimento (dados, visão computacional, texto), contra um
  único ambiente com pacotes instalados na hora.
- ~~Manter o build do Qdrant a partir do código-fonte contra adotar a imagem oficial.~~ Resolvido:
  imagem oficial adotada (PR #74).
- Descoberta de plataforma por script de shell contra um utilitário Python (`uv run`), em
  coerência com a regra de que scripts do projeto são Python.

---

## Consequências esperadas (se as ideias forem adotadas)

- Redução drástica do espaço em disco e do tempo de build, importante no Raspberry Pi 5.
- Primeira execução de cada experimento mais lenta, por causa da instalação de pacotes, salvo
  cache.
- O sandbox ganha rede para instalar pacotes, o que amplia a superfície de risco (o código gerado
  poderia acessar a internet); a mitigação precisa ser definida na revisão de segurança.
- Menos arquivos a manter: saem os Dockerfiles de agente e o de `slim` (o do Qdrant já saiu no PR #74).

---

## Revisão

A retomada ocorreu em 2026-10-01 (segunda onda do ADR 014 concluída). Próximos passos: descrever
as duas specs acima, fazer a revisão de segurança do sandbox (superfície de rede, usuário
não-root, bind mount) e, ao implementar, atualizar o ADR 014 §2 (já anotado em 2026-10-01).
