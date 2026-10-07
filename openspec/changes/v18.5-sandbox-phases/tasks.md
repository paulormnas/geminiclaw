# Tarefas: v18.5-sandbox-phases

## 0. Pré-requisitos
- [x] 0.1 **Aprovação explícita do pesquisador** para as mudanças de comportamento dos containers do sandbox (proposal, "Aprovações necessárias").
- [ ] 0.2 **Revisão do Analista de Segurança** do design (rede da preparação, montagens, usuário não-root).
- [x] 0.3 Worktree `.worktrees/feat-v185-sandbox-phases` (branch `feat/v185-sandbox-phases`).

## 1. Configuração e contratos
- [x] 1.1 Variáveis do design §9 em `src/config.py` e `.env.example`.
- [x] 1.2 `SandboxResult` estendido (`ImageInfo`, `AssetRecord`, `PhaseTiming`); `AssetSpec` e validação de `destino`.
- [x] 1.3 Validação de requisitos de pacote (PEP 508, sem URL, sem opções); `setup_commands` substituído por `packages`.
- [x] 1.4 Protocolo `InputClassifier` com implementação padrão que responde `False`.

## 2. Preparação
- [x] 2.1 `src/skills/code/fetch_assets.py` (somente stdlib): http/https, bloqueio de IPs internos com revalidação em redirecionamentos, limite de tamanho.
- [x] 2.2 `src/skills/code/assets.py`: hash no host, comparação com o declarado, cache por sha256, `origem`.
- [x] 2.3 Container de preparação: montagens `deps`/`staging`, UID/GID do host, ambiente fechado; ordem `fetch_assets` → verificação no host → `install`; timeouts por fase.
- [x] 2.4 Falha de `install` ou `fetch_assets` encerra o run sem criar o container de execução.

## 3. Execução
- [x] 3.1 Container de execução com `network_disabled=True`; montagens `/outputs` (rw), `/inputs`, `/deps`, `/assets/*`, `/prior/*` (ro), com resolução e recusa de symlinks.
- [x] 3.2 Modo `copy` por `put_archive` com `SANDBOX_COPY_MAX_BYTES`.
- [x] 3.3 Introspecção fixa (versão do Python e distribuições) e digest da imagem.
- [x] 3.4 Remover `user='root'`, `chown -R` e `chmod 777` (`sandbox.py:162-165`, `:276-282`).
- [x] 3.5 `NETWORK_FAILURE_SIGNATURES` e `download_nao_declarado`.
- [x] 3.6 Exceção de rede do design §6.
- [x] 3.7 Limpeza de `SANDBOX_WORK_DIR/<run_id>` em qualquer desfecho.

## 4. Skill e prompts
- [x] 4.1 Parâmetros `assets` e `needs_network`; descrição atualizada.
- [x] 4.2 `asyncio.to_thread` na chamada do sandbox (`skill.py:175`).
- [x] 4.3 Mensagem fixa de download não declarado; mensagem de falha de instalação.
- [x] 4.4 Instrução do Developer: ler de `/inputs`, declarar `assets`, sem downloads no código.

## 5. Testes
- [x] 5.1 Unit: validação de pacotes, `destino`, URLs bloqueadas, assinaturas de rede, condições da exceção de rede (com classificador falso e verdadeiro).
- [x] 5.2 Unit: argumentos passados ao cliente Docker por fase (rede, montagens, usuário, ambiente) com cliente simulado.
- [ ] 5.3 Integration: script sem rede não resolve DNS; com `packages` o script continua sem rede. _(escrito em `tests/integration/test_sandbox_phases.py`; não executado: bateria de integração ao final)_
- [ ] 5.4 Integration: pacote inexistente → `fase_falha="install"`, script não roda. _(escrito em `tests/integration/test_sandbox_phases.py`; não executado: bateria de integração ao final)_
- [ ] 5.5 Integration: hash divergente; ativo sem hash; ativo em cache sem container de preparação (servidor HTTP local de teste liberado apenas no teste, via lista de permissão injetada). _(escrito em `tests/integration/test_sandbox_phases.py`; não executado: bateria de integração ao final)_
- [ ] 5.6 Integration: `/inputs` somente leitura; modo `copy`; symlink recusado. _(escrito em `tests/integration/test_sandbox_phases.py`; não executado: bateria de integração ao final)_
- [ ] 5.7 Integration: arquivos em `/outputs` pertencem ao UID do host, sem `chmod 777`. _(escrito em `tests/integration/test_sandbox_phases.py`; não executado: bateria de integração ao final)_
- [ ] 5.8 Integration: duas execuções paralelas levam menos que a soma. _(escrito em `tests/integration/test_sandbox_phases.py`; não executado: bateria de integração ao final)_
- [x] 5.9 Atualizar `tests/unit/skills/test_sandbox.py`, `tests/unit/skills/test_sandbox_archive.py`, `tests/skills/test_code_skill.py` e `tests/integration/test_sandbox_volume.py` para o novo contrato.

## 5.5 Pendências herdadas da revisão de segurança do PR #99 (v16-sandbox-slim-image)
- [ ] 5.5.1 Cota de disco para os bind mounts `/outputs` e `/deps` (hoje só o `/tmp` em `tmpfs` tem limite; um script ou instalação pode encher o disco do Pi). Motivo: depende de decisão do mecanismo (quota de sistema de arquivos, `ulimit fsize` ou monitor) e de validação no Pi.
- [ ] 5.5.2 Teste de integração real de FIFO/arquivo especial criado em `/outputs` (a varredura `_purge_special_files` só tem teste unitário no host). Motivo: precisa de container e imagem reais. _(escrito em `tests/integration/test_sandbox_phases.py`; não executado: bateria de integração ao final)_
- [x] 5.5.3 Fechar o residual de instalação com rede vendo `/outputs` (containers separados por fase) e documentar que `/deps` sombreia versões do lock com hash (`PYTHONPATH=/deps` precede o venv).

## 6. Fechamento
- [ ] 6.1 Medição no Pi 5: tempo por fase com e sem pacotes (registrar no PR).
- [ ] 6.2 Ruff, `uv run pytest -m "unit or integration"`.
- [ ] 6.3 Revisão nos 7 eixos, PR para `dev`.
