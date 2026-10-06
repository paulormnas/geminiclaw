# Design: Imagem Enxuta do Sandbox e Execução sem Root

## 0. Estado atual (verificado em `dev`, commit `40419ea`, 2026-10-01)

| Ponto | Onde | Situação |
|---|---|---|
| Imagem | `containers/Dockerfile` | `FROM --platform=linux/arm64 python:3.11-slim-bookworm`; `uv sync --extra deep_search --extra google --extra documents`; copia `src/` e `agents/`; `USER appuser`; `CMD` de agente. 10,8 GB. |
| Imagem no código | `src/skills/code/sandbox.py:161-176` | `PythonSandbox(image="geminiclaw-base")`; `CodeSkill` não passa imagem (`skill.py:72-76`). |
| Ambiente do script | `sandbox.py:322` | `VIRTUAL_ENV=/app/.venv`, `MPLCONFIGDIR=/tmp`. |
| Rede | `sandbox.py:321` | `network_disabled=not bool(setup_commands)`; o script roda no mesmo container, com rede, quando houve setup. |
| Instalação | `skill.py:130-138`; `sandbox.py:350-391` | `uv pip install --no-cache-dir <pacotes>` como root; falha só gera `logger.error`; timeout próprio (`CODE_SANDBOX_SETUP_TIMEOUT_SECONDS`). |
| Usuário do script | `containers/Dockerfile` (`USER appuser`) | O script roda como `appuser`; setup e ajustes de permissão rodam como root. |
| Permissões | `sandbox.py:275`, `:345-346`, `:425-430`, `:463-470` | `chmod 0o777` no host; `chmod 777`/`chown -R` como root no container; artefatos com `0o777`/`0o666`. |
| Cópia duplicada | `sandbox.py:432-476` | `get_archive("/outputs")` extrai para `<tarefa>/outputs` e move por cima dos arquivos que o bind mount já gravou. |
| DinD | `sandbox.py:280-286` | `HOST_PROJECT_PATH` traduz caminhos; sem uso desde #80/#81. |
| Endurecimento | `sandbox.py:314-333` | `mem_limit` e cota de CPU; sem `cap_drop`, `pids_limit`, `no-new-privileges` ou raiz somente leitura. |
| Conjunto científico | `pyproject.toml` (dependências do núcleo) | `numpy`, `pandas`, `matplotlib`, `scikit-learn`, `seaborn` entram hoje na imagem por serem do núcleo. A tarefa de referência (`run.sh`, Iris) usa `scikit-learn`. |

## 1. Imagem (`containers/sandbox/Dockerfile`)

```dockerfile
FROM python:3.11-slim-bookworm
COPY --from=ghcr.io/astral-sh/uv:<versão fixa> /uv /bin/uv
COPY containers/sandbox/requirements.lock /tmp/requirements.lock
RUN uv venv /opt/sandbox-venv \
 && uv pip install --python /opt/sandbox-venv/bin/python --require-hashes --no-cache \
      -r /tmp/requirements.lock \
 && rm /tmp/requirements.lock
ENV PATH=/opt/sandbox-venv/bin:$PATH PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    MPLCONFIGDIR=/tmp HOME=/tmp
WORKDIR /outputs
```

- Sem `--platform` fixo: constrói na arquitetura do host (a seleção de imagens é da
  `v16-platform-images`). A tag do `uv` é fixa (hoje `latest`).
- `/opt/sandbox-venv` pertence a root e é somente leitura para o usuário do script.
- **Conjunto científico básico** (`containers/sandbox/requirements.in`): `numpy`, `pandas`,
  `scipy`, `matplotlib`, `scikit-learn`, `seaborn`. É o que a imagem atual já oferece (núcleo do
  projeto) mais `scipy`, para não regredir a tarefa de referência. O `.lock` é gerado com
  `uv pip compile --generate-hashes` e versionado; atualizar é um PR (ver questão em aberto 1).
- Nada de `src/`, `agents/`, `docling`, `fastembed`, `qdrant-client`, SDKs de LLM, `docker`,
  `psycopg`. `scientific_helpers.py` continua sendo injetado por `put_archive` (só stdlib).

## 2. Container

