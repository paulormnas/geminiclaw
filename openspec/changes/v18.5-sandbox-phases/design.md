# Design: Sandbox com Fases Separadas de Rede e Dados

## Estado atual (levantamento em `dev`, commit `2146166`)

| Ponto | Onde | Observação |
|---|---|---|
| Rede ligada quando há setup | `src/skills/code/sandbox.py:211` | `network_disabled=not bool(setup_commands)`: com pacotes, o container inteiro tem rede. |
| Um único container para tudo | `sandbox.py:204-216`, `sandbox.py:261` | Container ocioso (`tail -f /dev/null`); setup e script rodam por `exec_run` no mesmo container. |
| Montagem de saída desde a criação | `sandbox.py:180-185` | `/outputs` (diretório da subtarefa) montado `rw` antes do setup; artefatos de passos anteriores já estão visíveis durante a instalação. |
| Tradução de caminho do DinD | `sandbox.py:170-178` | `HOST_PROJECT_PATH`, necessário só no modo container dos agentes. |
| Script injetado por `put_archive` | `sandbox.py:228-231` | `script.py` e arquivos extras (ex.: `scientific_helpers.py`). |
| Setup como root, falha só em log | `sandbox.py:234-240` | `exec_run(cmd, user='root')`; `exit_code != 0` apenas gera `logger.error`, e o script roda assim mesmo. |
| Timeout só do script | `sandbox.py:245-254` | `threading.Timer` mata o container; o setup não tem timeout. |
| Permissões por root | `sandbox.py:162-165`, `sandbox.py:276-282` | `chmod 777` no host e `chown -R`/`chmod -R 777` como root no container. |
| Erro de sandbox vira resultado | `sandbox.py:339-346` | Qualquer exceção vira `SandboxResult(exit_code=-1)` com texto livre; não há campo de fase. |
| Retentativa de conexão com o daemon | `sandbox.py:194-225` | Evento `connection_retry` (V18). Reaproveitado por todas as fases. |
| Imagem e usuário | `sandbox.py:58`; `containers/Dockerfile:44-45`, `:64` | Imagem padrão `geminiclaw-base`; `uv` presente; `USER appuser`. |
| Pacotes viram comando `uv pip install` | `src/skills/code/skill.py:126-135` | Filtra alguns nomes da stdlib; comando montado pela skill e passado como `setup_commands`. |
| Chamada síncrona dentro de corrotina | `skill.py:175-182` | `self.sandbox.run(...)` é chamado direto em `async def run`, bloqueando o event loop enquanto o container roda. O comentário em `sandbox.py:188-193` supõe `asyncio.to_thread`, que não existe. Com subtarefas em paralelo (`src/autonomous_loop.py:944-946`, `asyncio.gather`), execuções de sandbox hoje se serializam por acidente. |
| Dados de entrada não chegam ao sandbox | `src/orchestrator.py:474-503` | `input_context/` é copiado para `outputs/<sessão>/input_snapshot/` (nomes achatados, `:494`), mas só `outputs/<sessão>/<tarefa>/` é montado. O script não tem caminho definido para ler os insumos; o prompt do Developer só fala de `/outputs/` (`agents/developer/agent.py:54-55`). |

Consequência: com `packages`, código gerado roda com internet e com os artefatos da subtarefa
(dados produzidos por execuções anteriores). É exatamente o caso que o ADR 019 §5 proíbe.

## Decisões

### 1. Dois containers por execução, três fases

```
┌──────────── preparação (só se houver packages ou assets) ────────────┐
│ rede: SIM · dados: NÃO · montagens: /deps (rw), /staging (rw)        │
│   fase fetch_assets → host verifica sha256 e move para o cache       │
│   fase install      → uv pip install --target /deps                  │
└──────────────────────────────────────────────────────────────────────┘
                     container removido (processos da instalação morrem)
┌──────────────────────────── execução ────────────────────────────────┐
│ rede: NÃO · /inputs (ro) · /deps (ro) · /assets/* (ro) · /outputs (rw)│
│   introspecção fixa (python, pacotes) → script.py                    │
└──────────────────────────────────────────────────────────────────────┘
```

