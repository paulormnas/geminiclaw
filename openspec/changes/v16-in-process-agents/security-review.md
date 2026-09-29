# Revisão de Segurança (STRIDE): Ferramentas no Host do Runtime em Processo

**Mudança:** `v16-in-process-agents` · **Tarefa:** 6.1 · **Papel:** Analista de Segurança
(`.agents/rules/security-analyst.md`) · **Data:** 2026-09-29 · **Base revisada:** `dev` em `617b7cc`

## 1. Escopo e método

Com o ADR 014, os agentes deixam de rodar em containers e passam a executar no processo do
orquestrador, com as permissões do usuário do host. Esta revisão avalia **as ferramentas que os
agentes chamam no host** (fronteira de confiança nova) e o caminho pelo qual o **sandbox devolve
artefatos ao host**. Postura: toda saída de LLM, todo conteúdo web e todo artefato gerado no sandbox
é tratado como hostil.

Método: leitura do código das ferramentas, STRIDE por componente e verificação experimental dos
achados (marcada como *verificado* abaixo). As correções dos achados F1 a F4 foram implementadas
neste mesmo PR, com testes.

**Não avaliado** (fora do que foi lido): vazamento de segredos em logs e telemetria, política de
privilégios das roles do PostgreSQL, terminal/ANSI na skill `human_feedback`, o caminho legado
`AGENT_RUNTIME=container` (será removido na fase 2) e a qualidade dos prompts contra injeção.

## 2. Superfície de ferramentas no host

| Ferramenta | Origem | Recebe do LLM | Toca |
|---|---|---|---|
| `write_artifact` | `agents/base/tools.py` | nome e conteúdo | escrita em `outputs/<sessão>/artifacts/` |
| `manage_memory` / `memory` | `src/skills/memory/` | chave, valor, tags | PostgreSQL (consultas parametrizadas) |
| `web_reader` | `src/skills/web_reader/` | URL | rede (guard de SSRF) |
| `search_quick` | `src/skills/search_quick/` | consulta | rede (endpoints fixos do DuckDuckGo/Brave) |
| `deep_search` | `src/skills/search_deep/` | consulta e filtro de domínio | apenas o índice Qdrant (o crawler é CLI do operador) |
| `code` | `src/skills/code/` | código e pacotes | sandbox em container; devolve artefatos ao host |
| `document_processor` | `src/skills/document_processor/` | `file_path` | leitura de arquivo e indexação (hoje **não registrada**, ver F4b) |
| `human_feedback` | `src/skills/human_feedback/` | pergunta | terminal do pesquisador |

Nenhuma ferramenta aceita comando de shell, SQL ou Cypher arbitrário. A única que executa código é
a `code`, e ela delega ao sandbox (requisito da spec atendido).

## 3. Achados

| ID | Severidade | STRIDE | Achado | Estado |
|---|---|---|---|---|
| F1 | Alta | I, E | Guard de SSRF do `web_reader` era lista de bloqueio e **deixava passar a faixa CGNAT `100.64.0.0/10`** (Tailscale). *Verificado* no Python 3.11.2 do Pi: `100.110.171.110` (IP Tailscale do próprio Pi) não era bloqueado. O Qdrant está publicado em `0.0.0.0:6333` sem autenticação, então um `web_reader` induzido por injeção de prompt lia coleções do Qdrant por esse IP. | **Corrigido** (`is_global`) |
| F2 | Alta | D | `CodeSkill.run` chamava o sandbox síncrono **dentro da corrotina**, congelando o event loop do processo (todos os agentes, timeouts e Ctrl+C). Além disso, a instalação de pacotes (`uv pip install`, com rede) **não tinha timeout**: um mirror travado congelava o orquestrador indefinidamente. | **Corrigido** (`asyncio.to_thread` + `CODE_SANDBOX_SETUP_TIMEOUT_SECONDS`) |
| F3 | Média | T, E, I | O tar devolvido pelo container era extraído sem filtro e o host executava `os.chmod` seguindo symlinks: código no sandbox criava um symlink para um arquivo do host e o fazia virar `0666` (*verificado* com experimento: `600` → `666` no alvo fora da sessão). Além disso, o `/outputs` é um **bind mount de escrita**, então os symlinks criados no container aparecem direto na pasta do host e ficavam ali para qualquer leitor do host seguir (*verificado* no sandbox real do Pi). | **Corrigido** (filtro de membros do tar; `chmod` ignora symlinks; varredura pós-execução remove symlinks que apontam para fora da pasta da tarefa) |
| F4 | Alta (latente) | I | `document_processor.ingest` aceitava **qualquer caminho** vindo do LLM (`os.path.exists` apenas): leitura de `.env`, chaves privadas, `/etc/*` e indexação do conteúdo. | **Mitigado** (confinado a `input_snapshot/` e `artifacts/` da sessão, com symlinks resolvidos) |
| F4b | Média | (funcional) | `DocumentProcessorSkill` não implementa `run` (abstrato em `BaseSkill`): a instanciação falha e `_safe_register` só loga. **A skill nunca é registrada**, mesmo com `SKILL_DOCUMENT_PROCESSOR_ENABLED=true`. Por isso F4 é latente. | Pendente (fora do escopo; a skill precisa ser concluída antes de ser habilitada) |
| F5 | Média | I, T | Qdrant publicado em `0.0.0.0:6333/6334` sem autenticação; PostgreSQL com senha padrão `geminiclaw_secret` no compose quando `POSTGRES_PASSWORD` não é definida. | Pendente, decisão do pesquisador (ver ADR 018) |
| F6 | Alta | E, I | Sandbox executa como **root**, com **rede ligada durante a execução do script** sempre que há `packages` (mesmo container da instalação) e `/outputs` montado em modo `rw`. | Pendente, já registrado no ADR 018 (tratamento após a onda 2) |
| F7 | Média | T | Injeção de prompt indireta: conteúdo web lido por `web_reader` pode induzir `manage_memory` a gravar memória de **longo prazo persistente**, envenenando sessões futuras; `packages` aceita qualquer nome de pacote. | Pendente (recomendações na seção 5) |
| F8 | Baixa | I | O guard de SSRF **falha aberto** quando o DNS não resolve (documentado; evita falso positivo em CI). A requisição seguinte falha do mesmo modo, mas não há novo bloqueio. | Risco aceito |
| F9 | Baixa | I | `DomainCrawler` usa `follow_redirects=True` sem o guard. Só roda no CLI `indexer_cli` com domínios do operador (`DEEP_SEARCH_DOMAINS`); não é ferramenta de agente. | Pendente (baixo) |
| F10 | Info | I | `write_artifact` devolve ao LLM o caminho absoluto do host. | Risco aceito |
| F11 | Info | E | Os `forbidden_patterns` da `CodeSkill` são contornáveis (`__import__('subprocess')`). Não são fronteira de segurança; a fronteira é o sandbox. | Registrado |

