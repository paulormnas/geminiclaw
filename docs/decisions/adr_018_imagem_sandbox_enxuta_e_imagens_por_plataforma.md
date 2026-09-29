# ADR 018 — Imagem Enxuta do Sandbox de Código e Seleção de Imagens por Plataforma

**Status:** Proposto — registro de ideias para discussão posterior
**Data:** 2026-09-29
**Autores:** Arquiteto de Soluções (GeminiClaw)
**Relacionados:** ADR 014 (agentes em processo; sandbox como único uso de container), ADR 003 §2 (sandbox de código), ADR 016 (imagem do PostgreSQL), ADR 005 (persistência)
**Specs relacionadas:** `openspec/changes/v16-in-process-agents` (fase 2)

> **Este documento apenas registra ideias e observações para retomada futura.** Não define
> implementação, não tem OpenSpec associado e não deve ser tratado como decisão fechada. A
> discussão fica para depois que a segunda onda de implementação do ADR 014 for concluída.

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
- O `Dockerfile.qdrant` compila o Qdrant do código-fonte (Rust), porque uma imagem pré-compilada
  testada meses atrás **não funcionou no Raspberry Pi**. Esse build é lento e pesado no Pi.
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

### 4. Qdrant em ARM64

- A imagem pré-compilada do Qdrant falhou no Raspberry Pi meses atrás; por isso o projeto
  compila do código-fonte. É possível que as versões atuais já tenham suporte estável a ARM64.
- Ideia: **reavaliar a imagem oficial do Qdrant** no Raspberry Pi 5 e, se funcionar, abandonar o
  `Dockerfile.qdrant` e o build em Rust. Se continuar falhando, registrar o motivo (versão,
  tamanho de página do kernel, erro observado) para embasar a manutenção do build próprio.
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
- Manter o build do Qdrant a partir do código-fonte contra adotar a imagem oficial.
- Descoberta de plataforma por script de shell contra um utilitário Python (`uv run`), em
  coerência com a regra de que scripts do projeto são Python.

---

## Consequências esperadas (se as ideias forem adotadas)

- Redução drástica do espaço em disco e do tempo de build, importante no Raspberry Pi 5.
- Primeira execução de cada experimento mais lenta, por causa da instalação de pacotes, salvo
  cache.
- O sandbox ganha rede para instalar pacotes, o que amplia a superfície de risco (o código gerado
  poderia acessar a internet); a mitigação precisa ser definida na revisão de segurança.
- Menos arquivos a manter: saem os Dockerfiles de agente, o de `slim` e possivelmente o do Qdrant.

---

## Revisão

Retomar este ADR **após a conclusão da segunda onda de implementação do ADR 014** (fase 2 do
`v16-in-process-agents`), quando será feita a revisão de segurança e de tamanho da imagem. Na
retomada: transformar em decisão, atualizar o ADR 014 §2 (bind mount) e abrir o OpenSpec
correspondente.
