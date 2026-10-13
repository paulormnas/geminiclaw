# Tarefas: v16-platform-images

**Estado (2026-10-13):** Mergeada em `dev` (#123). Pendentes: 5.5.1 e 5.5.2
(alteram o `containers/sandbox/Dockerfile` e exigem rede/registro e decisão sobre lock por plataforma e política de
digests: ficam para aprovação do pesquisador), 6.6 (integração no Mac e no Pi 5) e a revisão nos 7 eixos. Desvios:
(a) o item `SETUP.md` não existe no repositório, então `scripts/setup_pi.sh` e o `README.md` chamam o utilitário;
(b) a lógica vive em `src/platform_images.py` (reuso pela checagem de sessão) e `scripts/platform_images.py` é a CLI;
(c) só um comentário do `containers/sandbox/Dockerfile` mudou (cita o novo utilitário).
Questões em aberto do design §7 resolvidas pela proposta: utilitário explícito, sem publicar imagens, registro em
`store/platform.json`.

## 0. Pré-requisitos
- [x] 0.1 `v16-sandbox-slim-image` concluída (Dockerfile do sandbox em `containers/sandbox/`).
- [x] 0.2 Aprovação do pesquisador: remoção de `scripts/build_images.sh` e `src/platform_utils.py`, alteração do `AGENTS.md` §6, respostas às questões em aberto do design §7.

## 1. Detecção
- [x] 1.1 `src/platform_info.py`: `PlatformInfo`, normalização de arquitetura, Pi 5 por `device-tree`, tamanho de página, `id`; funções puras com fontes injetáveis.

## 2. Manifesto e plano
- [x] 2.1 `containers/images.yaml` com `sandbox`, `postgres`, `qdrant`, `ollama` (opcional) e `validada_em` conhecido (Pi 5 para Postgres e Qdrant).
- [x] 2.2 Validação estrita do manifesto.
- [x] 2.3 Plano (`ok`, `pull`, `build`, `sem_suporte`, aviso `nao_validada`) sem efeitos.

## 3. Utilitário
- [x] 3.1 `scripts/platform_images.py` com `detect`, `plan`, `ensure` (`--yes`, `--imagens`, `--com-ollama`, `--json`, `--estrito`).
- [x] 3.2 `pull`/`build` com `platform=linux/<arch do daemon>`; conferência da arquitetura; `store/platform.json`.
- [x] 3.3 `scripts/setup_pi.sh` e `SETUP.md` passam a chamar o utilitário.

## 4. Sessão
- [x] 4.1 Checagem da imagem do sandbox no início da sessão (erro acionável; `WARNING` de não validada).

## 5. Remoções e documentação
- [x] 5.1 Remover `scripts/build_images.sh` e `src/platform_utils.py` (com aprovação).
- [x] 5.2 Atualizar `AGENTS.md` §6, `.agents/workflows/run_project.md` e `README.md` onde citam `build_images.sh`.

## 5.5 Pendências herdadas da revisão de segurança do PR #99 (v16-sandbox-slim-image)
- [ ] 5.5.1 Gerar `containers/sandbox/requirements.lock` multi-arquitetura (hoje só `aarch64-unknown-linux-gnu`; em `amd64` o `--require-hashes` falha). Motivo: precisa de decisão sobre uma lock por plataforma ou universal e de rede para compilar/validar em cada arquitetura.
- [ ] 5.5.2 Fixar por digest (`@sha256`) as imagens base `python:3.11-slim-bookworm` e `ghcr.io/astral-sh/uv:0.8.9` no `containers/sandbox/Dockerfile`. Motivo: exige rede para o registro e política de atualização dos digests (por plataforma).

## 6. Testes
- [x] 6.1 Detecção: Pi 5, macOS com Docker Desktop, Linux x86_64.
- [x] 6.2 Manifesto do repositório válido; chave desconhecida.
- [x] 6.3 Plano: `ok`, arquitetura divergente → `build`, `nao_validada` sem efeitos.
- [x] 6.4 `ensure` com cliente simulado: build nativo, arquitetura divergente após `pull`, sem suporte.
- [x] 6.5 Início de sessão: imagem ausente, plataforma não validada.
- [x] 6.6 Integração: `ensure --imagens sandbox --yes` no Pi 5 (2026-10-12: build nativo `linux/arm64` em 60 s, 539 MB, `store/platform.json` gravado; 27 testes de integração do sandbox passaram). *Mac: não executado.* Achado: o cliente Python do daemon não aplica o `.dockerignore` e enviou 6 GB de contexto; o manifesto ganhou `contexto`. O modo de entrega `copy` do sandbox falha no Pi (ver `v18.5-sandbox-phases`).

## 7. Fechamento
- [x] 7.1 `uv run ruff check .`; `uv run pytest -m "unit or integration" -v`.
- [ ] 7.2 Revisão nos 7 eixos; PR para `dev`; ADR 018 → Aceito quando esta mudança e a `v16-sandbox-slim-image` estiverem no `dev`.