- **Por que dois containers e não um container com `network.disconnect`:** o Docker não
  acrescenta montagens a um container em execução, então um container único teria os dados
  montados já na instalação. Além disso, código de instalação (ex.: `setup.py` de um pacote
  sem wheel) é código arbitrário; ele poderia deixar um processo residente esperando os dados.
  Com containers separados, nada da preparação sobrevive até a execução.
- **Ordem dentro da preparação:** `fetch_assets` roda **antes** de `install`, e o host verifica
  e move os ativos para o cache (§3) antes de a instalação começar. Assim o código de
  instalação nunca tem acesso aos arquivos baixados. Os nomes das fases seguem o ADR 019 §5;
  a numeração do ADR descreve as fases, não impõe ordem entre as duas que têm rede.
- **Sem pacotes nem ativos:** só o container de execução é criado (comportamento e custo
  iguais aos de hoje para esse caso, agora sempre sem rede).
- **Custo:** um container a mais (1–3 s no Pi 5) nas execuções com `packages` ou `assets`. O
  cache de pacotes do ADR 018 §1 continua em aberto e reduziria o custo; não é decidido aqui.

### 2. Fase `install`

- Comando fixo, montado pelo sandbox (não pela skill nem pelo LLM):
  `uv pip install --no-cache-dir --python /app/.venv/bin/python --target /deps <pacotes>`.
  O parâmetro `setup_commands` (lista livre de comandos) é **substituído** por
  `packages: list[str]`; cada nome é validado contra a gramática de requisito do PEP 508
  (sem URLs diretas, sem `-e`, sem opções iniciadas por `-`). A lista de nomes da stdlib
  filtrada hoje em `skill.py:130` passa para o sandbox.
- Usuário: `user=f"{os.getuid()}:{os.getgid()}"` (o do orquestrador), `HOME=/tmp`,
  `UV_CACHE_DIR=/tmp/uv-cache`. Nenhum `exec_run(..., user='root')`.
- `/deps` é um diretório temporário no host, `SANDBOX_WORK_DIR/<run_id>/deps`, montado `rw`
  na preparação e `ro` na execução; `PYTHONPATH=/deps` na execução.
- Timeout próprio: `SANDBOX_INSTALL_TIMEOUT_SECONDS` (padrão 300).
- **Falha de instalação falha a execução:** `exit_code != 0` ou timeout encerra o run com
  `fase_falha="install"`; a fase `execute` não é iniciada. A mensagem devolvida identifica os
  pacotes e traz o final do log do `uv` (que não contém dados de pesquisa, pois nenhum dado foi
  montado; o filtro de saída de `v18.5-egress-gate` se aplica de qualquer forma).
- Variáveis de ambiente da preparação: lista fechada (`HOME`, `UV_CACHE_DIR`, `PATH`). Nenhuma
  variável do host é repassada, para que código de instalação não leia segredos.

### 3. Fase `fetch_assets`

Declaração (parâmetro novo `assets` da skill):

```json
{"url": "https://…/weights.pt", "sha256": "ab12…" | null, "destino": "weights.pt"}
```

- `destino` é um nome simples (sem `/`, sem `..`); o ativo aparece em `/assets/<destino>`.
- Um script **fixo do projeto** (`src/skills/code/fetch_assets.py`, somente stdlib) é injetado
  pelo host em um diretório de controle (`SANDBOX_WORK_DIR/<run_id>/control`), montado `ro` em
  `/control` na preparação, e executado de lá (revisão A2: com a raiz somente leitura `put_archive`
  só funciona em pontos de montagem). Ele Ele aceita apenas `http`/`https`,
  resolve o nome antes de conectar e recusa loopback, faixas privadas, link-local e
  `169.254.169.254` (mesmas regras do `web_reader`, `v16-in-process-agents` design §4), revalida
  a cada redirecionamento, respeita `SANDBOX_ASSET_MAX_BYTES` e grava em `/staging/<destino>`.
