# Spec G7 — Controle de Equipamentos Físicos: Estratégia MHS + Interface Proprietária

**Versão:** V16.1
**Status:** Proposta aprovada — depende de V15 completo; MHS em avaliação contínua
**Gap:** G7 — Sem arquitetura para controle de equipamentos físicos
**ADRs relacionados:**
  - [ADR 001](../../docs/decisions/adr_001_proposito_harness_pesquisa_cientifica.md) — Propósito do sistema
  - [ADR 003](../../docs/decisions/adr_003_containerizacao_docker_dind.md) — Containerização (equipamentos ficam fora do sandbox)

---

## Objetivo

Habilitar o sistema a interagir com equipamentos físicos de laboratório (sensores, atuadores,
instrumentos de medição) de forma segura e rastreável, adotando uma **estratégia em duas fases**
que é implementável agora e compatível com o padrão emergente MHS da Anthropic quando ele
se tornar público.

---

## Contexto: Model Hardware Standard (MHS) da Anthropic

Em agosto de 2026, a Anthropic lançou o **Model Hardware Standard (MHS)** em research preview gated,
colaborando com HHMI Janelia Research Campus, Genentech, CMU, University of Washington e QuEra.

**O que o MHS oferece:**
- Padrão de drivers que expõe capacidades, limites de segurança e parâmetros operacionais em
  formato que LLMs conseguem raciocinar (chamados "device tags")
- Funciona em cima do **MCP (Model Context Protocol)** — o agente envia comandos via MCP;
  o MHS faz a tradução para o protocolo nativo do hardware
- Primitivas simples: `read(channel) → dict` e `write(channel, value) → None`
- Em uso para: robótica de laboratório, microscópios, liquid handlers, lasers de quantum computing

**Status atual (set/2026):** Research preview fechado, sem acesso público. Sem confirmação
de suporte a ARM/Raspberry Pi 5. Anthropic comprometeu-se a open-source futuro.

**Decisão de design:** Implementar interface proprietária com primitivas MHS-compatíveis
(Fase V16), e migrar para MHS nativo quando disponível (Fase V17+).

---

## Dependências

- **V15 completo:** Agentes estabilizados, modo de operação funcional, `ask_researcher` disponível
- **MHS não é pré-requisito:** Fase V16 não depende do MHS ser público

---

## Fase V16 — Interface Proprietária MHS-Compatível

### Tarefa 1: Definir `BaseEquipmentDriver` com primitivas MHS-compatíveis

- **Módulos afetados:** `src/skills/equipment/__init__.py` (novo), `src/skills/equipment/base.py` (novo)
- **Complexidade estimada:** Média
- **Critérios de aceite:**
  - [ ] `BaseEquipmentDriver` implementado com interface:
        ```python
        class BaseEquipmentDriver(ABC):
            device_tags: dict  # ex: {"name": "Sensor DHT22", "protocol": "I2C",
                               #      "safe_temp_range_c": [-40, 80], "read_channels": ["temperature", "humidity"]}
            safety_limits: dict  # limites que o agente não pode ultrapassar

            async def connect(self) -> None: ...
            async def disconnect(self) -> None: ...
            async def read(self, channel: str, params: dict = {}) -> dict: ...
            async def write(self, channel: str, value: Any, params: dict = {}) -> None: ...
            async def list_channels(self) -> list[dict]: ...  # autodescoberta de canais
        ```
  - [ ] `device_tags` é injetado automaticamente no contexto do Developer Agent quando
        a EquipmentSkill é ativada — para que o LLM saiba com o que está trabalhando
  - [ ] `safety_limits` são verificados em `write()` antes de qualquer operação —
        se violados, levanta `SafetyLimitViolation` e registra em log antes de falhar
  - [ ] Testes unitários: `write()` com valor fora de `safety_limits` → `SafetyLimitViolation`

### Tarefa 2: Implementar drivers para os protocolos do Raspberry Pi 5

- **Módulos afetados:** `src/skills/equipment/gpio_driver.py` (novo),
  `src/skills/equipment/i2c_driver.py` (novo), `src/skills/equipment/serial_driver.py` (novo)
- **Complexidade estimada:** Alta
- **Critérios de aceite:**

  **GPIODriver (gpiod):**
  - [ ] Leitura de pinos digitais e analógicos (via GPIO do Pi 5)
  - [ ] Escrita em pinos digitais (HIGH/LOW)
  - [ ] `device_tags` incluem mapa de pinos disponíveis e modo (input/output)
  - [ ] Biblioteca: `gpiod` (não `RPi.GPIO` — depreciada para Pi 5 com kernel ≥ 6.x)

  **I2CDriver (smbus2):**
  - [ ] Leitura de registradores de dispositivos I2C por endereço e registrador
  - [ ] Suporte a sensors comuns: DHT22, BMP280, BME280, ADS1115
  - [ ] `device_tags` incluem endereço I2C e lista de registradores com unidade de medida

  **SerialDriver (pyserial):**
  - [ ] Leitura/escrita em porta serial UART (USB ou hardware)
  - [ ] Suporte a instrumentos com protocolo ASCII (ex: multímetros, termostatos, balanças)
  - [ ] Configurável: baudrate, parity, stopbits, timeout via `device_tags`

  **Todos os drivers:**
  - [ ] Log de todas as operações com timestamp e valores em `logs/equipment_<session_id>.log`
  - [ ] Operações de `write` logadas ANTES de executar ("logs antes de ação" — AGENTS.md §6)
  - [ ] Testes de integração com mocks de hardware (sem hardware físico necessário para CI)