### Pontos verificados sem achado

- `write_artifact`: nome normalizado ao último componente, abertura com `O_NOFOLLOW` (sem janela de
  TOCTOU) e testes de `../`, caminho absoluto e symlink.
- `web_reader`: resolve o host uma vez, fixa o IP na conexão, revalida a cada redirecionamento e
  limita o número de saltos (sem janela de *DNS rebinding*).
- `memory`: consultas SQL parametrizadas; o único `f-string` monta placeholders `%s`.
- `deep_search`: o parâmetro `domain` é só valor de filtro no índice, nunca abre conexão.

## 4. Matriz ameaça, risco e mitigação

| Ameaça | Risco | Mitigação |
|---|---|---|
| **S** Agente forja identidade de outro | `AgentContext` é vinculado por tarefa (`contextvars`); sem IPC no modo em processo | Nenhuma ação necessária |
| **T** Sandbox altera arquivos fora da tarefa | F3 | Filtro do tar, `chmod` sem seguir links; pendente: F6 (usuário não-root e escopo do mount) |
| **R** Falta de auditoria por agente | Não avaliado | Revisar na fase 2 (telemetria direta) |
| **I** Leitura de rede interna ou arquivos do host | F1, F4, F5 | `is_global`; confinamento de `ingest`; publicar portas em `127.0.0.1` |
| **D** Bloqueio do processo | F2 | Thread para o sandbox; timeout de setup |
| **E** Escalada a partir do sandbox | F6 | ADR 018: usuário não-root, rede separada da execução |

## 5. Recomendações abertas

1. **F5:** publicar Qdrant e Postgres apenas em `127.0.0.1` no compose e exigir `POSTGRES_PASSWORD`
   sem valor padrão. Depende de o pesquisador acessar o Qdrant de outra máquina.
2. **F6:** tratar no ADR 018 (usuário não-root, instalação com rede e execução sem rede, `/outputs`
   restrito ao diretório da sessão).
3. **F7:** marcar a origem (`source`) de toda memória de longo prazo e tratar o `recall` como conteúdo
   não confiável no prompt; avaliar lista de permissão de pacotes ou índice de pacotes espelhado.
4. **F4b:** concluir a `DocumentProcessorSkill` (`run` retornando `SkillResult`) antes de habilitá-la;
   o confinamento já está pronto.
5. **F9:** aplicar `guarded_get` ao crawler quando ele deixar de ser apenas um CLI do operador.

## 6. Checklist de hardening do sandbox

- [x] Código gerado nunca executa no host (a `code` delega ao sandbox)
- [x] Timeout da execução do script
- [x] Timeout da instalação de pacotes (F2)
- [x] Sandbox fora do event loop (F2)
- [x] Retorno de artefatos filtrado, sem seguir links, e symlinks para fora removidos da pasta da tarefa (F3)
- [x] Limites de memória e CPU do container
- [ ] Usuário não-root (F6)
- [ ] Rede desligada durante a execução do script (F6)
- [ ] Montagem de `/outputs` restrita e sem `chmod 777` (F6)

## 7. Parecer

Os achados de severidade alta que dependem do código da fase 1 (F1, F2, F4) e o de severidade média
F3 foram corrigidos e cobertos por testes, o que **libera a fase 1 do ponto de vista de segurança**.
Os achados F5 a F7 não bloqueiam a fase 2 (remoção do modo container), mas devem ser decididos e tratados antes de expor o Pi a redes
fora do controle do pesquisador ou de habilitar `document_processor`.