- Terminada a fase, o **host** calcula o sha256 de cada arquivo em
  `SANDBOX_WORK_DIR/<run_id>/staging/`:
  - com `sha256` declarado e diferente do calculado → a execução falha com
    `fase_falha="fetch_assets"` e mensagem com os dois hashes;
  - sem `sha256` declarado → o hash calculado é aceito e registrado com
    `hash_declarado=false` (confiança no primeiro uso, visível no registro e no relatório).
- O arquivo verificado é movido para o cache por conteúdo `SANDBOX_ASSET_CACHE_DIR/<sha256>`
  (padrão `store/assets/`). Com `sha256` declarado e presente no cache, o download é pulado
  (`origem="cache"`) e, se não houver pacotes, nem o container de preparação é criado.
- Timeout próprio: `SANDBOX_FETCH_TIMEOUT_SECONDS` (padrão 600).
- O cache não é limpo automaticamente nesta mudança (ver questões em aberto).

### 4. Fase `execute`

- `network_disabled=True`, exceto no caso do §6.
- Montagens:

  | Caminho no container | Origem no host | Modo |
  |---|---|---|
  | `/outputs` | `outputs/<sessão>/<tarefa>/` (como hoje) | `rw` |
  | `/inputs` | `outputs/<sessão>/input_snapshot/` | `ro` (modo `mount`) |
  | `/deps` | `SANDBOX_WORK_DIR/<run_id>/deps` | `ro` |
  | `/assets/<destino>` | `SANDBOX_ASSET_CACHE_DIR/<sha256>` | `ro` (um arquivo por ativo) |
  | `/prior/<sessão>` | diretórios legíveis de sessões anteriores (`AgentContext.readable_dirs`, `v18-research-continuity`), quando existirem | `ro` |

- **Entrega de dados:** `SANDBOX_INPUT_DELIVERY=mount` (padrão) monta `input_snapshot/` somente
  leitura; `copy` cria `/inputs` como `Mount` tmpfs (tamanho `SANDBOX_COPY_MAX_BYTES`, modo 0555) e copia os
  arquivos por `put_archive`, até
  `SANDBOX_COPY_MAX_BYTES` (acima disso, erro acionável sugerindo `mount`). `copy` serve para
  ambientes em que o caminho do host não é montável (ex.: modo container dos agentes sem
  `HOST_PROJECT_PATH`). A escolha é informada no resultado.
- Toda origem de montagem é resolvida (`Path.resolve`), precisa descender do diretório esperado
  (`outputs/<sessão>`, `SANDBOX_WORK_DIR`, `SANDBOX_ASSET_CACHE_DIR`) e não pode ser symlink.
- Usuário do orquestrador (UID/GID), como na preparação. O `chown`/`chmod 777` de
  `sandbox.py:162-165` e `:276-282` é removido: os arquivos gravados já pertencem ao usuário do
  host.
- Antes do script, uma **introspecção fixa** (código do projeto, sem rede) registra
  `sys.version` e todas as distribuições visíveis (`importlib.metadata`) com versões: imagem e
  `/deps`. É a lista de "pacotes instalados com versões" do ADR 019 §4.
- O digest da imagem vem de `client.images.get(image)`: `id` e `RepoDigests`.
- Timeout do script: `CODE_SANDBOX_TIMEOUT_SECONDS`, como hoje.

### 5. Download não declarado: erro acionável

Se o script termina com `exit_code != 0`, a fase `execute` rodou sem rede e o `stderr` casa
com uma assinatura de falha de rede, o resultado recebe `download_nao_declarado=True` e a skill
devolve ao Developer uma mensagem **fixa**:

> A fase de execução não tem acesso à rede. Se o script precisa baixar pesos, corpora ou
> datasets, declare-os no parâmetro `assets` (url e, se souber, sha256) e leia de
> `/assets/<destino>`. Pacotes Python vão no parâmetro `packages`.

