# Tarefas: v16-sandbox-slim-image

## 0. Pré-requisitos
- [x] 0.1 Aprovação explícita do pesquisador: novo Dockerfile do sandbox, remoção de `containers/Dockerfile`, ajuste de texto dos ADRs 014 §2 e 003 §2, respostas às questões em aberto do design §8.
- [ ] 0.2 Liberar espaço em disco antes de construir imagens (o hook local bloqueia comandos de Docker com menos de 10 GB livres).

## 1. Imagem
- [x] 1.1 `containers/sandbox/requirements.in` com o conjunto básico aprovado; gerar `requirements.lock` com `uv pip compile --generate-hashes`.
- [x] 1.2 `containers/sandbox/Dockerfile` (design §1), com tag fixa do `uv` e sem `--platform`.
- [x] 1.3 Remover `containers/Dockerfile`; apontar `scripts/build_images.sh` para a nova imagem e a tag `SANDBOX_IMAGE`.
- [ ] 1.4 Medir o tamanho da imagem no Pi 5 e registrar no PR.

## 2. Sandbox
- [x] 2.1 `SANDBOX_IMAGE` e demais variáveis do design §4 em `src/config.py`; `CodeSkill` lê de `config`.
- [x] 2.2 Criação do container com usuário do host, `cap_drop`, `no-new-privileges`, `pids_limit`, `read_only` e `tmpfs`.
- [x] 2.3 `packages: list[str]` no lugar de `setup_commands`; validação PEP 508; filtro da stdlib e do conjunto básico.
- [x] 2.4 Instalação em `/deps` com comando fixo; falha e timeout encerram a execução (`install_failed`); `packages_installed`.
- [x] 2.5 Desconexão de rede verificada antes do script (fail-closed).
- [x] 2.6 Remover `chmod 777`, `chown` por root, permissões `0o777`/`0o666`, extração por `get_archive` e `HOST_PROJECT_PATH`.
- [x] 2.7 Erro acionável para imagem ausente (sem `pull`).
- [x] 2.8 Instrução do Developer (`agents/developer/agent.py`): conjunto básico disponível; o resto em `packages`.

## 3. Testes
- [x] 3.1 Unitários com cliente Docker simulado: parâmetros de criação, nenhum `user="root"`, requisito inválido, conjunto básico sem instalação, ordem desconexão → script, falha de desconexão, sem `get_archive`, imagem configurável, imagem ausente.
- [ ] 3.2 Integração (Mac e Pi 5): conteúdo da imagem; escrita fora das áreas permitidas; pacote inexistente; pacote real instalado e registrado; socket para fora falha no script; dono e modo dos artefatos; symlink que escapa. _(escrito em `tests/integration/test_sandbox_slim_image.py`; execução pendente no Mac e no Pi 5, pula sem imagem)_
- [x] 3.3 Ajustar `tests/unit/skills/test_sandbox.py` e `test_sandbox_archive.py` ao novo contrato.

## 4. Fechamento
- [x] 4.1 Nota na `openspec/changes/v18.5-sandbox-phases/design.md` sobre o que esta mudança já entregou (feita no PR de specs; conferir ao implementar).
- [x] 4.2 `.env.example`: novas variáveis; remover `HOST_PROJECT_PATH`.
- [ ] 4.3 `uv run ruff check .`; `uv run pytest -m "unit or integration" -v`.
- [ ] 4.4 Benchmark de referência (`run.sh`) no Pi 5 completo com a nova imagem.
- [ ] 4.5 Revisão do Analista de Segurança (design §6); revisão nos 7 eixos; PR para `dev`.

## 5. Correções da revisão de segurança (PR #99)
- [x] 5.1 B1 `.gitignore` restaurado (`*.pem` e `store/sandbox_work/` em linhas separadas).
- [x] 5.2 I1 a I7 corrigidos, com testes (desconexão antes da listagem, `python -I` e workdir `/tmp`; `--no-config` e `UV_NO_CONFIG`; `--only-binary :all:`; script injetado depois da desconexão; recusa de UID 0; kill antes da varredura; validação de `session_id`/`task_name`).
- [x] 5.3 Sugestões: `tmpfs` com `noexec,nosuid,nodev`, `memswap_limit`, teto em `packages`, remoção de FIFOs.
- [ ] 5.4 Validação real no Pi 5 e no Mac das correções acima (container e imagem reais): em particular, que o `uv` instala de `/tmp` com `noexec` e que `put_archive` funciona depois da desconexão. Motivo: sem imagem nem daemon neste ambiente.
- [ ] 5.5 Lock multi-arquitetura e digests das imagens base: movidos para `v16-platform-images` (5.5.1, 5.5.2). Cota de disco e FIFO real: `v18.5-sandbox-phases` (5.5.1, 5.5.2).
