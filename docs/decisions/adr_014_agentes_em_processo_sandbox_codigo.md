# ADR 014 — Agentes em Processo no Host; Containers Apenas como Sandbox de Código

**Status:** Aceito (implementado em 2026-09-29: runtime em processo, remoção do modo container e do IPC)
**Data:** 2026-09-28
**Autores:** Arquiteto de Soluções (GeminiClaw)
**Substitui:** ADR 003 §1 e §3 e ADR 004 — o sandbox de código do ADR 003 §2 permanece
**ADRs relacionados:** ADR 002 (MAS), ADR 010 (propósito), ADR 012 (Curator)

---

## Contexto

O ADR 003 colocou **cada agente em um container Docker efêmero**, e o ADR 004 definiu o
protocolo IPC (Unix sockets com length-prefix) que liga o orquestrador a esses containers.
Na prática, isso criou **gargalos na arquitetura**:

- **Latência de startup** de 1–3 s por container, somada a cada subtarefa e replanejamento.
- **Consumo de RAM** no Raspberry Pi 5 com vários containers de agente simultâneos
  (256–384 MB cada), além de PostgreSQL, Qdrant e do sandbox.
- **Complexidade:** imagens por agente, rede `geminiclaw-net`, protocolo de IPC, telemetria
  e logs extraídos via socket.
- **Comunicação entre agentes cara:** o ciclo ativo Curator ↔ Researcher (ADR 012) exigiria
  ainda mais trocas por IPC.

O isolamento que realmente importa é o do **código gerado pelo LLM**, não o dos agentes: os
agentes apenas chamam provedores LLM e ferramentas. O próprio Validator já roda como corrotina
no orquestrador, sem container.

---

## Decisão

### 1. Agentes rodam como processo no computador (host)

Todos os agentes (Researcher, Developer, Validator, Summarizer e o novo Curator) passam a
rodar **no processo do orquestrador** (ou em processos locais gerenciados por ele), sem
container dedicado por agente. A comunicação entre agentes passa a ser feita por chamadas
e filas em memória, mantendo o orquestrador como mediador e o registro de todas as mensagens.

### 2. Container apenas para executar código

Containers são mantidos **exclusivamente para executar o código implementado pelo
Developer**. O sandbox do ADR 003 §2 permanece: `put_archive`/`get_archive`, sem bind mounts,
usuário non-root, rede desabilitada e limites de CPU/RAM.

> **Nota de 2026-10-01 (ADR 018):** o sandbox real diverge deste parágrafo e o ADR 018 aprovou o
> rumo de corrigi-lo. O diretório `/outputs` **continua montado** (necessário para exportar código,
> gráficos e artefatos), a rede precisa estar disponível para instalar pacotes e o usuário
> deve ser não-root. Hoje a implementação ainda roda como root e usa `chmod 777`. O texto acima
> descreve o alvo anterior e será revisado quando as specs do ADR 018 forem implementadas.

### 3. Nenhum código gerado roda no computador principal

**Todo código gerado ou modificado por agentes, inclusive durante a exploração de resultados,
executa dentro do sandbox — nunca no host.** Isso inclui análises, scripts de geração de
gráficos, leitura de artefatos que exija execução, e instalação de pacotes. No host, os agentes
podem apenas:

- chamar provedores LLM;
- ler e escrever arquivos **dentro do diretório da sessão**, por ferramentas controladas;
- consultar os bancos (PostgreSQL, Qdrant, grafo) por interfaces do projeto;
- usar ferramentas de busca técnica de propósito fixo.

Nenhuma ferramenta disponível no host pode receber código ou comandos arbitrários vindos do
LLM. Ferramentas que precisem executar algo delegam ao sandbox.

### 4. Isolamento de falhas por supervisão, não por container

Como uma falha de agente não é mais contida por um container, o orquestrador deve isolar
cada agente com timeout, captura de exceções e limites de uso (ADR 012), de modo que a falha
de um agente não derrube a sessão.

### 5. Fora do escopo deste ADR

Ficam para a spec: se os agentes rodam como corrotinas no mesmo processo ou como processos
locais separados, o destino do protocolo IPC do ADR 004 (removido ou mantido só para o
sandbox), a política de rede do sandbox para instalação de pacotes e a migração do código
existente (`ContainerRunner`, imagens `geminiclaw-<tipo>`).

---

## Alternativas Consideradas

### Alternativa A: Manter um container por agente (ADR 003)

**Descartado porque:** é a origem dos gargalos descritos, e não protege contra o risco real,
que é o código gerado.

### Alternativa B: Um único container para todos os agentes

**Descartado porque:** mantém a complexidade de rede e IPC sem ganho de isolamento
relevante — os agentes continuariam compartilhando o mesmo ambiente.

### Alternativa C: Executar código gerado no host como subprocesso

**Descartado porque:** mantém-se o motivo do ADR 003 — sem isolamento nem limites de
recursos. Contraria a regra de que nenhum código gerado roda no computador principal.

---

## Consequências

### Positivas

- Fim da latência de startup por agente e redução do consumo de RAM no Pi 5.
- Comunicação entre agentes barata, viabilizando o ciclo ativo Curator ↔ Researcher.
- Arquitetura mais simples: menos imagens, sem rede de agentes, depuração direta.
- Fronteira de segurança clara: **o sandbox é o único lugar onde código gerado executa.**

### Negativas / Trade-offs

- **Superfície do host aumenta:** agentes rodam com as permissões do orquestrador. Exige
  revisão do Analista de Segurança — em especial das ferramentas de arquivo (confinamento ao
  diretório da sessão) e das que chamam processos externos.
- **Ferramentas existentes a revisar:** a busca do Researcher executa o Gemini CLI como
  subprocesso no host (`agents/researcher/tools.py`) — é um processo de propósito fixo, mas
  deve ser reavaliado (também pelo ADR 011, por depender de um fornecedor). O prompt base em
  `agents/base/agent.py` instrui instalar pacotes via `subprocess` — permitido apenas dentro do
  sandbox.
- **Falha de um agente pode afetar o processo** se a supervisão (§4) for mal implementada.
- **Mudança grande de infraestrutura:** altera `docker-compose.yml`, Dockerfiles e o
  `ContainerRunner`; exige aprovação explícita conforme o AGENTS.md.

---

## Revisão

Este ADR deve ser revisado quando:
- Um agente precisar de dependências incompatíveis com o ambiente do host.
- Surgir requisito multi-tenant ou multiusuário no mesmo nó.
- A federação (ADR 013) introduzir código vindo de outros nós — que também só poderá executar
  no sandbox.
