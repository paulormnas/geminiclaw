# Tarefas: v17-research-project

**Estado (2026-10-08):** Implementada, com pendências — PR #103. Os itens abertos abaixo são validação em ambiente real (AGE/Qdrant/Pi 5, adiada para a bateria final) e débitos documentados.

## 1. Projeto
- [x] 1.1 `src/knowledge/projects.py` (`create_project`, `list_projects`, `get_project`, `get_active_problem`).
- [x] 1.2 CLI `project new|list|show|use` e opção `--project`; projeto padrão persistido.
- [x] 1.3 Criação automática de projeto quando nenhum é informado.
- [x] 1.4 `project_id` no payload da sessão.

## 2. Problema
- [x] 2.1 `draft_problem` no Researcher com schema JSON validado e reparo.
- [x] 2.2 Fluxo de confirmação na CLI (confirmar, editar campo, novo rascunho); `delta_min` obrigatório.
- [x] 2.3 Gravação no grafo com resolução de métrica e domínios; auditoria da confirmação.
- [x] 2.4 Recusa em sessão não interativa sem problema confirmado.
- [x] 2.5 Injeção de `ProjectDetail` no contexto do planejamento.

## 3. Testes
- [x] 3.1 CLI com entrada simulada: confirmar, editar `delta_min`, pedir novo rascunho.
- [x] 3.2 Segunda sessão do projeto não pede confirmação.
- [x] 3.3 Modo `auto` sem TTY e sem problema confirmado é recusado.
- [x] 3.4 Rascunho com JSON inválido é reparado ou falha com mensagem clara.

## 4. Fechamento
- [x] 4.1 Ruff, testes, revisão nos 7 eixos, PR.

## 5. Pendências (adiadas)
- [ ] 5.1 Validar no Pi, com Apache AGE real, as propriedades de mapa (`criterio_sucesso`, `caracteristicas_dados`), `find_nodes` por `projeto_id`/`status` e `project_subgraph` (quando o projeto estiver mais estável).
- [ ] 5.2 `geminiclaw project confirm <id>` para confirmar o problema sem iniciar uma sessão (mudança própria).