Assinaturas (constante `NETWORK_FAILURE_SIGNATURES` em `sandbox.py`, testada):
`socket.gaierror`, `Temporary failure in name resolution`, `Name or service not known`,
`Network is unreachable`, `urllib.error.URLError`, `requests.exceptions.ConnectionError`,
`Max retries exceeded with url`, `We couldn't connect to 'https://huggingface.co'`,
`LocalEntryNotFoundError`. A mensagem não repete a URL nem trechos do `stderr`.
Para `v17-structural-fact-ingestion` §3, a falha é `causa_falha="abordagem"` com
`assinatura_falha="download_nao_declarado"`.

### 6. Exceção: rede na execução com entradas compartilháveis

A fase `execute` só roda com rede quando **todas** as condições valem:

0. o classificador de insumos **autoriza a rede explicitamente** (`InputClassifier.network_allowed()`),
   verificado antes de todas as outras regras. Sem manifesto, nenhuma execução tem rede, nem a que
   não tem insumos (`all([])` é verdadeiro e não pode valer como autorização; revisão A1);
1. a chamada pede rede explicitamente (parâmetro `needs_network=true` da skill);
2. todo arquivo de `/inputs` está marcado `compartilhavel`, segundo o classificador de
   insumos (`InputClassifier.is_shareable(path) -> bool`);
3. nenhum dado produzido por execução está visível: o diretório `/outputs` da subtarefa não
   contém arquivos além de `script.py` e dos arquivos injetados, e não há montagens `/prior/*`
   (saídas de execuções são dados de pesquisa pelo ADR 019 §3).

O classificador padrão desta mudança responde `False` para tudo; a implementação real vem de
`v18.5-research-data-ingestion` (manifesto `input_context/dados.yaml`). Portanto, **até essa
mudança existir, nenhuma execução tem rede**. Quando a exceção vale, o resultado traz
`rede_na_execucao=True`, o log registra `WARNING` e o relatório lista a execução. Se
`needs_network=true` e as condições falharem, a execução roda sem rede e o resultado explica
qual condição falhou (sem nomes de arquivos de dados).

### 7. Contrato do resultado

```python
@dataclass
class SandboxResult:
    # campos existentes: stdout, stderr, exit_code, artifacts, timed_out
    fase_falha: Literal["install", "fetch_assets", "execute", "infra"] | None = None
    download_nao_declarado: bool = False
    rede_na_execucao: bool = False
    modo_entrega: Literal["mount", "copy"] = "mount"
    entradas_entregues: list[str] = field(default_factory=list)   # caminhos relativos a /inputs
    imagem: ImageInfo | None = None           # nome, id, repo_digests
    python_version: str | None = None
    pacotes_solicitados: list[str] = field(default_factory=list)
    pacotes: dict[str, str] = field(default_factory=dict)          # distribuição -> versão
    ativos: list[AssetRecord] = field(default_factory=list)        # url, sha256, destino, tamanho, hash_declarado, origem
    fases: list[PhaseTiming] = field(default_factory=list)         # nome, inicio, fim, exit_code
```

`fase_falha="infra"` cobre daemon indisponível, imagem ausente e erro de montagem. Esses campos
são lidos por `v18.5-execution-provenance`; esta mudança não grava registro algum.

### 8. Skill de código

- Parâmetros novos: `assets` (lista de objetos do §3) e `needs_network` (booleano, padrão
  `false`). Descrição da ferramenta atualizada: sem rede na execução; dados em `/inputs`;
  ativos em `/assets`.
- `await asyncio.to_thread(self.sandbox.run, ...)` no lugar da chamada síncrona
  (`skill.py:175`).
- O Developer (`agents/developer/agent.py`) passa a ser instruído a ler insumos de
  `/inputs/<nome>` e a declarar ativos em vez de baixá-los no código.

### 9. Configuração (`src/config.py`, `.env.example`)