```python
client.containers.run(
    image=config.SANDBOX_IMAGE,
    command=["sleep", "infinity"],
    user=f"{os.getuid()}:{os.getgid()}",
    working_dir="/outputs",
    environment={"HOME": "/tmp", "MPLCONFIGDIR": "/tmp", "PYTHONPATH": "/deps",
                 "UV_CACHE_DIR": "/tmp/uv-cache"},
    volumes={task_dir: {"bind": "/outputs", "mode": "rw"},
             deps_dir: {"bind": "/deps", "mode": "rw"}},
    read_only=True, tmpfs={"/tmp": f"size={SANDBOX_TMPFS_SIZE}"},
    cap_drop=["ALL"], security_opt=["no-new-privileges:true"],
    pids_limit=SANDBOX_PIDS_LIMIT,
    mem_limit=..., cpu_period=..., cpu_quota=...,
    network_disabled=not packages, ...
)
```

- **Usuário:** UID/GID do processo do orquestrador. O UID pode não existir em `/etc/passwd` da
  imagem; `HOME=/tmp` evita as falhas conhecidas (mesma decisão da `v18.5-sandbox-phases`).
  Nenhum `exec_run(..., user='root')` permanece no módulo.
- **Diretório da subtarefa:** `outputs/<sessão>/<tarefa>/`, criado pelo host com o modo padrão
  (umask do usuário). Os arquivos gravados pelo script já pertencem ao usuário do host; o
  bind mount é a única via de retorno (sai a extração por `get_archive`). A varredura
  `_purge_escaping_symlinks` continua ao fim de cada execução.
- **`/deps`:** `SANDBOX_WORK_DIR/<run_id>/deps` (padrão `store/sandbox_work`), criado pelo host,
  removido no `finally`. Existe só quando há `packages`.
- **Imagem ausente:** `_ensure_image` deixa de tentar `pull` de um nome local; devolve erro
  acionável ("construa a imagem com `uv run python -m scripts.platform_images`" — ou, até a
  `v16-platform-images`, com `scripts/build_images.sh`).

## 3. Pacotes sob demanda

1. A skill passa `packages: list[str]`. O sandbox remove nomes da stdlib (lista que hoje está em
   `skill.py:133`) e os que já estão no conjunto básico **sem especificador de versão**, e valida
   cada item com a gramática de requisito do PEP 508 (`packaging.requirements.Requirement`):
   recusa URL direta (`@`), marcador de ambiente, nome iniciado por `-` e caminhos. Item
   inválido → execução não começa, erro que cita o item.
2. Comando fixo, montado pelo sandbox:
   `uv pip install --python /opt/sandbox-venv/bin/python --target /deps <pacotes>`, executado
   com o usuário do container (não-root) e a rede ligada.
3. `exit_code != 0` ou timeout (`CODE_SANDBOX_SETUP_TIMEOUT_SECONDS`, padrão 300, já existente)
   encerra a execução com `install_failed=True`; o script **não roda**. `stderr` traz os pacotes
   pedidos e as últimas `SANDBOX_INSTALL_LOG_TAIL_LINES` (padrão 40) linhas do `uv`.
4. Depois do sucesso, o sandbox registra os pacotes instalados com versão
   (`uv pip list --path /deps --format json`, comando fixo).
5. **Desconexão de rede:** o sandbox desconecta o container de todas as redes
   (`client.networks.get(n).disconnect(container)` para cada rede em
   `container.attrs["NetworkSettings"]["Networks"]`), recarrega o estado e confirma que a lista
   ficou vazia. Qualquer falha → execução abortada com erro (fail-closed). Só então o script roda.

