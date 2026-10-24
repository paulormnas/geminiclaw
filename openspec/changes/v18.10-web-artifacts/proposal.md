# Proposta: Visualizador de Artefatos do Projeto

**ID:** `v18.10-web-artifacts` · **Versão:** V18.10 · **Capacidade:** `web-interface`
**ADRs de origem:** [ADR 027](../../../docs/decisions/adr_027_interface_web.md) §6.3, §6.4; ADR 008 (pasta por sessão); ADR 019 (localidade: os artefatos não saem da máquina por esta mudança)
**Depende de:** `v18.10-web-skeleton`. Paralela a `v18.10-web-dashboard` e `v18.10-web-graph`.

## Por quê

Relatórios, gráficos, CSVs e scripts de cada sessão ficam em `outputs/<sessão>/`, e hoje o pesquisador os abre pelo Finder. A web os mostra por projeto e por sessão, com segurança, porque boa parte foi escrita por LLM ou por código gerado.

## O que muda

- **Novo:** `src/web/routes/artifacts.py` e `src/web/artifact_files.py`: sessões do projeto (pelo grafo, `Sessao-PERTENCE_A->Projeto`), árvore de arquivos da pasta da sessão, conteúdo para pré-visualização e download.
- **Novo:** páginas Artefatos (lista de sessões → árvore → visualizador por tipo).
- **Fora do escopo:** edição, exclusão ou upload de arquivos; busca de texto nos artefatos; arquivos fora de `OUTPUT_BASE_DIR`.

## Impacto

- **Código:** arquivos novos em `src/web/` e `frontend/`; reutiliza `resolve_session_dir` (`src/session/continuity.py`).
- **Schema:** nenhum. Só leitura do grafo e do sistema de arquivos.
- **Dependência nova (frontend):** `react-markdown` (sem `rehype-raw`).

## Aprovações necessárias

- **Dependência nova:** `react-markdown` no frontend.
