# Roadmap V20 — Federação entre Nós

## Objetivo

Rede pública e plug-and-play de nós do assistente em diferentes instituições, com registros
assinados, validação por reprodução e oportunidades de pesquisa documentadas para decisão
humana (ADR 013).

## Dependências

- V16 a V19 concluídas e **validadas** — decisão do pesquisador: a federação é a última etapa.

## Tarefas

ADR 013 aprovado em 2026-10-01. As questões em aberto do ADR foram distribuídas entre as
mudanças abaixo, cada uma com uma proposta do Arquiteto no `design.md` e as decisões que ainda
cabem ao pesquisador.

| Questão do ADR 013 | Onde é tratada |
|---|---|
| Privacidade e propriedade intelectual | `v20-federated-records` §3 (opt-in por projeto, revisão humana, sem dados brutos) |
| Nós maliciosos | `v20-remote-knowledge-intake` §5 (confiança local, reputação só por reproduções confiáveis); `v20-federation-transport` §4 (taxa por autor) |
| Custo computacional | `v20-reproduction-validation` §2 (limites por reprodução e por dia); `v20-federation-transport` §4 (sincronização fora das sessões) |
| Descoberta de oportunidades | `v20-remote-knowledge-intake` §3–§4 (relevância local, resumo limitado) |
| Governança | `v20-federation-transport` §1, §3 (relays institucionais, lista de partida por PR); `v20-federated-records` (formato versionado no repositório) |
| Variação de hardware | `v20-reproduction-validation` §3 (tolerâncias) |
| Tecnologia | `v20-federation-transport` §1 (relays no modelo Nostr, com spike no Pi 5 e plano B) |

### Tarefa 1: Identidade criptográfica do nó
- **Spec:** [`v20-node-identity`](../openspec/changes/v20-node-identity/proposal.md)
- **Critérios de aceite:** [ ] chave Ed25519 estável e protegida · [ ] sem identidade efêmera · [ ] rotação e revogação assinadas
- **Complexidade estimada:** Média

### Tarefa 2: Registros federados e política de publicação
- **Spec:** [`v20-federated-records`](../openspec/changes/v20-federated-records/proposal.md)
- **Critérios de aceite:** [ ] JSON canônico e `cid` com vetores de teste · [ ] opt-in por projeto · [ ] revisão humana antes de assinar · [ ] sem dados brutos
- **Complexidade estimada:** Alta

### Tarefa 3: Transporte, entrada e sincronização
- **Spec:** [`v20-federation-transport`](../openspec/changes/v20-federation-transport/proposal.md)
- **Critérios de aceite:** [ ] spike no Pi 5 · [ ] só conexões de saída `wss://` · [ ] lista de partida assinada · [ ] sincronização deduplicada com limites
- **Complexidade estimada:** Alta

### Tarefa 4: Entrada de conhecimento remoto
- **Spec:** [`v20-remote-knowledge-intake`](../openspec/changes/v20-remote-knowledge-intake/proposal.md)
- **Critérios de aceite:** [ ] quarentena e validação completa · [ ] resumo limitado · [ ] importação só pelo pesquisador · [ ] texto remoto só como dado
- **Complexidade estimada:** Alta

### Tarefa 5: Validação por reprodução
- **Spec:** [`v20-reproduction-validation`](../openspec/changes/v20-reproduction-validation/proposal.md)
- **Critérios de aceite:** [ ] reprodução só por decisão humana · [ ] sem LLM, no sandbox, sem rede · [ ] tolerâncias · [ ] registro revisado
- **Complexidade estimada:** Média

## Ordem de implementação

```
Tarefa 1 ─► Tarefa 2 ─► Tarefa 3 ─► Tarefa 4 ─► Tarefa 5
```

## Validação da Etapa

- [ ] Todos os testes unitários e de integração passam.
- [ ] Dois nós (Pi 5 e Mac) trocam registros por relays, sem configuração além de `FEDERATION_ENABLED=true`.
- [ ] Uma reprodução real entre os dois nós, publicada e refletida na reputação local.
- [ ] Revisão STRIDE do Analista de Segurança e testes do Pentester concluídos.
- [ ] ADR 013 marcado como Aceito; PRs merged em `dev`; mudanças arquivadas.

## Requisitos já atendidos pelas etapas anteriores (ADR 013 §6)

- IDs estáveis (UUIDv7) e `origem_no` em todo nó — `v17-graph-store`.
- Proveniência obrigatória e auditoria — `v17-graph-store`.
- Embeddings locais versionados; vetores nunca compartilhados — `v16-local-embeddings`.
- `visibilidade` (`privado` por padrão) em todo nó — `v17-graph-store`.
- Oportunidades só avançam com decisão humana — `v18-hypothesis-loop`.
