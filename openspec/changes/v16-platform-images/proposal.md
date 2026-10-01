# Proposta: Identificação de Plataforma e Seleção de Imagens

**ID:** `v16-platform-images` · **Versão:** V16 (complemento) · **Capacidade:** `platform-images`
**ADRs de origem:** [ADR 018](../../../docs/decisions/adr_018_imagem_sandbox_enxuta_e_imagens_por_plataforma.md)
§5 (script de plataforma e seleção de imagens) e §4 (precedente do Qdrant: validar a imagem
na plataforma, inclusive o tamanho de página do Pi 5); "Alternativas a considerar"
(utilitário Python em vez de shell)
**Depende de:** `v16-sandbox-slim-image` (a imagem do sandbox que este utilitário constrói)

## Por quê

Não existe uma forma única de saber em que plataforma o projeto roda (macOS/ARM64 em
desenvolvimento, Raspberry Pi 5/ARM64, Linux/x86_64) nem de obter as imagens certas para ela:

- `scripts/build_images.sh` constrói só o sandbox, em shell, e mostra o resultado com `grep`.
- O Dockerfile do sandbox fixa `--platform=linux/arm64`, o que força emulação em x86_64.
- As imagens de infraestrutura (Postgres/AGE, Qdrant, Ollama) são resolvidas pelo compose sem
  nenhuma verificação de arquitetura; o caso do Qdrant mostrou que "existe imagem ARM64" não
  basta: a imagem precisa funcionar com o kernel de páginas de 16K do Pi 5 (ADR 018 §4).
- `src/platform_utils.py` só decidia TCP/Unix para o IPC, que foi removido (ADR 014); hoje não
  tem uso.

## O que muda

- **Novo:** `containers/images.yaml`, manifesto das imagens do projeto: nome lógico, forma de
  obtenção (`pull` de referência fixa ou `build` de um Dockerfile), arquiteturas suportadas e
  plataformas em que já foi validada.
- **Novo:** utilitário Python `scripts/platform_images.py`
  (`uv run python -m scripts.platform_images <detect|plan|ensure>`): detecta a plataforma do
  host e do daemon Docker, planeja o que baixar ou construir e executa o plano, conferindo a
  arquitetura de cada imagem obtida.
- **Novo:** registro do resultado em `store/platform.json` (plataforma, imagens com digest),
  lido pelo orquestrador para conferir a imagem do sandbox no início da sessão e disponível
  para a proveniência das execuções (`v18.5-execution-provenance`).
- **Novo:** verificação no início da sessão: imagem do sandbox ausente ou de arquitetura
  diferente da do daemon → erro acionável, com o comando a executar.
- **Removido:** `scripts/build_images.sh` e `src/platform_utils.py` (sem uso).
- **Fora do escopo:** publicação de imagens num registro (não há registro do projeto; ver
  questão em aberto 2); troca da imagem do Postgres (ADR 016, ainda Proposto); alterar o
  `docker-compose.yml` (as imagens de infraestrutura atuais já são multiarquitetura).

## Impacto

- **Código:** `containers/images.yaml` (novo), `scripts/platform_images.py` (novo),
  `src/platform_info.py` (novo, detecção reutilizável e leitura de `store/platform.json`),
  `src/orchestrator.py` ou `src/infrastructure.py` (verificação no início),
  `scripts/build_images.sh` e `src/platform_utils.py` (removidos), `AGENTS.md` §6 e `SETUP.md`
  (comando de construção), `.agents/workflows/run_project.md`.
- **Comportamento:** sem mudança para quem já tem a imagem correta; quem não tem recebe a
  instrução no início da sessão em vez de um erro do Docker no meio da execução.
- **Dependências:** nenhuma nova (`docker` e `pyyaml` já usados; `pyyaml` direta pela
  `v16-model-catalog-router`).

## Aprovações necessárias

1. **Remoção de arquivos:** `scripts/build_images.sh` e `src/platform_utils.py`.
2. **Alteração do `AGENTS.md`** §6 ("Construir a imagem do sandbox de código"): troca do comando.
3. Nenhuma alteração de Dockerfile base, `docker-compose.yml` ou schema de banco.
