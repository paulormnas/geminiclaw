# Roadmap V18.10 — Interface Web do Pesquisador

## Objetivo
Interface web local (SPA em TypeScript servida por FastAPI no Mac, só loopback/Tailscale, autenticada) com CRUD de projetos, painel, artefatos, grafo e conversa com o sistema. Origem: [ADR 027](../docs/decisions/adr_027_interface_web.md). Trilha 2, em paralelo aos experimentos E0–E3 no Pi (trilha 1).

## Dependências
- ADR 023 implementado (sessão em processo próprio, `session_events`, gate persistente, caixa de entrada).
- ADR 024 (camadas): `cli | web` no topo.
- A trilha web só lê o grafo e não altera o esquema; mudança de esquema da trilha 1 avisa esta trilha.

## Tarefas

### Tarefa 1: Esqueleto (autenticação, estáticos, CRUD de projetos)
- **Spec:** [`v18.10-web-skeleton`](../openspec/changes/v18.10-web-skeleton/proposal.md)
- **Critérios de aceite:** [ ] só loopback · [ ] login argon2id, cookie `HttpOnly`/`Strict`, CSRF, `Host`/`Origin`, bloqueio · [ ] CSP e erros sem detalhe · [ ] CRUD sem exclusão física · [ ] frontend com tokens, tema, teclado, cobertura ≥ 70%
- **Complexidade estimada:** Alta

### Tarefa 2: Painel
- **Spec:** [`v18.10-web-dashboard`](../openspec/changes/v18.10-web-dashboard/proposal.md)
- **Critérios de aceite:** [ ] contagens por rótulo e estado, com zeros · [ ] custo sem registro explícito · [ ] só leitura
- **Complexidade estimada:** Média

### Tarefa 3: Artefatos
- **Spec:** [`v18.10-web-artifacts`](../openspec/changes/v18.10-web-artifacts/proposal.md)
- **Critérios de aceite:** [ ] caminho confinado, sem links simbólicos · [ ] HTML/SVG isolados · [ ] Markdown sem HTML · [ ] limites
- **Complexidade estimada:** Média

### Tarefa 4: Grafo
- **Spec:** [`v18.10-web-graph`](../openspec/changes/v18.10-web-graph/proposal.md)
- **Critérios de aceite:** [ ] filtros validados pelo esquema · [ ] limite com `omitidos` · [ ] lista acessível sincronizada · [ ] só leitura
- **Complexidade estimada:** Média

### Tarefa 6: Configurações do pesquisador
- **Spec:** [`v18.10-web-settings`](../openspec/changes/v18.10-web-settings/proposal.md)
- **Critérios de aceite:** [ ] lista fechada · [ ] chaves nunca voltam ao navegador · [ ] senha para salvar · [ ] vale para a próxima pesquisa
- **Complexidade estimada:** Média

### Tarefa 7: Containers web e lançador no host
- **Spec:** [`v18.10-web-containers`](../openspec/changes/v18.10-web-containers/proposal.md)
- **Critérios de aceite:** [ ] `scripts/up.sh` sobe tudo · [ ] container da web sem root, sem socket do Docker, porta só em loopback · [ ] build do frontend reprodutível · [ ] lançador inicia sessão como o REPL · [ ] fila de início aprovada (schema)
- **Complexidade estimada:** Alta

### Tarefa 5: Conversa
- **Spec:** [`v18.10-web-chat`](../openspec/changes/v18.10-web-chat/proposal.md)
- **Critérios de aceite:** [ ] consulta só leitura em processo filho · [ ] nova pesquisa com as confirmações do REPL · [ ] SSE sem perda · [ ] gate respondido pela web com senha nas decisões reservadas e `canal: web` · [ ] Problema definido pela web · [ ] comandos a qualquer momento · [ ] `assisted` só no REPL
- **Complexidade estimada:** Alta

## Ordem de implementação
1. Tarefa 1.
2. Tarefas 2, 3, 4 e 6 em paralelo (subagentes em worktrees próprias; conflito esperado só no OpenAPI e no `routes.tsx`, resolvido no merge, um PR por vez).
3. Tarefa 7 (spec escrita e aprovada antes).
4. Tarefa 5.

## Validação da Etapa
- [ ] Testes do backend (`unit or integration`) e do frontend passam.
- [ ] Validação manual no Mac com o `geminiclaw_bench` (leitura) e o `geminiclaw` (escrita).
- [ ] Pareceres do Analista de Segurança (esqueleto, artefatos, configurações, conversa).
- [ ] Design system (`docs/design-system/README.md`) seguido; página `/_design` com todos os estados.
- [ ] ADR 027 Aceito; PRs mergeados em `dev`; mudanças arquivadas.
