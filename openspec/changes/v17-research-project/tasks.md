# Tarefas: v17-research-project

## 1. Projeto
- [ ] 1.1 `src/knowledge/projects.py` (`create_project`, `list_projects`, `get_project`, `get_active_problem`).
- [ ] 1.2 CLI `project new|list|show|use` e opção `--project`; projeto padrão persistido.
- [ ] 1.3 Criação automática de projeto quando nenhum é informado.
- [ ] 1.4 `project_id` no payload da sessão.

## 2. Problema
- [ ] 2.1 `draft_problem` no Researcher com schema JSON validado e reparo.
- [ ] 2.2 Fluxo de confirmação na CLI (confirmar, editar campo, novo rascunho); `delta_min` obrigatório.
- [ ] 2.3 Gravação no grafo com resolução de métrica e domínios; auditoria da confirmação.
- [ ] 2.4 Recusa em sessão não interativa sem problema confirmado.
- [ ] 2.5 Injeção de `ProjectDetail` no contexto do planejamento.

## 3. Testes
- [ ] 3.1 CLI com entrada simulada: confirmar, editar `delta_min`, pedir novo rascunho.
- [ ] 3.2 Segunda sessão do projeto não pede confirmação.
- [ ] 3.3 Modo `auto` sem TTY e sem problema confirmado é recusado.
- [ ] 3.4 Rascunho com JSON inválido é reparado ou falha com mensagem clara.

## 4. Fechamento
- [ ] 4.1 Ruff, testes, revisão nos 7 eixos, PR.