| Variável | Padrão | Uso |
|---|---|---|
| `SANDBOX_INSTALL_TIMEOUT_SECONDS` | 300 | Timeout da fase `install` |
| `SANDBOX_FETCH_TIMEOUT_SECONDS` | 600 | Timeout da fase `fetch_assets` |
| `SANDBOX_ASSET_MAX_BYTES` | 536870912 | Tamanho máximo por ativo |
| `SANDBOX_ASSET_TOTAL_MAX_BYTES` | 2147483648 | Teto somado dos ativos baixados por execução |
| `SANDBOX_MIN_FREE_BYTES` | 1073741824 | Espaço livre mínimo no disco para iniciar a execução (erro explícito) |
| `SANDBOX_ASSET_CACHE_DIR` | `store/assets` | Cache de ativos por sha256 |
| `SANDBOX_WORK_DIR` | `store/sandbox_work` | Diretórios temporários por execução (`deps`, `staging`), removidos ao fim |
| `SANDBOX_INPUT_DELIVERY` | `mount` | `mount` ou `copy` |
| `SANDBOX_OUTPUT_MAX_BYTES` | 1048576 | Limite de stdout e de stderr do script devolvidos ao orquestrador (cada) |
| `SANDBOX_COPY_MAX_BYTES` | 67108864 | Limite do modo `copy` (o tmpfs conta na memória do container) |

## Análise de impacto (6 eixos)

| Eixo | Impacto |
|---|---|
| Orquestrador & Loop | Sandbox fora do event loop: subtarefas paralelas passam a executar código em paralelo de fato (limitadas pela CPU/RAM do Pi; os limites por container continuam). |
| Agentes & Prompts | Developer lê de `/inputs`, declara `assets`; descrição da skill atualizada. |
| Sandboxes & Containers | Duas fases com rede e sem dados, uma sem rede com dados; usuário não-root; montagens `ro`; fim do `chmod 777`. |
| Persistência | Cache de ativos em `store/assets/`; nenhum schema. |
| Segurança | Fecha o caso "script com dados e internet" (ADR 019 §5). Residual: a fase `install` tem rede sem filtro de destino (ver Riscos). |
| Testes & Telemetria | Tempo por fase na telemetria; testes de rede por fase, montagens, falha de instalação, hash de ativo, erro acionável. |

## Riscos

- **Código de instalação com rede alcança a rede local** (ex.: `setup.py` malicioso de um
  pacote sem wheel). Não tem dados nem segredos, mas pode sondar a LAN. Mitigação futura, para
  o Analista de Segurança: rede Docker dedicada com saída restrita a índices de pacotes, e
  `uv pip install --only-binary :all:` como opção (`SANDBOX_INSTALL_ONLY_BINARY`, não
  implementada aqui).
- **Ativos sem hash declarado** podem mudar entre execuções no mesmo URL. Mitigação: hash
  sempre registrado; `hash_declarado=false` visível no relatório.
- **Assinaturas de falha de rede incompletas**: uma biblioteca com mensagem própria cai no erro
  genérico. Mitigação: lista em constante testada, ampliável.
- **Disco do Pi 5**: cache de ativos cresce sem limite nesta versão.
- **UID do host dentro da imagem**: o UID do orquestrador pode não existir em `/etc/passwd` da
  imagem; `HOME=/tmp` evita as falhas conhecidas. Teste de integração cobre.

## Nota de 2026-10-01: divisão com a v16-sandbox-slim-image

A `v16-sandbox-slim-image` antecipa partes que não dependem do ADR 019: imagem mínima
(`SANDBOX_IMAGE`), usuário do orquestrador sem nenhum `exec_run` como root, instalação em
`/deps` com `packages` validados e falha de instalação fatal, fim do `chmod 777` e da cópia por
`get_archive`, remoção de `HOST_PROJECT_PATH` e desconexão da rede antes do script (ainda no
mesmo container). Ao implementar esta mudança, reaproveitar essas peças e entregar só o que é
próprio da V18.5: containers separados por fase, `fetch_assets`, `/inputs` somente leitura,
exceção para entradas compartilháveis e resultado estruturado. O **cache de pacotes entre
execuções** (ADR 018 §1), que a `v16-sandbox-slim-image` deixou de fora por segurança, cabe no
container de preparação desta mudança (ver questão 4).