**Decisões da revisão de segurança (2026-10-06, PR #99).** (a) A instalação usa
`--only-binary :all:`: nenhum `setup.py` ou backend de build roda com rede; um pacote que só tem
código-fonte falha de forma explícita (`install_failed`, mensagem acionável). Decisão de adotar,
com o custo de recusar pacotes sem wheel. (b) A instalação roda com `--no-config`,
`UV_NO_CONFIG=1` e workdir `/tmp`, para o código gerado não controlar o índice via `uv.toml`.
(c) A desconexão de rede ocorre antes de qualquer código no container além do `uv`; a listagem
de pacotes usa `python -I` com workdir `/tmp`. (d) `script.py` é injetado só depois da
desconexão. (e) O sandbox recusa UID 0. (f) O container é encerrado antes da varredura de links
simbólicos e arquivos especiais. (g) `session_id` e `task_name` seguem `^[A-Za-z0-9._-]+$`, sem
`..`, e o caminho resolvido precisa ficar sob o diretório de saída. (h) `/tmp` em `tmpfs` com
`noexec,nosuid,nodev` (o `uv` só grava arquivos; wheels não são executados de lá),
`memswap_limit` igual a `mem_limit`, no máximo 20 pacotes de 200 caracteres.

Limite conhecido: o código de instalação (ex.: `setup.py` de pacote sem wheel) roda com rede e
enxerga `/outputs` da subtarefa. A separação em containers por fase, que fecha esse caso, é da
`v18.5-sandbox-phases`.

## 4. Configuração (`src/config.py`, `.env.example`)

| Variável | Padrão | Uso |
|---|---|---|
| `SANDBOX_IMAGE` | `code-sandbox:latest` | Imagem do sandbox |
| `SANDBOX_WORK_DIR` | `store/sandbox_work` | Diretórios temporários por execução (`deps`) |
| `SANDBOX_PIDS_LIMIT` | 256 | Limite de processos |
| `SANDBOX_TMPFS_SIZE` | `256m` | Tamanho do `/tmp` em memória |
| `SANDBOX_INSTALL_LOG_TAIL_LINES` | 40 | Linhas do log do `uv` devolvidas em falha |
| `CODE_SANDBOX_SETUP_TIMEOUT_SECONDS` | 300 | (existente) timeout da instalação |

`HOST_PROJECT_PATH` sai do código e do `.env.example`. `CodeSkill` passa a ler os valores de
`src/config.py` em vez de `os.getenv` (`skill.py:67-70`).

## 5. Análise de impacto (6 eixos)

| Eixo | Impacto |
|---|---|
| Orquestrador & Loop | Nenhuma mudança de fluxo; falha de instalação passa a ser falha da subtarefa (entra nas retentativas normais). |
| Agentes & Prompts | Instrução do Developer lista o conjunto básico e diz que o resto vai em `packages`. |
| Sandboxes & Containers | Imagem nova e mínima; usuário não-root; `cap_drop`, `no-new-privileges`, `pids_limit`, raiz somente leitura; rede desligada antes do script. |
| Persistência | `store/sandbox_work/` temporário; nenhum schema. |
| Segurança | Remove root da instalação, `chmod 777` e capacidades; fecha "script com internet" já nesta versão. Residual: instalação com rede vê `/outputs` (§3). |
| Testes & Telemetria | Testes unitários com cliente Docker simulado; integração com a imagem real; `packages_installed` no resultado. |

## 6. Segurança

Para o Analista de Segurança: (a) confirmar que nenhuma chamada como root sobra no módulo;
(b) avaliar o residual do §3 (instalação com rede e `/outputs` visível) como aceitável até a
V18.5; (c) confirmar que a desconexão de rede antes do script é verificada e fail-closed;
(d) avaliar se `seccomp` padrão do Docker basta (nenhum perfil próprio é proposto);
(e) `read_only=True` com `tmpfs` em `/tmp` e `/deps` gravável: conferir que o script não
consegue gravar fora de `/outputs`, `/deps` e `/tmp`.

## 7. Riscos

- **Primeira execução mais lenta** com pacotes fora do conjunto básico (sem cache entre
  execuções nesta mudança). Mitigação: o conjunto básico cobre a tarefa de referência; o cache
  vem com a `v18.5-sandbox-phases` (ver questão em aberto 2).
- **UID do host no macOS (Docker Desktop):** o mapeamento de dono em bind mount é diferente do
  Linux. O teste de integração roda no Mac e no Pi.
- **Biblioteca que escreve em `$HOME` ou no diretório do pacote:** `HOME=/tmp` e
  `PYTHONDONTWRITEBYTECODE=1` cobrem os casos comuns; erros novos viram exceção documentada.
- **`.lock` envelhece:** atualização por PR, com rebuild da imagem.

## 8. Questões em aberto para o pesquisador

1. **Conjunto científico básico na imagem** (`numpy`, `pandas`, `scipy`, `matplotlib`,
   `scikit-learn`, `seaborn`) ou tudo sob demanda? A proposta é mantê-lo na imagem (sem
   regressão e sem rede para o caso comum).
2. **Cache de pacotes entre execuções:** a proposta é **não** ter cache nesta mudança (o
   container único deixaria o código gerado gravar no cache e envenenar execuções futuras) e
   implementá-lo no container de preparação da `v18.5-sandbox-phases`. Alternativa: imagens
   derivadas por perfil de experimento, construídas sob demanda.
3. **Nome padrão da imagem:** `code-sandbox:latest` (neutro, já que o nome do projeto vai mudar)
   ou outro?