### Tarefa 3: Implementar `EquipmentSkill` como skill do Developer Agent

- **Módulos afetados:** `src/skills/equipment/skill.py` (novo), `agents/developer/agent.py`
- **Complexidade estimada:** Média
- **Critérios de aceite:**
  - [ ] `EquipmentSkill` expõe tools `equipment_read(device, channel, params)` e
        `equipment_write(device, channel, value, params)` para o Developer Agent
  - [ ] Developer Agent **não acessa hardware diretamente** — apenas via `EquipmentSkill`
  - [ ] `EquipmentSkill` executa no processo do **host** (fora do container Docker) — única
        skill do projeto com execução no host por necessidade de acesso a hardware físico
  - [ ] Comunicação entre container do Developer e EquipmentSkill via IPC socket dedicado
        (separado do socket de sessão para não criar acoplamento)
  - [ ] Testes: Developer usa `equipment_read` → resultado salvo em `/outputs/<task>/sensor_data.json`

### Tarefa 4: Sistema de aprovação de operações por sessão

- **Módulos afetados:** `src/cli.py`, `src/session_manager.py`, `src/skills/equipment/skill.py`
- **Complexidade estimada:** Média
- **Critérios de aceite:**
  - [ ] No início de cada sessão com equipamentos, CLI exibe lista de dispositivos detectados e
        solicita confirmação do pesquisador: "Dispositivos encontrados: [DHT22 (I2C), GPIO-LED].
        Autorizar acesso? [s/N]"
  - [ ] Operações de `write` em hardware requerem que o canal esteja na `allowlist` configurada
        pelo pesquisador no início da sessão via CLI
  - [ ] Operações de `write` fora da `allowlist` → `PermissionDeniedError` com log e sem execução,
        independente do modo de operação (inclusive modo `auto`)
  - [ ] `allowlist` é persistida no `SessionManager` e registrada no relatório final

---

## Fase V17+ — Migração para MHS (quando disponível)

> Esta fase é condicional à abertura do MHS pela Anthropic como open-source.

### Tarefas planejadas (sem spec detalhada até MHS ser público):

- [ ] Avaliar especificação MHS quando publicada — verificar compatibilidade com Pi 5 / ARM
- [ ] Criar `MHSAdapter` que implementa `BaseEquipmentDriver` usando primitivas MHS nativas
- [ ] Migrar drivers I2C/GPIO/Serial para formato de "device tags" MHS
- [ ] Registrar GeminiClaw como cliente MCP para comunicação com MHS Server
- [ ] Manter `BaseEquipmentDriver` como fallback se MHS não suportar algum protocolo necessário

**Critério de decisão para V17:** MHS deve ser open-source, suportar ARM64, e ter pelo menos
1 driver I2C de referência disponível publicamente.

---

## Validação da Etapa (V16)

- [ ] `uv run pytest -m "unit or integration" -v` — todos os testes passam
- [ ] Mock hardware test: GPIODriver lê e escreve em pino simulado sem hardware físico
- [ ] Safety test: `write` com valor fora de `safety_limits` → falha limpa com log
- [ ] Permission test: `write` em canal fora da `allowlist` → `PermissionDeniedError`
- [ ] Integração test: Developer Agent usa `equipment_read` via IPC → dados em `/outputs/`
- [ ] PR merged em `dev`

---

## Arquivos (V16)

| Arquivo | Ação | Descrição |
|---|---|---|
| `src/skills/equipment/__init__.py` | NEW | Package de equipment skills |
| `src/skills/equipment/base.py` | NEW | `BaseEquipmentDriver` abstrato com `device_tags` e `safety_limits` |
| `src/skills/equipment/gpio_driver.py` | NEW | Driver GPIO via `gpiod` para Pi 5 |
| `src/skills/equipment/i2c_driver.py` | NEW | Driver I2C via `smbus2` |
| `src/skills/equipment/serial_driver.py` | NEW | Driver Serial/UART via `pyserial` |
| `src/skills/equipment/skill.py` | NEW | `EquipmentSkill` com tools `equipment_read` e `equipment_write` |
| `agents/developer/agent.py` | MODIFY | Registrar `EquipmentSkill` como tool disponível |
| `src/session_manager.py` | MODIFY | Persistir `allowlist` de equipamentos por sessão |
| `src/cli.py` | MODIFY | Exibir dispositivos detectados e solicitar aprovação no início da sessão |
| `tests/unit/test_equipment_drivers.py` | NEW | Testes com mock de hardware |
| `tests/integration/test_equipment_skill.py` | NEW | Testes de integração da EquipmentSkill via IPC |