## Questões em aberto para o pesquisador

1. A exceção de rede (§6) deve exigir pedido explícito (`needs_network`, como proposto) ou ser
   automática quando as condições valem?
2. Aceitar ativos **sem** sha256 declarado (confiança no primeiro uso, registrada), ou exigir o
   hash sempre?
3. Política de limpeza do cache de ativos (`store/assets/`): manual pelo workflow `clean`,
   limite de tamanho, ou por idade?
4. Cache de pacotes entre execuções no container de preparação (`UV_CACHE_DIR` persistente
   montado só na fase `install`): incluir nesta mudança ou deixar para depois?

## Achados da revisão de segurança (PR #111)

Registro das correções e dos riscos aceitos decorrentes da revisão do Analista de Segurança.

- **A1 (alta) — rede sem insumos:** a exceção do §6 passou a exigir `network_allowed()` do classificador
  antes de qualquer outra regra; sem insumos e com o classificador padrão, a execução roda sem rede.
  *Rede dedicada para a preparação:* avaliada e **não adotada aqui**. Uma rede de containers própria
  não filtra destinos por si só: restringir a saída aos índices de pacotes exige regras de firewall no
  host (iptables/nftables) ou proxy, fora do escopo sem tocar em Dockerfile/compose e sem validação no
  Pi. Fica como risco aceito (ver Riscos) para uma mudança futura.
- **A2 (alta) — `put_archive` com raiz somente leitura:** o daemon só aceita `put_archive` em pontos de
  montagem. `/inputs` (modo `copy`) passou de `HostConfig.Tmpfs` para `Mount(type="tmpfs")`; script e spec
  do fetch passaram para o diretório de controle `/control` (`ro`). O script e a spec do sandbox de
  execução continuam em `/outputs` (bind mount). Limitação: `Mount` tmpfs do SDK não expõe
  `noexec/nosuid/nodev` nem uid/gid; `/inputs` fica com dono root e modo 0555 (somente leitura para o
  usuário do sandbox). **Não validado com container real** (depende da bateria de integração).
- **M1 (média) — disco do Pi:** padrão por ativo reduzido para 512 MiB; teto somado por execução
  (`SANDBOX_ASSET_TOTAL_MAX_BYTES`, 2 GiB, aplicado no script de download); `shutil.disk_usage` checado
  antes de criar a preparação/execução (`SANDBOX_MIN_FREE_BYTES`, falha explícita `sandbox_disk_low`).
  **Risco aceito pendente (5.5.1):** sem cota de disco para os bind mounts `/outputs` e `/deps`; o
  script ainda pode encher o disco durante a execução.
- **M2 (média) — tmpfs e memória:** no modo `copy`, `SANDBOX_COPY_MAX_BYTES + SANDBOX_TMPFS_SIZE` precisa
  ser menor que o limite de memória do container (o tmpfs conta na memória); caso contrário a execução é
  recusada antes de criar o container. Padrão de `SANDBOX_COPY_MAX_BYTES` reduzido para 64 MiB. Com os
  padrões atuais (`/tmp` de 256m e memória de 256m) o modo `copy` exige ajustar um dos limites.
- **M3 (média) — saída do script:** o `exec_run` bufferiza toda a saída na RAM do orquestrador. O script
  passa a rodar por um lançador fixo do projeto (`python -I -c <lançador>`) que limita stdout e stderr a
  `SANDBOX_OUTPUT_MAX_BYTES` (1 MiB) cada, mantendo o início e o fim (o traceback fica no fim) com um
  marcador do trecho omitido, e propaga o código de saída (morte por sinal vira 128+sinal: 137 segue
  indicando OOM). O comportamento do lançador é testado localmente (subprocesso), não só com cliente simulado.
