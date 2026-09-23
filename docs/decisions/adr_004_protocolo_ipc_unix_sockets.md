# ADR 004 — Protocolo IPC via Unix Domain Sockets com Length-Prefix

**Status:** Aceito
**Data:** 2026-09-22
**Autores:** Arquiteto de Soluções (GeminiClaw)
**Roadmaps relacionados:** `roadmaps/roadmap.md` (Etapa 6), `roadmaps/roadmap_V12.md` (V12.3)

---

## Contexto

O orquestrador (processo host) precisa enviar tarefas para agentes em containers Docker e receber os resultados de volta. É necessário um canal de comunicação bidirecional, confiável e de baixa latência que funcione no contexto de Docker-in-Docker do Raspberry Pi 5.

---

## Decisão

### Protocolo IPC

**Transporte:** Unix Domain Sockets (Linux) com fallback automático para TCP loopback (macOS/Windows).

**Formato de mensagem:** JSON com length-prefix de 4 bytes big-endian:

```python
HEADER_SIZE = 4

# Envio
data = json.dumps(message).encode("utf-8")
header = struct.pack(">I", len(data))  # 4 bytes, big-endian
socket.sendall(header + data)

# Recepção
header = recv_exactly(socket, HEADER_SIZE)
length = struct.unpack(">I", header)[0]
data = recv_exactly(socket, length)
message = json.loads(data.decode("utf-8"))
```

**Schema de mensagem:**

```json
{
  "type": "task | result | error | ping | pong",
  "session_id": "<session_slug>",
  "payload": { ... },
  "timestamp": "ISO-8601",
  "_telemetry": {
    "token_usage": { ... },
    "tool_usage": [ ... ]
  }
}
```

O campo `_telemetry` (adicionado em V12.3) é um canal de fallback para ingestão de métricas de containers sem acesso direto ao PostgreSQL.

### Reconexão

Retry com backoff exponencial — até 3 tentativas — em caso de falha de transporte. Implementado em `src/ipc.py`.

### Diretório de Sockets

```
/tmp/geminiclaw-ipc/
└── <session_id>.sock    # socket por sessão
```

O diretório é montado como volume nos containers de agente:

```python
volumes={
    str(ipc_dir): {"bind": "/tmp/geminiclaw-ipc", "mode": "rw"},
}
```

---

## Alternativas Consideradas

### Alternativa A: HTTP REST entre host e containers

Cada agente expõe uma API HTTP; o orquestrador faz chamadas POST para enviar tarefas.

**Descartado porque:**
- Overhead de HTTP para mensagens pequenas e frequentes é desnecessário
- Requer exposição de portas nos containers (gerenciamento de conflitos)
- `adk web` não é o modelo de execução do GeminiClaw (conforme `backend-dev.md`)
- Autenticação de chamadas HTTP adiciona complexidade

### Alternativa B: Redis como message broker

Usar Redis pub/sub ou streams para comunicação assíncrona entre orquestrador e agentes.

**Descartado porque:**
- Dependência adicional de serviço externo
- Overhead de rede para comunicação local (host → container no mesmo host)
- Unix Domain Sockets têm latência ~10x menor do que TCP loopback para mensagens pequenas

### Alternativa C: Shared memory / mmap

Comunicação via memória compartilhada entre host e containers.

**Descartado porque:**
- Docker isola namespaces de memória — shared memory não funciona nativamente entre host e container sem configuração explícita
- Complexidade de sincronização (mutexes, semáforos) desnecessária

### Alternativa D: gRPC

Protocol Buffers + gRPC para comunicação tipada e eficiente.

**Descartado porque:**
- Complexidade de setup excessiva para o caso de uso
- Requer definição e compilação de schemas `.proto`
- JSON já é suficiente para as mensagens trocadas (tamanho < 1MB em todos os casos)

---

## Consequências

### Positivas

- **Latência mínima:** Unix Domain Sockets são o mecanismo de IPC mais rápido disponível no Linux — passagem de dados no kernel sem overhead de rede.
- **Sem dependências externas:** Nenhum serviço adicional necessário além do kernel Linux.
- **Detecção de fragmentação:** O length-prefix elimina o problema de mensagens fragmentadas em múltiplos `recv()`.
- **Telemetria embutida:** O campo `_telemetry` no payload permite ingestão de métricas mesmo de containers sem acesso ao PostgreSQL.

### Negativas / Trade-offs

- **Unix-only:** Em macOS e Windows, o fallback é TCP loopback — ligeiramente maior latência e necessidade de gerenciar portas.
- **Sem autenticação:** O socket não autentica o cliente — qualquer processo com acesso ao socket pode enviar mensagens. Mitigado por permissões de filesystem no diretório de sockets.
- **Mensagens síncronas:** O protocolo atual é request-response; notificações assíncronas do agente para o orquestrador requerem inversão de fluxo.

---

## Revisão

Este ADR deve ser revisado quando:
- V14 for implementado (containers por sessão podem usar o mesmo socket durante toda a sessão)
- Surgir necessidade de comunicação multi-hop (agente → agente, sem passar pelo orquestrador)
