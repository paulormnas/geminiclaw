# Regras de Code Review — GeminiClaw

As revisões de código neste projeto são conduzidas por agentes de IA e devem utilizar exclusivamente o **GitHub CLI (`gh`)** para analisar e comentar Pull Requests. O objetivo é manter o mais alto nível de estabilidade, performance e segurança sem sobrecarregar o desenvolvedor com minúcias desnecessárias.

---

## Ferramentas Necessárias

Antes de iniciar uma revisão de código, certifique-se de que o GitHub CLI está autenticado. Caso não esteja, notifique o usuário.

```bash
gh auth status
```

---

## Como Realizar um Code Review

Ao ser instruído para revisar um Pull Request, siga exatamente estes passos de forma autônoma:

### 1. Obter Contexto do Pull Request
Use o comando de visualização para ler o título, a descrição e o contexto da feature implementada.

```bash
gh pr view <numero-do-pr> --json title,body,author,state
```

### 2. Extrair o Diff
Analise as mudanças propostas extraindo o diff unificado.

```bash
gh pr diff <numero-do-pr>
```

### 3. Foco da Avaliação
Durante a análise do diff, seja **direto e geral**. O seu objetivo não é criticar sintaxe mínima ou exigir detalhes estéticos extremos, mas sim identificar gargalos estruturais.
O seu checklist de avaliação **deve ser focado nestes pontos críticos**:

- **Segurança**: Existe alguma vulnerabilidade óbvia (ex: injeção de SQL/NoSQL, logs contendo senhas, exposição de portas indevidas)?
- **Performance**: Há uso indevido de loops bloqueantes na event loop (`asyncio`), vazamento de memória explícito ou má gestão de conexões com o banco de dados?
- **Estabilidade**: O tratamento de exceções está mascarando erros? (ex: `except Exception: pass`).
- **Arquitetura**: A implementação fere o princípio de 100% Python sem ferramentas Node.js no runtime? As bibliotecas e pacotes foram gerenciadas corretamente pelo `uv`?

### 4. Emitir o Parecer
Após analisar, construa um comentário geral conciso (em português brasileiro).
- **Faça comentários gerais** sem entrar excessivamente em detalhes linha a linha.
- **Destaque os problemas críticos** (se houverem) em tópicos curtos.
- **Envie a revisão** utilizando o GitHub CLI.

Para enviar apenas um comentário construtivo sem forçar aprovação/bloqueio imediato:
```bash
gh pr review <numero-do-pr> --comment -b "## Revisão de Código

(Seus comentários gerais aqui)

### Pontos de Atenção (Segurança/Performance)
- Ponto 1
- Ponto 2"
```

Para aprovar formalmente quando não houver nenhum risco arquitetural:
```bash
gh pr review <numero-do-pr> --approve -b "Tudo certo! Código alinhado com a arquitetura."
```

Para solicitar mudanças em caso de falha crítica:
```bash
gh pr review <numero-do-pr> --request-changes -b "Por favor, corrija a vulnerabilidade de segurança apontada..."
```

---

## O que NÃO Fazer

- **NÃO** exija modificações estéticas triviais que não impactam diretamente segurança ou performance.
- **NÃO** sugira dependências externas que não agreguem muito valor (mantenha o footprint mínimo estipulado no projeto).
- **NÃO** tente revisar arquivos autogerados (`uv.lock`, logs) além do estritamente necessário para validar que foram atualizados corretamente.
- **NÃO** faça comentários por linha (inline-comments) no diff. Use sempre o comentário geral.
