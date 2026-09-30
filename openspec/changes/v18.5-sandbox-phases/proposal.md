# Proposta: Sandbox com Fases Separadas de Rede e Dados

**ID:** `v18.5-sandbox-phases` · **Versão:** V18.5 · **Capacidade:** `code-sandbox`
**ADRs de origem:** [ADR 019](../../../docs/decisions/adr_019_localidade_dados_proveniencia_resultados.md) §5
(também §1 e §3.3), [ADR 014](../../../docs/decisions/adr_014_agentes_em_processo_sandbox_codigo.md) §2, §3 e §5,
[ADR 003](../../../docs/decisions/adr_003_containerizacao_docker_dind.md) §2,
[ADR 018](../../../docs/decisions/adr_018_imagem_sandbox_enxuta_e_imagens_por_plataforma.md) §2 e §3

## Por quê

O ADR 019 §5 decide que **nenhum script com acesso a dados de pesquisa roda com rede**. O
sandbox atual faz o contrário quando há pacotes a instalar:

- A rede é ligada sempre que existem comandos de setup
  (`network_disabled=not bool(setup_commands)`, `src/skills/code/sandbox.py:211`), e o script
  principal roda no **mesmo container**, ainda com rede (`sandbox.py:261`).
- A instalação roda **como root** (`sandbox.py:238`) e uma falha de instalação é só
  registrada em log (`sandbox.py:239-240`): o script roda mesmo assim, sem o pacote.
- Não existe forma de declarar pesos, corpora ou datasets públicos. Um download dentro do
  script falha sem rede com um erro genérico, ou funciona com rede e fora de qualquer registro.
- O diretório de saída é montado com leitura e escrita desde a criação do container
  (`sandbox.py:180-185`) e o ajuste de permissões usa `chown`/`chmod 777` como root
  (`sandbox.py:276-280`).

Esta mudança decide a política de rede que o ADR 014 §5 deixou para a spec e implementa a
separação em três fases do ADR 019 §5.

## O que muda

- **Novo:** três fases por execução da skill de código:
  1. `install`: com rede, **sem** dados de pesquisa nem diretórios da sessão montados, como
     usuário não-root; falha de instalação **falha a execução**.
  2. `fetch_assets`: com rede, **sem** dados; baixa os ativos declarados (URL e, quando
     conhecido, sha256), verifica o hash e guarda em cache local por conteúdo.
  3. `execute`: **sem rede**; dados de pesquisa entregues por montagem somente leitura (padrão)
     ou por cópia (`put_archive`); só o diretório de saída da subtarefa é gravável.
- **Novo:** parâmetro `assets` na skill `python_interpreter` para declarar ativos a baixar.
- **Novo:** erro acionável quando o script tenta baixar algo na fase `execute` ("declare o
  ativo em `assets`"), em vez de um erro de rede genérico.
- **Novo:** exceção de rede na fase `execute` somente quando **todas** as entradas visíveis ao
  script estão marcadas como `compartilhavel` e a execução pede rede explicitamente.
- **Novo:** o resultado do sandbox passa a informar, de forma estruturada, a fase que falhou,
  o digest da imagem, os pacotes instalados com versões, os ativos baixados e se houve rede na
  execução — insumo de `v18.5-execution-provenance`.
- **Modificado:** containers do sandbox rodam com o UID/GID do orquestrador (não-root), sem
  `chown`/`chmod 777` como root.
- **Modificado:** a skill de código chama o sandbox fora do event loop (`asyncio.to_thread`),
  hoje a chamada é síncrona (`src/skills/code/skill.py:175`).

## Fora do escopo

- Imagem mínima do sandbox, cache de pacotes e seleção de imagens por plataforma (ADR 018 §1
  e §5): continuam em aberto. Esta mudança funciona com a imagem atual.
- Filtro da saída do sandbox antes de ir ao LLM (`v18.5-egress-gate`).
- Registro encadeado das execuções (`v18.5-execution-provenance`).
- Definição de quais arquivos são `compartilhavel` (`v18.5-research-data-ingestion`); aqui só
  se consome a marcação.

## Impacto

- **Código:** `src/skills/code/sandbox.py` (fases, montagens, usuário, resultado
  estruturado), `src/skills/code/fetch_assets.py` (novo: script fixo de download executado
  dentro do container da fase `fetch_assets`), `src/skills/code/assets.py` (novo: declaração,
  cache e verificação de ativos), `src/skills/code/skill.py` (parâmetro `assets`,
  `asyncio.to_thread`, erro acionável), `agents/developer/agent.py` (instrução sobre `assets`
  e leitura de `/inputs`), `src/config.py`, `.env.example`.
- **Comportamento:** scripts que baixavam arquivos durante a execução passam a falhar com
  erro acionável até declararem os ativos. Execuções com pacotes ficam mais lentas (um
  container a mais por execução com `packages` ou `assets`).
- **Contratos:** `SandboxResult` ganha campos; a skill ganha o parâmetro opcional `assets`.
- **Dependências:** V18 concluída. Se a fase 2 de `v16-in-process-agents` já tiver removido o
  modo container, a tradução de caminhos por `HOST_PROJECT_PATH` (`sandbox.py:170-178`) não é
  necessária; caso contrário, é mantida para as novas montagens. A exceção por
  `compartilhavel` só é ativada quando `v18.5-research-data-ingestion` existir; antes disso,
  toda execução roda sem rede.

## Aprovações necessárias

1. **Alteração do comportamento de containers do sandbox** (rede por fase, novas montagens
   somente leitura, usuário não-root, volumes de dependências e ativos): toca a fronteira de
   isolamento do ADR 014 §3. Exige **aprovação explícita do pesquisador** e **revisão do
   Analista de Segurança** (`.agents/rules/security-analyst.md`) antes do merge.
2. **Revisão do texto do ADR 014 §2 e do ADR 003 §2** ("sem bind mounts"): esta mudança
   mantém o bind mount de `/outputs` (já existente) e acrescenta montagens **somente leitura**.
   Os ADRs não são alterados aqui; o ajuste de texto deve ser aprovado junto com esta spec.
3. Nenhum Dockerfile, `docker-compose.yml` ou schema de banco é alterado. Diretórios
   temporários criados pela própria execução (dependências e área de download) são removidos
   ao fim de cada execução; nenhum arquivo do usuário é apagado.
