# Proposta: Imagem Enxuta do Sandbox e Execução sem Root

**ID:** `v16-sandbox-slim-image` · **Versão:** V16 (complemento) · **Capacidade:** `code-sandbox`
**ADRs de origem:** [ADR 018](../../../docs/decisions/adr_018_imagem_sandbox_enxuta_e_imagens_por_plataforma.md)
§1 (imagem mínima, pacotes sob demanda), §2 (usuário sem privilégios), §3 (montagem do
`/outputs`); [ADR 014](../../../docs/decisions/adr_014_agentes_em_processo_sandbox_codigo.md) §2;
[ADR 003](../../../docs/decisions/adr_003_containerizacao_docker_dind.md) §2
**Depende de:** `v16-in-process-agents` fase 2 (concluída: #80 e #81)
**Relaciona-se com:** `v18.5-sandbox-phases` (que passa a depender desta mudança; ver
"Divisão com a v18.5-sandbox-phases")

## Por quê

Com os agentes rodando no host (ADR 014), o container existe só para executar o código do
Developer, mas a imagem ainda é a do modelo antigo:

- `containers/Dockerfile` instala os extras `deep_search`, `google` e `documents` (`docling`,
  `qdrant-client`, `google-genai`…) e copia `src/` e `agents/`. A imagem `geminiclaw-base` tem
  **10,8 GB**, um problema sério no disco do Raspberry Pi 5.
- A instalação de pacotes roda **como root** (`src/skills/code/sandbox.py:369`,
  `exec_run(cmd, user='root')`) e uma falha de instalação só vai para o log; o script roda
  assim mesmo.
- A saída é ajustada por root com `chmod 777`/`chown -R` (`sandbox.py:275`, `:345-346`,
  `:427-428`) e os artefatos copiados de volta recebem `0o777`/`0o666` (`sandbox.py:463-470`).
- Os artefatos chegam duas vezes: pelo bind mount e por `get_archive` (`sandbox.py:432-476`).
- `HOST_PROJECT_PATH` (`sandbox.py:280-286`) só existia para o orquestrador em container.
- A imagem é fixa no código (`PythonSandbox(image="geminiclaw-base")`, `sandbox.py:163`); não há
  variável de configuração.
- Com pacotes, a rede fica ligada durante o script (`sandbox.py:321`).

## O que muda

- **Novo:** imagem do sandbox mínima em `containers/sandbox/Dockerfile`: Python 3.11 slim, `uv`
  e um **conjunto científico básico** com versões travadas e hashes
  (`containers/sandbox/requirements.lock`), instalado num ambiente virtual somente leitura.
  Sem `src/`, `agents/`, extras do projeto, `docling`, `fastembed`, `qdrant-client` ou SDKs de LLM.
- **Novo:** `SANDBOX_IMAGE` (padrão `code-sandbox:latest`) lido de `src/config.py`.
- **Novo:** container do sandbox endurecido: usuário = UID/GID do orquestrador, `cap_drop=ALL`,
  `no-new-privileges`, limite de processos e sistema de arquivos raiz somente leitura com
  `/tmp` em `tmpfs`.
- **Novo:** pacotes sob demanda instalados **sem root** em `/deps` (diretório temporário por
  execução), com comando fixo montado pelo sandbox e nomes validados (PEP 508, sem URLs nem
  opções); falha ou timeout da instalação **falha a execução**.
- **Novo:** depois da instalação, o container é **desconectado da rede** antes de o script
  rodar; se a desconexão falhar, a execução é abortada.
- **Modificado:** `/outputs` continua montado (ADR 018 §3), restrito ao diretório da subtarefa,
  sem `chmod 777`, sem `chown` por root e sem a cópia duplicada por `get_archive`.
- **Modificado:** o parâmetro interno `setup_commands` dá lugar a `packages: list[str]`.
- **Removido:** `HOST_PROJECT_PATH`; o `containers/Dockerfile` atual (substituído pelo novo);
  `--platform=linux/arm64` fixo (a seleção de plataforma é da `v16-platform-images`).
- **Fora do escopo:** separação em containers por fase, ativos declarados, `/inputs` somente
  leitura e cache de pacotes entre execuções (`v18.5-sandbox-phases`); script de plataforma e
  publicação de imagens (`v16-platform-images`).

## Divisão com a v18.5-sandbox-phases

A `v18.5-sandbox-phases` foi escrita supondo a imagem atual e já previa usuário não-root,
instalação em `/deps` e fim do `chmod 777`. Esta mudança antecipa essas partes, que não
dependem do ADR 019, e deixa para a V18.5 só o que depende dele: containers separados por
fase, `fetch_assets`, `/inputs`, a exceção de rede para entradas compartilháveis e o resultado
estruturado. O `design.md` da V18.5 recebe uma nota com essa divisão.

## Impacto

- **Código:** `containers/sandbox/Dockerfile` (novo), `containers/sandbox/requirements.in` e
  `requirements.lock` (novos), `containers/Dockerfile` (removido), `scripts/build_images.sh`
  (aponta para a nova imagem até ser substituído pela `v16-platform-images`),
  `src/skills/code/sandbox.py`, `src/skills/code/skill.py`, `src/config.py`, `.env.example`,
  `agents/developer/agent.py` (lista do conjunto básico na instrução).
- **Disco:** imagem estimada abaixo de 1 GB (medir no Pi 5 na validação), contra 10,8 GB.
- **Comportamento:** pacotes fora do conjunto básico são instalados a cada execução que os
  pede (primeira execução mais lenta, ADR 018). Scripts que dependiam de bibliotecas do projeto
  dentro da imagem (ex.: `docling`) passam a pedi-las em `packages`.
- **Contratos:** `SandboxResult` ganha `install_failed: bool` e `packages_installed` (nomes e
  versões); a assinatura pública da skill não muda.

## Aprovações necessárias

1. **Dockerfile base:** criação de `containers/sandbox/Dockerfile` e **remoção** de
   `containers/Dockerfile` (AGENTS.md §1.5). Aprovação explícita do pesquisador.
2. **Comportamento do container do sandbox** (usuário, capacidades, raiz somente leitura,
   desconexão de rede): fronteira de isolamento do ADR 014 §3. Exige revisão do Analista de
   Segurança antes do merge.
3. **Texto do ADR 014 §2 e do ADR 003 §2** ("sem bind mounts"): esta mudança mantém o bind mount
   de `/outputs`, como o ADR 018 §3 decidiu. O ajuste de texto dos ADRs deve ser aprovado junto.
4. Remoção da imagem antiga `geminiclaw-base` do disco do Pi (operação manual do pesquisador,
   depois da validação; não é feita pelo código).
